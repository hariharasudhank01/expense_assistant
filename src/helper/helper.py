import json
import sys
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
project_dir = os.getenv("PROJECT_DIR")
file = os.getenv("FILENAME")
model = os.getenv("LLM_MODEL")

def write_json(file, path):
    try:
        with open(path, "w") as output:
            json.dump(file, output, indent=1)
    except Exception as e:
        print(f"Error writing file {path}, {e}")
        sys.exit(1)

def read_json(filename):
    try:
        with open(filename, "r") as file:
            return json.load(file)
    except Exception as e:
        print(f"Error Reading the File, {e}")
        sys.exit(1)