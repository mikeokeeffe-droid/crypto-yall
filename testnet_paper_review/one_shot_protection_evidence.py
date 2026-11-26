"""Write-once review-only SOL Testnet bracket/ack evidence, no exchange access.

Prepared order intent survives restart, and unknown ACK always remains UNKNOWN.
The stored ACK is only transport evidence, not proof exits are live. No CLI,
private key, network requests, journal mutations, or order submission.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import stat

from testnet_paper_review.offline_daily_bracket_plan import OfflineBracketPlan
from testnet_paper_review.offline_client_order_bundle import OfflineClientOrderBundle
from testnet_paper_review.offline_order_guard import TESTNET_ACCOUNT, TESTNET_ENDPOINT

ROOT="/home/testadmin/crypto-yall-testnet-state"
PREPARED="testnet-bracket-prepared.json"
ACK="testnet-bracket-ack.json"
MAX_BYTES=32768
SCHEMA=1


class EvidenceHold(RuntimeError):
    pass


def _bytes(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),
                      allow_nan=False).encode("ascii")


def _hash(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def _validate_pair(plan,bundle):
    if (type(plan) is not OfflineBracketPlan
            or type(bundle) is not OfflineClientOrderBundle
            or plan.permits_submission or bundle.permits_submission
            or plan.account.lower()!=TESTNET_ACCOUNT.lower()
            or bundle.account.lower()!=TESTNET_ACCOUNT.lower()
            or bundle.endpoint!=TESTNET_ENDPOINT
            or plan.symbol!="SOL" or plan.direction!="long"
            or plan.grouping!="normalTpsl"
            or bundle.grouping!=plan.grouping
            or type(plan.orders) is not tuple
            or type(bundle.orders) is not tuple
            or len(plan.orders)!=3 or len(bundle.orders)!=3):
        raise EvidenceHold("HOLD: unsupported original SOL Daily bracket")
    stripped=[]
    for src in bundle.orders:
        if type(src) is not dict or set(src)!={
            "coin","is_buy","sz","limit_px","order_type","reduce_only","cloid"
        }:
            raise EvidenceHold("HOLD: malformed SDK bracket")
        stripped.append({k:v for k,v in src.items() if k!="cloid"})
    if tuple(stripped)!=plan.orders or plan.orders[0]["is_buy"] is not True:
        raise EvidenceHold("HOLD: protected order details mismatch")


@dataclass(frozen=True)
class EvidenceReceipt:
    plan: OfflineBracketPlan
    bundle: OfflineClientOrderBundle
    response: dict|None
    ack_present: bool
    may_trade: bool=False


class WriteOnceProtectionEvidence:
    def __init__(self,root=None):
        target=ROOT if root is None else root
        if target!=ROOT:
            raise EvidenceHold("HOLD: unknown evidence directory")
        self.root=Path(target)
        try:
            s=os.lstat(self.root)
        except OSError as exc:
            raise EvidenceHold("HOLD: missing evidence folder") from exc
        if (not stat.S_ISDIR(s.st_mode) or s.st_uid!=os.getuid()
                or stat.S_IMODE(s.st_mode)!=0o700):
            raise EvidenceHold("HOLD: evidence directory not private")

    def _path(self,name):
        if name not in (PREPARED,ACK):
            raise EvidenceHold("HOLD: invalid evidence file name")
        return self.root / name

    def _write_once(self,name,value):
        raw=_bytes(value)
        if not 0<len(raw)<=MAX_BYTES:
            raise EvidenceHold("HOLD: invalid evidence length")
        path=self._path(name)
        try:
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|
                       getattr(os,"O_NOFOLLOW",0),0o600)
        except OSError as exc:
            raise EvidenceHold("HOLD: evidence already present or inaccessible") from exc
        try:
            with os.fdopen(fd,"wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            dirfd=os.open(self.root,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        except OSError as exc:
            # NEVER remove or retry a potentially partially written file.
            raise EvidenceHold("HOLD: uncertain evidence write; no retry") from exc

    def _read(self,name):
        path=self._path(name)
        try:
            fd=os.open(path,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0))
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise EvidenceHold("HOLD: evidence unavailable") from exc
        try:
            with os.fdopen(fd,"rb") as stream:
                s=os.fstat(stream.fileno())
                if (not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid()
                        or stat.S_IMODE(s.st_mode)!=0o600
                        or not 1<=s.st_size<=MAX_BYTES):
                    raise EvidenceHold("HOLD: unsafe evidence file")
                raw=stream.read(MAX_BYTES+1)
            if len(raw)>MAX_BYTES:
                raise EvidenceHold("HOLD: oversized evidence")
            doc=json.loads(raw)
            if (type(doc) is not dict or doc.get("schema")!=SCHEMA
                    or type(doc.get("payload")) is not dict
                    or doc.get("sha256")!=_hash(doc["payload"])):
                raise EvidenceHold("HOLD: tampered evidence file")
            return doc["payload"]
        except (ValueError,TypeError,UnicodeError) as exc:
            raise EvidenceHold("HOLD: malformed evidence") from exc

    def prepare_before_order(self,*,plan,bundle):
        _validate_pair(plan,bundle)
        if self._path(PREPARED).exists() or self._path(ACK).exists():
            raise EvidenceHold("HOLD: one-shot evidence already consumed")
        value={"plan":asdict(plan),"bundle":asdict(bundle)}
        self._write_once(PREPARED,{
            "schema":SCHEMA,"payload":value,"sha256":_hash(value)
        })
        return "PREPARED_DURABLE_BEFORE_ORDER_NO_RETRY"

    def read_prepared(self):
        try:
            value=self._read(PREPARED)
            if type(value) is not dict or set(value)!={"plan","bundle"}:
                raise EvidenceHold("HOLD: unexpected evidence schema")
            p=value["plan"];b=value["bundle"]
            plan=OfflineBracketPlan(**{**p,"orders":tuple(p["orders"])})
            bundle=OfflineClientOrderBundle(**{**b,"orders":tuple(b["orders"])})
            _validate_pair(plan,bundle)
            return plan,bundle
        except (FileNotFoundError,TypeError,KeyError,ValueError,AttributeError) as exc:
            raise EvidenceHold("HOLD: no original prepared bracket evidence") from exc

    def write_exact_ack(self,*,bundle,response):
        plan,original=self.read_prepared()
        if type(bundle) is not OfflineClientOrderBundle \
                or asdict(bundle)!=asdict(original):
            raise EvidenceHold("HOLD: ACK bundle mismatches prepared order")
        from testnet_paper_review.isolated_testnet_sender import acknowledge_exact_protected_order
        if not acknowledge_exact_protected_order(response=response,bundle=bundle):
            raise EvidenceHold("HOLD: unknown, partial or rejected bracket ACK")
        if self._path(ACK).exists():
            raise EvidenceHold("HOLD: ACK already written")
        value={
            "prepared_sha256":_hash({"plan":asdict(plan),"bundle":asdict(original)}),
            "response":response
        }
        self._write_once(ACK,{
            "schema":SCHEMA,"payload":value,"sha256":_hash(value)
        })
        return "ACK_DURABLE_NOT_PROOF_OF_LIVE_STOPS"

    def read_restart_state(self):
        plan,bundle=self.read_prepared()
        try:
            stored=self._read(ACK)
        except FileNotFoundError:
            return EvidenceReceipt(
                plan=plan,bundle=bundle,response=None,ack_present=False
            )
        if (type(stored) is not dict
                or set(stored)!={"prepared_sha256","response"}
                or stored["prepared_sha256"]!=_hash({
                    "plan":asdict(plan),"bundle":asdict(bundle)
                })):
            raise EvidenceHold("HOLD: ACK does not match prepared bracket")
        from testnet_paper_review.isolated_testnet_sender import acknowledge_exact_protected_order
        if not acknowledge_exact_protected_order(
                response=stored["response"],bundle=bundle):
            raise EvidenceHold("HOLD: stored ACK is invalid")
        return EvidenceReceipt(
            plan=plan,bundle=bundle,response=stored["response"],
            ack_present=True
        )
