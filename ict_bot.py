import os, io, anthropic, yfinance as yf, pandas as pd, numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt, matplotlib.patches as mpatches
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ['TELEGRAM_TOKEN']
ANTHROPIC_KEY = os.environ['ANTHROPIC_KEY']
client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

TF = {'1d':{'period':'180d','interval':'1d','label':'Daily'},'1h':{'period':'60d','interval':'1h','label':'1H'},'15m':{'period':'10d','interval':'15m','label':'15M'},'5m':{'period':'5d','interval':'5m','label':'5M'}}

def get_df(symbol, interval):
    try:
        cfg = TF.get(interval, TF['1h'])
        df = yf.download(symbol, period=cfg['period'], interval=interval, auto_adjust=True, progress=False)
        if df.empty or len(df) < 10: return None
        df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
        return df.tail(120)
    except: return None

def get_obs(df):
    obs = []
    if df is None or len(df) < 7: return obs
    c,h,l,o = df['close'].values,df['high'].values,df['low'].values,df['open'].values
    for i in range(5, len(df)-1):
        if c[i]>o[i] and c[i+1]<o[i+1] and c[i+1]<l[i]: obs.append({'type':'Bearish OB','top':round(float(h[i]),4),'bot':round(float(o[i]),4),'idx':i})
        if c[i]<o[i] and c[i+1]>o[i+1] and c[i+1]>h[i]: obs.append({'type':'Bullish OB','top':round(float(o[i]),4),'bot':round(float(l[i]),4),'idx':i})
    return obs[-4:] if obs else []

def get_fvg(df):
    fvgs = []
    if df is None or len(df) < 3: return fvgs
    h,l,c = df['high'].values,df['low'].values,df['close'].values
    for i in range(1, len(df)-1):
        if l[i+1]>h[i-1]: fvgs.append({'type':'Bullish FVG','top':round(float(l[i+1]),4),'bot':round(float(h[i-1]),4),'size':round(float(l[i+1]-h[i-1]),4),'filled':float(c[-1])<=float(l[i+1]),'idx':i})
        if h[i+1]<l[i-1]: fvgs.append({'type':'Bearish FVG','top':round(float(l[i-1]),4),'bot':round(float(h[i+1]),4),'size':round(float(l[i-1]-h[i+1]),4),'filled':float(c[-1])>=float(l[i-1]),'idx':i})
    return sorted([f for f in fvgs if not f['filled']], key=lambda x:x['size'], reverse=True)[:4]

def get_liq(df, sw=5):
    if df is None or len(df) < sw*2+1: return {'BSL':[],'SSL':[],'price':0}
    h,l,c = df['high'].values,df['low'].values,df['close'].values
    price = float(c[-1])
    bsl = [round(float(h[i]),4) for i in range(sw,len(h)-sw) if h[i]==max(h[i-sw:i+sw+1]) and float(h[i])>price]
    ssl = [round(float(l[i]),4) for i in range(sw,len(l)-sw) if l[i]==min(l[i-sw:i+sw+1]) and float(l[i])<price]
    return {'BSL':sorted(bsl)[:3],'SSL':sorted(ssl,reverse=True)[:3],'price':round(price,4)}

