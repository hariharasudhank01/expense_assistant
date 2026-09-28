# All regex/lookup patterns for splitting a transaction description into
# merchant, suburb, state and country. Built by mining output/valid_transaction.json -
# add new tokens here as new statements bring in new suburbs/states.

country_pattern = r"(aus|au|australia)$"

state_pattern = r"(act|ac|nsw|ns|ca)$"

suburb_pattern = r"(canberra|acton|fyshwick|braddon|dickson|gungahli|o'connor|" \
                  r"brisbane|north sydney|sydney|san francisco|city|belconnen|griffith)$"

# Bank descriptions sometimes glue two tail tokens together with no space
# (e.g. "actau" = "act" + "au"). Fix these before splitting.
glued_token_fixes = {
    "actau": "act au",
    "cityau": "city au",
    "canbe": "canberra",
    "braddo": "braddon"
}

# Standalone tokens that carry no merchant/location meaning (store numbers,
# reference numbers, processor prefixes, filler words).
noise_words = ["pty", "ltd", "limited", "stores", "retail", "-", "*", ","]

# Rows that describe money movement rather than a purchase. Detected by a
# leading phrase, not location tokens, so they skip the location split.
transfer_prefixes = ["transfer from", "transfer to", "fast transfer from",
                      "fast transfer to", "direct credit", "direct debit", "salary"]

# Normalise abbreviations once a token has been identified as state/country.
state_normalise = {
    "act": "ACT",
    "ac": "ACT",
    "nsw": "NSW",
    "ns": "NSW",
    "ca": "CA",
}

country_normalise = {
    "aus": "Australia",
    "au": "Australia",
}

# Category -> spend_type. Anything not listed in either falls into "others"
# (transfers, salary - money movement, not spend).
essential_categories = ["rent", "groceries", "utilities", "health_fitness",
                         "education", "transport", "personal_care"]

discretionary_categories = ["dining_out", "shopping", "vending", "cafe",
                             "subscriptions", "entertainment", "fee_charges"]

# Transactions at or below this amount are treated as one-off lump expenses
# (e.g. tuition) and excluded from recurring-spend analysis.
lump_expense_threshold = -2000
