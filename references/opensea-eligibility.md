# OpenSea Drop Eligibility — API Reference

Condensed from the OpenSea drop-eligibility methodology. Full external doc preserved by user at `~/.hermes/cache/documents/doc_bb8fe67fffc4_opensea-drop-eligibility.md`.

## A. Server-side (SIWE + GraphQL) — authoritative for gated drops

### A1. SIWE login → session

1. **Get nonce**: `POST https://opensea.io/__api/auth/siwe/nonce` (no body, no `Content-Length: 0` — Cloudflare 400s it). Returns `{"nonce": "..."}`.
2. **Build EIP-4361 message** (byte-exact, EIP-55 checksummed address, exact blank lines, NO trailing newline):
   ```
   opensea.io wants you to sign in with your Ethereum account:
   <CHECKSUMMED_ADDRESS>

   Click to sign in and accept the OpenSea Terms of Service (https://opensea.io/tos) and Privacy Policy (https://opensea.io/privacy).

   URI: https://opensea.io/
   Version: 1
   Chain ID: 1
   Non: <nonce>
   Issued At: <ISO-8601, e.g. 2026-06-20T00:00:00.000Z>
   ```
   Sign with `personal_sign` (EIP-191) → `signature = 0x...` (v as 27/28).
3. **Verify → cookies**: `POST https://opensea.io/__api/auth/siwe/verify` with body `{message: {...}, signature, chainArch: "EVM", connectorId: "io.metamask"}`. Keep ALL returned cookies. Missing `access_token` ⇒ login failed.

### A2. DropEligibilityQuery

```
POST https://gql.opensea.io/graphql
Content-Type: application/json
x-app-id: os2-web
x-graphql-operation-type: query
origin: https://opensea.io
referer: https://opensea.io/
Cookie: <SIWE cookies>; connected-account-server-hint=<WALLET>
```

**`connected-account-server-hint` MUST = the SIWE'd wallet.** OpenSea reads the active wallet from this cookie, not the variable. Mismatch → `PERMISSION_DENIED`.

Body (persisted query):
```json
{
  "extensions": {"persistedQuery": {"sha256Hash": "d893f026d731e8f14986921fa4229098e018289f6cc7683f8ee2dd83749dd95d", "version": 1}},
  "operationName": "DropEligibilityQuery",
  "variables": {"address": "<WALLET>", "collectionSlug": "<SLUG>"}
}
```

**Response shape:** `data.dropBySlug.stages[]`. Each stage: `stageType` (`SIGNED_PRESALE` | `PUBLIC_SALE`), `stageIndex`, `isEligible`, `maxTotalMintableByWallet`, `eligibleMaxTotalMintableByWallet`, `eligiblePrice.token.unit` (ETH float).

**Failure handling:**
- 401/403 or `PERMISSION_DENIED` → SIWE session missing/expired or hint cookie wrong → re-run A1.
- 429 → throttled, back off / rotate egress.
- `PersistedQueryNotFound` → OpenSea rotated the hash; refresh from browser network trace.

> The `sha256Hash` is OpenSea-version-specific and changes when they update the query — treat as refreshable, not constant.

## B. On-chain (SeaDrop) — public drops, no signing

All `eth_call`. Contracts:
- **SeaDrop** (drop controller): `0x00005EA00Ac477B1030CE78506496e8C2dE24bf5` (first arg = NFT address)
- **nft** — the collection contract

### B1. Per-wallet count + supply (every drop)
`nft.getMintStats(address minter)` — selector `0x840e15d4`
→ `(uint256 minterNumMinted, uint256 currentTotalSupply, uint256 maxSupply)`
- Sold out if `currentTotalSupply == maxSupply`.
- Under cap if `minterNumMinted + Q ≤ maxTotalMintableByWallet`.

