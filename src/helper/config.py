# Regex/lookup patterns for cleaning a transaction description down to the
# merchant name. Trailing country/state/suburb tokens are stripped, not kept.
# Built by mining output/valid_transaction.json - add new tokens here as new
# statements bring in new suburbs/states.

country_pattern = r"\b(aus|au|australia|usa|us)$"

state_pattern = r"\b(act|ac|nsw|ns|vic|vi|qld|ca|mn)$"

# The bank truncates long tails, so "canberra city" can arrive as "canberra c"/"canberra ci".
city_pattern = r"\b(canberra(?: c| ci| cit)?|brisbane|north sydney|sydney|melbourne|" \
               r"san francisco|bloomington)$"

suburb_pattern = r"\b(acton|fyshwick|braddon|dickson|gungahli|o'connor|" \
                  r"city|belconnen|griffith|macquariepark|mascot|" \
                    r"campbelltown|torrens|woden|florey|charnwood|parkes|" \
                    r"nicholls|zetland|mosman|green point|bella vista|bentleigh eas(?:t)?)$"

# Payment-channel text the bank appends after the merchant (BPAY refs, help URLs).
payment_suffix_pattern = r"\b(commbank app bpay|netbank bpay|bpay|help\.uber\.\S*)$"

# Payment-channel text the bank puts before the merchant.
payment_prefixes = ["direct debit", "direct credit"]

# Card-processor prefixes (Square, Lightspeed, Worldline, ...). Only stripped
# as the first word, e.g. "sq *cheesymoon" -> "cheesymoon".
processor_prefixes = ["sq", "sp", "ls", "zlr", "wl", "smp"]

# Bank descriptions sometimes glue two tail tokens together with no space
# (e.g. "actau" = "act" + "au"). Only applied to the last word while the
# location tail is being peeled, so "flo coffee" isn't rewritten.
glued_token_fixes = {
    "actau": "act au",
    "cityau": "city au",
    "canbe": "canberra",
    "braddo": "braddon",
    "torre": "torrens",
    "flo": "florey",
    "ltbrisbane": "brisbane",
    "nationa": "national"
}

# Standalone tokens that carry no merchant meaning (company suffixes, filler
# words, separators). A "-" inside a word ("7-eleven") is kept.
noise_words = ["pty", "ltd", "limited", "stores", "retail", "-", "*", ","]

transfer_prefixes = ["transfer from", "transfer to", "fast transfer from",
                      "fast transfer to"]

self_transfer_prefixes = ["transfer from xx8798", "transfer to xx8798", 
                          "fast transfer from hariharasudhan", "fast transfer to hariharasudhan",
                          "fast transfer from xx8798", "fast transfer to xx8798"]

smart_saving_prefixes = ["approved smart savings debit"]

return_prefixes = ["return"]

# Category -> spend_type. Anything not listed in either falls into "others"
# (transfers, salary - money movement, not spend).
essential_categories = ["rent", "groceries", "utilities", "health_fitness",
                         "education", "transport", "personal_care", "refund"]

discretionary_categories = ["dining_out", "shopping", "vending", "cafe",
                             "subscriptions", "entertainment", "fee_charges"]

shared_expense_categories = ["shared_expenses"]

self_transfer_categories = ["self_transfer", "smart_savings"]

# Labels assigned by rules in extract_merchant - used as both merchant and category.
special_labels = ["self_transfer", "shared_expenses", "refund", "smart_savings"]

# Categories the LLM is allowed to return. Anything else is rejected.
llm_categories = [c for c in essential_categories + discretionary_categories
                  if c not in special_labels] + ["salary", "unknown"]

# Merchant -> category pins. Win over the LLM and the cache.
category_overrides = {
    "the australian national": "education",
    "the australian national university": "education",
    "anu": "education",
    "salary intercontinental": "salary",
}

# Transactions at or below this amount are treated as one-off lump expenses
# (e.g. tuition) and excluded from recurring-spend analysis.
lump_expense_threshold = -2000
