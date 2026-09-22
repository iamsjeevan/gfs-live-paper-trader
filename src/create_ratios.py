import sqlite3


DB="data/stocks.db"


conn=sqlite3.connect(DB)


conn.execute("DROP TABLE IF EXISTS ratios")


conn.execute("""
CREATE TABLE ratios(

symbol TEXT,
year INTEGER,

roe REAL,
debt_equity REAL,
asset_turnover REAL,

sales_growth REAL,
profit_growth REAL

)
""")


# calculate yearly metrics
conn.execute("""
INSERT INTO ratios

SELECT

f.symbol,
f.year,


-- ROE
CASE
WHEN b.equity > 0
THEN f.net_profit / b.equity
END,


-- Debt Equity
CASE
WHEN b.equity > 0
THEN (b.long_term_debt + b.short_term_debt) / b.equity
END,


-- Asset turnover
CASE
WHEN b.assets > 0
THEN f.revenue / b.assets
END,


-- Sales growth
CASE
WHEN p.revenue > 0
THEN (f.revenue-p.revenue)/p.revenue
END,


-- Profit growth
CASE
WHEN p.net_profit > 0
THEN (f.net_profit-p.net_profit)/p.net_profit
END


FROM financials f


JOIN balance_sheet b

ON f.symbol=b.symbol
AND f.year=b.year


LEFT JOIN financials p

ON f.symbol=p.symbol
AND f.year=p.year+1

""")


conn.commit()
conn.close()


print("Ratios created")
