import os
import asyncio
import pandas as pd
import yfinance as yf
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN")
genai.configure(api_key=os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_KEY"))

# --- MODULE 1: MARKET STRUCTURE (THE CHART MAPPER) ---
def map_market_structure(ticker, period="1mo", interval="1h"):
    """Fetches data and calculates HH, HL, LH, LL using swing highs/lows."""
    df = yf.download(ticker, period=period, interval=interval, progress=False)
    
    if df.empty:
        return None
    
    # Simple swing high/low detection (5-candle window)
    window = 5
    df['Swing_High'] = df['High'][df['High'] == df['High'].rolling(window=window*2+1, center=True).max()]
    df['Swing_Low'] = df['Low'][df['Low'] == df['Low'].rolling(window=window*2+1, center=True).min()]
    
    # Get the latest price action narrative
    recent_highs = df['Swing_High'].dropna().tail(2).values
    recent_lows = df['Swing_Low'].dropna().tail(2).values
    
    structure_narrative = "Market Structure: "
    if len(recent_highs) == 2 and recent_highs[1] > recent_highs[0]:
        structure_narrative += "Higher Highs (HH) detected. "
    elif len(recent_highs) == 2 and recent_highs[1] < recent_highs[0]:
        structure_narrative += "Lower Highs (LH) detected. "
        
    if len(recent_lows) == 2 and recent_lows[1] > recent_lows[0]:
        structure_narrative += "Higher Lows (HL) - Bullish structure. "
    elif len(recent_lows) == 2 and recent_lows[1] < recent_lows[0]:
        structure_narrative += "Lower Lows (LL) - Bearish structure. "

    current_price = df['Close'].iloc[-1]
    
    return {
        "ticker": ticker,
        "current_price": float(current_price.iloc[0]) if isinstance(current_price, pd.Series) else float(current_price),
        "structure": structure_narrative,
        "raw_data": df.tail(20) # Last 20 candles for the AI
    }

# --- MODULE 2: NEWS FETCHING ---
def fetch_latest_news(ticker):
    """Fetches recent news headlines to provide fundamental context to the AI."""
    stock = yf.Ticker(ticker)
    news = stock.news
    headlines = [item['title'] for item in news[:3]] if news else ["No recent major news."]
    return headlines

# --- MODULE 3: THE AI DRIVEN ANALYST ---
def generate_ai_analysis(market_data, news_data, strategy_preference):
    """Feeds the technicals and fundamentals to the LLM to act as a financial analyst."""
    model = genai.GenerativeModel('gemini-2.5-flash') # Fast model for snappy responses
    
    prompt = f"""
    You are an expert financial analyst and proprietary trader. 
    Review the following asset: {market_data['ticker']}
    Current Price: {market_data['current_price']}
    
    Technical State (Market Structure):
    {market_data['structure']}
    
    Recent News/Fundamentals:
    {news_data}
    
    The user prefers the following strategy: {strategy_preference}.
    
    Based on the market structure (HH, HL, LH, LL) and the news, provide a trade signal.
    Format your response strictly as:
    
    🎯 SIGNAL: [BUY, SELL, or HOLD]
    📊 REASONING: [Brief technical and fundamental justification]
    💰 ENTRY ZONE: [Price range]
    🛑 STOP LOSS (SL): [Strict price level based on recent swing low/high]
    🏆 TAKE PROFIT (TP): [Price level targeting the next liquidity zone]
    ⚠️ RISK MANAGEMENT: [Position sizing or validity warning, e.g., "Invalidate if 1H candle closes below SL"]
    """
    
    response = model.generate_content(prompt)
    return response.text

# --- MODULE 4: TELEGRAM BOT INTERFACE ---
async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggered by /analyze <ticker> <strategy>"""
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /analyze <TICKER> <STRATEGY>\nExample: /analyze BTC-USD Breakout")
        return

    ticker = context.args[0].upper()
    strategy = " ".join(context.args[1:]) if len(context.args) > 1 else "Trend Following"

    await update.message.reply_text(f"🔍 AI Analyst is mapping charts and reading news for {ticker}...")

    try:
        # 1. Analyze (Chart Mapping)
        market_data = map_market_structure(ticker)
        if not market_data:
            await update.message.reply_text(f"Could not fetch data for {ticker}.")
            return
            
        # 2. News Gathering
        news_data = fetch_latest_news(ticker)
        
        # 3. AI Plan & Signal Generation
        analysis_report = generate_ai_analysis(market_data, news_data, strategy)
        
        # 4. Act (Send to User)
        await update.message.reply_text(f"*{ticker} Analysis Report*\n\n{analysis_report}", parse_mode="Markdown")
        
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error during analysis: {str(e)}")

# --- MAIN EXECUTION ---
if __name__ == '__main__':
    print("Starting AI Analyst Bot...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("analyze", analyze_command))
    print("Bot is polling. Send /analyze in Telegram.")
    app.run_polling()
