"""Staging-only RPC transport with independently injected credentials.

The caller supplies a dedicated reconciler credential and HTTPS endpoint.
Do not use SUPABASE_SERVICE_ROLE_KEY or executor credentials. No deployment.
"""
import json
import ipaddress
from urllib.parse import urlparse
from urllib.request import Request, urlopen

_ALLOWED = frozenset({"record_bot_position_owner",
                      "mark_bot_position_closed", "release_closed_bot_position",
                      "release_resolved_bot_entry_intent"})

class TrustedRpcTransport:
    def __init__(self, endpoint, reconciler_token, *, opener=urlopen):
        parsed = urlparse(endpoint)
        try:
            ip = ipaddress.ip_address(parsed.hostname or "")
        except ValueError:
            ip = None
        if (ip is not None and not ip.is_global):
            raise ValueError("public HTTPS RPC endpoint required")
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.port == 0
                or parsed.path not in ("", "/") or parsed.hostname in ("localhost", "127.0.0.1", "::1")
                or parsed.hostname.endswith(".localhost") or parsed.hostname.endswith(".local")):
            raise ValueError("HTTPS RPC endpoint required")
        if (not isinstance(reconciler_token, str) or not reconciler_token.strip()
                or any(ch.isspace() for ch in reconciler_token)):
            raise ValueError("dedicated reconciler token required")
        self.endpoint = endpoint.rstrip("/")
        self.token = reconciler_token
        self.opener = opener

    def __call__(self, function, params):
        if function not in _ALLOWED or not isinstance(params, dict):
            raise ValueError("RPC not allowed")
        request = Request(
            self.endpoint + "/rest/v1/rpc/" + function,
            data=json.dumps(params).encode("utf-8"),
            headers={"Authorization": "Bearer " + self.token,
                     "Content-Type": "application/json",
                     "Accept": "application/json"},
            method="POST")
        with self.opener(request, timeout=10) as response:
            if getattr(response, "status", None) != 200:
                return False
            body = response.read(256)
        return body.strip() == b"true"
