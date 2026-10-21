# R7 private-cache drain observation (default off)

This checkpoint adds opt-in real private-owner quiescence observation only. It does not connect a CMU ACK, enable a rate whitelist, switch clocks, or claim system/CDC/physical qualification. Existing cache interfaces and behavior remain unchanged when `reportQuiescence=false` (the default).

The observed state includes miss/probe/flush phases, deferred dirty writes, queued replies and metadata, native response ownership and protocol offers. Sticky flush completion alone is not idle. Existing coherent acquire logic retains ownership through the actual E handshake.

Verified with the pinned GSIM backend and Clang 19:

- `mill --no-server IonSoC.test.testOnly inorder.I1CacheQuiescenceSpec`: PASS, default/explicit-false CHIRRTL identical and optional observation absent.
- `GSIM_CXX=clang++-19 python3 simulator/gsim/i1_cache_quiescence.py --tag 20261021-private-drain-v3`: PASS for six delayed-owner scenarios and six intentionally incorrect owner oracles rejected.
- The same runner independently checks back-to-back cache write/read data and 32 same-address ReadFirst collisions; the intentionally incorrect new-value oracle is rejected.

The pinned GSIM parser requires `smem ... old` instead of emitted `smem ..., old`. The test runner removes only that comma and preserves the explicit OLD policy. Original/adapted FIR and parser/scheduler source hashes plus the collision witness are recorded in `receipt.json`. No simulator backend or production RTL is patched. Prior v1 syntax failure and v2 experiments remain in local build outputs; v3 is the authoritative consolidated result.

Limitations: single-clock component test; no whole-lineGrant behavioral coverage, complete tile/Home epoch barrier, AON resume protocol, clock gating, DRP, timing, or board claim. Those require separate checkpoints. A1 runtime support remains unimplemented.
