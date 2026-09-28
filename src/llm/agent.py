import ollama
import json
from src.helper.helper import model as model_name
from src.tools.tool import (
    weekly_balance_forecast, spend_breakdown, top_merchants, anomaly_check
)

model = model_name

SYSTEM_PROMPT = """
Role:
You are a personal finance assistant answering questions about the user's
own bank transactions.

Rules:
- Never compute numbers yourself. Always call the correct tool and use its
  returned values in your answer.
- If a question needs more than one tool (e.g. a breakdown and an anomaly
  check), call each tool separately.
- If a required detail (like a date range or a current balance) is missing
  from the question, ask the user for it instead of guessing.
- Keep answers short and in plain language, quoting the real numbers the
  tools returned.
"""

tool_registry = {
    "weekly_balance_forecast": weekly_balance_forecast,
    "spend_breakdown": spend_breakdown,
    "top_merchants": top_merchants,
    "anomaly_check": anomaly_check,
}

tools = [
    {
        "type": "function",
        "function": {
            "name": "weekly_balance_forecast",
            "description": "Project the account balance for the next 7 days using historical weekday spending medians, and flag any day that risks going below zero.",
            "parameters": {
                "type": "object",
                "properties": {
                    "current_balance": {"type": "number", "description": "The user's current account balance"},
                    "start_date": {"type": "string", "description": "YYYY-MM-DD date to start the forecast from, defaults to today"},
                    "scheduled_inflows": {"type": "object", "description": "Optional map of YYYY-MM-DD date to a known incoming amount, e.g. salary"}
                },
                "required": ["current_balance"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "spend_breakdown",
            "description": "Aggregate the user's spending over a date range, grouped by a chosen dimension such as category, spend_type, day_of_week, month_name or merchant.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period_start": {"type": "string", "description": "YYYY-MM-DD start date, optional"},
                    "period_end": {"type": "string", "description": "YYYY-MM-DD end date, optional"},
                    "group_by": {"type": "string", "description": "Column to group by: category, spend_type, day_of_week, month_name, or merchant"},
                    "agg": {"type": "string", "description": "Aggregation to apply: sum, mean, median or count"}
                },
                "required": ["group_by"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "top_merchants",
            "description": "Rank merchants by total real spend (excludes transfers and salary) over an optional date range and category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period_start": {"type": "string", "description": "YYYY-MM-DD start date, optional"},
                    "period_end": {"type": "string", "description": "YYYY-MM-DD end date, optional"},
                    "category": {"type": "string", "description": "Only rank merchants within this category, optional"},
                    "top_n": {"type": "integer", "description": "How many merchants to return"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "anomaly_check",
            "description": "Find transactions in a date range that are unusually large compared to that category's normal historical range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period_start": {"type": "string", "description": "YYYY-MM-DD start date"},
                    "period_end": {"type": "string", "description": "YYYY-MM-DD end date"},
                    "threshold": {"type": "number", "description": "How many IQRs below the normal range counts as anomalous, defaults to 1.5"}
                },
                "required": ["period_start", "period_end"]
            }
        }
    }
]

def run_tool_calls(tool_calls):
    results = []
    for call in tool_calls:
        name = call.function.name
        args = call.function.arguments or {}
        fn = tool_registry.get(name)
        if not fn:
            output = f"Unknown tool {name}"
        else:
            try:
                output = fn(**args)
            except Exception as e:
                output = f"Tool {name} failed, {e}"
        results.append({"name": name, "output": output})
    return results

def ask(query):
    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": query}
        ]

        response = ollama.chat(model=model, messages=messages, tools=tools)
        messages.append(response.message)

        if not response.message.tool_calls:
            return response.message.content

        for result in run_tool_calls(response.message.tool_calls):
            messages.append({
                "role": "tool",
                "name": result["name"],
                "content": json.dumps(result["output"], default=str)
            })

        final = ollama.chat(model=model, messages=messages)
        return final.message.content
    except Exception as e:
        print(f"Failed to answer query, {e}")
