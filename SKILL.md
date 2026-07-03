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

## Verification Checklist

- [ ] `pip install httpx eth-account` succeeds
- [ ] On-chain check returns supply numbers (not error)
- [ ] API v2 returns stage labels (if API key provided)
- [ ] SIWE login produces `access_token` cookie
- [ ] GraphQL returns `dropBySlug` with `stages` array
- [ ] No private keys logged in output
