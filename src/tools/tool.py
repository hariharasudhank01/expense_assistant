import os
import calendar
import pandas as pd
import matplotlib
matplotlib.use("Agg") # No window, Streamlit only needs the PNG
import matplotlib.pyplot as plt
from matplotlib.ticker import StrMethodFormatter
from src.helper.helper import project_dir
from src.helper.config import pay_cycle_anchor, pay_cycle_days, default_bill_periods
from src.helper.date import resolve_period

data_path = os.path.join(
    project_dir, "output", "transaction.csv"
)

SPEND_TYPES = ["essential", "discretionary"]
ALLOWED_GROUP_BY = ["category", "spend_type", "merchant", "day_of_week", "month_name", "pay_cycle_id"]
ALLOWED_AGG = ["sum", "mean", "median", "count"]
PERIOD_STEP = {
    "weekly": pd.Timedelta(days=7),
    "fortnightly": pd.Timedelta(days=14),
    "monthly": pd.DateOffset(months=1),
    "yearly": pd.DateOffset(years=1),
}

def actual_spending(df):
    """
    This functions returns the transactions that are only in SPEND_TYPES
    """
    return df[df["spend_type"].isin(SPEND_TYPES)]

def in_period(df, start=None, end=None):
    """
    This function is used to split the transaction based on 
    start and end date provided the user
    """
    if start:
        df = df[df["date"] >= pd.Timestamp(start)]
    if end:
        df = df[df["date"] <= pd.Timestamp(end)]

    return df

def load_data():
    """
    This function loads and parse the dates, and returns the DataFrame
    """
    return pd.read_csv(
        data_path,
        parse_dates=["date", "pay_cycle_start"]
    )

def resolve_window(df, period=None, period_start=None, period_end=None):
    """
    This function returns the dates a tool should use. The period phrase
    wins, period_start and period_end are the exact date overrides.

    Arguments:
        df, DataFrame, transactions, used for the data range
        period, str, period in the user's words
        period_start, str, start date
        period_end, str, end date
    Returns:
        dict, with start, end, label and note, or an error
    """
    if period:
        return resolve_period(period, data_start=df["date"].min(), data_end=df["date"].max())
    return {"start": period_start, "end": period_end, "label": "custom", "note": None}

"""
Tool 1 - Spend Breakdown

This tools helps me to understand the spend per category over the
given period of time.

The idea is to group by Category and use aggregate functions.
"""
def spend_breakdown(
        period=None,
        period_start=None,
        period_end=None,
        group_by="category",
        agg="sum",
        include_lump=False
):
    """
    This function groups the transaction based on the category and return
    the spending between the start and end date.

    Arguments:
        period, str, period in the user's words, eg "last month"
        period_start, str, start date
        period_end, str, end date
        group_by, str, Group by Column. default="category",
        agg, str, Aggregate functions. default="sum",
        include_lump, bool, should include lump transactions.  default=False        
    Returns:
        dict, with spending details
    """
    try:
        if group_by not in ALLOWED_GROUP_BY:
            return {"error": f"group by must be one of {ALLOWED_GROUP_BY}"}
        if agg not in ALLOWED_AGG:
            return {"error": f"agg must be one of {ALLOWED_AGG}"}

        data = load_data()
        window = resolve_window(data, period, period_start, period_end)
        if "error" in window:
            return window

        df = in_period(actual_spending(data), window["start"], window["end"])
        if not include_lump:
            df = df[~df["is_lump_expense"]]
        if agg != "sum":
            df = df[~df["is_refund"]] # Exclude refunds as it affects mean, median
        if df.empty:
            return {"error": "No spending found for this period"}

        result = df.groupby(group_by)["amount"].agg(agg)
        if agg != "count":
            result = -result # Make the results positive as it might confuse LLM
        result = result.sort_values(ascending=False).round(2)

        return {
            "period": window,
            "group_by": group_by,
            "agg": agg,
            "results": {
                str(i): float(j) for i, j in result.items()
            },
        }
    except Exception as e:
        return {"error": f"Tool Spend Breakdown failed: {e}"}

