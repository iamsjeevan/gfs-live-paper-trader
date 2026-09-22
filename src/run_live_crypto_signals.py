import sqlite3
import pandas as pd
import numpy as np
import yfinance as yf

def get_live_crypto_signals():
    print("=" * 80)
    print("   OPTIMAL CRYPTO SHORT-TERM SWING SIGNALS (BITCOIN & ETHEREUM)   ")
    print("=" * 80)

    # Optimal configurations from Grid Search
    # BTC: 15-Day Breakout, 5-Day Hold, 50 SMA Regime, 5% Stop Loss (CAGR: 45.4%, Max DD: -25.67%)
    # ETH: 30-Day Breakout, 5-Day Hold, 50 SMA Regime, 5% Stop Loss (CAGR: 29.81%, Max DD: -23.78%)
    configs = [
        ("BTC-USD", "BITCOIN", 15, 5, 0.05, "SMA50", 45.40, -25.67),
        ("ETH-USD", "ETHEREUM", 30, 5, 0.05, "SMA50", 29.81, -23.78)
    ]

    for ticker, name, bw, hold_d, sl_pct, regime_mode, cagr, max_dd in configs:
        try:
            data = yf.Ticker(ticker)
            df = data.history(period="1y", interval="1d").reset_index()
            df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')
            df['sma50'] = df['Close'].rolling(50).mean()
            df['sma200'] = df['Close'].rolling(200).mean()
            df['ema5'] = df['Close'].ewm(span=5, adjust=False).mean()
            df['breakout_high'] = df['High'].shift(1).rolling(bw).max()

            latest = df.iloc[-1]
            price = latest['Close']
            sma50 = latest['sma50']
            sma200 = latest['sma200']
            ema5 = latest['ema5']
            breakout_high = latest['breakout_high']
            date_str = latest['Date']

            regime_ok = (price > sma50)
            is_breakout = (price > breakout_high)

            stop_loss_price = price * (1.0 - sl_pct)

            print(f"\n📌 {name} ({ticker}) - Optimal Strategy Model (CAGR: {cagr}% | Max DD: {max_dd}%):")
            print(f"   - Live Date: {date_str}")
            print(f"   - Current Price: ${price:,.2f}")
            print(f"   - {bw}-Day Breakout Trigger Level: ${breakout_high:,.2f}")
            print(f"   - 50-Day Trend Shield Level: ${sma50:,.2f}")
            print(f"   - Bull Market Status: {'✅ BULLISH (Price > 50 SMA)' if regime_ok else '❌ BEARISH / CASH'}")

            if regime_ok and is_breakout:
                print(f"   🚀 LIVE ACTION TODAY: 🔥 BUY SIGNAL (Breakout > ${breakout_high:,.2f})!")
                print(f"   🎯 Order Rules: Buy {name} at ${price:,.2f}. Max Hold: {hold_d} Days. Hard Stop-Loss: ${stop_loss_price:,.2f} (-5%). Exit if price closes < 5-EMA (${ema5:,.2f}).")
            elif regime_ok:
                print(f"   ⏳ LIVE ACTION TODAY: WATCHLIST / HOLD (In Bull Regime, waiting for close > ${breakout_high:,.2f})")
            else:
                print(f"   🛡️ LIVE ACTION TODAY: 100% CASH (Price < 50 SMA, 100% Capital Protected)")

        except Exception as e:
            print(f"Error fetching live data for {ticker}: {e}")

if __name__ == "__main__":
    get_live_crypto_signals()
