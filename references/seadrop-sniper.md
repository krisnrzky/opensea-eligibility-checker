# SeaDrop Sniper — Pre-sign + Fire-at-T + Flashbots + RBF + Multi-wallet

Reference for `~/superagent-v4/skills/hermes/scripts/seadrop_sniper.py` and
`~/superagent-v4/skills/hermes/scripts/sniper_benchmark.py`.

## Architecture

```
parse input → resolve contract (API v2 /drops/{slug})
            → read on-chain config (getPublicDrop — READ_RPC, NOT Flashbots)
            → pre-sign EIP-1559 tx NOW (hold raw tx)
            → calibrate clock to chain time
            → wait until T (coarse sleep + busy-spin last 5s)
            → FIRE: broadcast raw tx to RPC_POOL in parallel (Flashbots first)
            → RBF retry: if not included in ~15s, re-sign +50% gas, re-broadcast
            → wait receipt → report
```

## RPC topology (critical)

**Flashbots Protect (`https://rpc.flashbots.net/fast`) is for BROADCAST ONLY.**
It does not reliably serve `eth_call` / `eth_estimateGas` / `eth_getTransactionReceipt`.
A `getPublicDrop` eth_call against Flashbots returns `None` → script exits "No public drop on-chain".

- `READ_RPC = "https://eth.drpc.org"` — all reads (getPublicDrop, getNonce, estimateGas, receipt checks).
- `RPC_POOL = [FLASHBOTS_RPC, ...PUBLIC_RPCS]` — broadcast only, parallel, fastest responder wins.
- Never index `RPC_POOL[0]` for reads — use `READ_RPC` explicitly.

## Benchmark (measured 2026-06-30)

| RPC | Ping avg | Mempool | Role |
|-----|----------|---------|------|
| `rpc.flashbots.net/fast` | 826ms | **private** (anti-frontrun) | Broadcast priority #1 |
| `eth.drpc.org` | 75ms | public | Fastest read + broadcast fallback |
| `ethereum-rpc.publicnode.com` | 235ms | public | Fallback |
| `1rpc.io/eth` | ❌ down | — | — |
| `rpc.ankr.com/eth` | ❌ down | — | — |
| `eth.llamarpc.com` | ❌ down (521) | — | — |

**Block time ETH:** avg 12.0s, median 12.0s (measured over 5 blocks). This is the
irreducible landing floor — tx can only enter the next block.

**Total T→inclusion:** ~75ms broadcast (fastest responder) + ~12s block = ~12.1s.
Baseline single public RPC: ~235ms + 12s + frontrun risk.

## eth_account signing quirks (hard-won)

### 1. TypedTransaction.from_dict FAILS with string type
```python
# ❌ BROKEN: "missing or incorrect transaction type"
from eth_account.typed_transactions import TypedTransaction
typed = TypedTransaction.from_dict({"type": "2", "chainId": 1, ...})
signed = Account.sign_transaction(typed, pk)

# ✅ WORKS: plain dict with int type
tx_dict = {"type": 2, "chainId": 1, "nonce": ..., "maxPriorityFeePerGas": ...,
           "maxFeePerGas": ..., "gas": ..., "to": ..., "value": hex(value),
           "data": "0x" + data.hex(), "accessList": []}
signed = Account.sign_transaction(tx_dict, pk)
raw = signed.raw_transaction.hex()
if not raw.startswith("0x"): raw = "0x" + raw
```

### 2. value MUST be hex string, data MUST have 0x prefix
- `eth_estimateGas` params: `{"data": "0x" + data.hex()}` (not bare `.hex()`),
  `"value": hex(value)` (not int). Bare hex → `"cannot unmarshal hex string
  without 0x prefix into Go struct field"`.
- Same for the signed tx dict: `"value": hex(value)`, `"data": "0x" + data.hex()`.

### 3. Function selector without web3
```python
from Crypto.Hash import keccak
def keccak256(data: bytes) -> bytes:
    h = keccak.new(digest_bits=256); h.update(data); return h.digest()
fn_sel = keccak256(b"mintPublic(address,address,address,uint256)")[:4]
```
For `getAllowedFeeRecipients(address)` selector use
`eth_utils.function_signature_to_sighash(sig).hex()` (needs `eth-utils` installed).

