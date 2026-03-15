import json
import requests as _requests
from pathlib import Path
from eth_utils import to_checksum_address
from config import PRIVATE_KEY, POLYMARKET_PROXY_ADDRESS

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs
    CLOB_AVAILABLE = True
except ImportError:
    CLOB_AVAILABLE = False

HISTORY_FILE = "bet_history.json"
DATA_API     = "https://data-api.polymarket.com"

CTF_ADDRESS  = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDC_E       = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
POLYGON_RPCS = [
    "https://1rpc.io/matic",
    "https://polygon-bor-rpc.publicnode.com",
    "https://rpc-mainnet.maticvigil.com",
]
CTF_ABI = [{
    "name": "redeemPositions",
    "type": "function",
    "inputs": [
        {"name": "collateralToken",      "type": "address"},
        {"name": "parentCollectionId",   "type": "bytes32"},
        {"name": "conditionId",          "type": "bytes32"},
        {"name": "indexSets",            "type": "uint256[]"},
    ],
    "outputs": [],
}]


def _load():
    if not Path(HISTORY_FILE).exists():
        return []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


def _get_redeemable_positions():
    """Fetch winning redeemable positions (curPrice=1) from Polymarket's data API."""
    if not POLYMARKET_PROXY_ADDRESS:
        return []
    try:
        url = f"{DATA_API}/positions"
        params = {"user": POLYMARKET_PROXY_ADDRESS, "limit": 100, "redeemable": "true"}
        resp = _requests.get(url, params=params, timeout=10)
        positions = resp.json()
        return [
            p for p in (positions if isinstance(positions, list) else [])
            if p.get("redeemable")
            and float(p.get("size", 0)) > 0
            and float(p.get("curPrice", 0)) >= 0.99  # only winning positions
        ]
    except Exception as e:
        print(f"  Warning: Could not fetch redeemable positions: {e}")
        return []


def _make_clob_client():
    """Create a fresh ClobClient — reinitializing allows price=0.999."""
    proxy_addr = to_checksum_address(POLYMARKET_PROXY_ADDRESS) if POLYMARKET_PROXY_ADDRESS else None
    client = ClobClient(
        host="https://clob.polymarket.com",
        key=PRIVATE_KEY,
        chain_id=137,
        funder=proxy_addr,
        signature_type=1 if proxy_addr else 0,
    )
    client.set_api_creds(client.create_or_derive_api_creds())
    return client


def _get_web3():
    """Return a connected Web3 instance, trying multiple Polygon RPC endpoints."""
    try:
        from web3 import Web3
    except ImportError:
        return None
    for rpc in POLYGON_RPCS:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 10}))
            w3.eth.block_number  # connectivity check
            return w3
        except Exception:
            continue
    return None


def _redeem_on_chain(positions):
    """
    Redeem resolved winning positions on-chain via the Polymarket CTF contract.
    Requires a small amount of POL on the signer address for gas.
    """
    try:
        from web3 import Web3
        from eth_account import Account
    except ImportError:
        print("  Warning: web3 not installed — skipping on-chain redemption. Run: pip install web3")
        return []

    w3 = _get_web3()
    if not w3:
        print("  Warning: Could not connect to any Polygon RPC — skipping on-chain redemption.")
        return []

    account = Account.from_key(PRIVATE_KEY)
    pol_balance = w3.eth.get_balance(account.address)
    pol_ether   = w3.from_wei(pol_balance, "ether")
    print(f"  POL balance on signer: {pol_ether:.4f} POL")

    if pol_balance < w3.to_wei(0.001, "ether"):
        print(f"  Warning: Not enough POL for gas. Send at least 0.01 POL to {account.address}")
        print("  You can buy POL on Coinbase and send it to that address.")
        return []

    ctf = w3.eth.contract(
        address=w3.to_checksum_address(CTF_ADDRESS),
        abi=CTF_ABI,
    )
    ZERO_BYTES32 = b"\x00" * 32
    redeemed = []

    for pos in positions:
        condition_id  = pos.get("conditionId")
        outcome_index = pos.get("outcomeIndex", 0)
        title         = (pos.get("title") or "")[:60]

        if not condition_id:
            continue

        index_set = 2 ** outcome_index  # index 0 → 1, index 1 → 2

        try:
            nonce     = w3.eth.get_transaction_count(account.address)
            gas_price = w3.eth.gas_price
            tx = ctf.functions.redeemPositions(
                w3.to_checksum_address(USDC_E),
                ZERO_BYTES32,
                w3.to_bytes(hexstr=condition_id),
                [index_set],
            ).build_transaction({
                "from":     account.address,
                "nonce":    nonce,
                "gas":      120_000,
                "gasPrice": gas_price,
                "chainId":  137,
            })
            signed   = account.sign_transaction(tx)
            tx_hash  = w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt  = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)

            if receipt.status == 1:
                print(f"  On-chain redeemed: '{title}' — tx: {tx_hash.hex()[:20]}...")
                redeemed.append(pos)
            else:
                print(f"  On-chain tx reverted for '{title}' — tx: {tx_hash.hex()[:20]}...")

        except Exception as e:
            print(f"  On-chain redemption failed for '{title}': {e}")

    return redeemed


def redeem_winnings():
    """
    Redeem all winning positions using two strategies:
    1. SELL at 0.999 via CLOB API (works when orderbook still exists — no gas needed)
    2. On-chain redeemPositions() via CTF contract (fallback for closed orderbooks — needs POL for gas)
    """
    if not PRIVATE_KEY:
        print("Warning: No PRIVATE_KEY — skipping redemption.")
        return

    positions = _get_redeemable_positions()
    if not positions:
        print("No winning positions to redeem.")
        return

    print(f"\n--- REDEEMING {len(positions)} WINNING POSITION(S) ---")

    history  = _load()
    won_bets = [h for h in history if h.get("won") and not h.get("redeemed")]
    changed  = False

    needs_onchain = []

    # Strategy 1: SELL via CLOB (no gas, works while orderbook is open)
    if CLOB_AVAILABLE:
        for pos in positions:
            token_id = pos.get("asset") or pos.get("token_id")
            size     = float(pos.get("size", 0))
            title    = (pos.get("title") or token_id or "")[:60]

            if not token_id or size <= 0:
                needs_onchain.append(pos)
                continue

            try:
                client = _make_clob_client()
                resp = client.create_and_post_order(OrderArgs(
                    price=0.999,
                    size=round(size, 2),
                    side="SELL",
                    token_id=token_id,
                ))
                order_id = (resp.get("orderID") or resp.get("id")) if isinstance(resp, dict) else str(resp)
                print(f"  Sell order placed: '{title}' ({size:.2f} shares @ 0.999) — ID: {order_id}")

                for entry in won_bets:
                    if not entry.get("redeemed"):
                        entry["redeemed"] = True
                        changed = True
                        break

            except Exception as e:
                err = str(e)
                if "orderbook" in err and "does not exist" in err:
                    needs_onchain.append(pos)  # market resolved, fall back to on-chain
                else:
                    print(f"  Sell failed for '{title}': {e}")
                    needs_onchain.append(pos)
    else:
        needs_onchain = list(positions)

    # Strategy 2: on-chain redeemPositions() for closed orderbooks
    if needs_onchain:
        print(f"  {len(needs_onchain)} position(s) need on-chain redemption (orderbooks closed)...")
        redeemed_onchain = _redeem_on_chain(needs_onchain)
        for _ in redeemed_onchain:
            for entry in won_bets:
                if not entry.get("redeemed"):
                    entry["redeemed"] = True
                    changed = True
                    break

    if changed:
        _save(history)
        print("bet_history.json updated.")
