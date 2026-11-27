"""Read public TESTNET extraAgents and userRole (no keys, trading or Mainnet).

The public list may omit unnamed agents. Presence of an agent does not
establish that it is safe for this bot or exclusively owned by the bot.
"""
import http.client
import json
import re
import ssl
import time
from testnet_paper_review.testnet_daily_admission_gate import EXPECTED_ACCOUNT

HOST="api.hyperliquid-testnet.xyz"
ADDR=re.compile(r"0x[0-9a-fA-F]{40}\Z")

class AgentHold(RuntimeError):
    pass

def read_public_agents(kind, address, *, connection_factory=None):
    if kind not in ("extraAgents","userRole") or type(address) is not str or not ADDR.fullmatch(address):
        raise AgentHold("HOLD: unapproved public info request")
    if kind=="extraAgents" and address.lower()!=EXPECTED_ACCOUNT.lower():
        raise AgentHold("HOLD: only pinned TESTNET owner agents")
    factory=connection_factory or (lambda: http.client.HTTPSConnection(
        HOST,443,timeout=8,context=ssl.create_default_context()))
    conn=factory()
    try:
        body=json.dumps({"type":kind,"user":address},separators=(",",":"))
        conn.request("POST","/info",body=body,headers={
            "Content-Type":"application/json","Accept":"application/json"})
        response=conn.getresponse()
        if response.status!=200:raise AgentHold("HOLD: public TESTNET query rejected")
        length=response.getheader("Content-Length")
        if length is not None and (
            not length.isascii() or not length.isdecimal() or int(length)>32768):
            raise AgentHold("HOLD: invalid public reply length")
        raw=response.read(32769)
        if len(raw)>32768:raise AgentHold("HOLD: oversized public reply")
        return json.loads(raw.decode("utf-8"))
    except (OSError,ValueError,UnicodeDecodeError,http.client.HTTPException) as e:
        raise AgentHold("HOLD: public TESTNET agent query failed") from e
    finally:conn.close()

def review_public_agents(*, fetcher=read_public_agents, clock=None):
    if clock is None:clock=lambda:int(time.time()*1000)
    begin=clock()
    agents=fetcher("extraAgents",EXPECTED_ACCOUNT)
    if type(agents) is not list or len(agents)>10:
        raise AgentHold("HOLD: invalid approved agent list")
    seen=set()
    result=[]
    for row in agents:
        if type(row) is not dict:raise AgentHold("HOLD: malformed agent")
        address=row.get("address")
        until=row.get("validUntil")
        if (type(address) is not str or not ADDR.fullmatch(address)
                or address.lower() in seen
                or address.lower()==EXPECTED_ACCOUNT.lower()
                or type(until) is not int or until<0):
            raise AgentHold("HOLD: invalid or duplicate public agent record")
        seen.add(address.lower())
        role=fetcher("userRole",address)
        if type(role) is not dict:raise AgentHold("HOLD: unknown public signer role")
        relation=role.get("data")
        matches=(role.get("role")=="agent" and type(relation) is dict
                 and type(relation.get("user")) is str
                 and relation["user"].lower()==EXPECTED_ACCOUNT.lower())
        result.append({"address":address,"valid_until_ms":until,
                       "role_matches_owner":matches})
    end=clock()
    if type(begin) is not int or type(end) is not int or not 0<=end-begin<=15000:
        raise AgentHold("HOLD: stale agent evidence")
    return {"agents":result,
            "active_named_owner_agents":sum(
                1 for x in result if x["role_matches_owner"]
                and x["valid_until_ms"]>end),
            "trading_authorized":False,
            "status":"PUBLIC_TESTNET_AGENT_REVIEW_HOLD"}
