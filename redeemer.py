import json
import requests
from pathlib import Path
from eth_utils import to_checksum_address
from config import PRIVATE_KEY, POLYMARKET_PROXY_ADDRESS

try:
    from web3 import Web3
except ImportError:
    Web3 = None

HISTORY_FILE = "bet_history.json"
POLYGON_RPCS = [
    "https://rpc.ankr.com/polygon",
    "https://polygon-rpc.com",
    "https://polygon-bor-rpc.publicnode.com",
]
CTF_ADDRESS  = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

CTF_ABI = [{
    "inputs": [
        {"name": "collateralToken",    "type": "address"},
        {"name": "parentCollectionId", "type": "bytes32"},
        {"name": "conditionId",        "type": "bytes32"},
        {"name": "indexSets",          "type": "uint256[]"},
    ],
    "name": "redeemPositions",
    "outputs": [],
    "stateMutability": "nonpayable",
    "type": "function",
}]


def _load():
    if not Path(HISTORY_FILE).exists():
        return []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


def _fetch_condition_id(market_id):
    try:
        data = requests.get(
            f"https://gamma-api.polymarket.com/markets/{market_id}", timeout=10
        ).json()
        return data.get("conditionId")
    except Exception:
        return None


def redeem_winnings():
    """Redeem all won + resolved positions on Polymarket via the CTF contract."""
    if Web3 is None:
        print("⚠️  web3 not installed — skipping redemption.")
        return

    if not PRIVATE_KEY:
        print("⚠️  No PRIVATE_KEY — skipping redemption.")
        return

    history = _load()
    redeemable = [
        h for h in history
        if h.get("resolved") and h.get("won") and not h.get("redeemed")
    ]

    if not redeemable:
        print("✅ No winning positions to redeem.")
        return

    print(f"\n--- REDEEMING {len(redeemable)} WINNING POSITION(S) ---")

    w3 = None
    for rpc in POLYGON_RPCS:
        try:
            candidate = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 10}))
            candidate.eth.block_number  # test call
            w3 = candidate
            break
        except Exception:
            continue

    if w3 is None:
        print("⚠️  Cannot connect to any Polygon RPC — skipping redemption.")
        return

    account  = w3.eth.account.from_key(PRIVATE_KEY)
    ctf_addr = to_checksum_address(CTF_ADDRESS)
    usdc_addr = to_checksum_address(USDC_ADDRESS)
    ctf      = w3.eth.contract(address=ctf_addr, abi=CTF_ABI)

    # The address that signs transactions — if this matches POLYMARKET_PROXY_ADDRESS,
    # it means the proxy is an EOA and we can redeem directly.
    sender = account.address
    if POLYMARKET_PROXY_ADDRESS:
        proxy = to_checksum_address(POLYMARKET_PROXY_ADDRESS)
        if proxy.lower() == sender.lower():
            print(f"  Sender matches proxy wallet — direct redemption.")
        else:
            print(f"  ⚠️  Signer ({sender}) ≠ proxy ({proxy}).")
            print(f"      Tokens are held by the proxy contract.")
            print(f"      Attempting direct CTF call (will succeed only if EOA holds tokens).")

    changed = False
    for entry in redeemable:
        question      = entry.get("market_question", "")[:60]
        market_id     = entry.get("market_id")
        outcome_index = entry.get("outcome_index")
        condition_id  = entry.get("condition_id")

        # Fetch conditionId if not stored (older bets)
        if not condition_id and market_id:
            condition_id = _fetch_condition_id(market_id)
            if condition_id:
                entry["condition_id"] = condition_id

        if not condition_id:
            print(f"  ⚠️  No conditionId for '{question}' — skipping.")
            continue

        if outcome_index is None:
            print(f"  ⚠️  No outcome_index for '{question}' — skipping.")
            continue

        try:
            cid_bytes = bytes.fromhex(condition_id.replace("0x", "")).ljust(32, b"\x00")[:32]
        except Exception as e:
            print(f"  ⚠️  Bad conditionId format for '{question}': {e}")
            continue

        index_set = 1 << outcome_index  # outcome 0 → 1, outcome 1 → 2

        try:
            nonce = w3.eth.get_transaction_count(sender)
            gas_price = w3.eth.gas_price
            tx = ctf.functions.redeemPositions(
                usdc_addr,
                b"\x00" * 32,
                cid_bytes,
                [index_set],
            ).build_transaction({
                "from":     sender,
                "nonce":    nonce,
                "gas":      250_000,
                "gasPrice": gas_price,
                "chainId":  137,
            })

            signed   = account.sign_transaction(tx)
            tx_hash  = w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt  = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)

            if receipt.status == 1:
                print(f"  ✅ Redeemed '{question}' (tx: {tx_hash.hex()})")
                entry["redeemed"] = True
                changed = True
            else:
                print(f"  ❌ Tx reverted for '{question}' (tx: {tx_hash.hex()})")
                print(f"     The proxy wallet may need to call redeemPositions instead.")
        except Exception as e:
            print(f"  ❌ Redemption error for '{question}': {e}")

    if changed:
        _save(history)
        print("📝 bet_history.json updated with redeemed positions.")
