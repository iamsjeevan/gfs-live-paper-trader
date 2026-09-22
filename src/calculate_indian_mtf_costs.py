import pandas as pd
import numpy as np

# Portfolio Parameters
EQUITY_CAPITAL = 1000000.0  # ₹10 Lakh Capital
NUM_STOCKS = 10

# Charge Constants
MTF_DAILY_RATE = 0.0004     # 0.04% per day (14.6% P.A.)
BROKERAGE_PER_ORDER = 20.0  # Zerodha ₹20 flat per order
PLEDGE_PER_ISIN = 15.0      # ₹15 + GST
DP_CHARGE_PER_SELL = 13.50  # ₹13.50 + GST
STT_DELIVERY = 0.001        # 0.1% on Buy & Sell
EXCHANGE_FEE = 0.0000345    # 0.00345% NSE fee
STAMP_DUTY_BUY = 0.00015    # 0.015% on Buy
GST_RATE = 0.18             # 18% GST

def calculate_costs_for_leverage(leverage_ratio=1.5, turnover_pct_per_month=0.30):
    portfolio_value = EQUITY_CAPITAL * leverage_ratio
    borrowed_amount = max(portfolio_value - EQUITY_CAPITAL, 0.0)

    # 1. MTF Interest
    daily_mtf_cost = borrowed_amount * MTF_DAILY_RATE
    monthly_mtf_cost = daily_mtf_cost * 30.0
    yearly_mtf_cost = daily_mtf_cost * 365.0

    # 2. Monthly Trading Turnover
    monthly_traded_value = portfolio_value * turnover_pct_per_month  # Traded value per month
    num_buys = int(NUM_STOCKS * turnover_pct_per_month)
    num_sells = num_buys
    total_orders = num_buys + num_sells

    # Brokerage
    monthly_brokerage = total_orders * BROKERAGE_PER_ORDER

    # Statutory Charges
    monthly_stt = monthly_traded_value * STT_DELIVERY * 2.0  # Buy & Sell
    monthly_stamp_duty = (monthly_traded_value * turnover_pct_per_month) * STAMP_DUTY_BUY
    monthly_exchange_fee = monthly_traded_value * 2.0 * EXCHANGE_FEE
    monthly_dp = num_sells * DP_CHARGE_PER_SELL
    monthly_pledge = (num_buys + num_sells) * PLEDGE_PER_ISIN

    # GST on (Brokerage + Exchange Fee + DP + Pledge)
    gst_taxable = monthly_brokerage + monthly_exchange_fee + monthly_dp + monthly_pledge
    monthly_gst = gst_taxable * GST_RATE

    monthly_trading_costs = monthly_brokerage + monthly_stt + monthly_stamp_duty + monthly_exchange_fee + monthly_dp + monthly_pledge + monthly_gst
    yearly_trading_costs = monthly_trading_costs * 12.0

    total_monthly_cost = monthly_mtf_cost + monthly_trading_costs
    total_yearly_cost = yearly_mtf_cost + yearly_trading_costs

    pct_of_equity_capital = (total_yearly_cost / EQUITY_CAPITAL) * 100.0
    pct_of_portfolio_val = (total_yearly_cost / portfolio_value) * 100.0

    return {
        'leverage_ratio': leverage_ratio,
        'borrowed_amount': borrowed_amount,
        'monthly_mtf_cost': monthly_mtf_cost,
        'monthly_trading_costs': monthly_trading_costs,
        'total_monthly_cost': total_monthly_cost,
        'total_yearly_cost': total_yearly_cost,
        'pct_equity': pct_of_equity_capital,
        'pct_portfolio': pct_of_portfolio_val
    }

