import os
import pandas as pd
import yfinance as yf
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from backtesting import Backtest, Strategy
from dotenv import load_dotenv

# ==========================================
# 1. ENVIRONMENT & API SETUP
# ==========================================
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    raise ValueError("🚨 MISSING API KEYS: Check your .env file!")

genai.configure(api_key=GEMINI_API_KEY)

# ==========================================
# 2. DATA PIPELINE & CHART MAPPER
# ==========================================
def fetch_clean_data(ticker, period="1y", interval="1d"):
    """Fetches data and fixes the yfinance MultiIndex bug that breaks backtesting."""
    try:
        df = yf.download(ticker, period=period, interval=interval, progress=False)
        if df.empty:
            return None
        
        # FIX: Flatten MultiIndex columns so backtesting.py doesn't crash
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
            
        return df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()
    except Exception as e:
        print(f"Data fetch error: {e}")
        return None

def map_market_structure(df):
    """Maps out Higher Highs, Higher Lows, Lower Highs, and Lower Lows."""
    window = 5
    df['Swing_High'] = df['High'][df['High'] == df['High'].rolling(window=window*2+1, center=True).max()]
    df['Swing_Low'] = df['Low'][df['Low'] == df['Low'].rolling(window=window*2+1, center=True).min()]
    
    highs = df['Swing_High'].dropna()
    lows = df['Swing_Low'].dropna()
    
    narrative = "Market Structure: "
    if len(highs) >= 2 and highs.iloc[-1] > highs.iloc[-2]:
        narrative += "Higher Highs (HH). "
    elif len(highs) >= 2:
        narrative += "Lower Highs (LH). "
        
    if len(lows) >= 2 and lows.iloc[-1] > lows.iloc[-2]:
        narrative += "Higher Lows (HL) - Bullish structure."
    elif len(lows) >= 2:
        narrative += "Lower Lows (LL) - Bearish structure."

    return narrative

# ==========================================
# 3. BACKTESTING MODULE
# ==========================================
def detect_swing_high(high_series, window=5):
    return high_series == high_series.rolling(window=window*2+1, center=True).max()

class MarketStructureStrategy(Strategy):
    def init(self):
        self.swing_highs = self.I(detect_swing_high, pd.Series(self.data.High))

    def next(self):
        if self.swing_highs[-1]:
            self.position.close()
            # Dynamic TP/SL built directly into the backtest engine
            self.buy(sl=self.data.Close[-1] * 0.98, tp=self.data.Close[-1] * 1.04)

def run_quick_backtest(ticker):
    """Runs a historical backtest to validate the strategy logic before asking the AI."""
    df = fetch_clean_data(ticker, period="1y", interval="1d")
    if df is None or len(df) < 50: 
        return "Insufficient data for backtest."
    bt = Backtest(df, MarketStructureStrategy, cash=10000, commission=.002)
    stats = bt.run()
    return f"Historical Return: {stats['Return [%]']:.2f}% | Win Rate: {stats['Win Rate [%]']:.2f}%"

# ==========================================
# 4. THE AI DRIVEN ANALYST
# ==========================================
def generate_ai_analysis(ticker, price, structure, news, strategy, backtest_stats):
    model = genai.GenerativeModel('gemini-2.5-flash')
    prompt = f"""
    You are an elite AI Proprietary Trader.
    Asset: {ticker} @ {price}
    Strategy Selected by User: {strategy}
    Current Technical Structure: {structure}
    Backtest of Core Strategy Logic: {backtest_stats}
    Latest Market News: {news}
    
    Provide a highly accurate trade setup. Determine if the setup is currently valid or invalid.
    Output your response cleanly without using markdown symbols that could break a Telegram bot:
    
    🎯 SIGNAL: [BUY, SELL, or HOLD]
    📊 REASONING: [Explain why based on the structure and news]
    💰 ENTRY ZONE: [Price range]
    🛑 STOP LOSS: [Strict price level based on recent swing low/high]
    🏆 TAKE PROFIT: [Price level targeting the next liquidity zone]
    ⚠️ RISK MANAGEMENT: [Position size advice and state exactly what makes this trade invalid]
    """
    return model.generate_content(prompt).text

# ==========================================
# 5. TELEGRAM BOT CONTROLLER
# ==========================================
async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ensure user provided a ticker
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /analyze <TICKER> <STRATEGY>\nExample: /analyze BTC-USD Breakout")
        return

    ticker = context.args[0].upper()
    # If user doesn't provide a strategy, default to Trend Following
    strategy = " ".join(context.args[1:]) if len(context.args) > 1 else "Trend Following"

    # Send a waiting message
    msg = await update.message.reply_text(f"⚙️ AI Analyst is mapping charts and backtesting {ticker}...")

    try:
        df = fetch_clean_data(ticker)
        if df is None:
            await msg.edit_text(f"⚠️ Could not fetch market data for {ticker}.")
            return

        current_price = df['Close'].iloc[-1]
        structure = map_market_structure(df)
        
        # Fetch actual news safely
        news = "No major breaking news"
        try:
            news_data = yf.Ticker(ticker).news
            if news_data: 
                news = news_data[0].get('title', 'No major breaking news')
        except Exception:
            pass
            
        # Run Backtest
        backtest_results = run_quick_backtest(ticker)
        
        # Trigger the AI Analyst
        ai_report = generate_ai_analysis(ticker, current_price, structure, news, strategy, backtest_results)
        
        # Edit the original message with the final report
        await msg.edit_text(f"{ticker} AI Analyst Report:\n\n{ai_report}")
        
    except Exception as e:
        await msg.edit_text(f"🚨 Critical Error during analysis: {str(e)}")

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == '__main__':
    print("Initializing AI Analyst Engine...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Add the analyze command handler
    app.add_handler(CommandHandler("analyze", analyze_command))
    
    print("Bot is successfully polling! Open Telegram and type /analyze to test.")
    app.run_polling()
