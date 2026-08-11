import os
from hyperliquid.info import Info
from hyperliquid.utils import constants

is_testnet = os.environ.get("HL_TESTNET", "true").lower() == "true"
base_url = constants.TESTNET_API_URL if is_testnet else constants.MAINNET_API_URL

info = Info(base_url, skip_ws=True)
mids = info.all_mids()

print("Environment:", "TESTNET" if is_testnet else "MAINNET")
print("Available markets:")
for coin in sorted(mids.keys()):
    print(coin)

for target in ["LINK", "XRP"]:
    print(f"{target} available:", target in mids)
