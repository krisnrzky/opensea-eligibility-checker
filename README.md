# OpenSea Eligibility Checker

Check NFT drop eligibility on OpenSea — GTD/WL/FCFS/Public stages.

## Quick Start

```bash
pip install httpx eth-account
python scripts/opensea_eligibility.py --address 0x... --nft-address 0x... --method onchain
```

## Methods

| Method | PK? | API Key? | What |
|--------|-----|----------|------|
| On-chain SeaDrop | ❌ | ❌ | Supply, cap, mint window |
| OpenSea API v2 | ❌ | ✅ | Stage labels, timing, price |
| SIWE + GraphQL | ✅ | ❌ | isEligible per stage (GTD/WL) |

## Stage Rules

- **Public** → skip check (everyone eligible)
- **FCFS** → check eligibility (race condition)
- **GTD/WL** → check eligibility (allowlist)

## Get API Key

https://opensea.io/settings → API Keys

## License

MIT
