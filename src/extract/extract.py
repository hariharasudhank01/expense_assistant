import pdfplumber
import re
import sys
import os
from src.helper.helper import write_json, project_dir

valid_trans_path = os.path.join(project_dir, "output", "valid_transaction.json")
review_trans_path = os.path.join(project_dir, "output", "manual_review.json")

def read_pdf(filename):
    transactions = []
    col_name = ["Date", "Transaction details", "Amount", "Balance"]
    vertical_line = [59, 120, 390, 480, 535] # Don't change the value
    try:
        with pdfplumber.open(filename) as pdf:
            # The last page of these statements is blank, so it's skipped.
            for page_no in range(len(pdf.pages)-1):
                page = pdf.pages[page_no]
                if page_no == 0:
                    bbox = (0, 350, page.width, page.height) # Page 0
                else:
                    bbox = (0, 144, page.width, page.height)
                crop_page = page.crop(bbox)
                table = crop_page.extract_table(
                    {
                        "horizontal_strategy": "text",
                        "vertical_strategy": "explicit",
                        "snap_y_tolerance": 8,
                        "explicit_vertical_lines": vertical_line
                    }
                )
                # extract_table returns None for a page with no table.
                for row in table or []:
                    if not row == col_name:
                        row_dict = dict(zip(col_name, [val or "" for val in row]))
                        transactions.append(row_dict)
        return transactions

    except Exception as e:
        print(f"Error reading the file {filename}, {e}")
        return []

def check_format(transactions):
    valid_transaction = []
    manual_review = []
    # Regex Patterns
    date_pattern = r"^(?:\d{2} [a-z]{3} \d{4})$"
    value_pattern = r"^(-)?\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?$"
    id = 1
    for transaction in transactions:
        date = transaction.get("Date")
        details = transaction.get("Transaction details")
        amount = transaction.get("Amount")
        balance = transaction.get("Balance")
        if re.fullmatch(date_pattern, date, re.IGNORECASE) and \
           re.fullmatch(value_pattern, amount, re.IGNORECASE) and \
           re.fullmatch(value_pattern, balance, re.IGNORECASE):
            transaction["ID"] = id
            valid_transaction.append(transaction)
            id += 1
        elif (date and amount and details and balance) or (re.fullmatch(value_pattern, amount, re.IGNORECASE) or \
           re.fullmatch(value_pattern, balance, re.IGNORECASE)):
            manual_review.append(transaction)
    return valid_transaction, manual_review

def check_sum(transactions):
    # Any error means the statement couldn't be verified, so it fails the check.
    if not transactions:
        print("No valid transactions extracted")
        return False

    n = len(transactions) - 1
    try:
        open_balance = float(transactions[0].get("Balance").replace("$", "").replace(",", ""))
        close_balance = float(transactions[n].get("Balance").replace("$", "").replace(",", ""))
    except Exception as e:
        print(f"Failed to convert Balance to float, {e}")
        return False

    try:
        for transaction_id in range(1, len(transactions)):
            amount = transactions[transaction_id].get("Amount")

            open_balance = open_balance + float(amount.replace("$", "").replace(",", ""))
    except Exception as e:
        print(f"Failed to convert Amount string to float, Error {e}")
        return False

    try:
        if not round(open_balance, 2) == close_balance:
            print(f"Expected {close_balance}, got {open_balance}")
            print("Review the JSON files for Missed transaction")
            return False
    except Exception as e:
        print(f"Error: {e}. Review the JSON file")
        return False
    return True

def validate_transaction(transactions):
    valid_transaction, manual_review = check_format(transactions)
    valid_sum = check_sum(valid_transaction)
    if valid_transaction:
        write_json(valid_transaction, valid_trans_path)
    if manual_review:
        write_json(manual_review, review_trans_path)
    return valid_sum

def extract(filename):
    transactions = read_pdf(filename)
    if not validate_transaction(transactions):
        print(f"Extraction failed for {filename}")
        sys.exit(1)
    print(f"Completed Extracting PDF: {filename}")
    return valid_trans_path
