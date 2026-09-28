import pandas as pd
import numpy as np
import re
import os
from src.transform.llm import categorise_transaction
from src.helper.helper import read_json, write_json, project_dir
from src.helper.config import (
    country_pattern, state_pattern, suburb_pattern,
    glued_token_fixes, noise_words, transfer_prefixes,
    state_normalise, country_normalise,
    essential_categories, discretionary_categories, lump_expense_threshold
)

merchant_category_path = os.path.join(project_dir, "output", "merchant_category.json")

def fix_glued_tokens(text):
    for glued, fixed in glued_token_fixes.items():
        text = re.sub(rf"\b{re.escape(glued)}\b", fixed, text)
    return text

def strip_noise(text):
    for word in noise_words:
        text = text.replace(word, " ")
    text = re.sub(r"\b\d+\b", " ", text)   # standalone reference/store numbers
    text = re.sub(r"\s+", " ", text).strip()
    return text

def is_transfer(text):
    return any(text.startswith(prefix) for prefix in transfer_prefixes)

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

def split_transaction_detail(text):
    text = fix_glued_tokens(text)
    text = strip_noise(text)

    if is_transfer(text):
        return pd.Series([text, "unknown", "unknown", "unknown"])

    text, country = peel_tail(text, country_pattern)
    text, state = peel_tail(text, state_pattern)
    text, suburb = peel_tail(text, suburb_pattern)

    merchant = text.strip()
    state = state_normalise.get(state, "unknown")
    country = country_normalise.get(country.split()[-1], "unknown") if country else "unknown"
    suburb = suburb if suburb else "unknown"

    return pd.Series([merchant, suburb, state, country])

def populate_categories(df):
    cache = read_json(merchant_category_path) if os.path.exists(merchant_category_path) else {}
    unique_merchants = df["merchant"].unique()

    for merchant in unique_merchants:
        if merchant in cache:
            continue
        category = categorise_transaction(merchant)
        cache[merchant] = category if category else "unknown"

    write_json(cache, merchant_category_path)
    df["category"] = df["merchant"].map(cache)
    return df

def populate_spend_type(df):
    conditions = [
        df["category"].isin(essential_categories),
        df["category"].isin(discretionary_categories),
    ]
    choices = ["essential", "discretionary"]
    df["spend_type"] = np.select(conditions, choices, default="others")
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
    df[["merchant", "suburb", "state", "country"]] = df["transaction_details"].apply(split_transaction_detail)
    df = populate_categories(df)
    df = populate_spend_type(df)
    return df
