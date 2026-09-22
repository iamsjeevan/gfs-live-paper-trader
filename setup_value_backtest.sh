#!/bin/bash

set -e

PROJECT="value_investing_backtest"

echo "Creating $PROJECT..."

mkdir -p "$PROJECT"/{data,src,results}

# =========================
# requirements.txt
# =========================

cat > "$PROJECT/requirements.txt" <<'EOF'
pandas
numpy
yfinance
scipy
matplotlib
requests
beautifulsoup4
openpyxl
EOF


# =========================
# README.md
# =========================

cat > "$PROJECT/README.md" <<'EOF'
# Value Investing Backtest

Goal:

Test whether buying beaten-down stocks with
strong fundamentals in 2021 could outperform
Nifty 50 / Nifty 500 through 2026.

Strategies:

1. Deep Value
2. Quality Value
3. Quality + Momentum
4. Contrarian
5. Random Control

Important:

The backtest must avoid survivorship bias and
look-ahead bias.

Fundamentals must represent information available
at the time of the investment decision.
EOF


# =========================
# data_loader.py
# =========================

cat > "$PROJECT/src/data_loader.py" <<'PY'
import pandas as pd
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_universe():
    path = DATA_DIR / "universe.csv"

    if not path.exists():
        raise FileNotFoundError(path)

    return pd.read_csv(
        path,
        parse_dates=["date"]
    )


def load_fundamentals():
    path = DATA_DIR / "fundamentals.csv"

    if not path.exists():
        raise FileNotFoundError(path)

    return pd.read_csv(
        path,
        parse_dates=["date"]
    )


def load_prices():
    path = DATA_DIR / "prices.csv"

    if not path.exists():
        raise FileNotFoundError(path)

    return pd.read_csv(
        path,
        parse_dates=["date"]
    )


if __name__ == "__main__":
    print("Data loader ready.")
PY


# =========================
# strategies.py
# =========================

cat > "$PROJECT/src/strategies.py" <<'PY'
import pandas as pd


def quality_value(fundamentals):
    """
    Quality + Value strategy.

    Requirements:
    - ROE > 12%
    - ROCE > 15%
    - Debt/Equity < 1
    - Positive operating cash flow
    - Positive net profit
    - P/E > 0
    """

    df = fundamentals.copy()

    required = [
        "roe",
        "roce",
        "debt_equity",
        "operating_cf",
        "net_profit",
        "pe"
    ]

    df = df.dropna(subset=required)

    df = df[
        (df["roe"] > 12) &
        (df["roce"] > 15) &
        (df["debt_equity"] < 1) &
        (df["operating_cf"] > 0) &
        (df["net_profit"] > 0) &
        (df["pe"] > 0)
    ]

    # Lower PE = better value
    df["value_score"] = 1 / df["pe"]

    # Quality score
    df["quality_score"] = (
        df["roe"] * 0.4 +
        df["roce"] * 0.4 -
        df["debt_equity"] * 2
    )

    df["score"] = (
        df["quality_score"] * 0.7 +
        df["value_score"] * 100 * 0.3
    )

    return df.sort_values(
        "score",
        ascending=False
    )


def deep_value(fundamentals):
    """
    Pure value strategy.
    """

    df = fundamentals.copy()

    df = df.dropna(
        subset=["pe", "pb", "roe"]
    )

    df = df[
        (df["pe"] > 0) &
        (df["pb"] > 0) &
        (df["roe"] > 5)
    ]

    df["score"] = (
        1 / df["pe"] +
        1 / df["pb"]
    )

    return df.sort_values(
        "score",
        ascending=False
    )


def contrarian(fundamentals):
    """
    Buy stocks that are significantly
    below their 52-week high while
    fundamentals remain healthy.
    """

    df = fundamentals.copy()

    required = [
        "drawdown",
        "roe",
        "roce",
        "debt_equity"
    ]

    df = df.dropna(
        subset=required
    )

    df = df[
        (df["drawdown"] <= -30) &
        (df["roe"] > 12) &
        (df["roce"] > 15) &
        (df["debt_equity"] < 1)
    ]

    # Bigger drawdown = stronger contrarian signal
    df["score"] = -df["drawdown"]

    return df.sort_values(
        "score",
        ascending=False
    )