def draw_chart(df, obs, fvgs, liq, symbol, label):
    if df is None or len(df) < 5: return None
    fig, ax = plt.subplots(figsize=(12,6))
    fig.patch.set_facecolor('#0d1117'); ax.set_facecolor('#0d1117')
    tail = df.tail(60)
    for i,(idx,row) in enumerate(tail.iterrows()):
        o2,h2,l2,c2 = float(row['open']),float(row['high']),float(row['low']),float(row['close'])
        col = '#26a69a' if c2>=o2 else '#ef5350'
        ax.plot([i,i],[l2,h2],color=col,linewidth=0.8)
        ax.add_patch(plt.Rectangle((i-0.3,min(o2,c2)),0.6,abs(c2-o2),color=col,zorder=2))
    xlen = len(tail)
    for ob in obs:
        ri = max(0, ob['idx']-(len(df)-60))
        col = '#ef535033' if 'Bearish' in ob['type'] else '#26a69a33'
        brd = '#ef5350' if 'Bearish' in ob['type'] else '#26a69a'
        ax.add_patch(plt.Rectangle((ri,ob['bot']),xlen-ri,ob['top']-ob['bot'],color=col,zorder=1))
        ax.axhline(ob['top'],color=brd,linewidth=0.6,linestyle='--',alpha=0.7)
        ax.axhline(ob['bot'],color=brd,linewidth=0.6,linestyle='--',alpha=0.7)
    for fvg in fvgs:
        ri = max(0, fvg['idx']-(len(df)-60))
        col = '#ffeb3b22' if 'Bullish' in fvg['type'] else '#ff980022'
        ax.add_patch(plt.Rectangle((ri,fvg['bot']),xlen-ri,fvg['top']-fvg['bot'],color=col,zorder=1))
    for lvl in liq['BSL']:
        ax.axhline(lvl,color='#64b5f6',linewidth=0.8,linestyle=':',alpha=0.8)
        ax.text(xlen-1,lvl,' BSL',color='#64b5f6',fontsize=6,va='bottom',ha='right')
    for lvl in liq['SSL']:
        ax.axhline(lvl,color='#f48fb1',linewidth=0.8,linestyle=':',alpha=0.8)
        ax.text(xlen-1,lvl,' SSL',color='#f48fb1',fontsize=6,va='top',ha='right')
    ax.axhline(liq['price'],color='white',linewidth=1)
    ax.set_title(symbol+' - '+label+' | ICT',color='white',fontsize=10,pad=8)
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_color('#30363d'); ax.spines['left'].set_color('#30363d')
    ax.tick_params(colors='#8b949e',labelsize=7)
    items=[mpatches.Patch(color='#26a69a',label='Bullish OB'),mpatches.Patch(color='#ef5350',label='Bearish OB'),mpatches.Patch(color='#ffeb3b',label='FVG'),mpatches.Patch(color='#64b5f6',label='BSL'),mpatches.Patch(color='#f48fb1',label='SSL')]
    ax.legend(handles=items,loc='upper left',facecolor='#161b22',edgecolor='#30363d',labelcolor='white',fontsize=6)
    plt.tight_layout()
    buf=io.BytesIO(); plt.savefig(buf,format='png',dpi=130,facecolor=fig.get_facecolor()); plt.close(fig); buf.seek(0)
    return buf

def ai_analyze(symbol, obs, fvgs, liq, label, d_obs=None, d_fvgs=None, d_liq=None, h_obs=None, h_fvgs=None, h_liq=None, m_obs=None, m_fvgs=None, m_liq=None, mtf=False):
    if mtf:
        p = 'ICT expert. Analyze '+symbol+' top-down. Reply Arabic.\nDaily price:'+str((d_liq or {}).get('price',0))+' OB:'+str([x['type']+' '+str(x['bot'])+'-'+str(x['top']) for x in (d_obs or [])])+' FVG:'+str([x['type']+' '+str(x['bot'])+'-'+str(x['top']) for x in (d_fvgs or [])])+' BSL:'+str((d_liq or {}).get('BSL',[]))+' SSL:'+str((d_liq or {}).get('SSL',[]))+'\nHourly OB:'+str([x['type']+' '+str(x['bot'])+'-'+str(x['top']) for x in (h_obs or [])])+' BSL:'+str((h_liq or {}).get('BSL',[]))+' SSL:'+str((h_liq or {}).get('SSL',[]))+'\n5Min OB:'+str([x['type']+' '+str(x['bot'])+'-'+str(x['top']) for x in (m_obs or [])])+' BSL:'+str((m_liq or {}).get('BSL',[]))+' SSL:'+str((m_liq or {}).get('SSL',[]))+'\nFormat:\n📅 الاتجاه اليومي:\n⏰ تحليل الساعة:\n⚡ اشارة 5 دقائق:\n🎯 الاشارة: [شراء/بيع/انتظار]\n✅ الدخول: $\n🛑 وقف الخسارة: $\n🎁 الهدف 1: $\n🎁 الهدف 2: $\n📊 R:R: :1\n💡 ملاحظة ICT:\n⚠️ تحذير:'
    else:
        p = 'ICT expert. Analyze '+symbol+' on '+label+'. Reply Arabic.\nPrice:'+str(liq['price'])+' OB:'+str([x['type']+' '+str(x['bot'])+'-'+str(x['top']) for x in obs])+' FVG:'+str([x['type']+' '+str(x['bot'])+'-'+str(x['top']) for x in fvgs])+' BSL:'+str(liq['BSL'])+' SSL:'+str(liq['SSL'])+'\nFormat:\n📍 الوضع:\n🎯 الاشارة: [شراء/بيع/انتظار]\n📌 السبب:\n✅ الدخول: $\n🛑 وقف الخسارة: $\n🎁 الهدف 1: $\n🎁 الهدف 2: $\n📊 R:R: :1\n⚠️ تنبيه:'
    msg = client.messages.create(model='claude-sonnet-4-5',max_tokens=800,messages=[{'role':'user','content':p}])
    return msg.content[0].text.strip()

async def cmd_start(update, context):
    await update.message.reply_text('👋 ICT Bot\n\nارسل رمز السهم مثل: NVDA\nثم اختار الفريم 🚀')

