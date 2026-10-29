from hashlib import sha1
import pandas as pd
import numpy as np
import re
import os
from src.transform.llm import categorise_transaction
from src.helper.helper import read_json, write_json, project_dir
from src.helper.config import (
    country_pattern, state_pattern, cities, suburbs, payment_suffix_pattern,
    payment_prefixes, processor_prefixes, int_transfer_prefixes,
    glued_token_fixes, noise_words, transfer_prefixes, self_transfer_prefixes, return_prefixes,
    smart_saving_prefixes, essential_categories, discretionary_categories, lump_expense_threshold,
    special_labels, llm_categories, category_overrides, self_transfer_categories, shared_expense_categories,
    rent_rules, pay_cycle_anchor,
    recurring_periods, recurring_gap_tolerance, recurring_min_occurrences,
    recurring_gap_match_share, recurring_max_amount_spread,
    fixed_bill_categories, recurring_excluded_categories
)

merchant_category_path = os.path.join(project_dir, "output", "merchant_category.json")

places = cities + suburbs
place_pattern = rf"\b({'|'.join(re.escape(p) for p in places)})$"
tail_patterns = [country_pattern, state_pattern, place_pattern, payment_suffix_pattern]

def strip_truncated_place(text):
    # The bank cuts long place names short ("isabella plai", "canberr"). Drop a
    # tail that is the start of a known place. A lone word needs 5+ letters so
    # real words like "camp" aren't mistaken for "campbell".
    words = text.split()
    for n, min_len in ((2, 1), (1, 5)):
        if len(words) <= n or len(words[-1]) < min_len:
            continue
        tail = " ".join(words[-n:])
        if any(p.startswith(tail) and p != tail for p in places):
            return " ".join(words[:-n])
    return text

def strip_location_tail(text):
    # Location and payment tokens alternate in any order ("canberra city
    # canberra city au aus"), so keep fixing glued words and peeling every
    # tail pattern until nothing changes.
    while True:
        before = text
        text = fix_glued_tail(text)
        for pattern in tail_patterns:
            text, _ = peel_tail(text, pattern)
        text = strip_truncated_place(text)
        if text == before:
            return text

def cut_at_city(text):
    # Branch names sit inside the merchant name ("ikea canberra majura",
    # "kfc sydney t1 airside"). Cut at the first city word after the first
    # word, unless that would leave only "the" ("the canberra times").
    words = text.split()
    for i in range(1, len(words)):
        rest = " ".join(words[i:])
        if words[:i] != ["the"] and any(re.match(rf"{re.escape(c)}\b", rest) for c in cities):
            return " ".join(words[:i])
    return text

def fix_glued_tail(text):
    words = text.split()
    if words and words[-1] in glued_token_fixes:
        words[-1] = glued_token_fixes[words[-1]]
    return " ".join(words)

def starts_with_any(text, prefixes):
    # Whole-word match, so "return" doesn't catch "returned goods".
    return any(re.match(rf"{re.escape(prefix)}\b", text) for prefix in prefixes)

def strip_prefix(text, prefixes):
    for prefix in prefixes:
        text = re.sub(rf"^{re.escape(prefix)}\b\s*", "", text)
    return text

def strip_noise(text):
    symbols = [w for w in noise_words if not w.isalnum()]
    words = [w for w in noise_words if w.isalnum()]
    for symbol in symbols:
        if symbol == "-":
            # Keep hyphens inside names ("7-eleven"), drop separator dashes.
            text = re.sub(r"(?<!\w)-|-(?!\w)", " ", text)
        else:
            text = text.replace(symbol, " ")
    text = strip_prefix(text.strip(), processor_prefixes)
    for word in words:
        text = re.sub(rf"\b{re.escape(word)}\b", " ", text)
    text = re.sub(r"(?<!\S)[^\w\s]+(?!\S)", " ", text)   # stray punctuation tokens (" . ")
    # Standalone numbers are store/reference numbers, unless they start the
    # name ("1010 cafe").
    tokens = text.split()
    tokens = [t for i, t in enumerate(tokens) if i == 0 or not t.isdigit()]
    return " ".join(tokens)