PY


# =========================
# metrics.py
# =========================

cat > "$PROJECT/src/metrics.py" <<'PY'
import numpy as np
import pandas as pd


def calculate_metrics(values):
    values = pd.Series(values).dropna()

    if len(values) < 2:
        return {}

    start = values.iloc[0]
    end = values.iloc[-1]

    years = len(values) / 252

    cagr = (
        end / start
    ) ** (1 / years) - 1

    returns = values.pct_change().dropna()

    volatility = (
        returns.std() *
        np.sqrt(252)
    )

    sharpe = (
        returns.mean() /
        returns.std()
        * np.sqrt(252)
        if returns.std() != 0
        else np.nan
    )

    peak = values.cummax()

    drawdown = (
        values / peak - 1
    )

    max_drawdown = drawdown.min()

    return {
        "start_value": start,
        "end_value": end,
        "absolute_return": end / start - 1,
        "cagr": cagr,
        "volatility": volatility,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown
    }


def print_metrics(metrics):

    print("\n==============================")
    print("BACKTEST RESULTS")
    print("==============================")

    for key, value in metrics.items():

        if "value" in key:
            print(
                f"{key}: ₹{value:,.2f}"
            )

        else:
            print(
                f"{key}: {value:.2%}"
                if key != "sharpe"
                else f"{key}: {value:.2f}"
            )
PY


# =========================
# backtest.py
# =========================

cat > "$PROJECT/src/backtest.py" <<'PY'
"""
Value Investing Backtester

This is the main entry point.

Currently this validates that the project
and data pipeline are working.

The actual historical backtest will be added
after the point-in-time dataset is loaded.
"""

from pathlib import Path

from data_loader import (
    load_universe,
    load_fundamentals,
    load_prices
)


BASE_DIR = Path(__file__).resolve().parent.parent


def main():

    print("\n==============================")
    print("VALUE INVESTING BACKTEST")
    print("==============================\n")

    print("Project:", BASE_DIR)

    try:
        universe = load_universe()
        print(
            f"Universe rows: {len(universe):,}"
        )
    except FileNotFoundError:
        print(
            "Universe dataset not found yet."
        )
        universe = None

    try:
        fundamentals = load_fundamentals()
        print(
            f"Fundamental rows: {len(fundamentals):,}"
        )
    except FileNotFoundError:
        print(
            "Fundamentals dataset not found yet."
        )
        fundamentals = None

    try:
        prices = load_prices()
        print(
            f"Price rows: {len(prices):,}"
        )
    except FileNotFoundError:
        print(
            "Price dataset not found yet."
        )
        prices = None

    print("\nPipeline initialized.")
    print(
        "Next step: load historical "
        "point-in-time data."
    )


if __name__ == "__main__":
    main()
PY


# =========================
# Empty CSV headers
# =========================

cat > "$PROJECT/data/universe.csv" <<'EOF'
date,ticker
EOF

cat > "$PROJECT/data/fundamentals.csv" <<'EOF'
date,ticker,roe,roce,debt_equity,operating_cf,net_profit,pe,pb,drawdown
EOF

cat > "$PROJECT/data/prices.csv" <<'EOF'
date,ticker,close
EOF


# =========================
# Gitignore
# =========================

cat > "$PROJECT/.gitignore" <<'EOF'
__pycache__/
*.pyc
.venv/
.env
.DS_Store
results/*.csv
EOF


# =========================
# Virtual environment
# =========================

cd "$PROJECT"

python3 -m venv .venv

source .venv/bin/activate

python -m pip install --upgrade pip

pip install -r requirements.txt


# =========================
# Test
# =========================

echo ""
echo "Running project test..."
python src/backtest.py

echo ""
echo "================================"
echo "SETUP COMPLETE"
echo "================================"
echo ""
echo "Project:"
pwd
echo ""
echo "Next command:"
echo "source .venv/bin/activate"
echo ""
echo "Then:"
echo "python src/backtest.py"
echo ""
echo "Files:"
find . -maxdepth 3 -type f \
    -not -path './.venv/*' \
    | sort

