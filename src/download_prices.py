import yfinance as yf
import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

START = "2020-01-01"
END = "2026-08-21"

print("Downloading Nifty 500 list...")

url = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"

universe = pd.read_csv(url)

tickers = (
    universe["Symbol"]
    .astype(str)
    .str.strip()
    .str.upper()
    .tolist()
)

tickers = [
    f"{ticker}.NS"
    for ticker in tickers
    if ticker != "NAN"
]

print(f"Found {len(tickers)} stocks")
print("Downloading historical prices...\n")

all_data = []

for i, ticker in enumerate(tickers, 1):

    try:
        print(
            f"[{i}/{len(tickers)}] {ticker}",
            end="\r",
            flush=True
        )

        data = yf.download(
            ticker,
            start=START,
            end=END,
            auto_adjust=True,
            progress=False,
            threads=False
        )

        if data.empty:
            continue

        if isinstance(data.columns, pd.MultiIndex):
            close = data["Close"].iloc[:, 0]
        else:
            close = data["Close"]

        df = pd.DataFrame({
            "date": close.index,
            "ticker": ticker.replace(".NS", ""),
            "close": close.values
        })

        df["high_52w"] = (
            df["close"]
            .rolling(252)
            .max()
        )

        df["drawdown"] = (
            df["close"] /
            df["high_52w"] - 1
        )

        all_data.append(df)

    except Exception as e:
        print(f"\nFailed {ticker}: {e}")

if not all_data:
    raise RuntimeError("No data downloaded.")

prices = pd.concat(
    all_data,
    ignore_index=True
)

prices = prices.sort_values(
    ["ticker", "date"]
)

output = DATA_DIR / "prices.csv"

prices.to_csv(
    output,
    index=False
)

print("\n")
print("=" * 40)
print("PRICE DOWNLOAD COMPLETE")
print("=" * 40)

print(f"Stocks: {prices['ticker'].nunique()}")
print(f"Rows: {len(prices):,}")
print(f"Start: {prices['date'].min()}")
print(f"End:   {prices['date'].max()}")
print(f"Saved: {output}")
