import pandas as pd
import yfinance as yf
from backtesting import Backtest, Strategy

# ==========================================
# 1. STRATEGY LOGIC
# ==========================================
def detect_swing_high(high_series, window=5):
    """Returns True if the current high is the highest in the window."""
    # Note on backtesting: using `center=True` means the rolling window looks into the future.
    # While great for chart mapping (historical analysis), for live forward-trading, 
    # you'd typically use `center=False` to avoid lookahead bias.
    return high_series == high_series.rolling(window=window*2+1, center=True).max()

class MarketStructureStrategy(Strategy):
    def init(self):
        # Pre-compute swings using backtesting.py's I() wrapper
        self.swing_highs = self.I(detect_swing_high, pd.Series(self.data.High))

    def next(self):
        # Basic Logic: Buy if a new swing high is breached (Breakout)
        if self.swing_highs[-1]:
            # Close existing shorts and go long
            self.position.close()
            # Set a Stop Loss 2% below current price, Take Profit 4% above
            self.buy(sl=self.data.Close[-1] * 0.98, tp=self.data.Close[-1] * 1.04)

# ==========================================
# 2. DATA PIPELINE (MultiIndex Fix)
# ==========================================
def fetch_clean_data(ticker, start, end, interval="1d"):
    """Fetches data and fixes the yfinance MultiIndex bug that breaks backtesting."""
    print(f"Fetching {interval} data for {ticker} from {start} to {end}...")
    df = yf.download(ticker, start=start, end=end, interval=interval, progress=False)
    
    if df.empty:
        raise ValueError("No data fetched. Check the ticker symbol or date range.")
        
    # FIX: Flatten MultiIndex columns so backtesting.py doesn't crash
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
        
    return df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()

# ==========================================
# 3. BACKTEST EXECUTION
# ==========================================
if __name__ == '__main__':
    try:
        # Download and clean Historical Data
        data = fetch_clean_data("BTC-USD", start="2023-01-01", end="2024-01-01", interval="1d")
        
        # Initialize and run backtest
        print("Running backtest engine...")
        bt = Backtest(data, MarketStructureStrategy, cash=10000, commission=.002)
        stats = bt.run()
        
        print("\n==============================")
        print("      BACKTEST RESULTS")
        print("==============================")
        print(stats)
        
        # NOTE: To visualize the chart, uncomment the line below. 
        # (Requires running `pip install bokeh==3.4.1` in your terminal first)
        # bt.plot()
        
    except Exception as e:
        print(f"\n🚨 Critical Error during backtest: {e}")