def is_self_transfer(text):
    return starts_with_any(text, self_transfer_prefixes)

def is_transfer(text):
    return starts_with_any(text, transfer_prefixes)

def is_refund(text):
    return starts_with_any(text, return_prefixes)

def is_smart_saving(text):
    return starts_with_any(text, smart_saving_prefixes)

def is_int_transfer(text):
    return starts_with_any(text, int_transfer_prefixes)

def split_tail(text, pattern):
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return text, ""
    tail = match.group(1)
    rest = text[:match.start()].strip()
    return rest, tail

def peel_tail(text, pattern):
    # tokens like country/suburb can repeat back to back (e.g. "au aus"),
    # so keep stripping from the tail until the pattern no longer matches.
    tokens = []
    while True:
        text, token = split_tail(text, pattern)
        if not token:
            break
        tokens.insert(0, token)
    return text, " ".join(tokens)

def extract_merchant(text):
    text = strip_noise(text)

    if is_self_transfer(text):
        return "self_transfer"

    if is_transfer(text):
        return "shared_expenses"

    if is_refund(text):
        return "refund"

    if is_smart_saving(text):
        return "smart_savings"

    if is_int_transfer(text):
        return "international_transfer"

    text = strip_prefix(text, payment_prefixes)
    cleaned = text

    text = strip_location_tail(text)
    text = strip_location_tail(cut_at_city(text))

    # A description that is only a location ("woden") would leave nothing.
    return text.strip() or cleaned

def populate_categories(df):
    cache = read_json(merchant_category_path) if os.path.exists(merchant_category_path) else {}

    for merchant in df["merchant"].unique():
        if merchant in special_labels or merchant in category_overrides:
            continue
        # Cached entries are trusted as-is - the LLM can only return
        # llm_categories, so anything else is a manual edit to keep.
        if merchant in cache:
            continue
        category = categorise_transaction(merchant)
        # Failed calls aren't cached, so they're retried on the next run.
        if category:
            cache[merchant] = category

    write_json(cache, merchant_category_path)
    lookup = {**cache, **category_overrides, **{label: label for label in special_labels}}
    df["category"] = df["merchant"].map(lookup).fillna("unknown")
    return df

def apply_rent_rules(df):
    """
    This function is used to identify the rent payment made via 
    my room mate
    """
    for rule in rent_rules:
        payee = re.escape(rule["payee"])
        is_rent = (
            df["transaction_details"].str.match(rf"(fast )?transfer to {payee}\b")
            & df["amount"].round(2).eq(rule["amount"])
        )
        df.loc[is_rent, "merchant"] = rule["payee"]
        df.loc[is_rent, "category"] = "rent"
    return df

def populate_spend_type(df):
    conditions = [
        df["category"].isin(essential_categories),
        df["category"].isin(discretionary_categories),
        df["category"].isin(self_transfer_categories),
        df["category"].isin(shared_expense_categories)
    ]
    choices = ["essential", "discretionary", "self_transfer", "shared_expenses"]
    df["spend_type"] = np.select(conditions, choices, default="others")
    # Money back into a spend category is a refund, whether or not the bank
    # labelled it "return" - it offsets that category's spend.
    df["is_refund"] = (df["amount"] > 0) & df["spend_type"].isin(["essential", "discretionary"])
    df["is_lump_expense"] = df["amount"] < lump_expense_threshold
    return df

def populate_date(df):
    try:
        df["year"] = df["date"].dt.year
        df["quarter"] = df["date"].dt.quarter
        df["month"] = df["date"].dt.month
        df["month_name"] = df["date"].dt.month_name()
        df["week_no"] = df["date"].dt.isocalendar().week
        df["day_of_month"] = df["date"].dt.day
        df["day_of_week"] = df["date"].dt.day_name()
    except Exception as e:
        print(f"Failed to populate date, {e}")
    return df

def handle_dtypes(df):
    try:
        df["Date"] = pd.to_datetime(df['Date'])
    except Exception as e:
        print(f"Failed to Convert Date, {e}")
    try:
        df["Transaction details"] = df["Transaction details"].str.lower()
    except Exception as e:
        print(f"Failed to Transaction Details, {e}")
    try:
        df["Amount"] = pd.to_numeric(df["Amount"].str.replace("$", "").str.replace(",", ""))
        df["Balance"] = pd.to_numeric(df["Balance"].str.replace("$", "").str.replace(",", ""))
    except Exception as e:
        print(f"Failed to Convert Price, {e}")
    df.columns = df.columns.str.replace(" ", "_").str.lower()
    return df

