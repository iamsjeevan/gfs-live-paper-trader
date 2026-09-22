"""Quality + Growth + Value + Moat Proxy Strategy definition."""

STRATEGY = {
    "name": "Quality + Growth + Value + Moat Proxy",
    "description": "Comprehensive fundamental strategy incorporating quality, growth, leverage, and quantitative moat proxy.",
    "hard_filters": {
        "roe_min": 0.12,
        "roic_min": 0.10,
        "debt_equity_max": 1.0,
        "net_income_positive": True,
        "fcf_positive": True,
    },
    "weights": {
        "roe": 0.15,
        "roic": 0.20,
        "revenue_growth": 0.15,
        "earnings_growth": 0.10,
        "fcf_growth": 0.10,
        "debt_equity": 0.10,
        "operating_margin": 0.05,
        "fcf_margin": 0.05,
        "small_cap": 0.05,
        "moat": 0.05,
    },
    "ranking_direction": {
        "roe": "desc",
        "roic": "desc",
        "revenue_growth": "desc",
        "earnings_growth": "desc",
        "fcf_growth": "desc",
        "debt_equity": "asc",
        "operating_margin": "desc",
        "fcf_margin": "desc",
        "small_cap": "asc",  # smaller market cap preferred within range
        "moat": "desc",
    },
}
