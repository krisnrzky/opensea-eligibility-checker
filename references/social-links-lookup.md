# Social Links Lookup — OpenSea API v2

## Endpoint

```
GET https://api.opensea.io/api/v2/collections/{slug}
Headers: X-API-KEY: <your_opensea_api_key>
```

## Social Fields Returned

| Field | Example |
|-------|---------|
| `twitter_username` | `NeokitsuneNft` |
| `discord_url` | `https://discord.gg/Vu3JMdPuh7` |
| `telegram_url` | (empty if none) |
| `instagram_username` | (empty if none) |
| `project_url` | (empty if none) |
| `wiki_url` | (empty if none) |

## Key Notes

1. **Use `/collections/{slug}`, NOT `/drops/{slug}`.** The `/drops/{slug}` endpoint returns stage info (labels, timing, price) but has NO social links. The `/collections/{slug}` endpoint returns social links but has NO stage info. Query both for a complete picture.

2. **`twitter_username` is the bare handle** (e.g. `NeokitsuneNft`), not a URL. Construct the full URL as `https://x.com/{twitter_username}`.

3. **Many fields are empty strings** (not null) when the collection hasn't set them. Check `if field:` before using.

## Python Example

```python
import httpx

resp = httpx.get(
    f"https://api.opensea.io/api/v2/collections/{slug}",
    headers={"X-API-KEY": api_key},
    timeout=15,
)
data = resp.json()
twitter = data.get("twitter_username", "")
twitter_url = f"https://x.com/{twitter}" if twitter else "N/A"
discord = data.get("discord_url", "N/A")
```

## Other Useful Fields from `/collections/{slug}`

- `name` — collection display name
- `description` — collection description
- `image_url` — logo image
- `banner_image_url` — banner image
- `opensea_url` — `https://opensea.io/collection/{slug}`
- `total_supply` — minted count
- `unique_item_count` — unique NFTs
- `created_date` — creation timestamp
- `contracts` — array of contract addresses
