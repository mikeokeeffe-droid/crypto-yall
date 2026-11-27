"""Check the *real SDK* TESTNET client can use the separately authorised host key.

READ-ONLY, no account mutation and no order sender. This creates an SDK
Exchange object only to verify its pinned endpoint / wallet / SOL metadata.
It never calls bulk_orders, order, update_leverage, /exchange or starts jobs.
The existing isolated sender ACTIVATION_HOLD is NOT altered.

Run only on the dedicated server with its private, pre-created key file.
The key is never printed, committed, or put in CLI argv/env variables.
"""
import argparse
from dataclasses import asdict, dataclass
import os
import re
import stat
import sys

from testnet_paper_review.offline_order_guard import (
    TESTNET_ACCOUNT, TESTNET_ENDPOINT
)

AGENT_ADDRESS="0xa65e6f1495c95300E7364A1e68D8cfF3d2954FcC"
KEY_PATH="/home/testadmin/crypto-yall-testnet-state/testnet-agent.key"
KEY_DIR="/home/testadmin/crypto-yall-testnet-state"
KEY_RE=re.compile(rb"(?:0x)?[a-fA-F0-9]{64}\Z")
MAX_KEY_BYTES=68


class SignerSDKHold(RuntimeError):
    pass


@dataclass(frozen=True)
class ClientPreflight:
    owner: str
    agent: str
    testnet_endpoint: str
    sol_asset_id: int
    key_owner_and_permissions_verified: bool = True
    status: str = "TESTNET_SDK_CONNECTED_READ_ONLY_HOLD"

    @property
    def may_send(self):
        return False


def load_local_agent(*, key_path=KEY_PATH):
    """Read only an owned, private regular file; never use symlinks."""
    if key_path != KEY_PATH:
        raise SignerSDKHold("HOLD: unexpected signer path")
    parent=os.lstat(KEY_DIR)
    if (not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid != os.getuid()
            or stat.S_IMODE(parent.st_mode) != 0o700):
        raise SignerSDKHold("HOLD: signer directory not private")
    flags=os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd=None
    try:
        fd=os.open(KEY_PATH,flags)
        st=os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode)
                or st.st_uid != os.getuid()
                or stat.S_IMODE(st.st_mode) != 0o600
                or not 64 <= st.st_size <= 66):
            raise SignerSDKHold("HOLD: signing key permissions/size invalid")
        with os.fdopen(fd,"rb") as stream:
            fd=None
            raw=stream.read(MAX_KEY_BYTES)
        if not KEY_RE.fullmatch(raw.strip()):
            raise SignerSDKHold("HOLD: malformed server signing key")
        from eth_account import Account
        wallet=Account.from_key(bytes.fromhex(raw.decode("ascii").strip().removeprefix("0x")))
        if wallet.address.lower() != AGENT_ADDRESS.lower() \
                or wallet.address.lower() == TESTNET_ACCOUNT.lower():
            raise SignerSDKHold("HOLD: unexpected server signing identity")
        return wallet
    except (OSError, ValueError, TypeError) as exc:
        raise SignerSDKHold("HOLD: unable to validate private TESTNET server agent") from exc
    finally:
        if fd is not None:
            os.close(fd)


def inspect_sdk_client(*, wallet, exchange_factory=None):
    """Create a *read-only-used* SDK Testnet Exchange; never submit an action."""
    if wallet.address.lower() != AGENT_ADDRESS.lower():
        raise SignerSDKHold("HOLD: incorrect local agent")
    from hyperliquid.utils.constants import TESTNET_API_URL, MAINNET_API_URL
    if (TESTNET_API_URL != TESTNET_ENDPOINT or TESTNET_ENDPOINT == MAINNET_API_URL
            or not TESTNET_ENDPOINT.endswith("hyperliquid-testnet.xyz")):
        raise SignerSDKHold("HOLD: SDK's Testnet endpoint differs from pinned review")
    if exchange_factory is None:
        from hyperliquid.exchange import Exchange
        exchange_factory=Exchange
    try:
        client=exchange_factory(
            wallet,base_url=TESTNET_ENDPOINT,
            account_address=TESTNET_ACCOUNT,timeout=8
        )
        if (client.base_url != TESTNET_ENDPOINT
                or client.info.base_url != TESTNET_ENDPOINT
                or client.wallet.address.lower() != AGENT_ADDRESS.lower()
                or client.account_address.lower() != TESTNET_ACCOUNT.lower()
                or client.vault_address is not None):
            raise SignerSDKHold("HOLD: SDK host/wallet/account mismatch")
        asset=client.info.name_to_asset("SOL")
        if type(asset) is not int or asset < 0 or asset >= 10000:
            raise SignerSDKHold("HOLD: unknown Testnet SOL perpetual asset")
    except SignerSDKHold:
        raise
    except Exception as exc:
        raise SignerSDKHold("HOLD: SDK Testnet account/market metadata unavailable") from exc
    return ClientPreflight(
        owner=TESTNET_ACCOUNT,agent=AGENT_ADDRESS,
        testnet_endpoint=TESTNET_ENDPOINT,sol_asset_id=asset
    )


def main(argv=None):
    parser=argparse.ArgumentParser(description="TESTNET SDK signer preflight; no trades")
    parser.add_argument("--read-only-check",action="store_true")
    args=parser.parse_args(argv)
    if not args.read_only_check:
        print("HOLD: must specify --read-only-check",file=sys.stderr)
        return 2
    try:
        report=inspect_sdk_client(wallet=load_local_agent())
    except SignerSDKHold as exc:
        print(str(exc),file=sys.stderr)
        return 2
    print("PASS: local server key matches TESTNET-only SDK client")
    print("PASS: Testnet endpoint, owner and SOL asset verified")
    print("HOLD: no order sent; activation, emergency exit and deployment not approved")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
