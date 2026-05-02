import os
import anthropic
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_KEY  = os.environ["ANTHROPIC_KEY"]
client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

def get_ohlcv(symbol):
    try:
        df = yf.download(symbol, period="60d", interval="1h",
                         auto_adjust=True, progress=False)
        if df.empty or len(df) < 20:
            return None
        df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
        return df.tail(100)
    except:
        return None

def detect_order_blocks(df):
    obs = []
    closes, highs, lows, opens = df["close"].values, df["high"].values, df["low"].values, df["open"].values
    for i in range(5, len(df)-1):
        if closes[i]>opens[i] and closes[i+1]<opens[i+1] and closes[i+1]<lows[i]:
            obs.append({"type":"Bearish OB","top":round(float(highs[i]),4),"bot":round(float(opens[i]),4),"time":str(df.index[i])[:16]})
        if closes[i]<opens[i] and closes[i+1]>opens[i+1] and closes[i+1]>highs[i]:
            obs.append({"type":"Bullish OB","top":round(float(opens[i]),4),"bot":round(float(lows[i]),4),"time":str(df.index[i])[:16]})
    return obs[-3:] if obs else []

def detect_fvg(df):
    fvgs = []
    highs, lows, closes = df["high"].values, df["low"].values, df["close"].values
    for i in range(1, len(df)-1):
        if lows[i+1]>highs[i-1]:
            fvgs.append({"type":"Bullish FVG","top":round(float(lows[i+1]),4),"bot":round(float(highs[i-1]),4),"size":round(float(lows[i+1]-highs[i-1]),4),"filled":float(closes[-1])<=float(lows[i+1])})
        if highs[i+1]<lows[i-1]:
            fvgs.append({"type":"Bearish FVG","top":round(float(lows[i-1]),4),"bot":round(float(highs[i+1]),4),"size":round(float(lows[i-1]-highs[i+1]),4),"filled":float(closes[-1])>=float(lows[i-1])})
    open_fvgs = sorted([f for f in fvgs if not f["filled"]], key=lambda x:x["size"], reverse=True)
    return open_fvgs[:3]

def detect_liquidity(df):
    highs, lows, closes = df["high"].values, df["low"].values, df["close"].values
    price = float(closes[-1])
    bsl = [round(float(highs[i]),4) for i in range(5,len(highs)-5) if highs[i]==max(highs[i-5:i+6]) and float(highs[i])>price]
    ssl = [round(float(lows[i]),4) for i in range(5,len(lows)-5) if lows[i]==min(lows[i-5:i+6]) and float(lows[i])<price]
    return {"BSL":sorted(bsl)[:3],"SSL":sorted(ssl,reverse=True)[:3],"price":round(price,4)}

def analyze_with_claude(symbol, obs, fvgs, liq):
    price = liq["price"]
    near_zone = [f"السعر داخل {o['type']} ({o['bot']}–{o['top']})" for o in obs if o["bot"]*0.995<=price<=o["top"]*1.005]
    near_zone += [f"السعر داخل {f['type']} ({f['bot']}–{f['top']})" for f in fvgs if f["bot"]*0.995<=price<=f["top"]*1.005]
    swept = [f"سحب BSL عند {lvl}" for lvl in liq["BSL"] if price>=lvl*0.999]
    swept += [f"سحب SSL عند {lvl}" for lvl in liq["SSL"] if price<=lvl*1.001]

    prompt = f"""أنت محلل ICT/SMC محترف. السهم: {symbol} السعر: ${price}
OB: {[f"{o['type']} {o['bot']}-{o['top']}" for o in obs] or "لا يوجد"}
FVG: {[f"{f['type']} {f['bot']}-{f['top']}" for f in fvgs] or "لا يوجد"}
BSL: {liq['BSL']} / SSL: {liq['SSL']}
ملاحظات: {near_zone or ["خارج المناطق"]} {swept or ["لم يسحب سيولة"]}

أعطني التحليل بهذا الشكل فقط:
📍 الوضع: [وصف]
🎯 الإشارة: [شراء/بيع/انتظار]
📌 السبب: [جملة واحدة]
✅ الدخول: $[رقم]
🛑 وقف الخسارة: $[رقم]
🎁 الهدف 1: $[رقم]
🎁 الهدف 2: $[رقم]
📊 R:R: [رقم]:1
⚠️ تنبيه: [جملة واحدة]"""

    msg = client.messages.create(model="model="claude-sonnet-4-5"
", max_tokens=600,
                                  messages=[{"role":"user","content":prompt}])
    return msg.content[0].text.strip()

async def run_analysis(symbol):
    df = get_ohlcv(symbol)
    if df is None:
        return f"❌ تعذّر جلب بيانات '{symbol}'"
    obs  = detect_order_blocks(df)
    fvgs = detect_fvg(df)
    liq  = detect_liquidity(df)
    analysis = analyze_with_claude(symbol.upper(), obs, fvgs, liq)
    header = f"━━━━━━━━━━━━━━━━━━━━━\n📈 تحليل ICT — {symbol.upper()}\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    zones = ""
    if obs:
        zones += "🔲 Order Blocks:\n"
        for o in obs:
            zones += f"  {'🟢' if 'Bullish' in o['type'] else '🔴'} {o['type']}: ${o['bot']}–${o['top']}\n"
    if fvgs:
        zones += "\n🟡 FVG مفتوحة:\n"
        for f in fvgs:
            zones += f"  {'🟢' if 'Bullish' in f['type'] else '🔴'} {f['type']}: ${f['bot']}–${f['top']}\n"
    if liq["BSL"] or liq["SSL"]:
        zones += "\n💧 السيولة:\n"
        if liq["BSL"]: zones += f"  🔼 BSL: {liq['BSL']}\n"
        if liq["SSL"]: zones += f"  🔽 SSL: {liq['SSL']}\n"
    return header + zones + "\n" + "─"*21 + "\n\n" + analysis + "\n\n⚠️ للأغراض التعليمية"

async def cmd_start(update, context):
    await update.message.reply_text("👋 أهلاً في بوت ICT!\n\nأرسل رمز سهم أمريكي:\nمثال: AAPL — NVDA — TSLA 🚀")

async def cmd_help(update, context):
    await update.message.reply_text("📖 المصطلحات:\n🔲 OB: أوامر المؤسسات\n🟡 FVG: فراغ سعري\n💧 BSL/SSL: مناطق السيولة\n📊 R:R: نسبة المخاطرة")

async def handle_symbol(update, context):
    symbol = update.message.text.strip().upper()
    if len(symbol) > 10 or " " in symbol:
        await update.message.reply_text("أرسل رمز السهم فقط، مثل: NVDA")
        return
    msg = await update.message.reply_text(f"⏳ جاري تحليل {symbol}...")
    result = await run_analysis(symbol)
    await msg.edit_text(result)

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_symbol))
    print("✅ البوت يعمل على Railway")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