def populate_transaction_id(df):
    """
    This function creats a hashID for every transaction. So that re-run the same PDF
    or new PDF with same values wont create duplicate records.
    """
    key = ["date", "transaction_details", "amount", "balance"]
    df["occurrence"] = df.groupby(key).cumcount()
    text = (df["date"].dt.strftime("%Y-%m-%d") + "|" + df["transaction_details"] + "|"
            + df["amount"].map("{:.2f}".format) + "|" + df["balance"].map("{:.2f}".format)
            + "|" + df["occurrence"].astype(str))
    df["txn_id"] = text.map(lambda s: sha1(s.encode()).hexdigest()[:16])
    return df

def populate_pay_cycle(df):
    anchor = pd.Timestamp(pay_cycle_anchor)
    offset = (df["date"] - anchor).dt.days # Gives the number of days from Anchor
    df["pay_cycle_id"] = offset // 14
    df["days_since_payday"] = offset % 14 # O/P = 0 means payday and 13 day before payday
    df["pay_cycle_start"] = anchor + pd.to_timedelta(df["pay_cycle_id"] * 14, unit="D") # Says no of days to start
    df["cycle_complete"] = (df["pay_cycle_start"] >= df["date"].min()) & \
                       (df["pay_cycle_start"] + pd.Timedelta(days=13) <= df["date"].max())
    return df

def match_recurring_period(dates, amounts):
    """
    Returns the period name ("fortnightly", "monthly", ...) if one merchant's
    payments repeat at a regular gap with a similar amount, otherwise None.
    dates and amounts hold one row per payment day.
    """
    if len(dates) < recurring_min_occurrences:
        return None

    gaps = dates.diff().dt.days.dropna()
    median_gap = gaps.median()
    for name, days in recurring_periods.items():
        if abs(median_gap - days) > recurring_gap_tolerance:
            continue
        # Most gaps must fit, not just the median - one odd payment is fine.
        gaps_fit = (gaps - days).abs() <= recurring_gap_tolerance
        if gaps_fit.mean() < recurring_gap_match_share:
            return None
        # Median distance from the median amount ignores one-off outliers
        # (a price change, a single odd month).
        median_amount = amounts.median()
        spread = (amounts - median_amount).abs().median() / abs(median_amount)
        if spread > recurring_max_amount_spread:
            return None
        return name
    return None

def populate_recurring(df):
    """
    This function flags recurring payments (rent, phone, gym, subscriptions).
    It works on any DataFrame, so it can later run over the full history
    from the database.
    """
    candidates = df[
        (df["amount"] < 0) # Only expenses, money spended will be in negatives "Eg: -680"
        & ~df["category"].isin(special_labels)
        & ~df["category"].isin(recurring_excluded_categories)
    ]

    periods = {}
    for merchant, group in candidates.groupby("merchant"):
        # One row per day, so a split payment doesn't create a 0-day gap.
        daily = group.groupby("date")["amount"].sum().sort_index()
        period = match_recurring_period(daily.index.to_series(), daily)
        if period:
            periods[merchant] = period

    # Only money going out is a bill - a refund from the same merchant isn't.
    is_outgoing = df["amount"] < 0
    df["recurrence_period"] = df["merchant"].map(periods).where(is_outgoing)
    df["is_recurring"] = is_outgoing & (
        df["recurrence_period"].notna() | df["category"].isin(fixed_bill_categories)
    )
    return df


def run(filename):
    df = pd.read_json(filename)
    df = handle_dtypes(df)
    df = populate_transaction_id(df)
    df = populate_date(df)
    df = populate_pay_cycle(df)
    df["merchant"] = df["transaction_details"].apply(extract_merchant)
    df = populate_categories(df)
    df = apply_rent_rules(df)
    df = populate_recurring(df)
    df = populate_spend_type(df)
    return df
