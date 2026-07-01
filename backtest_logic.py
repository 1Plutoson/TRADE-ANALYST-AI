import yfinance as yf
import pandas as pd
from backtesting import Backtest, Strategy

def detect_swing_high(high_series, window=5):
    """Returns True if the current high is the highest in the window."""
    return high_series == high_series.rolling(window=window*2+1, center=True).max()

class MarketStructureStrategy(Strategy):
    def init(self):
        # Access the closing and high/low prices
        self.high = self.data.High
        self.low = self.data.Low
        
        # Pre-compute swings using backtesting.py's I() wrapper
        self.swing_highs = self.I(detect_swing_high, pd.Series(self.high))

    def next(self):
        # Basic Logic: Buy if a new swing high is breached (Breakout)
        if self.swing_highs[-1]:
            # Close existing shorts and go long
            self.position.close()
            # Set a Stop Loss 2% below current price, Take Profit 4% above
            self.buy(sl=self.data.Close[-1] * 0.98, tp=self.data.Close[-1] * 1.04)

if __name__ == '__main__':
    # Download Historical Data
    print("Fetching data for backtest...")
    data = yf.download("BTC-USD", start="2023-01-01", end="2024-01-01", interval="1d")
    
    # Initialize and run backtest
    bt = Backtest(data, MarketStructureStrategy, cash=10000, commission=.002)
    stats = bt.run()
    
    print("\n--- BACKTEST RESULTS ---")
    print(stats)
    # bt.plot() # Uncomment to see the visual chart of trades