"""
Tool 2 - Top Merchants

This tool helps me to identify the top n places I spend the most.
Hope, its not cafe.. haha
"""
def top_merchants(
        period=None,
        period_start=None,
        period_end=None,
        category=None,
        top_n=5,
        include_lump=False
):
    try:
        data = load_data()
        window = resolve_window(data, period, period_start, period_end)
        if "error" in window:
            return window

        df = in_period(actual_spending(data), window["start"], window["end"])
        if not include_lump:
            df = df[~df["is_lump_expense"]]
        if category:
            df = df[df["category"] == category]
        if df.empty:
            return {"error": "No spending found for these filters"}

        results = df.groupby("merchant").agg(
            total_spend=("amount", lambda s: round(-s.sum(), 2)), # Sum of amount
            visits=("amount", lambda s: int((s<0).sum())), # Exclude refund while counting the visits
        ).sort_values("total_spend", ascending=False)

        return {
            "period": window,
            "merchants": results.head(int(top_n)).reset_index().to_dict(orient="records"),
        }
    except Exception as e:
        return {"error": f"Tool Top Merchants failed: {e}"}

"""
Tool 3 - Anomaly Check

This tool helps me to find the unusually large spends in a given period.

The idea is to use IQR fence per category, fence = Q3 + threshold * IQR.
Anything above the fence is flagged.
"""
def anomaly_check(
        period=None,
        period_start=None,
        period_end=None,
        threshold=1.5,
        min_history=5
):
    """
    This function flags the purchases in the period which are above
    the category fence. The fence is built from the transactions outside
    the period, so the anomaly doesn't hide itself.

    Arguments:
        period, str, period in the user's words, eg "last month"
        period_start, str, start date
        period_end, str, end date
        threshold, float, how many IQRs above Q3 is unusual. default=1.5
        min_history, int, min purchases needed in a category. default=5
    Returns:
        dict, with flagged transactions and skipped categories
    """
    try:
        data = load_data()
        window = resolve_window(data, period, period_start, period_end)
        if "error" in window:
            return window
        if not (window["start"] and window["end"]):
            return {"error": "anomaly_check needs a period, eg 'last month', or both period_start and period_end"}

        df = actual_spending(data)
        df = df[df["amount"] < 0].assign(spend=lambda d: -d["amount"]) # Only purchases, as positive spend

        inside = (df["date"] >= pd.Timestamp(window["start"])) & (df["date"] <= pd.Timestamp(window["end"]))
        current = df[inside]
        history = df[~inside & ~df["is_lump_expense"]]

        stats = history.groupby("category")["spend"].agg(
            n="count",
            median="median",
            q1=lambda s: s.quantile(0.25),
            q3=lambda s: s.quantile(0.75),
        )
        stats = stats[stats["n"] >= min_history]
        stats["fence"] = stats["q3"] + threshold * (stats["q3"] - stats["q1"])

        checked = current.join(stats, on="category", how="inner") # Drops categories without enough history
        flagged = checked[checked["spend"] > checked["fence"]]
        skipped = sorted(set(current["category"]) - set(stats.index))

        flagged = flagged.assign(date=flagged["date"].dt.strftime("%Y-%m-%d"))
        flagged = flagged[["date", "merchant", "category", "spend", "median", "fence"]].round(2)

        return {
            "period": window,
            "flagged": flagged.to_dict(orient="records"),
            "skipped_categories": skipped,
        }
    except Exception as e:
        return {"error": f"Tool Anomaly Check failed: {e}"}

"""
Tool 4 - Recurring Bills

This tool helps me to see my bills (rent, phone, subscriptions) and
when they are due next.

Preprocessing already flags is_recurring and recurrence_period, so this
just works out the typical amount, last paid and next due date.
"""

def next_due_date(last_paid, period, as_of):
    """
    This function rolls the last paid date forward by the period until
    it reaches as_of, as the data can be older than today.
    """
    step = PERIOD_STEP.get(period)
    if step is None:
        return None
    due = last_paid + step
    while due < as_of:
        due += step
    return due

