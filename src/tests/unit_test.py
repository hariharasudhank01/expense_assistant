import pandas as pd
import pytest
from src.transform import pre_process
from src.helper import date
from src.transform.pre_process import extract_merchant, populate_spend_type

@pytest.mark.parametrize("desc, expected", [
    ("kfc canberra city canberra city au aus", "kfc"),            # repeated location tail
    ("snr dynamics pty ltd isabella plai",    "snr dynamics"),    # noise words + cut-off suburb
    ("ikea canberra majura act au",           "ikea"),            # branch name cut at city
    ("the canberra times act au",             "the canberra times"),  # place inside the name is kept
    ("acton tavern acton act au",             "acton tavern"),
    ("sq *originbake braddo",                 "originbake"),      # processor prefix + glued fix
    ("1010 cafe 0042 sydney nsw au",          "1010 cafe"),       # leading number kept, store no. dropped
    ("7-eleven 2231 belconnen",               "7-eleven"),        # hyphen kept
    ("transfer from xx8798 commbank app",     "self_transfer"),
    ("transfer to a thatte commbank app",     "shared_expenses"),
    ("return coles 0612 woden act au",        "refund"),
    ("woden act au",                          "woden act au"),    # location only, falls back to the full text
])

def test_extract_merchat(desc, expected):
    assert extract_merchant(desc) == expected

def test_spend_type_refund_and_lump():
    df = pd.DataFrame({
        "category": ["groceries", "groceries", "education", "shared_expenses", "salary"],
        "amount": [-50.0, 12.0, -5000.0, -100.0, 3000.0],
    })
    out = populate_spend_type(df)
    assert out["spend_type"].tolist() == ["essential", "essential", "essential", "shared_expenses", "others"]
    assert out["is_refund"].tolist() == [False, True, False, False, False]
    assert out["is_lump_expense"].tolist() == [False, False, True, False, False]

# Made-up rent amount, so the test doesn't depend on .env or real figures.
TEST_RENT_RULES = [
    {"payee": "a name", "amount": -500.0},
    {"payee": "archer", "amount": -500.0},
]

@pytest.mark.parametrize("detail, amount, merchant, category", [
    ("transfer to a name commbank app", -500.0, "a name",        "rent"),             # rent payee + rent amount
    ("fast transfer to a name",         -500.0, "a name",        "rent"),             # "fast" prefix also counts
    ("transfer to archer",                -500.0, "archer",          "rent"),             # second rule
    ("transfer to a name commbank app",  -30.0, "shared_expenses", "shared_expenses"),  # other amount stays shared
    ("transfer from a name",             500.0, "shared_expenses", "shared_expenses"),  # money in is never rent
    ("transfer to athe name",        -500.0, "shared_expenses", "shared_expenses"),  # similar name doesn't match
])
def test_apply_rent_rules(monkeypatch, detail, amount, merchant, category):
    monkeypatch.setattr(pre_process, "rent_rules", TEST_RENT_RULES)
    df = pd.DataFrame({
        "transaction_details": [detail],
        "amount": [amount],
        "merchant": ["shared_expenses"],
        "category": ["shared_expenses"],
    })
    out = pre_process.apply_rent_rules(df)
    assert out.loc[0, "merchant"] == merchant
    assert out.loc[0, "category"] == category

def make_txn_rows(ids):
    # Rows 0 and 2 are truly identical (purchase, reversal, same purchase again).
    return pd.DataFrame({
        "date": pd.to_datetime(["2026-01-05", "2026-01-05", "2026-01-05"]),
        "transaction_details": ["coles", "coles", "coles"],
        "amount": [-10.0, 10.0, -10.0],
        "balance": [90.0, 100.0, 90.0],
        "id": ids,
    })

def test_transaction_id_unique_and_stable():
    first = pre_process.populate_transaction_id(make_txn_rows([1, 2, 3]))
    again = pre_process.populate_transaction_id(make_txn_rows([1, 2, 3]))
    assert first["txn_id"].is_unique                            # identical rows still get different ids
    assert first["txn_id"].tolist() == again["txn_id"].tolist()  # same ids on every run

def test_transaction_id_ignores_position_in_file():
    # The same transactions at different positions in another statement keep their ids.
    here = pre_process.populate_transaction_id(make_txn_rows([1, 2, 3]))
    there = pre_process.populate_transaction_id(make_txn_rows([41, 42, 43]))
    assert here["txn_id"].tolist() == there["txn_id"].tolist()
# Made-up anchor payday, so the test doesn't depend on .env.
TEST_ANCHOR = pd.Timestamp("2030-01-02")

