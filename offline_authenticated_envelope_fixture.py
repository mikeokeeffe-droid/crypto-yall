"""Offline-only HMAC request-envelope prototype; NOT deployment authentication.

Tests message integrity, identity binding and replay resistance. Shared test
secrets are not production credentials. No network, SDK or order submission.
A real coordinator must protect its keys, authenticate transport peers and
persist replay state across restarts.
"""
import hashlib
import hmac
import json

def _payload(principal, operation, intent, nonce):
    return json.dumps(dict(principal=principal, operation=operation,
                           intent=intent, nonce=nonce),
                      sort_keys=True, separators=(",",":"), allow_nan=False).encode()

def sign_fixture_request(secret, principal, operation, intent, nonce):
    if not isinstance(secret,bytes) or len(secret)<32:
        raise ValueError("fixture key must be at least 32 bytes")
    payload=_payload(principal,operation,intent,nonce)
    return dict(principal=principal,operation=operation,intent=intent,nonce=nonce,
                mac=hmac.new(secret,payload,hashlib.sha256).hexdigest())

class OfflineAuthenticatedEnvelopeVerifier:
    def __init__(self,keys):
        self._keys=dict(keys)
        self._seen=set()

    def verify(self,envelope):
        if type(envelope) is not dict or set(envelope)!={"principal","operation","intent","nonce","mac"}:
            return None
        principal=envelope["principal"]
        nonce=envelope["nonce"]
        mac=envelope["mac"]
        if (type(principal) is not str or type(nonce) is not str
                or not nonce or len(nonce)>128 or type(mac) is not str):
            return None
        key=self._keys.get(principal)
        if type(key) is not bytes or len(key)<32:
            return None
        try:
            payload=_payload(principal,envelope["operation"],envelope["intent"],nonce)
            expected=hmac.new(key,payload,hashlib.sha256).hexdigest()
        except (TypeError,ValueError,OverflowError):
            return None
        if not hmac.compare_digest(expected,mac):
            return None
        replay_key=(principal,nonce)
        if replay_key in self._seen:
            return None
        self._seen.add(replay_key)
        return (principal,envelope["operation"],envelope["intent"])
