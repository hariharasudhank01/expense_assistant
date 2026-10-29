# Expense Analysis

A personal expense analysis project built from my own bank statements. It turns a raw PDF statement into structured, categorised transaction data, then layers an LLM tool-calling agent on top so I can ask plain-English questions about my own spending ("will I have enough money this week?", "who are my top merchants?").

Built primarily as a learning project — for data cleaning, EDA, and using an LLM correctly (as a router/narrator over deterministic tools, not as the thing doing the actual math).

## What it does

1. **Extract** — reads a bank statement PDF, pulls out the transaction table, and validates it against the running balance to catch missed/misread rows.
2. **Transform** — cleans each transaction description down to a merchant name by stripping trailing location tokens, then assigns a spending category. Categories are cached per merchant (`output/merchant_category.json`) and only looked up via an LLM the first time a new merchant is seen. Also adds, using fixed rules:
   - `spend_type` (essential / discretionary / self_transfer / shared_expenses / others), `is_refund` and `is_lump_expense`
   - a stable `txn_id` per transaction, so re-running a statement doesn't duplicate rows
   - pay-cycle columns (`pay_cycle_id`, `days_since_payday`, `cycle_complete`), counted in fortnights from `ANCHOR_PAY_DATE`
   - recurring-payment columns (`is_recurring`, `recurrence_period`) for rent, bills and subscriptions

   Writes `output/transaction.csv`.
3. **Analyse** — exploratory analysis (weekday patterns, monthly trends, essential vs discretionary spend) done in `src/analysis/analysis.ipynb`, reading straight from `output/transaction.csv`.
4. **Ask** — a small LLM agent (`src/llm/agent.py`) queried through a Streamlit chat UI. The LLM only picks a tool and writes the answer; every number comes from pandas code in `src/tools/tool.py`. It has seven tools:

   | Tool | Answers |
   |---|---|
   | `spend_breakdown` | "How much did I spend by category last month?" |
   | `top_merchants` | "Where did I spend the most in July?" |
   | `anomaly_check` | "Anything unusual in August?" |
   | `recurring_bills` | "What bills do I have? When is rent due?" |
   | `weekly_balance_forecast` | "I have $200, will I make it through the week?" (adds salary on paydays and bills on their due dates) |
   | `pay_cycle_summary` | "Am I on track this fortnight?" |
   | `make_chart` | "Show me a chart of my spending by category" (bar chart shown in the chat) |

   Time periods are passed in the user's own words ("last month", "July", "Q2", "since March", "last 3 weeks", "this pay cycle") and turned into exact dates by `src/helper/date.py`, not by the LLM. Ranges are clipped to the dates the data covers, and the answer says so (e.g. "data ends on 22 Sep").

## Project structure

```
expense-analysis/
├── main.py                    # extraction + preprocessing entry point
├── data/                      # source PDF statements
├── output/                    # generated JSON/CSV artifacts (not source data)
│   └── reports/               # chart PNGs drawn by make_chart
├── src/
│   ├── extract/extract.py     # PDF → validated transaction JSON
│   ├── transform/
│   │   ├── pre_process.py     # cleaning, merchant/category, spend_type, pay-cycle, recurring columns
│   │   └── llm.py             # LLM call used to categorise new merchants
│   ├── helper/
│   │   ├── helper.py          # env loading, json read/write helpers
│   │   ├── config.py          # parsing patterns, category lists, recurring/bill settings
│   │   └── date.py            # "last month" / "this pay cycle" → start and end dates
│   ├── tools/tool.py          # the 7 callable tools (breakdown, forecast, bills, chart, etc.)
│   ├── llm/
│   │   ├── agent.py           # LLM agent that calls the tools and answers questions
│   │   └── ui.py              # Streamlit chat UI on top of agent.py
│   ├── tests/unit_test.py     # pytest tests, made-up data only
│   └── analysis/analysis.ipynb
└── src/.env                   # PROJECT_DIR, FILENAME, LLM_MODEL, RENT, ANCHOR_PAY_DATE, etc.
```

## How to run

Everything reads its settings from `src/.env`, so set that up first:

| Variable | What it is |
|---|---|
| `PROJECT_DIR` | absolute path to this repo; all input/output paths are built from it |
| `FILENAME` | the statement PDF inside `data/` |
| `LLM_MODEL` | Ollama model for the chat agent |
| `CATEGORISE_MODEL` | optional, Ollama model for merchant categorisation (defaults to `LLM_MODEL`) |
| `RENT` | rent amount as a negative number (e.g. `-500`), used to spot rent paid to a person |
| `ANCHOR_PAY_DATE` | any past payday (`YYYY-MM-DD`); pay cycles are counted in fortnights from it |

**1. Extract and preprocess a statement (run once per new PDF):**

```bash
source env-exp/bin/activate
python main.py
```

This reads the PDF named in `.env`, validates and cleans the transactions, assigns merchant/category/`spend_type`/`is_lump_expense`, and writes the fully processed `output/transaction.csv`. Categorisation of any new merchants happens here too, calling the LLM only for merchants not already in `output/merchant_category.json`.

**2. Ask questions about your spending (run separately, any time after step 1):**

```bash
source env-exp/bin/activate
PYTHONPATH=. streamlit run src/llm/ui.py
```

Opens a chat UI at `http://localhost:8501`. `main.py` does not need to be re-run between questions — the UI reads directly from the already-processed data. Restart Streamlit after changing `agent.py` or `tool.py`; it doesn't reload imported modules.

Example questions:

- How much did I spend by category last month?
- Who are my top 5 merchants in July?
- Any unusual transactions in August?
- When is my rent due next?
- I have $200, will I have enough money this week?
- Am I on track this pay cycle?
- Show me a chart of my spending by day of the week

**3. Call a tool directly (no LLM), useful for checking numbers:**

```bash
PYTHONPATH=. python -c "from src.tools.tool import spend_breakdown; print(spend_breakdown(period='last month'))"
```

**4. Run the tests:**

```bash
PYTHONPATH=. python -m pytest src/tests/unit_test.py -q
```

## Requirements

- Python environment: `env-exp/` (pandas, pdfplumber, scikit-learn, streamlit, ollama, pydantic, python-dotenv, matplotlib, pytest)
- [Ollama](https://ollama.com) running locally, with the model set in `.env` (`LLM_MODEL`) available/pulled

## Planned next

1. **Database for transactions and chat history** — move from `output/transaction.csv` to a local SQLite database.
   - Transactions are upserted by `txn_id`, so loading overlapping statements never creates duplicates.
   - Chat history is saved per session, so conversations survive a page refresh and answers can be reviewed later.
   - The tools read from the database with the same shared "real spend" filters, so every number stays the same as it is with the CSV.

2. **Pre-built reports in the UI** — a reports page next to the chat with one-click views (spending by category, this pay cycle vs a typical one, upcoming bills, and a balance forecast). They're built from the same tools the agent uses, so a report and a chat answer always agree.

3. **Automated fortnightly pipeline** — no manual steps after a statement is downloaded.
   - A scheduled job (cron) watches `data/` for new PDFs and runs extraction and preprocessing on any it hasn't seen yet.
   - Once per pay cycle (aligned to `ANCHOR_PAY_DATE`), it builds a summary report: spend vs a typical cycle, top categories, unusual transactions and bills due, with charts.
   - The report is emailed. If a statement fails the balance check, an alert is emailed instead of the report.
