"""Audit existing Indian stock datasets in detail."""

import sqlite3
import pandas as pd
import json
from pathlib import Path

def audit_all():
    summary = {}

    for db_path in ["instocks.db", "data/nse_stocks_all_years.db", "data/nse_stocks_2021.db"]:
        p = Path(db_path)
        if not p.exists():
            continue
        conn = sqlite3.connect(db_path)
        tables = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table';", conn)["name"].tolist()
        summary[db_path] = {"size_mb": round(p.stat().st_size / (1024 * 1024), 2), "tables": {}}

        for t in tables:
            count = int(pd.read_sql(f"SELECT COUNT(*) as c FROM {t};", conn).iloc[0]["c"])
            cols = pd.read_sql(f"PRAGMA table_info({t});", conn)["name"].tolist()
            t_info = {"rows": count, "columns": cols}

            if "date" in cols:
                dates = pd.read_sql(f"SELECT MIN(date) as min_d, MAX(date) as max_d FROM {t};", conn)
                t_info["min_date"] = str(dates.iloc[0]["min_d"])
                t_info["max_date"] = str(dates.iloc[0]["max_d"])

            if "symbol" in cols:
                sc = int(pd.read_sql(f"SELECT COUNT(DISTINCT symbol) as c FROM {t};", conn).iloc[0]["c"])
                t_info["distinct_symbols"] = sc
                sample_syms = pd.read_sql(f"SELECT DISTINCT symbol FROM {t} LIMIT 5;", conn)["symbol"].tolist()
                t_info["sample_symbols"] = sample_syms

            if "close" in cols:
                nn = int(pd.read_sql(f"SELECT COUNT(*) as c FROM {t} WHERE close IS NOT NULL;", conn).iloc[0]["c"])
                t_info["non_null_close"] = nn
                if nn > 0:
                    v_dates = pd.read_sql(f"SELECT MIN(date) as min_d, MAX(date) as max_d FROM {t} WHERE close IS NOT NULL;", conn)
                    t_info["valid_min_date"] = str(v_dates.iloc[0]["min_d"])
                    t_info["valid_max_date"] = str(v_dates.iloc[0]["max_d"])

            summary[db_path]["tables"][t] = t_info

        conn.close()

    # Also check CSV/JSON files
    csv_files = ["data/bhavcopy_2021.csv", "data/equity_master.csv", "data/tickers.csv",
                 "india_stock_research/data/raw/india_retrospective_prices.json",
                 "india_stock_research/data/exports/india_strategy_abcd_rankings_2016.csv"]
    summary["other_files"] = {}
    for f in csv_files:
        fp = Path(f)
        if fp.exists():
            summary["other_files"][f] = {"size_kb": round(fp.stat().st_size / 1024, 2)}
            if f.endswith(".csv"):
                df = pd.read_csv(f, nrows=5)
                summary["other_files"][f]["columns"] = df.columns.tolist()
                summary["other_files"][f]["sample_rows"] = len(df)
            elif f.endswith(".json"):
                with open(f) as jf:
                    data = json.load(jf)
                    summary["other_files"][f]["keys_count"] = len(data) if isinstance(data, dict) else len(data)

    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    audit_all()
