import os
from src.extract.extract import extract
from src.transform.pre_process import run
from src.helper.helper import project_dir, file

filename = os.path.join(project_dir, "data", file)

def main():
    valid_content = extract(filename)
    df = run(valid_content)
    try:
        df.to_csv(os.path.join(project_dir, "output", "transaction.csv"), index=False)
    except Exception as e:
        print(f"Failed, {e}")

if __name__ == "__main__":
    main()