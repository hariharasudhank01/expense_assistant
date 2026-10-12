import ollama
from typing import Literal
from pydantic import BaseModel
from src.helper.config import llm_categories
from src.helper.helper import categorise_model

SYSTEM_PROMTP=f"""
Role:
You classify Australian merchant names from bank statements into a spending category.

Task:
You are given a cleaned merchant name (store numbers, locations and card-processor
prefixes like "sq *" are already removed; names may be cut short by the bank).
Return the merchant name and exactly one category from this fixed list. Do not
invent new categories or use any label outside this list:

{chr(10).join(f"- {c}" for c in llm_categories)}

Rules:
- If the merchant is a supermarket or grocer (coles, woolworths, aldi, iga), use "groceries".
- If the merchant is fast food (gyg, kfc, mcd), a restaurant, takeaway, or food delivery app, use "dining_out".
- If the merchant is a coffee shop, bakery, juice or dessert bar, use "cafe".
- If the merchant is a rideshare, public transport, fuel station, or parking, use "transport".
- If the merchant is a pharmacy, chemist, hairdresser or barber, use "personal_care".
- If the merchant is a vending machine operator (e.g. cocacolaepp), use "vending".
- If the merchant is a bank fee, ATM fee or international transaction fee, use "fee_charges".
- If the merchant is intercontinental, use "salary".
- If the merchant is unilodge or archer, use "rent".
- If the merchant is a utility or phone provider (actewagl, felix), use "utilities".
- If the merchant is a subscription (netflix, prime, disney, openai, claude, spotify), use "subscriptions".
- If you cannot confidently match the merchant to any category, use "unknown".
  Do not guess.

Respond with JSON only, matching this shape exactly - no markdown, no extra text:

Examples:
"subway" -> {{"merchant": "subway", "category": "dining_out"}}
"woolworths" -> {{"merchant": "woolworths", "category": "groceries"}}
"uber trip" -> {{"merchant": "uber", "category": "transport"}}
"spotify p1234567" -> {{"merchant": "spotify", "category": "subscriptions"}}
"anytime fitness" -> {{"merchant": "anytime fitness", "category": "health_fitness"}}
"chemist on northbourne" -> {{"merchant": "chemist on northbourne", "category": "personal_care"}}

"""

# The enum in the JSON schema constrains the model to the allowed categories,
# and pydantic rejects anything else.
Category = Literal[tuple(llm_categories)]

class Response(BaseModel):
    merchant: str
    category: Category

def categorise_transaction(transactions):
    try:
        response = ollama.chat(
            model=categorise_model,
            messages=[
                {"role": "system",
                 "content": SYSTEM_PROMTP},
                 {"role": "user",
                  "content": transactions}
            ],
            format=Response.model_json_schema()
        )
        resp = Response.model_validate_json(response.message.content)
        return resp.category
    except Exception as e:
        print(f"Failed, {e}")

