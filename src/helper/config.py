import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# Regex/lookup patterns for cleaning a transaction description down to the
# merchant name. Trailing country/state/city/suburb tokens are stripped, not
# kept. Add new places to the lists below as new statements bring them in -
# truncated tails ("isabella plai", "canberr") are matched automatically.

# Foreign rows end in a 2- and 3-letter ISO pair ("my mys", "ir irl").
country_pattern = r"\b(aus|au|aust|australia|usa|us|my mys|ir irl|gb gbr|nz nzl|sg sgp|in ind)$"

state_pattern = r"\b(act|ac|nsw|ns|vic|vi|qld|ca|mn)$"

# Cities and unambiguous city words. Stripped from the tail AND used to cut a
# branch name out of the middle ("ikea canberra majura" -> "ikea").
# The bank truncates long tails, so "canberra city" can arrive as "canberra c"/"canberra ci".
cities = ["canberra", "canberra c", "canberra ci", "canberra cit", "cbr", "civic",
          "sydney", "north sydney", "brisbane", "melbourne", "perth", "adelaide",
          "hobart", "darwin", "gold coast", "newcastle", "wollongong", "queanbeyan",
          "san francisco", "bloomington", "seattle", "sepang"]

# Suburbs. Only stripped from the tail - many are ordinary words (cook, hall,
# page, watson) that could be part of a real merchant name.
act_suburbs = [
    "acton", "ainslie", "amaroo", "aranda", "banks", "barton", "beard", "belconnen",
    "bonner", "bonython", "braddon", "bruce", "calwell", "campbell", "capital hill",
    "casey", "chapman", "charnwood", "chifley", "chisholm", "city", "conder", "cook",
    "coombs", "crace", "curtin", "deakin", "denman prospect", "dickson", "downer",
    "duffy", "dunlop", "evatt", "fadden", "farrer", "fisher", "florey", "flynn",
    "forde", "forrest", "franklin", "fraser", "fyshwick", "garran", "gilmore",
    "giralang", "gordon", "gowrie", "greenway", "griffith", "gungahlin", "gungahli",
    "hackett", "hall", "harrison", "hawker", "higgins", "holder", "holt", "hughes",
    "hume", "isaacs", "isabella plains", "jacka", "kaleen", "kambah", "kingston",
    "latham", "lawson", "lyneham", "lyons", "macarthur", "macgregor", "macnamara",
    "macquarie", "majura", "majura park", "mawson", "mckellar", "melba", "mitchell",
    "molonglo", "monash", "narrabundah", "ngunnawal", "nicholls", "o'connor",
    "o'malley", "oxley", "page", "palmerston", "parkes", "pearce", "phillip",
    "pialligo", "red hill", "reid", "richardson", "rivett", "russell", "scullin",
    "spence", "stirling", "strathnairn", "symonston", "taylor", "tharwa", "theodore",
    "throsby", "torrens", "tuggeranong", "turner", "wanniassa", "waramanga",
    "watson", "weetangera", "weston", "whitlam", "woden", "wright", "yarralumla",
]

other_suburbs = ["macquarie park", "macquariepark", "mascot", "campbelltown", "zetland",
                 "currans hill", "abbotsford", "chatswood", "miranda", "parramatta", "jolimont",
                 "mosman", "green point", "bella vista", "bentleigh east", "mount annan"]

suburbs = act_suburbs + other_suburbs

# Payment-channel text the bank appends after the merchant (BPAY refs, help URLs).
# A trailing web address needs a word before it, so "netflix.com" alone is kept.
payment_suffix_pattern = r"\s(commbank app bpay|netbank bpay|bpay|help\.uber\.\S*|\S+\.com\S*)$"

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
    "nationa": "national",
    "nswau": "nsw au",
    "courau": "court au",
    "ato": "australian taxation office"
}

# Standalone tokens that carry no merchant meaning (company suffixes, filler
# words, separators). A "-" inside a word ("7-eleven") is kept.
noise_words = ["pty", "ltd", "limited", "stores", "retail", "-", "*", ","]

transfer_prefixes = ["transfer from", "transfer to", "fast transfer from",
                      "fast transfer to"]

self_transfer_prefixes = ["transfer from xx8798", "transfer to xx8798", 
                          "fast transfer from hariharasudhan", "fast transfer to hariharasudhan",
                          "fast transfer from xx8798", "fast transfer to xx8798",
                          "hariharasudhan kalyanasundaram"]

smart_saving_prefixes = ["approved smart savings debit"]

return_prefixes = ["return"]

int_transfer_prefixes = ["rmtly"]

# Category -> spend_type. Anything not listed in either falls into "others"
# (transfers, salary - money movement, not spend).
essential_categories = ["rent", "groceries", "utilities", "health_fitness",
                         "education", "transport", "personal_care", "refund", "laundry"]

discretionary_categories = ["dining_out", "shopping", "vending", "cafe",
                             "subscriptions", "entertainment", "fee_charges", "liquor",
                             "delivery"]

shared_expense_categories = ["shared_expenses"]

self_transfer_categories = ["self_transfer", "smart_savings"]

# Labels assigned by rules in extract_merchant - used as both merchant and category.
special_labels = ["self_transfer", "shared_expenses", "refund", "smart_savings", "international_transfer"]

# Categories the LLM is allowed to return. Anything else is rejected.
llm_categories = [c for c in essential_categories + discretionary_categories
                  if c not in special_labels] + ["salary", "unknown"]

# Merchant -> category pins. Win over the LLM and the cache.
category_overrides = {
    "the australian national": "education",
    "the australian national university": "education",
    "anu": "education",
    "salary intercontinental": "salary",
    "australian taxation office": "tax",
    "ato": "tax",
    "unilodge": "laundry"
}

# Transactions at or below this amount are treated as one-off lump expenses
# (e.g. tuition) and excluded from recurring-spend analysis.
lump_expense_threshold = -2000

# Rent rules. Update the amount once the rent changes
rent_rules = [
    {"payee": "a thatte", "amount": float(os.environ.get("RENT"))},
    {"payee": "archer", "amount": float(os.environ.get("RENT"))}
]

# Recurring payments. A merchant is recurring by pattern when the gaps between
# its payments fit one of these periods and the amounts are similar.
recurring_periods = {"weekly": 7, "fortnightly": 14, "monthly": 30, "yearly": 365}
recurring_gap_tolerance = 3          # +- days around the period
recurring_min_occurrences = 3        # payment days needed to see a pattern
recurring_gap_match_share = 0.7      # share of gaps that must fit the period
recurring_max_amount_spread = 0.15   # typical distance from the median amount, as a share of it

# Bills are recurring even when irregular (utilities) or too new to show a pattern.
fixed_bill_categories = ["rent", "utilities", "subscriptions"]

# Habits, not bills - never recurring even when they look regular.
recurring_excluded_categories = ["groceries", "cafe", "dining_out", "shopping",
                                 "transport", "liquor", "delivery", "vending"]

pay_cycle_days = 14
pay_cycle_anchor = os.environ.get("ANCHOR_PAY_DATE")