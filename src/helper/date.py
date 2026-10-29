import re
import calendar
import pandas as pd
from src.helper.config import pay_cycle_anchor, pay_cycle_days

"""
Date Helper

This helper turns the period in the user's words ("last month", "July",
"this pay cycle") into a start and end date. So the LLM only copies the
phrase and never works out the dates itself.

Rules:
    - Weeks start on Monday.
    - "last week/month/quarter/year" is the full calendar period before this one.
    - "last N days/weeks/months" is rolling and ends today (includes today).
    - A month or quarter without a year is the most recent one that isn't in
      the future ("November" asked in Oct 2026 is Nov 2025).
    - Ranges never go past today and are clipped to the dates in the data.
"""

DATE = r"\d{4}-\d{2}-\d{2}"
MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
MONTHS["sept"] = 9
MONTH = "(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")(?: (\d{4}))?" # Longest first, so "september" before "sep"
ONE_DAY = pd.Timedelta(days=1)
EXAMPLES = "'last month', 'July', 'Q2', 'since March', 'last 3 weeks', 'this pay cycle' or 'YYYY-MM-DD to YYYY-MM-DD'"

def period_bounds(day, unit):
    """
    This function returns the start and end of the calendar week, month,
    quarter or year that the day falls in.
    """
    if unit == "week":
        start = day - pd.Timedelta(days=day.weekday()) # Monday is 0
        return start, start + pd.Timedelta(days=6)
    p = pd.Period(day, freq={"month": "M", "quarter": "Q", "year": "Y"}[unit])
    return p.start_time.normalize(), p.end_time.normalize()

def month_bounds(name, year, today):
    """
    This function returns the start and end of the month. Without a year,
    it picks the most recent one that isn't in the future.
    """
    month = MONTHS[name]
    if year:
        year = int(year)
    else:
        year = today.year if month <= today.month else today.year - 1
    return period_bounds(pd.Timestamp(year, month, 1), "month")

def pay_cycle_bounds(day, offset=0):
    """
    This function returns the start and end of the pay cycle the day falls
    in. Same formula as populate_pay_cycle, so the cycles always match.

    Arguments:
        day, Timestamp, any day in the cycle
        offset, int, -1 for the cycle before. default=0
    Returns:
        tuple, (start, end)
    """
    anchor = pd.Timestamp(pay_cycle_anchor)
    cycle_id = (day - anchor).days // pay_cycle_days + offset
    start = anchor + pd.Timedelta(days=cycle_id * pay_cycle_days)
    return start, start + pd.Timedelta(days=pay_cycle_days - 1)

def parse_period(text, today):
    """
    This function matches the phrase against each pattern in order and
    returns the calendar range. It doesn't clip anything.

    Arguments:
        text, str, period in the user's words
        today, Timestamp, date the question is asked
    Returns:
        tuple, (start, end) or None if the phrase is not understood
    """
    text = " ".join(text.lower().split())
    text = re.sub(r"^(?:in|during|for|over) (?:the )?|^the ", "", text) # "in the last month" -> "last month"

    if m := re.fullmatch(rf"({DATE}) (?:to|until) ({DATE})", text):
        return pd.Timestamp(m[1]), pd.Timestamp(m[2])
    if re.fullmatch(DATE, text):
        return pd.Timestamp(text), pd.Timestamp(text)
    if text == "today":
        return today, today
    if text == "yesterday":
        return today - ONE_DAY, today - ONE_DAY
    if m := re.fullmatch(r"(this|last) pay ?cycle", text):
        return pay_cycle_bounds(today, 0 if m[1] == "this" else -1)
    if m := re.fullmatch(r"(this|last) (week|month|quarter|year)", text):
        start, end = period_bounds(today, m[2])
        return period_bounds(start - ONE_DAY, m[2]) if m[1] == "last" else (start, end)
    if m := re.fullmatch(r"(?:last|past) (\d+) (day|week|month)s?", text):
        n = int(m[1])
        step = {"day": pd.DateOffset(days=n), "week": pd.DateOffset(weeks=n), "month": pd.DateOffset(months=n)}[m[2]]
        return today - step + ONE_DAY, today
    if m := re.fullmatch(r"q([1-4])(?: (\d{4}))?", text):
        q = int(m[1])
        year = int(m[2]) if m[2] else (today.year if q <= today.quarter else today.year - 1)
        return period_bounds(pd.Timestamp(year, 3 * q - 2, 1), "quarter")
    if m := re.fullmatch(rf"since {MONTH}", text):
        return month_bounds(m[1], m[2], today)[0], today
    if m := re.fullmatch(rf"{MONTH} to {MONTH}", text):
        return month_bounds(m[1], m[2], today)[0], month_bounds(m[3], m[4], today)[1]
    if m := re.fullmatch(MONTH, text):
        return month_bounds(m[1], m[2], today)
    return None

def resolve_period(text, today=None, data_start=None, data_end=None):
    """
    This function turns the phrase into the dates a tool should use. The
    range is clipped to today and to the data, with a note when it is.

    Arguments:
        text, str, period in the user's words
        today, str/Timestamp, date the question is asked. default=today
        data_start, Timestamp, first date in the data
        data_end, Timestamp, last date in the data
    Returns:
        dict, with start, end, label and note, or an error
    """
    today = pd.Timestamp(today or pd.Timestamp.today()).normalize()
    bounds = parse_period(text, today)
    if bounds is None:
        return {"error": f"Could not understand the period '{text}'. Try {EXAMPLES}"}

    start, end = bounds
    end = min(end, today)
    notes = []
    if data_start is not None and start < data_start:
        start = data_start
        notes.append(f"data starts on {data_start:%d %b %Y}")
    if data_end is not None and end > data_end:
        end = data_end
        notes.append(f"data ends on {data_end:%d %b %Y}")
    if start > end:
        # Nothing left, an empty result would read as $0 spent
        covers = f". Data covers {data_start:%d %b %Y} to {data_end:%d %b %Y}" if data_end is not None else ""
        return {"error": f"No data for '{text}'{covers}"}

    return {
        "start": f"{start:%Y-%m-%d}",
        "end": f"{end:%Y-%m-%d}",
        "label": text,
        "note": ", ".join(notes) or None,
    }
