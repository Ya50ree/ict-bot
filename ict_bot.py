# “””

# بوت ICT متعدد الفريمات مع صورة شارت

“””

import os
import io
import anthropic
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use(“Agg”)
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
Application, CommandHandler, MessageHandler,
CallbackQueryHandler, filters, ContextTypes
)

TELEGRAM_TOKEN = os.environ[“TELEGRAM_TOKEN”]
ANTHROPIC_KEY  = os.environ[“ANTHROPIC_KEY”]
client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

TIMEFRAME_CONFIG = {
“1d”:  {“period”: “180d”, “interval”: “1d”,  “label”: “يومي”},
“1h”:  {“period”: “60d”,  “interval”: “1h”,  “label”: “ساعة”},
“15m”: {“period”: “10d”,  “interval”: “15m”, “label”: “15 دقيقة”},
“5m”:  {“period”: “5d”,   “interval”: “5m”,  “label”: “5 دقائق”},
}

def get_ohlcv(symbol, interval=“1h”, period=None):
cfg = TIMEFRAME_CONFIG.get(interval, TIMEFRAME_CONFIG[“1h”])
if period is None:
period = cfg[“period”]
try:
df = yf.download(symbol, period=period, interval=interval,
auto_adjust=True, progress=False)
if df.empty or len(df) < 10:
return None
if isinstance(df.columns, pd.MultiIndex):
df.columns = [c[0].lower() for c in df.columns]
else:
df.columns = [c.lower() for c in df.columns]
df.index = pd.to_datetime(df.index)
return df.tail(120)
except:
return None

def detect_order_blocks(df, lookback=5):
obs = []
if df is None or len(df) < lookback + 2:
return obs
closes = df[“close”].values
highs  = df[“high”].values
lows   = df[“low”].values
opens  = df[“open”].values
for i in range(lookback, len(df) - 1):
if (closes[i] > opens[i] and closes[i+1] < opens[i+1] and closes[i+1] < lows[i]):
obs.append({“type”: “Bearish OB”, “top”: round(float(highs[i]), 4),
“bot”: round(float(opens[i]), 4), “idx”: i})
if (closes[i] < opens[i] and closes[i+1] > opens[i+1] and closes[i+1] > highs[i]):
obs.append({“type”: “Bullish OB”, “top”: round(float(opens[i]), 4),
“bot”: round(float(lows[i]), 4), “idx”: i})
return obs[-4:] if obs else []

def detect_fvg(df):
fvgs = []
if df is None or len(df) < 3:
return fvgs
highs  = df[“high”].values
lows   = df[“low”].values
closes = df[“close”].values
for i in range(1, len(df) - 1):
if lows[i+1] > highs[i-1]:
fvgs.append({“type”: “Bullish FVG”, “top”: round(float(lows[i+1]), 4),
“bot”: round(float(highs[i-1]), 4),
“size”: round(float(lows[i+1] - highs[i-1]), 4),
“filled”: float(closes[-1]) <= float(lows[i+1]), “idx”: i})
if highs[i+1] < lows[i-1]:
fvgs.append({“type”: “Bearish FVG”, “top”: round(float(lows[i-1]), 4),
“bot”: round(float(highs[i+1]), 4),
“size”: round(float(lows[i-1] - highs[i+1]), 4),
“filled”: float(closes[-1]) >= float(lows[i-1]), “idx”: i})
open_fvgs = sorted([f for f in fvgs if not f[“filled”]], key=lambda x: x[“size”], reverse=True)
return open_fvgs[:4]

def detect_liquidity(df, swing=5):
if df is None or len(df) < swing * 2 + 1:
return {“BSL”: [], “SSL”: [], “price”: 0}
highs  = df[“high”].values
lows   = df[“low”].values
closes = df[“close”].values
price  = float(closes[-1])
bsl = [round(float(highs[i]), 4) for i in range(swing, len(highs) - swing)
if highs[i] == max(highs[i-swing:i+swing+1]) and float(highs[i]) > price]
ssl = [round(float(lows[i]), 4) for i in range(swing, len(lows) - swing)
if lows[i] == min(lows[i-swing:i+swing+1]) and float(lows[i]) < price]
return {“BSL”: sorted(bsl)[:3], “SSL”: sorted(ssl, reverse=True)[:3], “price”: round(price, 4)}

