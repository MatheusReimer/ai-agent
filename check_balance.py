import requests
from config import PRIVATE_KEY, POLYMARKET_PROXY_ADDRESS
from eth_account import Account
from eth_utils import to_checksum_address

# USDC contracts on Polygon
USDC_NATIVE  = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"  # native USDC
USDC_BRIDGED = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e
POLYGON_RPC  = "https://polygon-rpc.com"

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
except ImportError:
    ClobClient = None

def _erc20_balance(token: str, address: str) -> float:
    selector = "0x70a08231"
    padded = address[2:].lower().zfill(64)
    payload = {
        "jsonrpc": "2.0", "method": "eth_call",
        "params": [{"to": token, "data": selector + padded}, "latest"],
        "id": 1,
    }
    result = requests.post(POLYGON_RPC, json=payload, timeout=10).json().get("result", "0x0")
    return int(result, 16) / 1e6

def check_usdc_balance() -> float:
    if not PRIVATE_KEY:
        print("❌ Error: POLYMARKET_KEY not found in .env")
        return 0.0

    try:
        acct = Account.from_key(PRIVATE_KEY)
        print(f"🔑 Signer Address (Key): {acct.address}")
    except Exception as e:
        print(f"❌ Could not derive address from key: {e}")
        return 0.0

    check_addr = to_checksum_address(POLYMARKET_PROXY_ADDRESS) if POLYMARKET_PROXY_ADDRESS else acct.address
    label = "Proxy" if POLYMARKET_PROXY_ADDRESS else "Signer"
    print(f"🏦 {label} Address: {check_addr}")

    # 1. Check on-chain wallet balance (both USDC variants)
    try:
        native  = _erc20_balance(USDC_NATIVE,  check_addr)
        bridged = _erc20_balance(USDC_BRIDGED, check_addr)
        wallet_balance = native + bridged
        print(f"   On-chain wallet — native USDC: ${native:.2f} | USDC.e: ${bridged:.2f}")
        if wallet_balance > 0:
            print(f"💰 USDC Balance (wallet): ${wallet_balance:.2f}")
            return wallet_balance
    except Exception as e:
        print(f"⚠️ On-chain query failed: {e}")

    # 2. Fallback: query Polymarket CLOB API (funds already deposited for trading)
    if not ClobClient:
        print("❌ py_clob_client not installed — cannot check CLOB balance")
        return 0.0

    try:
        print("🔌 Checking Polymarket CLOB balance (funds inside trading system)...")
        proxy_addr = to_checksum_address(POLYMARKET_PROXY_ADDRESS) if POLYMARKET_PROXY_ADDRESS else None
        client = ClobClient(
            host="https://clob.polymarket.com",
            key=PRIVATE_KEY,
            chain_id=137,
            funder=proxy_addr,
            signature_type=1 if proxy_addr else 0,  # 1 = Magic.Link/email proxy
        )
        client.set_api_creds(client.create_or_derive_api_creds())
        resp = client.get_balance_allowance(
            params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        )
        balance = float(resp.get("balance", 0.0)) / 1e6
        print(f"💰 CLOB Balance: ${balance:.2f}")
        return balance
    except Exception as e:
        print(f"❌ CLOB balance check failed: {e}")
        return 0.0

if __name__ == "__main__":
    check_usdc_balance()
