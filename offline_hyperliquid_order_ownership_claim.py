"""Offline-only comparison of claimed order ownership against a pinned intent.

A matching claim is not authenticated exchange evidence and never releases
an entry lock. No exchange, database, network, or executor imports.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class OwnershipReview:
    status: str
    reason: str

def inspect_claimed_order_ownership_offline(*, intent, claim):
    def hold(reason):
        return OwnershipReview("hold", reason)
    required = {"account", "coin", "direction", "oid"}
    if type(intent) is not dict or type(claim) is not dict:
        return hold("missing ownership evidence")
    if set(intent) != required or set(claim) != required:
        return hold("missing or unexpected ownership fields")
    for item in (intent, claim):
        if (type(item["account"]) is not str or not item["account"]
                or item["account"].strip() != item["account"]
                or type(item["coin"]) is not str or not item["coin"]
                or not item["coin"].isascii() or not item["coin"].isalnum()
                or item["coin"] != item["coin"].upper()
                or type(item["direction"]) is not str
                or item["direction"] not in ("long", "short")
                or type(item["oid"]) is not int or item["oid"] <= 0):
            return hold("invalid ownership identity")
    if any(claim[key] != intent[key] for key in required):
        return hold("claimed ownership contradicts pinned intent")
    return OwnershipReview(
        "hold", "synthetic identity fields match but account ownership "
                "and exchange provenance are not authenticated")
