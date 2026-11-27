"""Public Hyperliquid Testnet Spot USDC reader. No exchange/signing calls."""
import http.client, ssl, json
from decimal import Decimal
from testnet_paper_review.testnet_daily_admission_gate import EXPECTED_ACCOUNT

HOST="api.hyperliquid-testnet.xyz"

class SpotHold(RuntimeError): pass

def fetch_spot(*, connection_factory=None):
    factory=connection_factory or (lambda: http.client.HTTPSConnection(
        HOST,443,timeout=8,context=ssl.create_default_context()))
    conn=factory()
    try:
        body=json.dumps({"type":"spotClearinghouseState","user":EXPECTED_ACCOUNT})
        conn.request("POST","/info",body=body,headers={"Content-Type":"application/json"})
        response=conn.getresponse()
        if response.status!=200:raise SpotHold("HOLD: Testnet spot request failed")
        if int(response.getheader("Content-Length") or 0)>262144:
            raise SpotHold("HOLD: oversize spot response")
        data=response.read(262145)
        if len(data)>262144:raise SpotHold("HOLD: oversize spot response")
        result=json.loads(data)
        if type(result) is not dict or type(result.get("balances")) is not list:
            raise SpotHold("HOLD: invalid spot response")
        return result
    except (OSError,ValueError,http.client.HTTPException) as error:
        raise SpotHold("HOLD: Testnet spot read unsuccessful") from error
    finally:conn.close()

def review_usdc_spot(state):
    if type(state) is not dict or type(state.get("balances")) is not list:
        raise SpotHold("HOLD: unavailable spot balances")
    entries=[x for x in state["balances"] if type(x) is dict and x.get("coin")=="USDC"]
    if len(entries)>1:raise SpotHold("HOLD: ambiguous spot USDC")
    if not entries:return {"total":"0","available":"0","may_trade":False}
    row=entries[0]
    try:
        total,held=Decimal(row["total"]),Decimal(row["hold"])
    except (KeyError,ValueError,TypeError) as error:
        raise SpotHold("HOLD: invalid spot amount") from error
    if any(not x.is_finite() or x<0 for x in (total,held)) or held>total:
        raise SpotHold("HOLD: invalid or held spot USDC")
    return {"total":str(total),"available":str(total-held),"may_trade":False}

def read_account_mode(*, connection_factory=None):
    """Public TESTNET userAbstraction; no keys, trades or transfers."""
    factory=connection_factory or (lambda: http.client.HTTPSConnection(
        HOST,443,timeout=8,context=ssl.create_default_context()))
    conn=factory()
    try:
        body=json.dumps({"type":"userAbstraction","user":EXPECTED_ACCOUNT})
        conn.request("POST","/info",body=body,headers={"Content-Type":"application/json"})
        response=conn.getresponse()
        if response.status!=200:raise SpotHold("HOLD: abstraction HTTP error")
        raw=response.read(257)
        if len(raw)>256:raise SpotHold("HOLD: abstraction oversized")
        mode=json.loads(raw)
        if type(mode) is not str or mode not in (
            "unifiedAccount","disabled","default","portfolioMargin"):
            raise SpotHold("HOLD: unknown Testnet account mode")
        return mode
    except (OSError,ValueError,http.client.HTTPException) as exc:
        raise SpotHold("HOLD: account mode unavailable") from exc
    finally:conn.close()