### B2. Public stage
`SeaDrop.getPublicDrop(address nft)` — selector `0xbc6a629c`
→ `PublicDrop { uint80 mintPrice, uint48 startTime, uint48 endTime, uint16 maxTotalMintableByWallet, uint16 feeBps, bool restrictFeeRecipients }` (one 32-byte slot per field, in order). Eligible if `startTime ≤ now ≤ endTime` + cap + payment. `startTime == endTime == 0` ⇒ no public stage.

### B3. Gated (allowlist) stage
`SeaDrop.getAllowListMerkleRoot(address nft)` — selector `0x32bf11f5` → `bytes32 root`
- Zero root ⇒ no allowlist on-chain (gating server-side → use method A).
- Non-zero root ⇒ membership list off-chain. Prove on-chain: `leaf = keccak256(abi.encode(minter, mintParams))`, verify Merkle proof against root.

## C. API v2 `/drops/{slug}` — stage labels + timing (AUTHORITATIVE, no signing)

`GET https://api.opensea.io/api/v2/drops/{slug}` header `X-API-KEY: <key>`

**Top-level fields:** `collection_slug`, `collection_name`, `chain`, `contract_address` (the NFT contract), `drop_type` ("seadrop_v1_erc721"), `is_minting`, `image_url`, `opensea_url`, `active_stage` (null if none live), `next_stage`, `stages[]`, `total_supply`, `max_supply`.

**Each stage object:**
```json
{
  "uuid": "...",
  "stage_type": "signed_presale" | "public_sale",
  "label": "WL" | "GTD" | "FCFS" | "BlockPass / 120" | "Public stage" | <custom>,
  "price": "1500000000000000",           // wei string
  "price_currency_address": "0x000...0", // ETH
  "start_time": "2026-06-30T15:00:00Z",  // ISO 8601
  "end_time": "2026-06-30T16:00:00Z",
  "max_per_wallet": "3"                   // string
}
```

**This is the ONLY source of real `label` + `start_time`/`end_time`.** GraphQL (Method A) gives `isEligible` per stage but no label; on-chain (Method B) gives the public drop config but not presale stage names. Cross-reference Method A (`isEligible` by `stageIndex`, sorted) with Method C (stages in array order) to build a labeled eligibility report.

**On-chain price check:** API v2 `price` is a wei string but may lag updates. For the automint script, read price from `SeaDrop.getPublicDrop(nft)` (on-chain, Method B2) — it's the value the tx will actually pay. Example discrepancy observed: API v2 said 0.00064 ETH, on-chain confirmed 0.00064 ETH (matched); but GraphQL `eligiblePrice.token.unit` said 0.0015 ETH for the same drop's public stage — the on-chain value is authoritative for tx value.

## Quick reference table

| Check | How |
|---|---|
| Stage labels + timing (authoritative) | REST `GET api.opensea.io/api/v2/drops/{slug}` (`X-API-KEY`) → `stages[].label`, `start_time`, `end_time`, `max_per_wallet` |
| Gated eligibility (authoritative) | SIWE → `DropEligibilityQuery` (`isEligible` per stage) |
| GraphQL endpoint | `POST gql.opensea.io/graphql` (`x-app-id: os2-web`, `connected-account-server-hint=<wallet>`) |
| SIWE nonce/verify | `POST opensea.io/__api/auth/siwe/nonce` → sign → `POST .../siwe/verify` |
| Public window/price (tx-value authoritative) | `SeaDrop.getPublicDrop(nft)` — `0xbc6a629c` |
| Per-wallet minted + supply | `nft.getMintStats(wallet)` — `0x840e15d4` |
| Allowlist root | `SeaDrop.getAllowListMerkleRoot(nft)` — `0x32bf11f5` |
| Can pay | `eth_getBalance(wallet)` ≥ `mintPrice × Q` + gas |

**Ineligible when:** stage not open; `isEligible=false`; not on allowlist root; per-wallet cap reached; sold out; insufficient balance; no valid SIWE session for gated query.