def test_pay_cycle_position(monkeypatch):
    monkeypatch.setattr(pre_process, "pay_cycle_anchor", str(TEST_ANCHOR.date()))
    # Days from the anchor. 28 has no salary in the fortnight before it,
    # which must not stretch the cycle.
    offsets = [-1, 0, 13, 14, 28]
    df = pd.DataFrame({
        "date": [TEST_ANCHOR + pd.Timedelta(days=d) for d in offsets],
        "category": ["cafe", "salary", "cafe", "salary", "salary"],
    })
    out = pre_process.populate_pay_cycle(df)
    assert out["pay_cycle_id"].tolist() == [-1, 0, 0, 1, 2]
    assert out["days_since_payday"].tolist() == [13, 0, 13, 0, 0]
    assert out["pay_cycle_start"].tolist() == [TEST_ANCHOR + pd.Timedelta(days=d) for d in [-14, 0, 0, 14, 28]]

def test_pay_cycle_complete_only_when_all_14_days_in_data(monkeypatch):
    monkeypatch.setattr(pre_process, "pay_cycle_anchor", str(TEST_ANCHOR.date()))
    # Data covers anchor-1 .. anchor+20: only the anchor's cycle has all 14 days.
    df = pd.DataFrame({
        "date": [TEST_ANCHOR + pd.Timedelta(days=d) for d in [-1, 0, 20]],
        "category": ["cafe", "salary", "cafe"],
    })
    out = pre_process.populate_pay_cycle(df)
    assert out["cycle_complete"].tolist() == [False, True, False]

def make_payments(merchant, category, day_offsets, amounts):
    start = pd.Timestamp("2030-01-01")
    return pd.DataFrame({
        "date": [start + pd.Timedelta(days=d) for d in day_offsets],
        "merchant": merchant,
        "category": category,
        "amount": amounts,
    })

def test_populate_recurring():
    df = pd.concat([
        # Every 30 days with one dearer month: monthly by pattern.
        make_payments("streamco", "subscriptions", [0, 30, 60, 90, 120], [-20, -20, -25, -20, -20]),
        # Random gaps: not recurring.
        make_payments("gym", "health_fitness", [0, 3, 23, 32, 73], [-24, -24, -24, -24, -24]),
        # Random gaps and amounts, but a bill: recurring by category, no period.
        make_payments("powerco", "utilities", [0, 17, 92, 115], [-35, -196, -540, -5]),
    ], ignore_index=True)
    out = pre_process.populate_recurring(df).groupby("merchant").first()
    assert out.loc["streamco", "is_recurring"] and out.loc["streamco", "recurrence_period"] == "monthly"
    assert not out.loc["gym", "is_recurring"] and pd.isna(out.loc["gym", "recurrence_period"])
    assert out.loc["powerco", "is_recurring"] and pd.isna(out.loc["powerco", "recurrence_period"])

# Fixed "today" (a Thursday) and anchor, so the test doesn't depend on the real date or .env.
TODAY = pd.Timestamp("2026-10-29")

@pytest.mark.parametrize("text, start, end", [
    ("today",                    "2026-10-29", "2026-10-29"),
    ("this week",                "2026-10-26", "2026-11-01"),   # weeks start on Monday
    ("last week",                "2026-10-19", "2026-10-25"),
    ("last month",               "2026-09-01", "2026-09-30"),
    ("last quarter",             "2026-07-01", "2026-09-30"),
    ("last 7 days",              "2026-10-23", "2026-10-29"),   # rolling, includes today
    ("past 3 weeks",             "2026-10-09", "2026-10-29"),
    ("July",                     "2026-07-01", "2026-07-31"),
    ("november",                 "2025-11-01", "2025-11-30"),   # not in the future, so last year
    ("july 2025",                "2025-07-01", "2025-07-31"),
    ("Q2",                       "2026-04-01", "2026-06-30"),
    ("since sept",               "2026-09-01", "2026-10-29"),
    ("july to september",        "2026-07-01", "2026-09-30"),
    ("in the last month",        "2026-09-01", "2026-09-30"),   # filler words stripped
    ("2026-07-01 to 2026-07-15", "2026-07-01", "2026-07-15"),
    ("this pay cycle",           "2026-10-22", "2026-11-04"),
    ("last pay cycle",           "2026-10-08", "2026-10-21"),
])
def test_parse_period(monkeypatch, text, start, end):
    monkeypatch.setattr(date, "pay_cycle_anchor", "2026-01-01")
    got = date.parse_period(text, TODAY)
    assert (f"{got[0]:%Y-%m-%d}", f"{got[1]:%Y-%m-%d}") == (start, end)

def test_resolve_period_clips_to_data():
    data_start, data_end = pd.Timestamp("2026-01-01"), pd.Timestamp("2026-09-22")
    out = date.resolve_period("last month", TODAY, data_start, data_end)
    assert (out["start"], out["end"]) == ("2026-09-01", "2026-09-22")
    assert "22 Sep" in out["note"]
    assert "error" in date.resolve_period("this month", TODAY, data_start, data_end)   # no data, not $0
    assert "error" in date.resolve_period("the summer", TODAY)