async def handle_symbol(update, context):
    symbol = update.message.text.strip().upper()
    if len(symbol)>10 or ' ' in symbol:
        await update.message.reply_text('ارسل رمز فقط مثل: NVDA'); return
    kb = [
        [InlineKeyboardButton('📅 يومي',callback_data='tf_'+symbol+'_1d'),InlineKeyboardButton('⏰ ساعة',callback_data='tf_'+symbol+'_1h')],
        [InlineKeyboardButton('🕐 15 دقيقة',callback_data='tf_'+symbol+'_15m'),InlineKeyboardButton('⚡ 5 دقائق',callback_data='tf_'+symbol+'_5m')],
        [InlineKeyboardButton('🔥 تحليل كامل يومي+ساعة+5د',callback_data='tf_'+symbol+'_mtf')],
    ]
    await update.message.reply_text('📊 '+symbol+' - اختار الفريم:',reply_markup=InlineKeyboardMarkup(kb))

async def handle_tf(update, context):
    q = update.callback_query
    await q.answer()
    parts = q.data.split('_')
    symbol = parts[1]; tf = parts[2]
    chat_id = q.message.chat_id
    await q.edit_message_text('⏳ جاري تحليل '+symbol+'...')
    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    if tf == 'mtf':
        daily=get_df(symbol,'1d'); h1=get_df(symbol,'1h'); m5=get_df(symbol,'5m')
        if daily is None or h1 is None:
            await q.edit_message_text('❌ تعذر جلب '+symbol); return
        d_obs=get_obs(daily); d_fvgs=get_fvg(daily); d_liq=get_liq(daily)
        h_obs=get_obs(h1); h_fvgs=get_fvg(h1); h_liq=get_liq(h1)
        m_obs=get_obs(m5) if m5 is not None else []; m_fvgs=get_fvg(m5) if m5 is not None else []; m_liq=get_liq(m5) if m5 is not None else {'BSL':[],'SSL':[],'price':0}
        analysis = ai_analyze(symbol,[],[],'','' ,d_obs,d_fvgs,d_liq,h_obs,h_fvgs,h_liq,m_obs,m_fvgs,m_liq,mtf=True)
        caption = '━━━━━━━━━━━━━━━━━━━━━\n🔥 تحليل كامل - '+symbol+'\n📅+⏰+⚡ | '+now+'\n━━━━━━━━━━━━━━━━━━━━━\n\n'+analysis+'\n\n⚠️ للاغراض التعليمية'
        chart = draw_chart(daily,d_obs,d_fvgs,d_liq,symbol,'Daily')
        await q.delete_message()
        if chart:
            await context.bot.send_photo(chat_id=chat_id,photo=chart,caption=caption[:1024])
            if len(caption)>1024: await context.bot.send_message(chat_id=chat_id,text=caption[1024:])
        else: await context.bot.send_message(chat_id=chat_id,text=caption)
        return

    cfg=TF.get(tf,TF['1h']); df=get_df(symbol,tf)
    if df is None:
        await q.edit_message_text('❌ تعذر جلب '+symbol); return
    obs=get_obs(df); fvgs=get_fvg(df); liq=get_liq(df)
    analysis = ai_analyze(symbol,obs,fvgs,liq,cfg['label'])
    zones=''
    if obs:
        zones+='🔲 OB:\n'
        for ob in obs: zones+='  '+('🟢' if 'Bullish' in ob['type'] else '🔴')+' '+ob['type']+': $'+str(ob['bot'])+'–$'+str(ob['top'])+'\n'
    if fvgs:
        zones+='\n🟡 FVG:\n'
        for f2 in fvgs: zones+='  '+('🟢' if 'Bullish' in f2['type'] else '🔴')+' '+f2['type']+': $'+str(f2['bot'])+'–$'+str(f2['top'])+'\n'
    if liq['BSL'] or liq['SSL']:
        zones+='\n💧 السيولة:\n'
        if liq['BSL']: zones+='  🔼 BSL: '+str(liq['BSL'])+'\n'
        if liq['SSL']: zones+='  🔽 SSL: '+str(liq['SSL'])+'\n'
    caption='━━━━━━━━━━━━━━━━━━━━━\n📈 '+symbol+' - '+cfg['label']+'\n⏰ '+now+'\n━━━━━━━━━━━━━━━━━━━━━\n\n'+zones+'\n'+'─'*21+'\n\n'+analysis+'\n\n⚠️ للاغراض التعليمية'
    chart=draw_chart(df,obs,fvgs,liq,symbol,cfg['label'])
    await q.delete_message()
    if chart:
        await context.bot.send_photo(chat_id=chat_id,photo=chart,caption=caption[:1024])
        if len(caption)>1024: await context.bot.send_message(chat_id=chat_id,text=caption[1024:])
    else: await context.bot.send_message(chat_id=chat_id,text=caption)

def main():
    app=Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start',cmd_start))
    app.add_handler(CallbackQueryHandler(handle_tf,pattern='^tf_'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_symbol))
    print('Bot running...')
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
