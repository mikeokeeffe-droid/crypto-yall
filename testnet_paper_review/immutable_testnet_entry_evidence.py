"""Write-once review evidence for a potential single SOL TESTNET bracket.

The entry journal records a request hash but not the complete TP/SL order
identifiers. This separate *non-secret* record allows an operator to compare
the exact 3-order intent after an unknown ACK or process restart. It never
grants order authority, reads a signer, changes either journal, or sends HTTP.

Write-once by O_EXCL with fsync on file + directory. Existing files are never
overwritten, unlinked or silently regenerated. This is supplementary evidence
only: a durable receipt is NOT proof that the exchange accepted an order.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from testnet_paper_review.offline_client_order_bundle import OfflineClientOrderBundle
from testnet_paper_review.offline_order_guard import TESTNET_ACCOUNT, TESTNET_ENDPOINT

EVIDENCE_DIR="/home/testadmin/crypto-yall-testnet-state"
EVIDENCE_PATH=EVIDENCE_DIR+"/testnet-one-shot-order-evidence.json"
HEX64=re.compile(r"[a-f0-9]{64}\Z")
HEX40=re.compile(r"[a-f0-9]{40}\Z")
CLOID=re.compile(r"0x[a-f0-9]{32}\Z")
REQUEST=re.compile(r"[a-z0-9][a-z0-9-]{7,63}\Z")
MAX_BYTES=16384


class EntryEvidenceHold(RuntimeError):
    pass


def _check_path(path):
    if path != EVIDENCE_PATH:
        raise EntryEvidenceHold("HOLD: unapproved entry evidence path")
    directory=Path(EVIDENCE_DIR)
    folder=os.lstat(directory)
    if (not stat.S_ISDIR(folder.st_mode) or folder.st_uid!=os.getuid()
            or stat.S_IMODE(folder.st_mode)!=0o700):
        raise EntryEvidenceHold("HOLD: unsafe evidence directory")
    return directory


def _canonical_payload(bundle):
    if (type(bundle) is not OfflineClientOrderBundle
            or bundle.permits_submission is not False
            or bundle.account.lower()!=TESTNET_ACCOUNT.lower()
            or bundle.endpoint!=TESTNET_ENDPOINT
            or bundle.grouping!="normalTpsl"
            or type(bundle.code_sha) is not str
            or not HEX40.fullmatch(bundle.code_sha)
            or type(bundle.request_id) is not str
            or not REQUEST.fullmatch(bundle.request_id)
            or type(bundle.plan_hash) is not str
            or not HEX64.fullmatch(bundle.plan_hash)
            or type(bundle.orders) is not tuple
            or len(bundle.orders)!=3):
        raise EntryEvidenceHold("HOLD: unapproved Testnet order evidence")
    entry,take,stop=bundle.orders
    if (any(type(x) is not dict or set(x)!={
            "coin","is_buy","sz","limit_px","order_type","reduce_only","cloid"
        } for x in bundle.orders)
            or any(x["coin"]!="SOL" for x in bundle.orders)
            or [x["reduce_only"] for x in bundle.orders]!=[False,True,True]
            or [x["is_buy"] for x in bundle.orders]!=[True,False,False]
            or entry["order_type"]!={"limit":{"tif":"Ioc"}}
            or take["order_type"].get("trigger",{}).get("tpsl")!="tp"
            or stop["order_type"].get("trigger",{}).get("tpsl")!="sl"
            or any(type(o["cloid"]) is not str or not CLOID.fullmatch(o["cloid"])
                   for o in bundle.orders)
            or len({o["cloid"] for o in bundle.orders})!=3):
        raise EntryEvidenceHold("HOLD: unexpected three-order Testnet SOL bracket")
    # Keep only safe, public trading intent values; no wallet/key values.
    data={
        "schema_version":1,
        "account":bundle.account.lower(),"endpoint":TESTNET_ENDPOINT,
        "request_id":bundle.request_id,"plan_hash":bundle.plan_hash,
        "code_sha":bundle.code_sha,"grouping":"normalTpsl",
        "orders":list(bundle.orders),
        "status":"REVIEW_ONLY_NOT_EXCHANGE_ACK",
        "may_send":False,
    }
    raw=json.dumps(data,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")
    if len(raw)>MAX_BYTES:
        raise EntryEvidenceHold("HOLD: oversized order evidence")
    return raw


def persist_review_evidence(*, bundle, path=EVIDENCE_PATH):
    """Exclusive file creation; caller must never treat output as trade approval."""
    directory=_check_path(path)
    raw=_canonical_payload(bundle)
    fd=None
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|
                   getattr(os,"O_NOFOLLOW",0),0o600)
        os.write(fd,raw)
        os.fsync(fd)
        os.close(fd)
        fd=None
        folder_fd=os.open(directory,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
        try:
            os.fsync(folder_fd)
        finally:
            os.close(folder_fd)
    except OSError as exc:
        raise EntryEvidenceHold("HOLD: evidence missing/uncertain; never overwrite or retry") from exc
    finally:
        if fd is not None:os.close(fd)
    return {
        "status":"ENTRY_EVIDENCE_PERSISTED_REVIEW_ONLY_HOLD",
        "sha256":hashlib.sha256(raw).hexdigest(),
        "may_send":False
    }


def read_review_evidence(*,path=EVIDENCE_PATH):
    """Safely reopen a prior write-once record, without trusting it as an ACK."""
    _check_path(path)
    flags=os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)
    try:
        fd=os.open(path,flags)
        with os.fdopen(fd,"rb") as stream:
            meta=os.fstat(stream.fileno())
            if (not stat.S_ISREG(meta.st_mode)
                    or meta.st_uid!=os.getuid()
                    or stat.S_IMODE(meta.st_mode)!=0o600
                    or meta.st_size>MAX_BYTES):
                raise EntryEvidenceHold("HOLD: unsafe evidence record")
            raw=stream.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:
            raise EntryEvidenceHold("HOLD: oversized evidence record")
        doc=json.loads(raw)
        if (type(doc) is not dict
                or doc.get("schema_version")!=1
                or doc.get("account")!=TESTNET_ACCOUNT.lower()
                or doc.get("endpoint")!=TESTNET_ENDPOINT
                or doc.get("may_send") is not False
                or doc.get("status")!="REVIEW_ONLY_NOT_EXCHANGE_ACK"):
            raise EntryEvidenceHold("HOLD: unrecognised stored evidence")
        return {
            "status":"STORED_ENTRY_PLAN_ONLY_NOT_EXCHANGE_PROOF",
            "plan_hash":doc["plan_hash"],
            "request_id":doc["request_id"],
            "cloids":[o["cloid"] for o in doc["orders"]],
            "sha256":hashlib.sha256(raw).hexdigest(),
            "may_send":False
        }
    except (OSError,ValueError,TypeError,KeyError,AttributeError) as exc:
        raise EntryEvidenceHold("HOLD: cannot inspect immutable evidence") from exc