def get_recurring_bills(df, as_of):
    """
    This function builds the bill list with Timestamps. Also used by
    the weekly balance forecast.

    Arguments:
        df, DataFrame, transactions
        as_of, Timestamp, date to find the next due from
    Returns:
        list, of bill dicts
    """
    bills = []
    for merchant, group in df[df["is_recurring"]].groupby("merchant"):
        daily = group.groupby("date")["amount"].sum() # Split payment on the same day is one bill
        category = group["category"].iloc[0]
        periods = group["recurrence_period"].dropna()
        period = periods.iloc[0] if not periods.empty else default_bill_periods.get(category) # No pattern found, assume by category
        last_paid = daily.index.max()
        step = PERIOD_STEP.get(period)
        bills.append({
            "merchant": merchant,
            "category": category,
            "period": period,
            "typical_amount": round(-daily.median(), 2),
            "last_paid": last_paid,
            "next_due": next_due_date(last_paid, period, as_of),
            "active": step is None or last_paid + step * 2 >= as_of, # Not paid for 2 periods means it stopped
        })
    return bills

def recurring_bills(as_of=None):
    """
    This function returns the active bills with their next due date.

    Arguments:
        as_of, str, date to find the next due from. default=today
    Returns:
        dict, with bill details
    """
    try:
        as_of = pd.Timestamp(as_of) if as_of else pd.Timestamp.today().normalize()
        bills = get_recurring_bills(load_data(), as_of)
        fmt = lambda d: d.strftime("%Y-%m-%d") if d is not None else None

        return {
            "as_of": fmt(as_of),
            "bills": [
                {**b, "last_paid": fmt(b["last_paid"]), "next_due": fmt(b["next_due"])}
                for b in bills if b["active"]
            ],
        }
    except Exception as e:
        return {"error": f"Tool Recurring Bills failed: {e}"}

"""
Tool 5 - Weekly Balance Forecast

This tool helps me to know whether I will have enough money this week.

The idea is to split the money into three streams,
    salary - known date and amount
    bills - known date and amount (from Tool 4)
    habit spending - estimated from the daily totals of each weekday
Only the habit spending has best, median and worst cases.
"""
def weekday_habit_stats(df):
    """
    This function returns the median, best and worst daily spend for
    each weekday. Bills are excluded as they are added on their due date.
    """
    habit = actual_spending(df)
    habit = habit[~habit["is_recurring"] & ~habit["is_lump_expense"]]
    days = pd.date_range(df["date"].min(), df["date"].max())
    daily = habit.groupby("date")["amount"].sum().reindex(days, fill_value=0) # Zero spend days count too
    return daily.groupby(daily.index.day_name()).agg(
        median="median",
        best=lambda s: s.quantile(0.75),
        worst=lambda s: s.quantile(0.25),
    )

def paydays_between(start, end):
    """
    This function returns the paydays between start and end, every
    pay_cycle_days from the anchor pay date.
    """
    paydays = pd.date_range(pd.Timestamp(pay_cycle_anchor), end, freq=f"{pay_cycle_days}D")
    return set(paydays[paydays >= start])

def weekly_balance_forecast(
        current_balance,
        start_date=None,
        days=7
):
    """
    This function projects the balance for each day and flags the days
    where the worst case goes below zero.

    Arguments:
        current_balance, float, balance as of start date
        start_date, str, date to start the forecast. default=today
        days, int, number of days to forecast. default=7
    Returns:
        dict, with daily forecast and risk days
    """
    try:
        df = load_data()
        start = pd.Timestamp(start_date) if start_date else pd.Timestamp.today().normalize()
        end = start + pd.Timedelta(days=int(days) - 1)

        stats = weekday_habit_stats(df)
        salary = df.loc[df["category"] == "salary", "amount"].median()
        paydays = paydays_between(start, end)

        bills_by_day = {}
        for bill in get_recurring_bills(df, start):
            if bill["active"] and bill["next_due"] is not None and bill["next_due"] <= end:
                bills_by_day.setdefault(bill["next_due"], []).append(bill)

        running = dict.fromkeys(["median", "best", "worst"], float(current_balance))
        forecast, risk_days = [], []
        for day in pd.date_range(start, end):
            events, fixed = [], 0.0
            if day in paydays:
                fixed += salary
                events.append(f"salary +{salary:.2f}")
            for bill in bills_by_day.get(day, []):
                fixed -= bill["typical_amount"]
                events.append(f"{bill['merchant']} -{bill['typical_amount']:.2f}")

            for key in running:
                running[key] += stats.loc[day.day_name(), key] + fixed

            date = day.strftime("%Y-%m-%d")
            forecast.append({
                "date": date,
                "day_of_week": day.day_name(),
                "events": events,
                **{f"balance_{k}": round(v, 2) for k, v in running.items()},
            })
            if running["worst"] < 0:
                risk_days.append(date)

        return {"forecast": forecast, "risk_days": risk_days}
    except Exception as e:
        return {"error": f"Tool Weekly Balance Forecast failed: {e}"}