def draw_chart(df, obs, fvgs, liq, symbol, tf_label):
if df is None or len(df) < 5:
return None
fig, ax = plt.subplots(figsize=(12, 6))
fig.patch.set_facecolor(”#0d1117”)
ax.set_facecolor(”#0d1117”)
tail = df.tail(60)
for i, (idx, row) in enumerate(tail.iterrows()):
o, h, l, c = float(row[“open”]), float(row[“high”]), float(row[“low”]), float(row[“close”])
color = “#26a69a” if c >= o else “#ef5350”
ax.plot([i, i], [l, h], color=color, linewidth=0.8)
ax.add_patch(plt.Rectangle((i - 0.3, min(o, c)), 0.6, abs(c - o), color=color, zorder=2))
x_len = len(tail)
for ob in obs:
rel_idx = max(0, ob[“idx”] - (len(df) - 60))
color  = “#ef535033” if “Bearish” in ob[“type”] else “#26a69a33”
border = “#ef5350”   if “Bearish” in ob[“type”] else “#26a69a”
ax.add_patch(plt.Rectangle((rel_idx, ob[“bot”]), x_len - rel_idx,
ob[“top”] - ob[“bot”], color=color, zorder=1))
ax.axhline(ob[“top”], color=border, linewidth=0.6, linestyle=”–”, alpha=0.7)
ax.axhline(ob[“bot”], color=border, linewidth=0.6, linestyle=”–”, alpha=0.7)
ax.text(x_len - 1, ob[“top”], f” {ob[‘type’][:3]} OB”,
color=border, fontsize=6, va=“bottom”, ha=“right”)
for fvg in fvgs:
rel_idx = max(0, fvg[“idx”] - (len(df) - 60))
color = “#ffeb3b22” if “Bullish” in fvg[“type”] else “#ff980022”
ax.add_patch(plt.Rectangle((rel_idx, fvg[“bot”]), x_len - rel_idx,
fvg[“top”] - fvg[“bot”], color=color, zorder=1))
for lvl in liq[“BSL”]:
ax.axhline(lvl, color=”#64b5f6”, linewidth=0.8, linestyle=”:”, alpha=0.8)
ax.text(x_len - 1, lvl, f” BSL ${lvl}”, color=”#64b5f6”, fontsize=6, va=“bottom”, ha=“right”)
for lvl in liq[“SSL”]:
ax.axhline(lvl, color=”#f48fb1”, linewidth=0.8, linestyle=”:”, alpha=0.8)
ax.text(x_len - 1, lvl, f” SSL ${lvl}”, color=”#f48fb1”, fontsize=6, va=“top”, ha=“right”)
ax.axhline(liq[“price”], color=”#ffffff”, linewidth=1, linestyle=”-”, alpha=0.9)
ax.text(x_len - 1, liq[“price”], f” ${liq[‘price’]}”,
color=“white”, fontsize=7, va=“center”, ha=“right”, fontweight=“bold”)
ax.spines[“top”].set_visible(False)
ax.spines[“right”].set_visible(False)
ax.spines[“bottom”].set_color(”#30363d”)
ax.spines[“left”].set_color(”#30363d”)
ax.tick_params(colors=”#8b949e”, labelsize=7)
ax.set_title(f”{symbol} — {tf_label}  |  ICT Analysis”, color=“white”, fontsize=10, pad=8)
ax.set_xlabel(“الشموع الأخيرة”, color=”#8b949e”, fontsize=7)
ax.set_ylabel(“السعر $”, color=”#8b949e”, fontsize=7)
legend_items = [
mpatches.Patch(color=”#26a69a”, label=“Bullish OB”),
mpatches.Patch(color=”#ef5350”, label=“Bearish OB”),
mpatches.Patch(color=”#ffeb3b”, label=“FVG”),
mpatches.Patch(color=”#64b5f6”, label=“BSL”),
mpatches.Patch(color=”#f48fb1”, label=“SSL”),
]
ax.legend(handles=legend_items, loc=“upper left”,
facecolor=”#161b22”, edgecolor=”#30363d”, labelcolor=“white”, fontsize=6)
plt.tight_layout()
buf = io.BytesIO()
plt.savefig(buf, format=“png”, dpi=130, facecolor=fig.get_facecolor())
plt.close(fig)
buf.seek(0)
return buf

def analyze_mtf_claude(symbol, daily, h1, m5):
d_liq = detect_liquidity(daily)
h_liq = detect_liquidity(h1)
m_liq = detect_liquidity(m5) if m5 is not None else {“BSL”: [], “SSL”: [], “price”: 0}
d_obs = detect_order_blocks(daily)
h_obs = detect_order_blocks(h1)
m_obs = detect_order_blocks(m5) if m5 is not None else []
d_fvgs = detect_fvg(daily)
h_fvgs = detect_fvg(h1)
m_fvgs = detect_fvg(m5) if m5 is not None else []

```
prompt = f"""أنت محلل ICT/SMC محترف. حلل السهم {symbol} بمنهجية Top-Down من اليومي للـ 5 دقائق.
```

اليومي — السعر: ${d_liq[‘price’]}
OB: {[f”{o[‘type’]} {o[‘bot’]}-{o[‘top’]}” for o in d_obs] or ‘لا يوجد’}
FVG: {[f”{f[‘type’]} {f[‘bot’]}-{f[‘top’]}” for f in d_fvgs] or ‘لا يوجد’}
BSL: {d_liq[‘BSL’]} / SSL: {d_liq[‘SSL’]}

الساعة:
OB: {[f”{o[‘type’]} {o[‘bot’]}-{o[‘top’]}” for o in h_obs] or ‘لا يوجد’}
FVG: {[f”{f[‘type’]} {f[‘bot’]}-{f[‘top’]}” for f in h_fvgs] or ‘لا يوجد’}
BSL: {h_liq[‘BSL’]} / SSL: {h_liq[‘SSL’]}

5 دقائق:
OB: {[f”{o[‘type’]} {o[‘bot’]}-{o[‘top’]}” for o in m_obs] or ‘لا يوجد’}
FVG: {[f”{f[‘type’]} {f[‘bot’]}-{f[‘top’]}” for f in m_fvgs] or ‘لا يوجد’}
BSL: {m_liq[‘BSL’]} / SSL: {m_liq[‘SSL’]}

أعطني:
📅 الاتجاه اليومي: [صاعد/هابط/محايد + سبب]
⏰ تحليل الساعة: [وصف المنطقة]
⚡ إشارة الـ5 دقائق: [تفصيل الدخول]

🎯 الإشارة: [شراء/بيع/انتظار]
✅ الدخول: $[رقم] — السبب: [OB/FVG/سيولة]
🛑 وقف الخسارة: $[رقم]
🎁 الهدف 1: $[رقم]
🎁 الهدف 2: $[رقم]
📊 R:R: [رقم]:1
💡 ملاحظة ICT: [نصيحة جملة واحدة]
⚠️ تحذير: [خطر محتمل جملة واحدة]”””

```
msg = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=900,
    messages=[{"role": "user", "content": prompt}]
)
return msg.content[0].text.strip(), d_liq, d_obs, d_fvgs
```

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
await update.message.reply_text(
“👋 أهلاً في بوت ICT المتقدم!\n\n”
“📌 كيف تستخدمه:\n”
“1️⃣ أرسل رمز السهم مثل: NVDA\n”
“2️⃣ اختار الفريم من الأزرار\n”
“3️⃣ استلم تحليل كامل + صورة شارت\n\n”
“جرّب: AAPL أو TSLA أو NVDA 🚀”
)

async def handle_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE):
symbol = update.message.text.strip().upper()
if len(symbol) > 10 or “ “ in symbol:
await update.message.reply_text(“أرسل رمز السهم فقط، مثل: NVDA”)
return
context.user_data[“symbol”] = symbol
keyboard = [
[InlineKeyboardButton(“📅 يومي”, callback_data=f”tf_{symbol}*1d”),
InlineKeyboardButton(“⏰ ساعة”, callback_data=f”tf*{symbol}*1h”)],
[InlineKeyboardButton(“🕐 15 دقيقة”, callback_data=f”tf*{symbol}*15m”),
InlineKeyboardButton(“⚡ 5 دقائق”, callback_data=f”tf*{symbol}*5m”)],
[InlineKeyboardButton(“🔥 تحليل كامل (يومي+ساعة+5د)”, callback_data=f”tf*{symbol}_mtf”)],
]
await update.message.reply_text(
f”📊 السهم: *{symbol}*\nاختار الفريم:”,
reply_markup=InlineKeyboardMarkup(keyboard),
parse_mode=“Markdown”
)

async def handle_timeframe(update: Update, context: ContextTypes.DEFAULT_TYPE):
query = update.callback_query
await query.answer()
parts  = query.data.split(”_”)
symbol = parts[1]
tf     = parts[2]
await query.edit_message_text(f”⏳ جاري تحليل {symbol}…”)

```
if tf == "mtf":
    daily = get_ohlcv(symbol, "1d")
    h1    = get_ohlcv(symbol, "1h")
    m5    = get_ohlcv(symbol, "5m")
    if daily is None or h1 is None:
        await query.edit_message_text(f"❌ تعذّر جلب بيانات {symbol}")
        return
    analysis, d_liq, d_obs, d_fvgs = analyze_mtf_claude(symbol, daily, h1, m5)
    header = (f"━━━━━━━━━━━━━━━━━━━━━\n"
              f"🔥 تحليل كامل — {symbol}\n"
              f"📅 يومي ← ⏰ ساعة ← ⚡ 5د\n"
              f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
              f"━━━━━━━━━━━━━━━━━━━━━\n\n")
    caption = header + analysis + "\n\n⚠️ للأغراض التعليمية"
    chart = draw_chart(daily, d_obs, d_fvgs, d_liq, symbol, "يومي")
    await query.delete_message()
    if chart:
        await context.bot.send_photo(chat_id=query.message.chat_id,
                                     photo=chart, caption=caption[:1024])
        if len(caption) > 1024:
            await context.bot.send_message(chat_id=query.message.chat_id,
                                           text=caption[1024:])
    else:
        await context.bot.send_message(chat_id=query.message.chat_id, text=caption)
    return

cfg = TIMEFRAME_CONFIG.get(tf, TIMEFRAME_CONFIG["1h"])
df  = get_ohlcv(symbol, tf)
if df is None:
    await query.edit_message_text(f"❌ تعذّر جلب بيانات {symbol}")
    return

obs  = detect_order_blocks(df)
fvgs = detect_fvg(df)
liq  = detect_liquidity(df)
price = liq["price"]

near  = [f"السعر داخل {o['type']}" for o in obs if o["bot"]*0.995 <= price <= o["top"]*1.005]
near += [f"السعر داخل {f['type']}" for f in fvgs if f["bot"]*0.995 <= price <= f["top"]*1.005]
swept  = [f"سحب BSL {l}" for l in liq["BSL"] if price >= l*0.999]
swept += [f"سحب SSL {l}" for l in liq["SSL"] if price <= l*1.001]

prompt = f"""أنت محلل ICT/SMC. السهم {symbol} فريم {cfg['label']} السعر ${price}
```

OB: {[f”{o[‘type’]} {o[‘bot’]}-{o[‘top’]}” for o in obs] or ‘لا يوجد’}
FVG: {[f”{f[‘type’]} {f[‘bot’]}-{f[‘top’]}” for f in fvgs] or ‘لا يوجد’}
BSL: {liq[‘BSL’]} / SSL: {liq[‘SSL’]}
{near or [‘خارج المناطق’]} {swept or [’’]}

أعطني:
📍 الوضع: [وصف دقيق]
🎯 الإشارة: [شراء/بيع/انتظار]
📌 السبب: [OB/FVG/سيولة]
✅ الدخول: $[رقم]
🛑 وقف الخسارة: $[رقم]
🎁 الهدف 1: $[رقم]
🎁 الهدف 2: $[رقم]
📊 R:R: [رقم]:1
⚠️ تنبيه: [جملة واحدة]”””

```
msg = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=600,
    messages=[{"role": "user", "content": prompt}]
)
analysis = msg.content[0].text.strip()

header = (f"━━━━━━━━━━━━━━━━━━━━━\n"
          f"📈 {symbol} — {cfg['label']}\n"
          f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
          f"━━━━━━━━━━━━━━━━━━━━━\n\n")
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

caption = header + zones + "\n" + "─"*21 + "\n\n" + analysis + "\n\n⚠️ للأغراض التعليمية"
chart = draw_chart(df, obs, fvgs, liq, symbol, cfg["label"])

await query.delete_message()
if chart:
    await context.bot.send_photo(chat_id=query.message.chat_id,
                                 photo=chart, caption=caption[:1024])
    if len(caption) > 1024:
        await context.bot.send_message(chat_id=query.message.chat_id, text=caption[1024:])
else:
    await context.bot.send_message(chat_id=query.message.chat_id, text=caption)
```

def main():
app = Application.builder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler(“start”, cmd_start))
app.add_handler(CallbackQueryHandler(handle_timeframe, pattern=”^tf_”))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_symbol))
print(“✅ البوت يعمل — متعدد الفريمات + صورة شارت”)
app.run_polling(drop_pending_updates=True)

if **name** == “**main**”:
main()
