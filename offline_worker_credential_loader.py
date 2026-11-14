"""Offline coordinator credential loading with strict fail-closed file checks.

Disposable fixture only. Does not create secrets, authenticate OS peers,
or protect against privileged/same-UID access.
"""
import json
import os
import stat

def load_offline_worker_keys(path):
    try:
        info=os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o600:
            raise RuntimeError("fixture credential file must be regular mode 0600")
        if hasattr(os,"geteuid") and info.st_uid!=os.geteuid():
            raise RuntimeError("fixture credential owner mismatch")
        with open(path,"rb") as file:
            raw=file.read(8193)
        if len(raw)>8192:
            raise RuntimeError("fixture credential file too large")
        parsed=json.loads(raw)
        if type(parsed) is not dict or not parsed:
            raise RuntimeError("invalid credential mapping")
        keys={}
        for principal,hexkey in parsed.items():
            if type(principal) is not str or not principal or type(hexkey) is not str:
                raise RuntimeError("invalid credential entry")
            key=bytes.fromhex(hexkey)
            if len(key)<32:
                raise RuntimeError("fixture key too short")
            keys[principal]=key
        return keys
    except (OSError,ValueError,TypeError,UnicodeError) as exc:
        raise RuntimeError("offline coordinator credentials unavailable") from exc
