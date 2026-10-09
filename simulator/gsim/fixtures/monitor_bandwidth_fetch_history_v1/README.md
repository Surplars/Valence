# Original monitor ELF, fetch-history OFF/ON

This source-only successor of the qualified LSU4 observer reuses the unchanged
archived GCC 14.2 monitor diagnostic ELF and the exact V1 static-r1 launcher and
manifest in the sibling Valence-cpu-retire-prefix-next checkout. It is not an
exact-board GCC 13.2 reproduction. No benchmark or guest code is recompiled.

Production anchor: 2288c7f008e9d6440e8a28e339da28152b54892a. Both cached models
use LSU4, physical ingress ON, DMA line4/yield0, prechecked flow OFF and older
prefix OFF. Only fetch_previous_packet changes. Host/document commits may advance
HEAD only while the complete src/main committed tree, working contents and file
set remain identical to the production anchor. The complete model inventory,
artifacts, exact plan, tools, original source/archive mapping, prepared guest,
fixture and validator helper are independently hash-bound.

The unchanged data oracle, full-token ownership/cancellation, UART, 18 rdtime
markers, complete raw positive traffic and final return/full drain checks remain.
The strict comparator incorporates the measured-ELF initial-sum provenance rule:
ADDI x14,x0,0 at 0xfff787cc (0x00000713) allocates a nonzero physical destination;
the first scalar ADD must join that exact external full-token producer. The
original V2 observer, comparator and receipts remain untouched.

## Passive frontend evidence

Every cycle of the original hot interval is retained and joined to accepted
full-token allocations, including cancelled owners. Primary snapshot presence is
separate from effective packet0 validity. ON additionally records the raw saved
payload, both fault fields, full aligned key, context and present flag, and checks
that each cycle equals the previous cycle's primary row zero. OFF compiles out
all history field references and requires zero history columns.

Generated names were checked against both wholeboard headers, FIR and C++:
RegisteredFetchWindow.scala:72-81 maps historyContents to history_1's flattened
data/accessFaults/pageFaults fields, key to history_2, context to history_3 and
present to history_4. The effective packet0 wire is optimized locally; the exposed
alignment$_candidates_c_present_T_3 is exactly p & (short | p), therefore p,
where p is packet0.valid. Both generated variants preserve this equivalence.
The parser independently reconstructs full key/context matching, invalidation,
history continuity and primary/effective/backedge counters. No hypothesized
performance gain or causal explanation is asserted as an expected result.

## Run from the fetch-history checkout

Use the installed clang++-19 spelling, not its resolved clang symlink. The parent
owns CPU-heavy link/run admission; --run is explicit. Without --run these commands
produce fresh preflight receipts only. --compress-debug retains both new host
executables and checks loaded bytes, program headers, non-debug sections, symbols,
decompressed DWARF and main addr2line via the shared source-bound helper.

    source ../Valence/scripts/cloud/env.sh
    export GSIM_CXX=/workspace/scratch/41e4a649bb60/Valence/simulator/build/cloud-env/sysroot/usr/bin/clang++-19
    fixture=simulator/gsim/fixtures/monitor_bandwidth_fetch_history_v1
    prepared=../Valence-cpu-retire-prefix-next/simulator/gsim/fixtures/monitor_bandwidth_replay/static-r1
    python3 -B "$fixture/run_replay.py" --model-repo . --model-receipt build/gsim/fpga-next-board-cpu-fetch-history-off-r1/receipt.json --prepared "$prepared" --fetch-previous-packet 0 --compress-debug --out build/gsim/monitor-fetch-history-off-v1-r1 --run
    python3 -B "$fixture/run_replay.py" --model-repo . --model-receipt build/gsim/fpga-next-board-cpu-fetch-history-on-r1/receipt.json --prepared "$prepared" --fetch-previous-packet 1 --compress-debug --out build/gsim/monitor-fetch-history-on-v1-r1 --run
    python3 -B "$fixture/compare.py" build/gsim/monitor-fetch-history-off-v1-r1/receipt.json build/gsim/monitor-fetch-history-on-v1-r1/receipt.json --out build/gsim/monitor-fetch-history-comparison-v1-r1.json

Lightweight checks: test_compare.py exercises the exact strict parser with OFF/ON
synthetic timelines and malformed-data probes; test_compression.py exercises
compression inventory/proof integration without linking. Generated-header
-fsyntax-only checks are distinct from model execution. Copied v2-pins.json is
inactive provenance; fetch-history-pins.json is the only active model pin map.
