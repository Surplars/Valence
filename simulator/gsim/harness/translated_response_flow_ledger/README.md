# Preserved same-edge return observer

This directory tracks the exact header, full validate/advance host controls and
patch used by the source-bound observer continuation. `provenance.json` binds
original NEMU/DMA receipts and the terminal archive, which preserves original
observers, launchers, failures, successes and guests. No CPU execution is claimed
from this new tracked location.

From the repository root:

```sh
python3 -B simulator/gsim/test_return_flow_ledger.py --cxx clang++ --output build/return-flow-ledger-controls
```

The output must be fresh. An installed C++20 compiler with ASan/UBSan is required;
`GSIM_CXX` also selects it. The runner installs no tools and builds/executes no
DUT. It expects 44 positive validations and 19 negative controls, hashes actual
source/compiler inputs and writes a fresh receipt. Complete validate/advance
transitions include held capture/later pop, old pop/new capture, full-two pop
without borrowed credit, all flag tuples and separate posted ACK/physical duties.

This is a separate snapshot of the physical M/Bare integer observer, including
its existing checked-store-prefetch authorization oracle. The old shared header
is preserved. Explicit consumers put this directory before the shared harness
include directory and define `BACKEND_OWNER_COUNT=4`, `STORE_PREFETCH_PROFILE=1`,
`PHYSICAL_INGRESS_FLOW=1` for the qualified profile. The observer rejects foreign
FP/system epochs; it is not a general privileged or cancellation oracle.

Actual input is `adapter.virtual.response.fire`; in this integer-only scope the
actual output is `StoreBuffer.memory.response.fire`. `returnPush`/`returnPop`
are internal queue handshakes. Empty bypass needs an empty pre-edge shadow and
both actual port fires. Old registered heads win; full pre-edge occupancy rejects
input even while popping. Input/queue/pass and output/queue/pass conservation
must both hold.

The preserved patch is relative to the original supplemental host header, not
the older shared repository header. Do not blindly apply it to a different base.
Provenance identifies exact bytes so future adaptations cannot silently inherit
the original runtime PASS.
