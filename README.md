# Expense Analysis

A personal expense analysis project built from my own bank statements. It turns a raw
PDF statement into structured, categorised transaction data, then layers an LLM
tool-calling agent on top so I can ask plain-English questions about my own spending
("will I have enough money this week?", "who are my top merchants?").

Built primarily as a learning project — for data cleaning, EDA, and using an LLM
correctly (as a router/narrator over deterministic tools, not as the thing doing the
actual math).

## What it does

1. **Extract** — reads a bank statement PDF, pulls out the transaction table, and
   validates it against the running balance to catch missed/misread rows.
2. **Transform** — cleans each transaction description down to a merchant name by
   stripping trailing location tokens, then assigns a spending category.
   Categories are cached per merchant (`output/merchant_category.json`) and only
   looked up via an LLM the first time a new merchant is seen. Also tags each
   transaction with `spend_type` (essential / discretionary / other) and
   `is_lump_expense`, using fixed rules. Writes `output/transaction.csv`.
3. **Analyse** — exploratory analysis (weekday patterns, monthly trends, essential vs
   discretionary spend) done in `src/analysis/analysis.ipynb`, reading straight from
   `output/transaction.csv`.
4. **Ask** — a small LLM agent (`src/llm/agent.py`) with four tools (weekly balance
   forecast, spend breakdown, top merchants, anomaly check), also reading straight
   from `output/transaction.csv`, queried through a Streamlit chat UI.

## Project structure

```
expense-analysis/
├── main.py                    # extraction + preprocessing entry point
├── data/                      # source PDF statements
├── output/                    # generated JSON/CSV artifacts (not source data)
├── src/
│   ├── extract/extract.py     # PDF → validated transaction JSON
│   ├── transform/
│   │   ├── pre_process.py     # cleaning, merchant/category, spend_type columns
│   │   └── llm.py             # LLM call used to categorise new merchants
│   ├── helper/
│   │   ├── helper.py          # env loading, json read/write helpers
│   │   └── config.py          # regex patterns for merchant/location parsing
│   ├── tools/tool.py          # the 4 callable tools (forecast, breakdown, etc.)
│   ├── llm/
│   │   ├── agent.py           # LLM agent that calls the tools and answers questions
│   │   └── ui.py              # Streamlit chat UI on top of agent.py
│   └── analysis/analysis.ipynb
└── .env                       # PROJECT_DIR, FILENAME, LLM_MODEL, etc.
```

## How to run

Everything reads its paths from `src/.env` (`PROJECT_DIR`, `FILENAME`, `LLM_MODEL`),
so set that up first.

**1. Extract and preprocess a statement (run once per new PDF):**

```bash
source env-exp/bin/activate
python main.py
```

This reads the PDF named in `.env`, validates and cleans the transactions, assigns
merchant/category/`spend_type`/`is_lump_expense`, and writes the fully processed
`output/transaction.csv`. Categorisation of any new merchants happens here too,
calling the LLM only for merchants not already in `output/merchant_category.json`.

**2. Ask questions about your spending (run separately, any time after step 1):**

```bash
source env-exp/bin/activate
PYTHONPATH=. streamlit run src/llm/ui.py
```

Opens a chat UI at `http://localhost:8501`. `main.py` does not need to be re-run
between questions — the UI reads directly from the already-processed data.

## Requirements

- Python environment: `env-exp/` (pandas, pdfplumber, scikit-learn, streamlit, ollama,
  pydantic, python-dotenv)
- [Ollama](https://ollama.com) running locally, with the model set in `.env` (`LLM_MODEL`)
  available/pulled
