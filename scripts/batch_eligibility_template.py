#!/usr/bin/env python3
"""
Batch eligibility check template — check multiple OpenSea drops for a wallet.

Copy this script, edit the `collections` list and wallet info, and run:
    python batch_eligibility_template.py

Requirements:
    - opensea_eligibility.py in the same directory or on sys.path
    - A wallet address + private key (for SIWE login)

Output: JSON array of results with per-stage eligibility.
"""
import json, sys, os, time
from datetime import datetime, timezone, timedelta

# --- CONFIG ---
WIB = timezone(timedelta(hours=7))

# Add opensea_eligibility.py to path (adjust as needed)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from opensea_eligibility import siwe_login, check_eligibility_graphql

# --- WALLET ---
# Replace with your wallet address and private key
ADDRESS = "0xYOUR_ADDRESS"
PRIVATE_KEY = "0xYOUR_PRIVATE_KEY"

# --- COLLECTIONS TO CHECK ---
# (slug, display_name, start_timestamp_unix, price_description, total_supply)
collections = [
    # Example entries — replace with your list
    ("neokitsune", "Neokitsune", 1783083600, "GTD/FCFS 0.002 | Public 0.003", 777),
    # ("motorheads-5555", "MotorHeads", 1783080000, "0.0067 ETH", 5555),
]

# --- RUN ---

print(f"Wallet: {ADDRESS}", file=sys.stderr)

# Login ONCE — reuse session for all collections
client = siwe_login(ADDRESS, PRIVATE_KEY)

results = []
for slug, name, ts, price, supply in collections:
    dt = datetime.fromtimestamp(ts, tz=WIB)
    now_ts = time.time()
    status = "LIVE" if ts <= now_ts else f"starts {dt.strftime('%H:%M')} WIB"

    try:
        data = check_eligibility_graphql(client, ADDRESS, slug)
        if "error" in data:
            results.append({
                "name": name, "slug": slug, "time": dt.strftime("%d Jul %H:%M WIB"),
                "status": status, "price": price, "supply": supply, "error": data["error"]
            })
            continue

        drop = data.get("dropBySlug", {})
        stages = []
        for s in drop.get("stages", []):
            price_info = s.get("eligiblePrice", {})
            token = price_info.get("token", {}) if price_info else {}
            stages.append({
                "type": s.get("stageType", "?"),
                "index": s.get("stageIndex", 0),
                "eligible": s.get("isEligible", False),
                "max": s.get("maxTotalMintableByWallet", 0),
                "price_eth": token.get("unit", 0) if token else 0,
                "price_usd": price_info.get("usd", 0) if price_info else 0
            })
        results.append({
            "name": name, "slug": slug, "time": dt.strftime("%d Jul %H:%M WIB"),
            "status": status, "price": price, "supply": supply, "stages": stages
        })
    except Exception as e:
        results.append({
            "name": name, "slug": slug, "time": dt.strftime("%d Jul %H:%M WIB"),
            "status": status, "price": price, "supply": supply, "error": str(e)
        })
    time.sleep(1)  # Rate limit courtesy

print(json.dumps(results, indent=2))