## WalletManager quirks

- `wm.list_wallets()` returns `list[dict]` with keys `['label', 'chain', 'address']` —
  **NO `private_key`**. Iterating `.address` on the dicts works, but to sign you must
  call `wm.get(label)` which returns an object with `.address` AND `.private_key`.
- Dedup aliases: `main_evm` == `wallet_0` (same address). Filter by unique address
  before multi-wallet fire.
- Filter by `chain == "evm"` — vault may hold non-EVM entries.

## Clock sync to chain time

```python
local_before = time.time()
blk = rpc_call(rpc, "eth_getBlockByNumber", ["latest", False])
chain_ts = int(blk["timestamp"], 16)
local_after = time.time()
offset = chain_ts - (local_before + local_after) / 2
```
Observed offset: chain was -3s to -9s behind local clock. Fire time target must be
in CHAIN time: `fire when (time.time() + offset) >= fire_ts`.

## Wait loop precision

- Coarse sleep until 5s before T: `time.sleep(max(0, wait_s - 5))`.
- Busy-spin last 5s for ms precision: `while time.time() + offset < fire_ts: ...`
  with `time.sleep(0.1)` when >0.5s remaining, pure spin under 0.5s.
- `--no-wait` flag skips the loop entirely (for testing — fires immediately).

## RBF retry logic

1. Broadcast signed tx to all RPCs in parallel.
2. Poll `eth_getTransactionReceipt` every 3s for 15s (~1 block + margin).
3. If not included → re-sign SAME nonce with `gas * (1 + 0.5 * (attempt-1))`,
   re-broadcast. Max 3 attempts → +100% gas by attempt 3.
4. Track per-attempt: `broadcast_ms`, `gas_bump_pct`, `inclusion_s`, `block`, `status`.

## Multi-wallet parallel fire

- Load unique EVM wallets from vault (11 wallets typical).
- Pre-sign all in parallel (ThreadPool, max 5 workers) — each gets its own nonce.
- At T, fire all raw txs in parallel (ThreadPool, max 11 workers).
- Each wallet broadcasts to the full RPC_POOL → first responder per wallet wins.
- Report: total fire time, success count, per-wallet tx hash + etherscan link.

## Gas estimation when window not open

`eth_estimateGas` against a SeaDrop `mintPublic` call REVERTS before `startTime`
(contract checks `block.timestamp >= startTime`). Revert data starts with `0x13da22f2`
(SeaDrop `Mint_Time_Closed`-style selector) + encoded window boundaries. This is
NORMAL pre-mint — the sniper falls back to `gas_limit = 200000` (+30% buffer for
safety). The tx will succeed once the window opens at T.

## CLI

```bash
# Single wallet, fire at on-chain start time
python seadrop_sniper.py --slug blockhz --wallet wallet_0 --qty 2 --auto-time

# Multi-wallet parallel (all vault wallets)
python seadrop_sniper.py --slug blockhz --wallet all --qty 1 --auto-time

# Manual fire time (WIB)
python seadrop_sniper.py --slug blockhz --wallet wallet_0 --qty 2 \
  --fire-at "2026-07-01 02:00:00" --timezone WIB

# Dry-run + no-wait (test, no broadcast, skip wait loop)
python seadrop_sniper.py --slug blockhz --wallet all --qty 1 --auto-time --dry-run --no-wait

# Benchmark RPCs
python sniper_benchmark.py
```

## Speed optimization summary (what helps, what doesn't)

| Optimization | Effect | Measured |
|---|---|---|
| Flashbots Protect | Anti-frontrun (private mempool) | 826ms, zero public exposure |
| Multi-RPC parallel broadcast | Redundancy + fastest wins | 75ms vs 235ms baseline |
| Pre-sign + hold | Zero signing delay at T | Sign hours ahead |
| Clock sync to chain | Fire accurate to chain second | -9s offset corrected |
| RBF gas bump retry | Ensure inclusion if missed | +50%/attempt, max 3 |
| Multi-wallet parallel | N wallets fire simultaneously | 11 wallets, ThreadPool |
| ~~Sub-block landing~~ | NOT possible | 12s block time = floor |