"""
Tool 6 - Pay Cycle Summary

This tool helps me to know whether I am on track this fortnight.

The idea is to compare like with like, spend by day N of this cycle vs
spend by day N of the past complete cycles.
"""
def pay_cycle_summary(cycle_id=None):
    """
    This function compares the spend so far in a pay cycle with the
    typical spend by the same day in past complete cycles.

    Arguments:
        cycle_id, int, pay cycle to check. default=latest cycle in data
    Returns:
        dict, with spend so far, typical spend and difference
    """
    try:
        df = load_data()
        spend = actual_spending(df)
        spend = spend[~spend["is_lump_expense"]]

        cycle_id = int(cycle_id) if cycle_id is not None else int(df["pay_cycle_id"].max())
        cycle_rows = df[df["pay_cycle_id"] == cycle_id]
        if cycle_rows.empty:
            return {"error": f"No data for pay cycle {cycle_id}"}
        day_reached = int(cycle_rows["days_since_payday"].max())

        spent_so_far = -spend.loc[spend["pay_cycle_id"] == cycle_id, "amount"].sum()

        past = spend[spend["cycle_complete"] & (spend["pay_cycle_id"] < cycle_id)] # Half cycles pull the median down
        if past.empty:
            return {"error": "No complete past pay cycles to compare against"}
        by_this_day = -past[past["days_since_payday"] <= day_reached].groupby("pay_cycle_id")["amount"].sum()
        full_cycle = -past.groupby("pay_cycle_id")["amount"].sum()
        typical = by_this_day.median()

        return {
            "pay_cycle_id": cycle_id,
            "cycle_start": cycle_rows["pay_cycle_start"].iloc[0].strftime("%Y-%m-%d"),
            "day_of_cycle": day_reached + 1,
            "days_left": pay_cycle_days - 1 - day_reached,
            "spent_so_far": round(spent_so_far, 2),
            "typical_by_this_day": round(typical, 2),
            "difference_vs_typical": round(spent_so_far - typical, 2),
            "typical_full_cycle": round(full_cycle.median(), 2),
            "past_cycles_compared": int(full_cycle.size),
        }
    except Exception as e:
        return {"error": f"Tool Pay Cycle Summary failed: {e}"}

"""
Tool 7 - Make Chart

This tool draws a simple bar chart of my spending on request, eg
"show me a chart of my spending by category last month".

The idea is to reuse Tool 1 and Tool 2 for the numbers, so the chart
always matches what the other tools say. matplotlib only draws it.
"""
reports_dir = os.path.join(project_dir, "output", "reports")
CHART_KINDS = ["category", "merchant", "day_of_week", "month"]
CHART_COLORS = {
    "bar": "#2a78d6",
    "text": "#0b0b0b",
    "muted": "#52514e",
    "grid": "#e4e3df",
    "surface": "#fcfcfb",
}

