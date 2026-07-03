---
name: opensea-eligibility-checker
description: "Use when checking NFT drop eligibility on OpenSea — GTD/WL/FCFS/Public stages, SeaDrop on-chain supply/cap/window, SIWE+GraphQL eligibility, API v2 stage labels. Standalone Python script, no vault dependency."
version: 1.0.0
author: SUPERAGENT
license: MIT
metadata:
  hermes:
    tags: [opensea, nft, eligibility, seadrop, siwe, graphql, airdrop, mint]
    related_skills: [nft-mint-sniping, web3]
---

# OpenSea Drop Eligibility Checker

## Overview

Check wallet eligibility for OpenSea NFT drops using 3 complementary methods. Standalone Python script — no vault or agent framework required. Shareable on GitHub.

## When to Use

- Check if a wallet is eligible for an NFT drop (GTD/WL/FCFS/Public)
- Get on-chain supply/cap/mint-window status for SeaDrop contracts
- Fetch authoritative stage labels (GTD/FCFS/WL/Public) with timing + price
- Verify GTD/WL eligibility via OpenSea's SIWE authentication + GraphQL

**Don't use for:**
- Non-OpenSea drops (uses SeaDrop contract + OpenSea GraphQL specifically)
- Minting (this is read-only eligibility check, not a minting tool)
- Solana drops (ETH-only — SeaDrop + EVM SIWE. Solana drops need a separate checker)

## Quick Reference

| Method | Needs PK? | Needs API Key? | What it checks |
|--------|-----------|----------------|----------------|
| On-chain SeaDrop | ❌ | ❌ | Supply, cap, mint window, allowlist root |
| OpenSea API v2 | ❌ | ✅ | Stage labels, timing, max/wallet, price |
| SIWE + GraphQL | ✅ | ❌ | isEligible per stage (GTD/WL/FCFS — same method) |

**Stage skip rules:**
- **Public** → skip eligibility check (everyone eligible)
- **GTD/WL/FCFS** → all use SIWE + GraphQL (same method, GraphQL returns isEligible per stage)

## Setup

```bash
pip install httpx eth-account
```

## Usage

```bash
# On-chain only (no PK needed — just address + NFT contract)
python opensea_eligibility.py \
  --address 0xYourWallet \
  --nft-address 0xNFTContract \
  --method onchain

# API v2 stage labels (needs OpenSea API key)
python opensea_eligibility.py \
  --slug collection-slug \
  --api-key YOUR_OPENSEA_API_KEY

# GTD/WL check (needs private key for SIWE signing)
python opensea_eligibility.py \
  --address 0xYourWallet \
  --private-key 0xYourPK \
  --slug collection-slug \
  --method server

# Full check (all 3 methods)
python opensea_eligibility.py \
  --address 0xYourWallet \
  --private-key 0xYourPK \
  --nft-address 0xNFTContract \
  --slug collection-slug \
  --api-key YOUR_OPENSEA_API_KEY
```

## How It Works

### Method 1: On-chain SeaDrop

Uses `eth_call` to the SeaDrop contract (`0x00005EA00Ac477B1030CE78506496e8C2dE24bf5`) via free public RPC.

| Function | Selector | Returns |
|----------|----------|---------|
| `getMintStats(address)` | `0x840e15d4` | minter_minted, total_supply, max_supply |
| `getPublicDrop(nft)` | `0xbc6a629c` | mintPrice, startTime, endTime, maxPerWallet, feeBps |
| `getAllowListMerkleRoot(nft)` | `0x32bf11f5` | Merkle root (if allowlist set) |

Eligibility = `window_open AND NOT sold_out AND NOT cap_reached`

### Method 2: OpenSea API v2

`GET https://api.opensea.io/api/v2/drops/{slug}` with `X-API-KEY` header.

Returns authoritative stage labels: **GTD**, **FCFS**, **WL**, **BlockPass**, **Public** — plus `start_time`, `end_time`, `max_per_wallet`, `price` (in wei).

> Get your API key at https://opensea.io/settings → API Keys

### Method 3: SIWE + GraphQL

1. **SIWE login**: Get nonce → build EIP-4361 message → sign with `personal_sign` → verify → get session cookies
2. **GraphQL query**: `DropEligibilityQuery` at `gql.opensea.io` with persisted query hash
3. Returns `isEligible` per stage — same method for GTD/WL/FCFS

**Critical quirk**: GraphQL returns key `dropBySlug` (NOT `drop`), and stages are only labeled `SIGNED_PRESALE` / `PUBLIC_SALE`. For real stage labels (GTD/FCFS/WL), use API v2.

## Common Pitfalls

1. **Persisted query hash expiry.** The GraphQL hash (`d893f026...`) can expire. If you get `PersistedQueryNotFound`, refresh it by inspecting browser network traffic on an OpenSea drop page → look for `DropEligibilityQuery` request → copy the `sha256Hash` from the request body.

2. **GraphQL returns `dropBySlug`, not `drop`.** Always access `result.get("dropBySlug")` — using `drop` will return None.

3. **Stage labels differ between API v2 and GraphQL.** API v2 gives real labels (GTD/FCFS/WL/Public). GraphQL only gives `SIGNED_PRESALE`/`PUBLIC_SALE`. Cross-reference both for complete picture.

4. **Public stage = always eligible.** Don't waste API calls checking public stage eligibility. Only check GTD/WL/FCFS.

