import ollama
import json
import pandas as pd
from src.helper.helper import model as model_name
from src.tools.tool import (
    load_data, weekly_balance_forecast, spend_breakdown, top_merchants, anomaly_check,
    recurring_bills, pay_cycle_summary, make_chart, ALLOWED_GROUP_BY, ALLOWED_AGG, CHART_KINDS
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
- For a time period, pass the user's own words as `period` (e.g. "last month",
  "July", "this pay cycle"). Never convert it to dates yourself.
- Always state the dates from the tool's `period` in your answer, and mention
  its `note` if there is one (e.g. the data ends earlier).
- If the user asks for a chart, graph or plot, call make_chart. The chart is
  shown to them automatically, so just summarise it in one or two sentences.
  Never add image links or markdown images.
- If a required detail (like a current balance) is missing from the question,
  ask the user for it instead of guessing.
- Keep answers short and in plain language, quoting the real numbers the
  tools returned.
"""

PERIOD_DESCRIPTION = (
    "Time period in the user's own words, e.g. 'last month', 'July', 'Q2', 'since March', "
    "'last 3 weeks', 'this pay cycle'. Copy the phrase, don't convert it to dates. Optional"
)

def system_prompt():
    """
    This function adds today's date and the data range to the prompt. Built
    on every question, as the UI can run across days.
    """
    dates = load_data()["date"]
    return SYSTEM_PROMPT + (
        f"\nToday is {pd.Timestamp.today():%Y-%m-%d}. "
        f"Transaction data covers {dates.min():%Y-%m-%d} to {dates.max():%Y-%m-%d}.\n"
    )

tool_registry = {
    "weekly_balance_forecast": weekly_balance_forecast,
    "spend_breakdown": spend_breakdown,
    "top_merchants": top_merchants,
    "anomaly_check": anomaly_check,
    "recurring_bills": recurring_bills,
    "pay_cycle_summary": pay_cycle_summary,
    "make_chart": make_chart,
}

tools = [
    {
        "type": "function",
        "function": {
            "name": "weekly_balance_forecast",
            "description": "Project the account balance for the next 7 days using historical weekday spending, salary on paydays and bills on their due dates, and flag any day that risks going below zero.",
            "parameters": {
                "type": "object",
                "properties": {
                    "current_balance": {"type": "number", "description": "The user's current account balance"},
                    "start_date": {"type": "string", "description": "YYYY-MM-DD date to start the forecast from, defaults to today"},
                    "days": {"type": "integer", "description": "How many days to forecast, defaults to 7"}
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
                    "period": {"type": "string", "description": PERIOD_DESCRIPTION},
                    "group_by": {"type": "string", "enum": ALLOWED_GROUP_BY, "description": "Column to group by"},
                    "agg": {"type": "string", "enum": ALLOWED_AGG, "description": "Aggregation to apply"}
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
                    "period": {"type": "string", "description": PERIOD_DESCRIPTION},
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
                    "period": {"type": "string", "description": PERIOD_DESCRIPTION.replace(". Optional", "")},
                    "threshold": {"type": "number", "description": "How many IQRs above the normal range counts as anomalous, defaults to 1.5"}
                },
                "required": ["period"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "recurring_bills",
            "description": "List the user's active bills and subscriptions (rent, utilities, phone, subscriptions) with their period, typical amount, last paid date and next due date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "as_of": {"type": "string", "description": "YYYY-MM-DD date to find the next due dates from, defaults to today"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "pay_cycle_summary",
            "description": "Check whether the user is on track this pay cycle (fortnight): spend so far vs the typical spend by the same day in past pay cycles, and days left until payday.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cycle_id": {"type": "integer", "description": "Pay cycle number to check, defaults to the latest cycle in the data"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "make_chart",
            "description": "Draw a bar chart of the user's spending when they ask for a chart, graph or plot. The chart is shown to the user automatically.",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": CHART_KINDS, "description": "Exactly one of: category, merchant, day_of_week, month"},
                    "period": {"type": "string", "description": PERIOD_DESCRIPTION},
                    "top_n": {"type": "integer", "description": "Max bars for category or merchant charts, defaults to 10"}
                },
                "required": ["kind"]
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
    """
    This function answers the question and returns the answer with the
    paths of any charts drawn, so the UI can show them.

    Returns:
        tuple, (answer, chart_paths)
    """
    try:
        messages = [
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": query}
        ]

        response = ollama.chat(model=model, messages=messages, tools=tools)
        messages.append(response.message)

        if not response.message.tool_calls:
            return response.message.content, []

        charts = []
        for result in run_tool_calls(response.message.tool_calls):
            output = result["output"]
            if isinstance(output, dict) and output.get("chart_path"):
                # The UI shows the image, the LLM only gets the numbers so it can't invent a link
                charts.append(output["chart_path"])
                output = {k: v for k, v in output.items() if k != "chart_path"}
            messages.append({
                "role": "tool",
                "name": result["name"],
                "content": json.dumps(output, default=str)
            })

        final = ollama.chat(model=model, messages=messages)
        return final.message.content, charts
    except Exception as e:
        print(f"Failed to answer query, {e}")
        return f"Sorry, something went wrong: {e}", []
