# Original monitor ELF, fixed fetch history ON, older-prefix OFF/ON

This separate fixture preserves the unchanged GCC 14.2 diagnostic ELF, launcher,
data oracle, full-token ownership/cancellation, raw traffic, UART/18 rdtime
markers, source-ready/staged/start evidence, continuous frontend timeline,
registered previous-packet checks and full return/drain proof of fetch-history V1.
All C++ observer headers and source are byte-identical to that qualified fixture.
The actual board GCC 13.2 ELF remains unavailable.

Production anchor remains 2288c7f008e9d6440e8a28e339da28152b54892a. Both sides are
LSU4, physical ingress ON, DMA line4/yield0, prechecked flow OFF, fetch history ON.
Only older-prefix retirement changes. The OFF model is the existing qualified
fetch-history-on-r1 model; ON is fetch-history-prefix-on-r1. Both replay binaries
must be newly linked against this identical observer fixture. No guest or RTL is
changed. Complete source-tree/file-set, model/input/artifact/profile, compiler,
guest, fixture, validator and optional debug-compression proofs remain strict.
The exact external ADDI x14,x0,0 initial-sum producer rule is retained.

The motivation is measured, not an expected result: the earlier history-only
experiment retained approximately 3210 ticks despite recovering some backward
fetch packets, while retirement order-hold counters increased. This experiment
measures whether the existing prefix option changes that outcome; no cycle gain,
order-hold reduction or frontend recovery count is required to pass. Previous
history-only outputs and their fixture remain intact.

## Parent-owned heavy run

    source ../Valence/scripts/cloud/env.sh
    export GSIM_CXX=/workspace/scratch/41e4a649bb60/Valence/simulator/build/cloud-env/sysroot/usr/bin/clang++-19
    fixture=simulator/gsim/fixtures/monitor_bandwidth_fetch_prefix_v2
    prepared=../Valence-cpu-retire-prefix-next/simulator/gsim/fixtures/monitor_bandwidth_replay/static-r1
    python3 -B "$fixture/run_replay.py" --model-repo . --model-receipt build/gsim/fpga-next-board-cpu-fetch-history-on-r1/receipt.json --prepared "$prepared" --older-prefix 0 --compress-debug --out build/gsim/monitor-fetch-prefix-off-v2-r1 --run
    python3 -B "$fixture/run_replay.py" --model-repo . --model-receipt build/gsim/fpga-next-board-cpu-fetch-history-prefix-on-r1/receipt.json --prepared "$prepared" --older-prefix 1 --compress-debug --out build/gsim/monitor-fetch-prefix-on-v2-r1 --run
    python3 -B "$fixture/compare.py" build/gsim/monitor-fetch-prefix-off-v2-r1/receipt.json build/gsim/monitor-fetch-prefix-on-v2-r1/receipt.json --out build/gsim/monitor-fetch-prefix-comparison-v2-r1.json

Omit --run and use fresh output names for preflight only. No old executable is
modified: optional compression retains newly linked replay.uncompressed and
replay plus its strictly revalidated debug-compression.json proof.

Lightweight host checks: test_profile.py (fixed history, exact single-flag plan
and compile macros), test_compare.py (43 malformed exact-parser probes), and
test_compression.py (17 strict integration probes). Only fetch-prefix-pins.json
is active; copied older pin maps are inactive provenance. Runtime acceptance
still requires both complete original diagnostic positives and all negatives.