def draw_bar_chart(values, title, subtitle, horizontal):
    """
    This function draws one bar chart and saves it as a PNG.

    Arguments:
        values, dict, label -> amount
        title, str, chart title
        subtitle, str, the dates used
        horizontal, bool, horizontal bars for long labels (category, merchant)
    Returns:
        str, path of the saved PNG
    """
    labels, amounts = list(values), list(values.values())
    size = (8, max(3, 0.45 * len(labels) + 1.5)) if horizontal else (8, 4.5)
    fig, ax = plt.subplots(figsize=size)
    fig.patch.set_facecolor(CHART_COLORS["surface"])
    ax.set_facecolor(CHART_COLORS["surface"])

    if horizontal:
        bars = ax.barh(labels[::-1], amounts[::-1], height=0.6, color=CHART_COLORS["bar"]) # Biggest on top
        value_axis, label_axis = ax.xaxis, ax.yaxis
    else:
        bars = ax.bar(labels, amounts, width=0.6, color=CHART_COLORS["bar"])
        value_axis, label_axis = ax.yaxis, ax.xaxis
        ax.tick_params(axis="x", labelrotation=30 if len(labels) > 7 else 0)

    ax.bar_label(bars, fmt="${:,.0f}", padding=3, fontsize=9, color=CHART_COLORS["muted"])
    value_axis.set_major_formatter(StrMethodFormatter("${x:,.0f}"))
    value_axis.grid(True, color=CHART_COLORS["grid"], linewidth=0.8)
    label_axis.grid(False)
    ax.set_axisbelow(True)
    for side in ["top", "right", "bottom" if horizontal else "left"]: # Keep only the baseline
        ax.spines[side].set_visible(False)
    for spine in ax.spines.values():
        spine.set_color(CHART_COLORS["grid"])
    ax.tick_params(colors=CHART_COLORS["muted"], labelsize=9, length=0)

    fig.suptitle(title, x=0.02, ha="left", fontsize=13, fontweight="bold", color=CHART_COLORS["text"])
    ax.set_title(subtitle, loc="left", fontsize=9, color=CHART_COLORS["muted"])
    fig.tight_layout()

    os.makedirs(reports_dir, exist_ok=True)
    path = os.path.join(reports_dir, f"{title.lower().replace(' ', '_')}_{pd.Timestamp.now():%Y%m%d_%H%M%S}.png")
    fig.savefig(path, dpi=150, facecolor=CHART_COLORS["surface"])
    plt.close(fig)
    return path

def make_chart(
        kind="category",
        period=None,
        top_n=10
):
    """
    This function gets the numbers from Tool 1 or Tool 2 and draws them
    as a bar chart.

    Arguments:
        kind, str, one of CHART_KINDS. default="category"
        period, str, period in the user's words, eg "last month"
        top_n, int, max bars for category and merchant. default=10
    Returns:
        dict, with chart path, period and the values drawn
    """
    try:
        # The LLM sends things like "spend per category" or "day of week", so match loosely
        text = str(kind).lower().replace(" ", "_")
        kind = next((k for k in CHART_KINDS if k in text), None)
        if kind is None:
            return {"error": f"kind must be one of {CHART_KINDS}"}

        if kind == "merchant":
            out = top_merchants(period=period, top_n=top_n)
            if "error" in out:
                return out
            values = {m["merchant"]: m["total_spend"] for m in out["merchants"]}
        else:
            group_by = "month_name" if kind == "month" else kind
            out = spend_breakdown(period=period, group_by=group_by)
            if "error" in out:
                return out
            values = out["results"]

        # Days and months read in calendar order, not by size
        if kind == "day_of_week":
            values = {d: values.get(d, 0.0) for d in calendar.day_name}
        elif kind == "month":
            values = {m: values[m] for m in calendar.month_name if m in values}
        else:
            values = dict(list(values.items())[:int(top_n)])

        window = out["period"]
        if window["start"] or window["end"]:
            subtitle = f"{window['start'] or 'start'} to {window['end'] or 'end'}"
        else:
            subtitle = "All data"
        if window.get("note"):
            subtitle += f" ({window['note']})"

        title = f"Spend by {kind.replace('_', ' ')}"
        path = draw_bar_chart(values, title, subtitle, horizontal=kind in ["category", "merchant"])

        return {"chart_path": path, "kind": kind, "period": window, "values": values}
    except Exception as e:
        return {"error": f"Tool Make Chart failed: {e}"}