import pandas as pd
import sqlite3
from pathlib import Path
from datetime import datetime


DB = Path("data/stocks.db")


df = pd.read_csv(
    "data/tickers.csv"
)

df["date"] = "2021-01-01"
df["active"] = 1

df = df[
    ["date","Symbol","active"]
]

df.columns = [
    "date",
    "ticker",
    "active"
]


conn = sqlite3.connect(DB)

df.to_sql(
    "universe",
    conn,
    if_exists="replace",
    index=False
)

conn.close()

print("Universe table created")
print(df.head())
print("Rows:",len(df))
