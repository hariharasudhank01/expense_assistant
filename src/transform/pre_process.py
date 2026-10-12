import pandas as pd
import numpy as np
import re
import os
from src.transform.llm import categorise_transaction
from src.helper.helper import read_json, write_json, project_dir
from src.helper.config import (
    country_pattern, state_pattern, suburb_pattern, city_pattern, payment_suffix_pattern,
    payment_prefixes, processor_prefixes,
    glued_token_fixes, noise_words, transfer_prefixes, self_transfer_prefixes, return_prefixes,
    smart_saving_prefixes, essential_categories, discretionary_categories, lump_expense_threshold,
    special_labels, llm_categories, category_overrides, self_transfer_categories, shared_expense_categories
)

merchant_category_path = os.path.join(project_dir, "output", "merchant_category.json")

tail_patterns = [country_pattern, state_pattern, city_pattern, suburb_pattern, payment_suffix_pattern]

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

    text = strip_prefix(text, payment_prefixes)
    cleaned = text

    # Location and payment tokens alternate in any order ("canberra city
    # canberra city au aus"), so keep fixing glued words and peeling every
    # tail pattern until nothing changes.
    while True:
        before = text
        text = fix_glued_tail(text)
        for pattern in tail_patterns:
            text, _ = peel_tail(text, pattern)
        if text == before:
            break

    # A description that is only a location ("woden") would leave nothing.
    return text.strip() or cleaned

def populate_categories(df):
    cache = read_json(merchant_category_path) if os.path.exists(merchant_category_path) else {}

    for merchant in df["merchant"].unique():
        if merchant in special_labels or merchant in category_overrides:
            continue
        # Re-ask for entries an older run cached with an invalid label.
        if cache.get(merchant) in llm_categories:
            continue
        category = categorise_transaction(merchant)
        # Failed calls aren't cached, so they're retried on the next run.
        if category:
            cache[merchant] = category

    write_json(cache, merchant_category_path)
    lookup = {**cache, **category_overrides, **{label: label for label in special_labels}}
    df["category"] = df["merchant"].map(lookup).fillna("unknown")
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

def run(filename):
    df = pd.read_json(filename)
    df = handle_dtypes(df)
    df = populate_date(df)
    df["merchant"] = df["transaction_details"].apply(extract_merchant)
    df = populate_categories(df)
    df = populate_spend_type(df)
    return df