5. **GTD/WL/FCFS use the same method.** All three go through SIWE + GraphQL `DropEligibilityQuery`. The GraphQL response returns `isEligible` per stage regardless of stage type.

6. **SIWE needs checksummed address.** Use `Account.from_key(pk).address` for EIP-55 checksummed address in the SIWE message. Raw lowercase may fail verification.

7. **Rate limiting.** GraphQL returns 429 if queried too fast. Add 2-3s delay between batch wallet checks.

## Batch Checking Multiple Collections

When checking eligibility for many drops at once (e.g. a daily mint list):

1. **Login once, reuse session.** Call `siwe_login()` once → get authenticated `httpx.Client` → pass it to `check_eligibility_graphql()` for every collection. Do NOT re-login per collection — SIWE is rate-limited and slow.
2. **Add 1-2s delay between GraphQL queries** to avoid 429 rate limiting.
3. **Use structured JSON output, not stdout parsing.** The script's pretty-printed JSON output gets truncated in terminal capture (Hermes `terminal()` caps at ~50KB). Write a custom batch script that imports `siwe_login` + `check_eligibility_graphql` directly and outputs `json.dumps(results)` — parse the structured data instead of regex-matching truncated stdout.
4. **Cross-reference API v2 for stage labels.** GraphQL only returns `SIGNED_PRESALE`/`PUBLIC_SALE` — it does NOT tell you which stage is GTD vs FCFS vs WL. If the user's mint list specifies stage types, map them by `stageIndex` order (stage 1 = first presale = usually GTD/WL, last presale = usually FCFS, index 0 = public). For authoritative labels, query API v2 separately.

### Batch script pattern

```python
import sys, os, json, time
sys.path.insert(0, os.path.expanduser("~/superagent-v4/skills/hermes/scripts"))
from opensea_eligibility import siwe_login, check_eligibility_graphql, get_wallet_from_vault

addr, pk = get_wallet_from_vault("wallet_0")
client = siwe_login(addr, pk)  # Login ONCE

results = []
for slug, name, ts, price, supply in collections:
    data = check_eligibility_graphql(client, addr, slug)
    drop = data.get("dropBySlug", {})
    stages = [{"type": s["stageType"], "eligible": s["isEligible"],
               "max": s["maxTotalMintableByWallet"],
               "price_eth": s.get("eligiblePrice",{}).get("token",{}).get("unit",0)}
              for s in drop.get("stages", [])]
    results.append({"name": name, "slug": slug, "stages": stages})
    time.sleep(1)

print(json.dumps(results, indent=2))
```

## Publishing to GitHub

When sharing this skill as a public repo:

1. **Scrub internal references.** Remove any `references/*.md` files that mention vault structure, wallet aliases (`wallet_0`, `main_evm`), wallet counts, or internal script paths (`~/superagent-v4/...`). Run: `grep -rnE 'wallet_[0-9]|main_evm|vault|superagent|\.env' . --include="*.md" --include="*.py"`
2. **Keep only 3 files:** `README.md`, `SKILL.md`, `scripts/opensea_eligibility.py`
3. **Standalone script only.** The published `scripts/opensea_eligibility.py` must have NO vault dependency — all inputs via CLI args (`--address`, `--private-key`, `--slug`, `--nft-address`, `--api-key`). The vault-tied version stays internal.
4. **No API keys, wallet addresses, or credentials** in any pushed file.

## Price Reporting (user preference)

Always show price in **both ETH and USD ($)**. Convert realtime using Coinbase or Coingecko spot price at report time. GraphQL `eligiblePrice.usd` field provides USD directly — use it when available.

## Eligible Stage Output Format (user preference)

When eligibility check finds a wallet **eligible for GTD/FCFS/WL** (not public-only), provide **full mint data** for that collection:

1. **Collection name + OpenSea drop link** — `https://opensea.io/drops/{slug}`
2. **Twitter link** — search the collection's Twitter/X account (from OpenSea drop page or API v2 `creator` field). Include `https://x.com/{handle}`.
3. **Eligible stages** — which stages W0 (or checked wallet) is eligible for
4. **Price per stage** — ETH + USD ($), realtime converted
5. **Max per wallet** — `maxTotalMintableByWallet` per stage
6. **Start time** — WIB (UTC+7), converted from on-chain/API `start_time`
7. **Supply** — total supply if available

**Example output:**
```
🎯 Neokitsune — W0 ✅ GTD + FCFS
Link: https://opensea.io/drops/neokitsune
Twitter: https://x.com/neokitsune
Stage 1 (GTD): ✅ eligible, 0.002 ETH ($3.49), max 2/wallet
Stage 2 (FCFS): ✅ eligible, 0.002 ETH ($3.49), max 2/wallet
Start: 20:00 WIB hari ini
```

**Skip public-only collections** from detailed output — just list name + link + public price in a compact table. Focus detailed output on GTD/WL/FCFS eligible ones only.

## Verification Checklist

- [ ] `pip install httpx eth-account` succeeds
- [ ] On-chain check returns supply numbers (not error)
- [ ] API v2 returns stage labels (if API key provided)
- [ ] SIWE login produces `access_token` cookie
- [ ] GraphQL returns `dropBySlug` with `stages` array
- [ ] No private keys logged in output
- [ ] Batch check: single SIWE login, 1-2s delay between queries
- [ ] GitHub publish: no vault refs, wallet addresses, or API keys in repo