def main():
    print("=" * 90)
    print("        REAL-WORLD INDIAN BROKERAGE & MTF INTEREST COST ANALYSIS        ")
    print("=" * 90)

    # A, B, C, D Calculations for ₹10 Lakh Capital + ₹5 Lakh MTF Borrowed (1.5x Leverage)
    c15 = calculate_costs_for_leverage(leverage_ratio=1.5, turnover_pct_per_month=0.30)

    print(f"\n--- 1. COST BREAKDOWN FOR ₹10 LAKH CAPITAL + ₹5 LAKH MTF BORROWED (1.5x LEVERAGE) ---")
    print(f"A) Total Cost Per Month:            ₹{c15['total_monthly_cost']:,.2f} / month")
    print(f"   - MTF Interest (0.04%/day):      ₹{c15['monthly_mtf_cost']:,.2f}")
    print(f"   - Taxes & Brokerage Fees:        ₹{c15['monthly_trading_costs']:,.2f}")
    print(f"B) Total Cost Per Year:             ₹{c15['total_yearly_cost']:,.2f} / year")
    print(f"C) Cost as % of ₹10 Lakh Capital:   {c15['pct_equity']:.2f}% per year")
    print(f"D) Cost as % of ₹15 Lakh Portfolio: {c15['pct_portfolio']:.2f}% per year")

    # E & F Comparison Table across Leverage Ratios (1.0x, 1.25x, 1.5x, 2.0x) and Strategy CAGRs (30%, 35%, 40%)
    leverage_levels = [1.0, 1.25, 1.5, 2.0]
    cagr_levels = [30.0, 35.0, 40.0]

    final_table = []
    for lev in leverage_levels:
        costs = calculate_costs_for_leverage(leverage_ratio=lev, turnover_pct_per_month=0.30)
        cost_drag_pct = costs['pct_equity']
        
        for gross_cagr in cagr_levels:
            # Net CAGR = (Gross CAGR * Leverage) - MTF Cost Drag
            gross_leveraged_return = gross_cagr * lev
            net_cagr = gross_leveraged_return - cost_drag_pct
            cagr_reduction = gross_leveraged_return - net_cagr

            final_table.append({
                'Leverage': f"{lev}x",
                'Equity Capital': "₹10 Lakhs",
                'Borrowed MTF': f"₹{(lev - 1.0)*10:,.1f} Lakhs",
                'Gross Strategy CAGR': f"{gross_cagr}%",
                'Yearly Total Cost': f"₹{costs['total_yearly_cost']:,.0f}",
                'Cost Drag (% Capital)': f"{cost_drag_pct:.2f}%",
                'Net Realized CAGR': f"{net_cagr:.2f}%",
                'CAGR Drag Impact': f"-{cost_drag_pct:.2f}%"
            })

    print("\n" + "=" * 90)
    print("--- E & F) FINAL LEVERAGE vs REALIZED NET CAGR TABLE (AFTER ALL TAXES & MTF INTEREST) ---")
    print("=" * 90)
    df_table = pd.DataFrame(final_table)
    print(df_table.to_string(index=False))

    # 8-Year Total Wealth Compounding Impact (2018 - 2026)
    print("\n" + "=" * 90)
    print("--- 8.5-YEAR TOTAL NET WEALTH COMPOUNDING (₹10 LAKH CAPITAL: 2018 - 2026) ---")
    print("=" * 90)
    
    wealth_summary = []
    for lev in [1.0, 1.25, 1.5, 2.0]:
        costs = calculate_costs_for_leverage(leverage_ratio=lev, turnover_pct_per_month=0.30)
        net_cagr_35 = (35.0 * lev) - costs['pct_equity']
        final_wealth = EQUITY_CAPITAL * ((1.0 + net_cagr_35/100.0) ** 8.5)
        
        wealth_summary.append({
            'Leverage': f"{lev}x",
            'Yearly Cost Drag': f"₹{costs['total_yearly_cost']:,.0f}/yr ({costs['pct_equity']:.2f}%)",
            'Net Realized CAGR (At 35% Base)': f"{net_cagr_35:.2f}%",
            'Final Wealth After 8.5 Years': f"₹{final_wealth:,.2f}"
        })
    
    print(pd.DataFrame(wealth_summary).to_string(index=False))

if __name__ == "__main__":
    main()
