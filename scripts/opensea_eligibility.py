#!/usr/bin/env python3
"""
opensea_eligibility.py — OpenSea Drop Eligibility Checker (Standalone)

3 methods:
  1. On-chain SeaDrop   — public/FCFS drops, check supply/cap/window (no PK needed)
  2. OpenSea API v2     — stage labels (GTD/FCFS/WL/Public), timing, price
  3. SIWE + GraphQL     — GTD/WL eligibility (needs PK for signing)

Requirements:
  pip install httpx eth-account

Usage:
  # On-chain only (address + NFT contract, no PK needed)
  python opensea_eligibility.py --address 0x... --nft-address 0x... --method onchain

  # API v2 stage labels (needs OpenSea API key)
  python opensea_eligibility.py --slug collection-slug --api-key YOUR_KEY

  # GTD/WL check (needs private key for SIWE signing)
  python opensea_eligibility.py --address 0x... --private-key 0x... --slug collection-slug --method server

  # Full check (onchain + API v2 + SIWE)
  python opensea_eligibility.py --address 0x... --private-key 0x... --nft-address 0x... --slug collection-slug --api-key YOUR_KEY --method auto
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone

import httpx

# ── Constants ──────────────────────────────────────────────────────
SIWE_NONCE_URL = "https://opensea.io/__api/auth/siwe/nonce"
SIWE_VERIFY_URL = "https://opensea.io/__api/auth/siwe/verify"
GRAPHQL_URL = "https://gql.opensea.io/graphql"
OPENSEA_API_V2 = "https://api.opensea.io/api/v2/drops"
SEADROP_ADDRESS = "0x00005EA00Ac477B1030CE78506496e8C2dE24bf5"
# Free public RPC (no API key needed)
ETH_RPC = "https://ethereum-rpc.publicnode.com"

# GraphQL persisted query hash (refresh from browser network trace if expired)
DROP_ELIGIBILITY_HASH = "d893f026d731e8f14986921fa4229098e018289f6cc7683f8ee2dd83749dd95d"


# ── Method 1: On-chain SeaDrop ─────────────────────────────────────

def eth_call(client: httpx.Client, to: str, data: str) -> str:
    """Raw eth_call, return hex result."""
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_call",
        "params": [{"to": to, "data": data}, "latest"],
        "id": 1,
    }
    resp = client.post(ETH_RPC, json=payload, timeout=15)
    resp.raise_for_status()
    result = resp.json()
    if "error" in result:
        raise RuntimeError(f"eth_call error: {result['error']}")
    return result.get("result", "0x")


def check_onchain(wallet: str, nft_address: str) -> dict:
    """Check SeaDrop on-chain for public/FCFS drops. No PK needed."""
    client = httpx.Client(timeout=15)
    wallet_padded = wallet[2:].lower().zfill(64)
    nft_padded = nft_address[2:].lower().zfill(64)

    # 1. getMintStats(address) — selector 0x840e15d4
    print("  [On-chain] getMintStats...")
    try:
        raw = eth_call(client, nft_address, "0x840e15d4" + wallet_padded)
        raw_bytes = bytes.fromhex(raw[2:])
        if len(raw_bytes) >= 96:
            minter_minted = int.from_bytes(raw_bytes[0:32], "big")
            total_supply = int.from_bytes(raw_bytes[32:64], "big")
            max_supply = int.from_bytes(raw_bytes[64:96], "big")
        else:
            return {"error": f"getMintStats returned short data: {raw[:20]}"}
    except Exception as e:
        return {"error": f"getMintStats failed: {e}"}

    # 2. getPublicDrop(nft) — selector 0xbc6a629c (called on SeaDrop contract)
    print("  [On-chain] getPublicDrop...")
    public_drop = {}
    try:
        raw = eth_call(client, SEADROP_ADDRESS, "0xbc6a629c" + nft_padded)
        raw_bytes = bytes.fromhex(raw[2:])
        if len(raw_bytes) >= 192:
            public_drop = {
                "mintPrice": int.from_bytes(raw_bytes[0:32], "big"),
                "startTime": int.from_bytes(raw_bytes[32:64], "big"),
                "endTime": int.from_bytes(raw_bytes[64:96], "big"),
                "maxTotalMintableByWallet": int.from_bytes(raw_bytes[96:128], "big"),
                "feeBps": int.from_bytes(raw_bytes[128:160], "big"),
                "restrictFeeRecipients": raw_bytes[160:192][-1] == 1,
            }
    except Exception as e:
        public_drop = {"error": f"getPublicDrop failed: {e}"}

    # 3. getAllowListMerkleRoot — selector 0x32bf11f5
    print("  [On-chain] getAllowListMerkleRoot...")
    allowlist_root = None
    try:
        raw = eth_call(client, SEADROP_ADDRESS, "0x32bf11f5" + nft_padded)
        if raw and raw != "0x":
            root_bytes = bytes.fromhex(raw[2:])
            if len(root_bytes) >= 32:
                root_val = int.from_bytes(root_bytes[0:32], "big")
                allowlist_root = hex(root_val) if root_val != 0 else None
    except:
        pass

    # Determine eligibility
    now = int(time.time())
    sold_out = total_supply >= max_supply if max_supply > 0 else False
    cap_reached = (
        public_drop.get("maxTotalMintableByWallet", 0) > 0
        and minter_minted >= public_drop["maxTotalMintableByWallet"]
    )
    window_open = (
        public_drop.get("startTime", 0) <= now <= public_drop.get("endTime", 0)
        if public_drop.get("startTime", 0) != 0 or public_drop.get("endTime", 0) != 0
        else False
    )
    eligible = window_open and not sold_out and not cap_reached

    result = {
        "method": "onchain",
        "wallet": wallet,
        "nft_address": nft_address,
        "minter_minted": minter_minted,
        "total_supply": total_supply,
        "max_supply": max_supply,
        "sold_out": sold_out,
        "public_drop": public_drop,
        "allowlist_root": allowlist_root,
        "window_open": window_open,
        "cap_reached": cap_reached,
        "eligible": eligible,
    }

    # Print results
    print(f"\n  ═══ ON-CHAIN CHECK (SeaDrop) ═══")
    print(f"  Wallet:      {wallet}")
    print(f"  NFT:         {nft_address}")
    print(f"  Supply:      {total_supply}/{max_supply}")
    print(f"  You minted:  {minter_minted}")
    if public_drop.get("mintPrice", 0) > 0:
        print(f"  Price:       {public_drop['mintPrice'] / 1e18:.4f} ETH")
    if public_drop.get("maxTotalMintableByWallet", 0) > 0:
        print(f"  Max/wallet:  {public_drop['maxTotalMintableByWallet']}")
    if allowlist_root:
        print(f"  Allowlist:   YES (Merkle root: {allowlist_root[:20]}...)")

    if eligible:
        print(f"\n  ✅ ELIGIBLE — can mint now")
    else:
        reasons = []
        if sold_out:
            reasons.append("SOLD OUT")
        if cap_reached:
            reasons.append(f"Cap reached ({minter_minted}/{public_drop.get('maxTotalMintableByWallet', 0)})")
        if not window_open:
            st = public_drop.get("startTime", 0)
            et = public_drop.get("endTime", 0)
            if st == 0 and et == 0:
                reasons.append("no public stage configured")
            elif now < st:
                reasons.append(f"not started yet (starts {datetime.utcfromtimestamp(st).isoformat()})")
            else:
                reasons.append(f"ended ({datetime.utcfromtimestamp(et).isoformat()})")
        print(f"\n  ❌ NOT ELIGIBLE: {', '.join(reasons)}")

    return result


# ── Method 2: OpenSea API v2 ───────────────────────────────────────

def check_api_v2(slug: str, api_key: str) -> dict:
    """Get stage labels (GTD/FCFS/WL/Public), timing, price from OpenSea API v2."""
    if not api_key:
        print("  [API v2] Skipped — no API key provided")
        return {}

    print(f"  [API v2] Fetching drop stages for slug: {slug}...")
    try:
        resp = httpx.get(
            f"{OPENSEA_API_V2}/{slug}",
            headers={"X-API-KEY": api_key},
            timeout=15,
        )
        if resp.status_code == 404:
            print(f"  [API v2] Drop not found — check slug")
            return {}
        if resp.status_code == 401:
            print(f"  [API v2] Unauthorized — check API key")
            return {}
        resp.raise_for_status()

        data = resp.json()
        print(f"\n  ═══ OPENSEA API v2 — STAGE LABELS ═══")
        if data.get("name"):
            print(f"  Collection: {data['name']}")

        stages = data.get("stages", [])
        for i, stage in enumerate(stages):
            label = stage.get("label", "Unknown")
            print(f"\n  Stage {i+1}: {label}")
            if stage.get("start_time"):
                print(f"    Start:       {datetime.utcfromtimestamp(stage['start_time']).isoformat()}")
            if stage.get("end_time"):
                print(f"    End:         {datetime.utcfromtimestamp(stage['end_time']).isoformat()}")
            if stage.get("max_per_wallet"):
                print(f"    Max/wallet:  {stage['max_per_wallet']}")
            if stage.get("price"):
                price_eth = int(stage["price"]) / 1e18
                print(f"    Price:       {price_eth:.4f} ETH")

        return data
    except Exception as e:
        print(f"  [API v2] Error: {e}")
        return {}


# ── Method 3: SIWE + GraphQL (GTD/WL) ──────────────────────────────

def siwe_login(address: str, private_key: str) -> httpx.Client:
    """SIWE login → return authenticated httpx client with session cookies."""
    from eth_account import Account
    from eth_account.messages import encode_defunct

    client = httpx.Client(timeout=30, follow_redirects=True, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    })

    # 1) Get nonce
    print("  [SIWE] Getting nonce...")
    resp = client.post(SIWE_NONCE_URL)
    resp.raise_for_status()
    nonce = resp.json()["nonce"]

    # 2) Build EIP-4361 message
    issued_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    checksummed = Account.from_key(private_key).address  # EIP-55

    siwe_message = (
        f"opensea.io wants you to sign in with your Ethereum account:\n"
        f"{checksummed}\n\n"
        f"Click to sign in and accept the OpenSea Terms of Service "
        f"(https://opensea.io/tos) and Privacy Policy (https://opensea.io/privacy).\n\n"
        f"URI: https://opensea.io/\n"
        f"Version: 1\n"
        f"Chain ID: 1\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {issued_at}"
    )

    # 3) Sign (EIP-191 personal_sign)
    print("  [SIWE] Signing message...")
    msg_encoded = encode_defunct(text=siwe_message)
    signed = Account.sign_message(msg_encoded, private_key=private_key)
    signature = signed.signature.hex()
    if not signature.startswith("0x"):
        signature = "0x" + signature

    # 4) Verify → get session cookies
    print("  [SIWE] Verifying...")
    verify_body = {
        "message": {
            "domain": "opensea.io",
            "address": checksummed,
            "statement": "Click to sign in and accept the OpenSea Terms of Service (https://opensea.io/tos) and Privacy Policy (https://opensea.io/privacy).",
            "uri": "https://opensea.io/",
            "version": "1",
            "chainId": "1",
            "nonce": nonce,
            "issuedAt": issued_at,
            "accountType": "Ethereum",
        },
        "signature": signature,
        "chainArch": "EVM",
        "connectorId": "io.metamask",
    }

    resp = client.post(SIWE_VERIFY_URL, json=verify_body)
    resp.raise_for_status()

    # Check access_token cookie
    has_token = False
    for cookie in client.cookies.jar:
        if "access_token" in cookie.name:
            has_token = True
            break
    if not has_token:
        raise RuntimeError(f"SIWE login failed — no access_token cookie. Response: {resp.text[:200]}")

    client.cookies.set("connected-account-server-hint", checksummed, domain="opensea.io")
    print("  [SIWE] ✅ Login successful")
    return client


def check_eligibility_graphql(client: httpx.Client, wallet: str, slug: str) -> dict:
    """Query DropEligibilityQuery via GraphQL. Returns isEligible per stage."""
    print(f"  [GraphQL] Querying eligibility for {slug}...")

    headers = {
        "Content-Type": "application/json",
        "x-app-id": "os2-web",
        "x-graphql-operation-type": "query",
        "accept": "*/*",
        "origin": "https://opensea.io",
        "referer": "https://opensea.io/",
    }

    body = {
        "extensions": {
            "persistedQuery": {
                "sha256Hash": DROP_ELIGIBILITY_HASH,
                "version": 1,
            }
        },
        "operationName": "DropEligibilityQuery",
        "variables": {"address": wallet, "collectionSlug": slug},
    }

    resp = client.post(GRAPHQL_URL, json=body, headers=headers)
    if resp.status_code == 401 or resp.status_code == 403:
        return {"error": f"AUTH_FAILED ({resp.status_code})"}
    if resp.status_code == 429:
        return {"error": "RATE_LIMITED — wait and try again"}
    if resp.status_code != 200:
        return {"error": f"HTTP_{resp.status_code}: {resp.text[:200]}"}

    data = resp.json()
    if "errors" in data:
        err_msg = data["errors"][0].get("message", "")
        if "PersistedQueryNotFound" in err_msg:
            return {"error": "QUERY_HASH_EXPIRED — need to refresh hash from browser network trace"}
        return {"error": f"GRAPHQL_ERROR: {err_msg}"}

    return data.get("data", {})


def check_gtd_wl(address: str, private_key: str, slug: str) -> dict:
    """Full GTD/WL eligibility check via SIWE + GraphQL."""
    try:
        client = siwe_login(address, private_key)
        result = check_eligibility_graphql(client, address, slug)

        if "error" in result:
            print(f"\n  ❌ {result['error']}")
            return result

        # Parse result — GraphQL returns "dropBySlug" NOT "drop"
        drop = result.get("dropBySlug") or result.get("drop")
        if not drop:
            print(f"\n  ❌ Drop not found — check slug")
            print(f"  Raw: {json.dumps(result, indent=2)[:500]}")
            return result

        print(f"\n  ═══ GTD/WL ELIGIBILITY (GraphQL) ═══")
        print(f"  Wallet: {address}")
        print(f"  Slug:   {slug}")

        stages = drop.get("stages", [])
        if not stages:
            print(f"\n  No stages found")
            print(f"  Raw: {json.dumps(drop, indent=2)[:500]}")
            return result

        for i, stage in enumerate(stages):
            stage_type = stage.get("__typename", "Unknown")
            is_eligible = stage.get("isEligible", False)
            has_merkle = bool(stage.get("merkleRoot"))

            status = "✅ ELIGIBLE" if is_eligible else "❌ NOT eligible"
            print(f"\n  Stage {i+1}: {stage_type} → {status}")
            if has_merkle:
                print(f"    Allowlist: YES (Merkle root set)")

        return result

    except Exception as e:
        print(f"\n  ❌ GTD/WL check failed: {e}")
        return {"error": str(e)}


# ── CLI ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="OpenSea Drop Eligibility Checker (Standalone)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # On-chain only (no PK needed, just address + NFT contract)
  python opensea_eligibility.py --address 0x... --nft-address 0x... --method onchain

  # API v2 stage labels
  python opensea_eligibility.py --slug collection-slug --api-key YOUR_KEY

  # GTD/WL check (needs private key)
  python opensea_eligibility.py --address 0x... --private-key 0x... --slug collection-slug --method server

  # Full check (all methods)
  python opensea_eligibility.py --address 0x... --private-key 0x... --nft-address 0x... --slug collection-slug --api-key YOUR_KEY
        """,
    )
    parser.add_argument("--address", help="Wallet address (0x...)")
    parser.add_argument("--private-key", help="Wallet private key (0x...) — needed for GTD/WL SIWE")
    parser.add_argument("--slug", help="OpenSea collection slug (e.g. azuki-animus)")
    parser.add_argument("--nft-address", help="NFT contract address (for on-chain check)")
    parser.add_argument("--api-key", help="OpenSea API key (for API v2 stage labels)")
    parser.add_argument("--method", choices=["auto", "onchain", "server"], default="auto",
                        help="auto=try all, onchain=SeaDrop only, server=SIWE+GraphQL only")
    args = parser.parse_args()

    if not args.address:
        parser.error("--address is required")

    print(f"\n{'='*60}")
    print(f"  OpenSea Drop Eligibility Checker")
    print(f"  Wallet: {args.address}")
    if args.slug:
        print(f"  Slug:   {args.slug}")
    print(f"{'='*60}\n")

    # Method 1: On-chain
    if args.method in ("auto", "onchain") and args.nft_address:
        print("─ Method 1: On-chain SeaDrop ─")
        check_onchain(args.address, args.nft_address)
        print()

    # Method 2: API v2
    if args.method == "auto" and args.slug and args.api_key:
        print("─ Method 2: OpenSea API v2 ─")
        check_api_v2(args.slug, args.api_key)
        print()

    # Method 3: SIWE + GraphQL
    if args.method in ("auto", "server") and args.private_key and args.slug:
        print("─ Method 3: SIWE + GraphQL (GTD/WL) ─")
        check_gtd_wl(args.address, args.private_key, args.slug)
        print()

    if args.method == "onchain" and not args.nft_address:
        print("❌ On-chain method needs --nft-address")
    if args.method == "server" and not args.private_key:
        print("❌ Server method needs --private-key")
    if args.method == "server" and not args.slug:
        print("❌ Server method needs --slug")

    print("\nDone.")


if __name__ == "__main__":
    main()
