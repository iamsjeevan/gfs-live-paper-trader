"""Quality Strategy definition."""

STRATEGY = {
    "name": "Quality",
    "description": "Screens for high return on capital, conservative leverage, and positive cash flow.",
    "hard_filters": {
        "roe_min": 0.10,
        "roic_min": 0.08,
        "debt_equity_max": 1.0,
        "net_income_positive": True,
        "fcf_positive": True,
        "operating_margin_min": 0.05,
    },
    "weights": {
        "roe": 0.30,
        "roic": 0.30,
        "debt_equity": 0.20,
        "operating_margin": 0.10,
        "fcf_margin": 0.10,
    },
    "ranking_direction": {
        "roe": "desc",
        "roic": "desc",
        "debt_equity": "asc",  # lower leverage is better
        "operating_margin": "desc",
        "fcf_margin": "desc",
    },
}
