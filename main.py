import os
import pandas as pd
import yfinance as yf
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from backtesting import Backtest, Strategy
from dotenv import load_dotenv

# ==========================================
# 1. ENVIRONMENT & API SETUP (RAILWAY READY)
# ==========================================
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    print("🚨 FATAL ERROR: Missing API Keys! If on Railway, check the 'Variables' tab.")
    exit(1)

genai.configure(api_key=GEMINI_API_KEY)

# Global dictionary to track active trades for the monitoring engine
active_monitors = {}

# ==========================================
# 2. DATA PIPELINE & CHART MAPPER
# ==========================================
def fetch_clean_data(ticker, period="1mo", interval="1h"):
    """Fetches data and fixes the yfinance MultiIndex bug."""
    try:
        df = yf.download(ticker, period=period, interval=interval, progress=False)
        if df.empty:
            return None
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
            self.buy(sl=self.data.Close[-1] * 0.98, tp=self.data.Close[-1] * 1.04)

def run_quick_backtest(ticker):
    """Runs a historical backtest to validate logic."""
    df = fetch_clean_data(ticker, period="1y", interval="1d")
    if df is None or len(df) < 50: 
        return "Insufficient data for backtest."
    try:
        bt = Backtest(df, MarketStructureStrategy, cash=10000, commission=.002)
        stats = bt.run()
        return f"Historical Return: {stats['Return [%]']:.2f}% | Win Rate: {stats['Win Rate [%]']:.2f}%"
    except:
        return "Backtest Engine Error."

# ==========================================
# 4. THE AI DRIVEN ANALYST
# ==========================================
def generate_ai_analysis(ticker, price, structure, news, strategy, backtest_stats, is_update=False):
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    if is_update:
        prompt = f"""
        You are monitoring {ticker} at {price}. Structure: {structure}. News: {news}.
        Based on this new data, is the {strategy} setup STILL VALID or INVALID? 
        Give a short 3-sentence update on what the trader should do right now.
        """
    else:
        prompt = f"""
        You are an elite AI Proprietary Trader.
        Asset: {ticker} @ {price}
        Strategy Selected by User: {strategy}
        Current Technical Structure: {structure}
        Backtest of Core Strategy Logic: {backtest_stats}
        Latest Market News: {news}
        
        Provide a highly accurate trade setup cleanly without using markdown symbols.
        
        🎯 SIGNAL: [BUY, SELL, or HOLD]
        📊 REASONING: [Explain why based on structure and news]
        📈 TRADINGVIEW GUIDE: [Tell the user exactly how to map this strategy on their TradingView chart, identifying the HH/HL/LH/LL levels]
        💰 ENTRY ZONE: [Price range]
        🛑 STOP LOSS: [Strict price level based on structure]
        🏆 TAKE PROFIT: [Price level targeting liquidity]
        ⚠️ RISK MANAGEMENT: [Position size advice and state exactly what makes this trade invalid]
        """
    return model.generate_content(prompt).text

# ==========================================
# 5. TELEGRAM BOT CONTROLLERS & BACKGROUND JOBS
# ==========================================
async def fetch_and_analyze(ticker, strategy, is_update=False):
    """Helper function to fetch all data and call the AI."""
    df = fetch_clean_data(ticker)
    if df is None: return None
    
    current_price = df['Close'].iloc[-1]
    structure = map_market_structure(df)
    
    news = "No major breaking news"
    try:
        news_data = yf.Ticker(ticker).news
        if news_data: news = news_data[0].get('title', 'No major breaking news')
    except: pass
        
    backtest_results = run_quick_backtest(ticker) if not is_update else ""
    return generate_ai_analysis(ticker, current_price, structure, news, strategy, backtest_results, is_update)

async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /analyze <TICKER> <STRATEGY>"""
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /analyze <TICKER> <STRATEGY>")
        return

    ticker = context.args[0].upper()
    strategy = " ".join(context.args[1:]) if len(context.args) > 1 else "Trend Following"

    msg = await update.message.reply_text(f"⚙️ AI Analyst is mapping charts and backtesting {ticker}...")
    try:
        ai_report = await fetch_and_analyze(ticker, strategy)
        if ai_report:
            await msg.edit_text(f"{ticker} AI Analyst Report:\n\n{ai_report}")
        else:
            await msg.edit_text(f"⚠️ Could not fetch market data for {ticker}.")
    except Exception as e:
        await msg.edit_text(f"🚨 Critical Error: {str(e)}")

async def monitor_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /monitor <TICKER> <STRATEGY> - Adds to background loop"""
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /monitor <TICKER> <STRATEGY>")
        return

    ticker = context.args[0].upper()
    strategy = " ".join(context.args[1:]) if len(context.args) > 1 else "Trend Following"
    chat_id = update.message.chat_id
    
    # Store in memory for background tracking
    active_monitors[f"{chat_id}_{ticker}"] = {"chat_id": chat_id, "ticker": ticker, "strategy": strategy}
    
    await update.message.reply_text(f"👀 Now monitoring {ticker} for {strategy} setups. I will alert you if market structure breaks or validity changes.")
    # Run initial analysis
    await analyze_command(update, context)

async def check_active_monitors(context: ContextTypes.DEFAULT_TYPE):
    """Background Job: Runs periodically to check all active monitors."""
    for key, data in list(active_monitors.items()):
        try:
            update_report = await fetch_and_analyze(data['ticker'], data['strategy'], is_update=True)
            if update_report:
                # Send the update to the specific user chat
                await context.bot.send_message(
                    chat_id=data['chat_id'], 
                    text=f"⚠️ MARKET UPDATE for {data['ticker']} ⚠️\n\n{update_report}"
                )
        except Exception as e:
            print(f"Monitor error for {data['ticker']}: {e}")

# ==========================================
# MAIN EXECUTION (RAILWAY OPTIMIZED)
# ==========================================
if __name__ == '__main__':
    print("Initializing AI Analyst Engine on Railway...")
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Register Commands
    app.add_handler(CommandHandler("analyze", analyze_command))
    app.add_handler(CommandHandler("monitor", monitor_command))
    
    # Register Background Job (Runs every 3600 seconds / 1 Hour)
    # Note: Frequent updates easily eat up Gemini API limits, 1 hour is safe for swing trading structure.
    job_queue = app.job_queue
    job_queue.run_repeating(check_active_monitors, interval=3600, first=3600)
    
    print("Bot is successfully polling on Railway cloud!")
    app.run_polling()
