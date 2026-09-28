import ollama
from pydantic import BaseModel

SYSTEM_PROMTP="""
Role:
You classify Australian bank transaction descriptions into a spending category.

Task:
For each transaction description given, identify the merchant name and 
assign exactly one category from this fixed list. Do not invent new 
categories or use any label outside this list:

- groceries
- dining_out
- cafe
- transport
- shopping
- subscriptions
- utilities
- health_fitness
- education
- entertainment
- transfer
- unknown
- salary
- rent

Rules:
- If the merchant is a supermarket (coles, woolworths, aldi, iga), use "groceries".
- If the merchant is a fast food(gyg, kfc, Mcd), restaurant, takeaway, or food delivery app, use "dining_out".
- If the merchant is a coffee shop or bakery, use "cafe".
- If the merchant is a rideshare, public transport, fuel station, or parking, use "transport".
- If the transaction is a transfer between accounts, a payment to a person, 
  or a refund, use "transfer" (this describes the type of movement, not what 
  it was for).
- If the transaction is a Intercontinental, use "salary"
- If the transaction is unilodge or archer, use "rent"
- If the transaction is related to providers like actewagle or felix, use "utilities"
- If the transaction is related to Subscription like Netflix or Prime or Disney or OpenAI or Claude, use "subscriptions"
- If a transaction starts with "sq" it will mostly be cafe or dining_out, remove the sq and analyse
- If you cannot confidently match the merchant to any category, use "unknown". 
  Do not guess.

Respond with JSON only, matching this shape exactly - no markdown, no extra text:

Examples:
"subway fyshwick 337 canberra au" -> {"merchant": "subway", "category": "dining_out"}
"woolworths 442 belconnen" -> {"merchant": "woolworths", "category": "groceries"}
"uber *trip help.uber.com" -> {"merchant": "uber", "category": "transport"}
"spotify p1234567" -> {"merchant": "spotify", "category": "subscriptions"}
"transfer to j smith" -> {"merchant": "j smith", "category": "transfer"}
"anytime fitness canberra" -> {"merchant": "anytime fitness", "category": "health_fitness"}

"""

class Response(BaseModel):
    merchant: str
    category: str

def categorise_transaction(transactions):
    try:
        response = ollama.chat(
            model="gpt-oss:20b-cloud",
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

