import pandas as pd
import os
from src.helper.helper import project_dir

data_path = os.path.join(project_dir, "output", "transaction.csv")

def load_data():
    df = pd.read_csv(data_path)
    df["date"] = pd.to_datetime(df["date"])
    return df

def recurring_spend(df):
    return df[(~df["is_lump_expense"]) & (df["spend_type"].isin(["essential", "discretionary"]))]

def weekly_balance_forecast(current_balance, start_date=None, scheduled_inflows=None):
    try:
        df = load_data()
        spend_df = recurring_spend(df)

        day_stats = spend_df.groupby("day_of_week")["amount"].agg(
            median="median",
            best=lambda s: s.quantile(0.75),  
            worst=lambda s: s.quantile(0.25)
        )

        start_date = pd.Timestamp(start_date) if start_date else pd.Timestamp.today().normalize()
        scheduled_inflows = scheduled_inflows or {}

        running = {"median": current_balance, "best": current_balance, "worst": current_balance}
        forecast = []
        dips_below_zero = []

        for i in range(7):
            day = start_date + pd.Timedelta(days=i)
            dow = day.day_name()
            row = day_stats.loc[dow] if dow in day_stats.index else pd.Series({"median": 0, "best": 0, "worst": 0})
            inflow = scheduled_inflows.get(day.strftime("%Y-%m-%d"), 0)

            for key in running:
                running[key] = running[key] + row[key] + inflow

            forecast.append({
                "date": day.strftime("%Y-%m-%d"),
                "day_of_week": dow,
                "projected_balance_median": round(running["median"], 2),
                "projected_balance_best_case": round(running["best"], 2),
                "projected_balance_worst_case": round(running["worst"], 2)
            })

            if running["worst"] < 0:
                dips_below_zero.append(day.strftime("%Y-%m-%d"))

        return {"forecast": forecast, "risk_days": dips_below_zero}
    except Exception as e:
        print(f"Failed to build weekly balance forecast, {e}")

def spend_breakdown(period_start=None, period_end=None, group_by="category", agg="sum", exclude_lump_expense=True):
    try:
        df = load_data()
        if exclude_lump_expense:
            df = df[~df["is_lump_expense"]]
        if period_start:
            df = df[df["date"] >= pd.Timestamp(period_start)]
        if period_end:
            df = df[df["date"] <= pd.Timestamp(period_end)]

        result = df.groupby(group_by)["amount"].agg(agg).sort_values()
        return result.round(2).to_dict()
    except Exception as e:
        print(f"Failed to build spend breakdown, {e}")

def top_merchants(period_start=None, period_end=None, category=None, top_n=5):
    try:
        df = load_data()
        # Real spend only - drops salary, self transfers and shared expenses.
        df = df[df["spend_type"].isin(["essential", "discretionary"])]
        if category:
            df = df[df["category"] == category]
        if period_start:
            df = df[df["date"] >= pd.Timestamp(period_start)]
        if period_end:
            df = df[df["date"] <= pd.Timestamp(period_end)]

        # Spend is negative, so negate the sum - refunds (positive) then reduce it.
        summary = df.groupby("merchant")["amount"].agg(
            total_spend=lambda s: round(-s.sum(), 2),
            visits="count"
        ).sort_values("total_spend", ascending=False)

        return summary.head(top_n).reset_index().to_dict(orient="records")
    except Exception as e:
        print(f"Failed to get top merchants, {e}")

def anomaly_check(period_start, period_end, threshold=1.5):
    try:
        df = load_data()
        history = recurring_spend(df)
        stats = history.groupby("category")["amount"].agg(
            median="median",
            q1=lambda s: s.quantile(0.25),
            q3=lambda s: s.quantile(0.75)
        )
        stats["iqr"] = stats["q3"] - stats["q1"]

        window = df[(df["date"] >= pd.Timestamp(period_start)) & (df["date"] <= pd.Timestamp(period_end))]

        flagged = []
        for _, row in window.iterrows():
            cat_stats = stats.loc[row["category"]] if row["category"] in stats.index else None
            if cat_stats is None or cat_stats["iqr"] == 0:
                continue
            lower_bound = cat_stats["q1"] - threshold * cat_stats["iqr"]
            if row["amount"] < lower_bound:
                flagged.append({
                    "date": row["date"].strftime("%Y-%m-%d"),
                    "merchant": row["merchant"],
                    "category": row["category"],
                    "amount": row["amount"],
                    "category_median": round(cat_stats["median"], 2)
                })

        return flagged
    except Exception as e:
        print(f"Failed to run anomaly check, {e}")
