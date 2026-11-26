"""Read-only TESTNET release checkpoint: both journals, SOL 1x, sender locks.

This is NOT a trade launcher, scheduler, approval mechanism or a GO verdict.
The two SDK order senders MUST remain permanently disabled here. Read-only
HTTP only to the pinned Testnet POST /info method activeAssetData. It cannot
submit /exchange, claim a journal, close or open a position, or change leverage.
"""
from dataclasses import dataclass, asdict
import argparse
import http.client
import json
import ssl
import sys

from testnet_paper_review.offline_order_guard import (
    TESTNET_ACCOUNT, TESTNET_ENDPOINT
)
from testnet_paper_review.single_host_live_journal import (
    SingleHostOneShotJournal, PersistentHold
)
from testnet_paper_review.emergency_close_one_shot_journal import (
    EmergencyCloseJournal, EmergencyJournalHold
)
from testnet_paper_review.testnet_one_shot_operator_preview import (
    JOURNAL_PATH, inspect_one_shot_preview, OneShotPreviewHold
)
from testnet_paper_review.isolated_testnet_sender import ACTIVATION_HOLD as ENTRY_HOLD
from testnet_paper_review.isolated_testnet_emergency_sender import (
    ACTIVATION_HOLD as EMERGENCY_HOLD
)

HOST="api.hyperliquid-testnet.xyz"
ENDPOINT="/info"
MAX_BYTES=16384


class ReleaseGateHold(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseCheckpoint:
    account: str
    coin: str
    endpoint: str
    margin_mode: str
    leverage: int
    entry_journal_unspent: bool
    emergency_journal_unspent: bool
    sender_disabled: bool
    emergency_sender_disabled: bool
    private_wallet_verified_by_sdk: bool
    emergency_live_recovery_proven: bool=False
    exact_daily_signal_confirmed: bool=False
    independent_review_signed_off: bool=False
    may_trade: bool=False
    status: str="TESTNET_RELEASE_CHECK_HOLD_NO_ORDER"


def fetch_sol_leverage(*, connection_factory=None):
    """Fixed Testnet-only public method, never loads wallet keys."""
    factory=connection_factory or (lambda: http.client.HTTPSConnection(
        HOST,443,timeout=8,context=ssl.create_default_context()
    ))
    connection=factory()
    payload=json.dumps({
        "type":"activeAssetData","user":TESTNET_ACCOUNT,"coin":"SOL"
    },separators=(",",":")).encode("ascii")
    try:
        connection.request("POST",ENDPOINT,body=payload,headers={
            "Content-Type":"application/json","Accept":"application/json",
            "Connection":"close"
        })
        response=connection.getresponse()
        if response.status!=200:
            raise ReleaseGateHold("HOLD: public Testnet SOL leverage query failed")
        header=response.getheader("Content-Length")
        if header is not None and (not header.isdecimal() or int(header)>MAX_BYTES):
            raise ReleaseGateHold("HOLD: unexpected leverage response length")
        raw=response.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:
            raise ReleaseGateHold("HOLD: oversized leverage response")
        data=json.loads(raw.decode("utf-8"))
        if type(data) is not dict:
            raise ReleaseGateHold("HOLD: malformed Testnet leverage response")
        return data
    except (OSError,ValueError,TypeError,
            http.client.HTTPException,UnicodeError) as exc:
        raise ReleaseGateHold("HOLD: invalid public Testnet leverage evidence") from exc
    finally:
        connection.close()


def review_release_checkpoint(*, preview_reader=inspect_one_shot_preview,
                              leverage_reader=fetch_sol_leverage,
                              entry_journal_factory=SingleHostOneShotJournal,
                              emergency_journal_factory=EmergencyCloseJournal,
                              entry_sender_held=None, emergency_sender_held=None):
    """No mutation. All safety failures are HOLD, including prior claims."""
    try:
        if entry_sender_held is None:
            entry_sender_held=ENTRY_HOLD
        if emergency_sender_held is None:
            emergency_sender_held=EMERGENCY_HOLD
        if entry_sender_held is not True or emergency_sender_held is not True:
            raise ReleaseGateHold("HOLD: a sender has unexpectedly been activated")
        p=preview_reader()
        if (p.may_send is not False
                or p.account.lower()!=TESTNET_ACCOUNT.lower()
                or p.endpoint!=TESTNET_ENDPOINT
                or p.journal_empty is not True
                or p.position_count!=0 or p.open_order_count!=0):
            raise ReleaseGateHold("HOLD: account or trade journal not suitable")
        data=leverage_reader()
        if type(data) is not dict or type(data.get("leverage")) is not dict:
            raise ReleaseGateHold("HOLD: missing public SOL margin setting")
        lev=data["leverage"]
        if lev.get("type")!="isolated" or type(lev.get("value")) is not int \
                or lev["value"]!=1:
            raise ReleaseGateHold("HOLD: SOL must remain isolated at 1x")
        with entry_journal_factory(JOURNAL_PATH) as entry:
            if entry.view()!={"frozen":False,"claim":None}:
                raise ReleaseGateHold("HOLD: original entry journal consumed")
        with emergency_journal_factory() as emergency:
            if emergency.view() is not None:
                raise ReleaseGateHold("HOLD: emergency close journal consumed")
        return ReleaseCheckpoint(
            account=TESTNET_ACCOUNT,coin="SOL",endpoint=TESTNET_ENDPOINT,
            margin_mode="isolated",leverage=1,
            entry_journal_unspent=True,emergency_journal_unspent=True,
            sender_disabled=True,emergency_sender_disabled=True,
            private_wallet_verified_by_sdk=True
        )
    except (OneShotPreviewHold,PersistentHold,EmergencyJournalHold,
            ReleaseGateHold,ValueError,TypeError,KeyError,AttributeError,OSError) as exc:
        raise ReleaseGateHold(
            "HOLD: Testnet trading release prerequisites not all verified"
        ) from exc


def main(argv=None):
    parser=argparse.ArgumentParser(
        description="Read-only SOL Testnet release checkpoint; NEVER submits"
    )
    parser.add_argument("--read-only-check",action="store_true")
    args=parser.parse_args(argv)
    if not args.read_only_check:
        print("HOLD: only explicit read-only check permitted",file=sys.stderr)
        return 2
    try:
        report=review_release_checkpoint()
    except ReleaseGateHold as exc:
        print(str(exc),file=sys.stderr)
        return 2
    print(json.dumps(asdict(report),sort_keys=True))
    print("HOLD: no order submitted; missing-stop live rescue not proven, "
          "Daily signal and independent approval still outstanding")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
