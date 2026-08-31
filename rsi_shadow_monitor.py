"""Read-only RSI 70/30 reversal monitor for currently owned Intraday positions."""
import datetime as dt
import json
import os
import requests
from hyperliquid.info import Info
from hyperliquid.utils import constants
from intraday_data_loader import fetch_all_intraday, HL_SYMBOL_MAP
from rsi_shadow_exit import rsi_reversal_shadow

STATE_FILENAME = "intraday_state.json"
TICKERS = ["BTC-USD","ETH-USD","SOL-USD","AVAX-USD","LINK-USD","SUI20947-USD","XRP-USD","ONDO-USD"]


def load_state():
    token, gist = os.environ.get("GIST_TOKEN"), os.environ.get("INTRADAY_GIST_ID")
    if not token or not gist: raise RuntimeError("Gist credentials missing")
    r=requests.get(f"https://api.github.com/gists/{gist}",headers={"Authorization":f"token {token}"},timeout=15); r.raise_for_status()
    return json.loads(r.json()["files"][STATE_FILENAME]["content"])


def save_state(state):
    token, gist = os.environ.get("GIST_TOKEN"), os.environ.get("INTRADAY_GIST_ID")
    r=requests.patch(f"https://api.github.com/gists/{gist}",headers={"Authorization":f"token {token}"},json={"files":{STATE_FILENAME:{"content":json.dumps(state,indent=2)}}},timeout=15); r.raise_for_status()


def send(lines):
    token, ids = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not ids: return
    text="\n".join(lines)
    for cid in [x.strip() for x in ids.split(",") if x.strip()]:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":cid,"text":text},timeout=15).raise_for_status()


def main():
    state=load_state(); address=os.environ.get("HL_ACCOUNT_ADDRESS")
    if not address: raise RuntimeError("HL_ACCOUNT_ADDRESS missing")
    base=constants.TESTNET_API_URL if os.environ.get("HL_TESTNET","true").lower()=="true" else constants.MAINNET_API_URL
    info=Info(base,skip_ws=True); owned=set(state.get("owned_coins",[]) or [])
    positions={}
    for item in info.user_state(address).get("assetPositions",[]):
        p=item.get("position",{}); size=float(p.get("szi",0) or 0); coin=str(p.get("coin"))
        if size and coin in owned: positions[coin]={"size":size,"entry_px":float(p.get("entryPx",0) or 0),"upnl":float(p.get("unrealizedPnl",0) or 0)}
    data=fetch_all_intraday(TICKERS,interval="1h",lookback_hours=1000)
    by_coin={c:t for t,c in HL_SYMBOL_MAP.items() if t in TICKERS}
    armed=dict(state.get("shadow_rsi_armed",{}) or {}); history=list(state.get("shadow_rsi_history",[]) or [])
    last=dict(state.get("shadow_rsi_last_signature",{}) or {}); new={}; lines=["🧪 Crypto Y'all RSI Shadow","Observation only — no order placed",""]
    now=dt.datetime.now(dt.UTC)
    for coin,p in positions.items():
        ticker=by_coin.get(coin); df=data.get(ticker) if ticker else None
        if df is None or df.empty or len(df)<20: continue
        side="long" if p["size"]>0 else "short"
        decision,is_armed,rsi=rsi_reversal_shadow(df,side,bool(armed.get(coin,False)))
        armed[coin]=is_armed; sig=f"{side}|{decision}|{is_armed}"
        new[coin]=sig
        snap={"timestamp":now.isoformat(),"ticker":ticker,"coin":coin,"side":side,"entry_px":p["entry_px"],"unrealized_pnl":p["upnl"],"rsi14":rsi,"rsi_armed":is_armed,"rsi_reversal":decision}
        history.append(snap)
        print(f"RSI shadow {coin} {side.upper()} RSI14={rsi:.2f} armed={is_armed} decision={decision}")
        if last.get(coin)!=sig:
            lines += [f"{coin} {side.upper()} | RSI14 {rsi:.1f}",f"  RSI70/30 reversal: {decision} | {'ARMED' if is_armed else 'waiting'}",""]
    armed={k:v for k,v in armed.items() if k in positions}; state["shadow_rsi_armed"]=armed; state["shadow_rsi_history"]=history[-1000:]; state["shadow_rsi_last_signature"]=new
    save_state(state)
    if len(lines)>3:
        lines.append(now.strftime("%Y-%m-%d %H:%M UTC")); send(lines)

if __name__=="__main__": main()
