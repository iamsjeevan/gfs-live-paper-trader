"""Quality + Growth Strategy definition."""

STRATEGY = {
    "name": "Quality + Growth",
    "description": "Combines fundamental quality with multi-year revenue, earnings, and FCF growth.",
    "hard_filters": {
        "roe_min": 0.12,
        "roic_min": 0.10,
        "debt_equity_max": 0.80,
        "net_income_positive": True,
        "fcf_positive": True,
        "revenue_growth_min": 0.05,
    },
    "weights": {
        "roe": 0.20,
        "roic": 0.20,
        "revenue_growth": 0.20,
        "earnings_growth": 0.15,
        "fcf_growth": 0.15,
        "debt_equity": 0.10,
    },
    "ranking_direction": {
        "roe": "desc",
        "roic": "desc",
        "revenue_growth": "desc",
        "earnings_growth": "desc",
        "fcf_growth": "desc",
        "debt_equity": "asc",
    },
}
