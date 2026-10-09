# Current-profile LSU capacity experiment

This separate experiment starts from CPU/DMA integration commit
`66c06d786275dc28c099301162cd09e70497f6eb`. It does not change release defaults.
The explicit `--lsu-entries=4` selects four LSU owners; the default is two.

## Controlled comparison

Both sides use current selected RV64GC, physical-load ingress enabled, line-copy
DMA enabled with four line entries and zero yield, 32 KiB two-way I/D caches,
two data MSHRs/response entries/writeback entries, four DDR slots and two write
slots. Virtual precheck and prechecked flow remain disabled. Only `memoryEntries`
and dimensions derived from it change. A Scala equality test checks all other
`OooParams` fields, cache, DDR, storage, floating-point and network configuration.

Derived changes are two additional LSU instances, request arbitration and
completion arbitration width, backend request FIFO 2→4, LSU response-owner FIFO
2×1→4×2 bits, StoreBuffer physical-owner FIFO 3→5 bits, and forwarding/selection
metadata. StoreBuffer write entries and adapter ingress/checked/response queues
remain two. Native emitted-geometry checks establish these independently of the
profile name. Literal register counts are only a resource proxy; mapped area,
critical paths, routed 100 MHz timing and board results require separate proof.

The earlier measured five-cycle load residency gives a local two-owner supply
bound near 305.2 MiB/s at a nominal 100 MHz. Doubling capacity permits a higher
bound, but issue bandwidth, return ordering, cache misses and instruction mix may
prevent reaching it. Stores' serial head supply is a separate bottleneck.

## Reproducible tests

The passive four-slot ABI and host-only proof are documented in
[the owner fixture](../simulator/gsim/tests/mlp4_owner/README.md). Its negative
checks do not constitute an executed hardware result.

After configuring the repository's existing pinned tools, run:

```sh
python3 -B simulator/gsim/tests/mlp4_owner/run_host_tests.py
python3 -B -m unittest discover -s simulator/gsim -p test_cpu_mlp_bandwidth.py
mill -i IonSoC.test.testOnly ooo.FpgaNextConfigSpec ooo.PhysicalLoadIngressFlowSpec ooo.PrecheckedQueueFlowSpec
python3 -B simulator/gsim/cpu_mlp_bandwidth_board.py --tag fresh-capacity
```

The last runner builds both full models from identical sources and assembles one
shared six-case guest set. Both physical-ingress flags are enabled; it is an
LSU2/4 comparison, not an ingress-off/on experiment. It preserves complete-token,
request/permission, physical read-data and final backing oracles. Every raw
physical access and elapsed cycle remains counted, including any canceled
speculation. A guard access must meet the existing exact address/class and
cancellation/drain/nonretirement rules. Useful payload is never inflated by it.
The runner does not demand or invent a performance improvement.

Further representative cold/chase, Sv39/PMP/MMIO/atomic, independent architectural
and executed CPU plus active DMA checks must use the same new capacity pair.
Neither an old-profile four-owner result nor the two-owner integration receipt
qualifies this experiment. The bounded hot/ownership checkpoint below is complete;
the later bounded functional and native-resource extensions are recorded below;
physical timing and board gates remain pending.


## Bounded hot/ownership checkpoint (2026-10-09)

Production/model-input freeze: `f15faab7586cbae18bda4edfd17b94e7714a21e8`.
The corrected hot observer is in `160dfe0ac0a06f710f7846602371a9981a29dd13`;
retirement attribution is in `6009fe1bbf84cfbdea8b80435504aecd68701bc5`.
The latter commits change host qualification only and reuse the same exact RTL
objects. Nineteen focused Scala checks and the four-owner host proof pass. Both
fresh full board models pass the RV64GC smoke and its negative control.

The strengthened same-guest pair passes twelve executions, eighteen external
observation-corruption negatives, and twenty terminal-state acceptance mutations
per execution. Every run verifies zero observed/shadow LSU owners, no new start,
and all named data-path stages and held handshakes drained. The capacity guard is
checked on every nonreset cycle. Full-token generations, payload/authorization,
physical read data, precise canceled-owner drain and final backing remain checked.
An independent reviewer verified all source/model/guest/executable/log bindings.

| Case, four passes | LSU2 kernel cycles | LSU4 kernel cycles | LSU2 complete cycles | LSU4 complete cycles |
| --- | ---: | ---: | ---: | ---: |
| Read 4 KiB | 5189 | 4669 | 5775 | 5255 |
| Write 4 KiB | 9801 | 9801 | 12527 | 12526 |
| Copy 4 KiB | 14353 | 14337 | 17026 | 17011 |
| Read 8 KiB | 10313 | 9277 | 10899 | 9864 |
| Write 8 KiB | 19529 | 19529 | 24390 | 24390 |
| Copy 8 KiB | 28689 | 28673 | 33501 | 33484 |

At the nominal 100 MHz conversion, hot 8 KiB read payload bandwidth is
303.016→336.855 MiB/s (+11.17%), including completion/flush 286.724→316.809
MiB/s. Hot writes are unchanged; 8 KiB copy improves only 0.056% in its kernel.
All timed data accesses satisfy the all-hit check. Both read sizes use four live
LSU owners in the candidate, but useful loads retain exactly five-cycle residency
and one-cycle physical service. All six two-owner result/guest maps reproduce the
prior integration before the added terminal-mutation count.

The two-owner read cases each have four extra canceled one-past-source physical
reads (32 bytes); the four-owner cases have none. They remain in raw traffic and
elapsed cycles. The same useful work, ELF/binary, committed PC trace and load/store
counts are retained. No wrong-path latency is subtracted.

### Measured retirement bottleneck

A separate passive read-4-KiB replay uses existing, hash-bound generated scalars.
It checks the exact done-head commit equation, the recovery equation and the
prior-cycle accepted-load/order-check relation. Both original result and complete
performance/pipeline/distribution maps remain unchanged; four counter-corruption
negatives reject. The entire done-head/no-retirement bucket is attributed solely
to the registered load-order check hold: 1526 cycles with two owners, 2028 with
four. This is measured attribution, not a claim that all those cycles can be saved.

The load-order check protects already-issued younger reads when an older load's
address becomes available. It cannot be removed merely because a guest has no
stores. A separately authorized future older-prefix experiment must still block
the checked load and all younger instructions, retain precise pending-replay
recovery, and prove wrap/full-generation/two-lane/exception cases. That change is
not part of this checkpoint.

### Exact entry receipts and remaining gates

- Corrected hot pair: `build/gsim/cpu-mlp-bandwidth-board-r3/receipt.json`, SHA-256
  `210d38af93f5fb294f51a6f58ad6996ee022d35fa94186320881b53d949b54d3`.
- Retirement attribution: `build/gsim/cpu-mlp-retire-attribution-r1/receipt.json`,
  SHA-256 `6302a00c26b8c3407a8596f3b21dc11afe59586cda2d31bde2659b23cb91c34f`.
- Model LSU2 receipt: `a755f9a63cb1e6b2fcadb7b30df6b086a759fe6dcfe054bddbd090dd8a0c4a05`.
- Model LSU4 receipt: `cf51cbd7b41f21e09099f8e0031a4a69a5fae8f1fb6f6e26f1267f6b286d1df4`.

The initial r1 hot result is retained with its subsequently discovered missing
terminal/capacity-guard assertions. The r2 receipt records a host-only Clang
aggregate-construction failure before execution. The corrected r3 replays close
both oracle omissions and preserve all measured cycles.

The later representative, denied-data-PMP, active-copy-DMA and native resource
checks below extend this hot checkpoint. Independent NEMU architecture checks
also pass within their stated integer/physical scope. Mapped area, routed 100 MHz timing and physical board bandwidth
remain separate unperformed gates. No release default changes here.

For the passive attribution after a successful capacity pair:

```sh
python3 -B simulator/gsim/cpu_mlp_retire_attribution.py \
  --receipt build/gsim/cpu-mlp-bandwidth-board-fresh-capacity/receipt.json \
  --out build/gsim/cpu-mlp-retire-fresh
```

## Current-model representative and resource extension

The exact same full models pass ten representative executions and ten negative
controls, with source-built identical guests on each side. The virtual observer
retains its independent data/signature/trap/MMIO checks and current ownership
ledger; a generated copy changes only its passive LSU-peak sum to cover all four
slots. This gate does not extend the virtual checker to a complete ISA oracle.

| Region | LSU2 cycles | LSU4 cycles |
| --- | ---: | ---: |
| 64 KiB sequential read, three passes | 268971 | 249635 |
| 64 KiB write kernel | 344151 | 344151 |
| Write flush tail | 17754 | 17753 |
| 64 KiB copy kernel | 627214 | 627132 |
| Copy flush tail | 9215 | 9217 |
| Dependent chase, 3072 hops | 227973 | 227973 |
| Independent one-word-per-line, 3072 loads | 112706 | 108964 |
| Sv39 warm / cold / dependent chase | 4422 / 512 / 2311 | 4422 / 512 / 2311 |

Sequential-read useful payload is 192 KiB: 69.710→75.110 MiB/s at nominal
100 MHz, a 7.75% throughput improvement. Independent-line useful payload is only
24 KiB, despite the 64 KiB working set and approximately 192 KiB line traffic.
Its cycle count improves 3.32%. The steady driver uses whole-cycle boundaries;
Sv39 uses lane-exact retired-PC traces, which match along with its signature,
precise page fault and exactly one permitted UART LSR read. Fetch-PMP grant,
execute revoke/fault/restore and the existing RV64GC AMO/LR/SC/F/D anchors pass.

Ordinary sequential reads still use one occupied MSHR at a time on both sides;
there are zero dual-occupied cycles. The independent-line kernel reaches two
MSHRs, with dual-occupied cycles 100795→105862. Ordinary-stream prefetch sees
3021 candidates but zero allocations/useful hits on both sides. More LSU owners
improve request supply but do not by themselves fix next-line prefetch supply.

The separate actual-CPU denied-data-PMP pair passes six negatives, with identical
1989 cycles, 108 retired instructions and PC trace. S-mode and MPRV=S loads fault
precisely with cause 5 and no forbidden physical request. This does not qualify
denied stores/AMOs or exhaustive privilege behavior. The virtual and denied-PMP
fixtures check accepted physical/backend request-response queue drain; they do
not independently assert every live LSU slot, held handshake and adapter stage.
The stronger complete-owner terminal predicate belongs to corrected hot, its
NEMU replay, and the active-DMA fixture.

Actual CPU plus active four-line copy DMA passes both capacity configurations and
eight negatives. Both retire 36322 instructions and witness 1024 dirty-source
and 1024 dirty-destination accepted C beats, four DMA residents, scratch-memory
traffic during active descriptors, denied-AXI-read error plus clean restart, and
complete owner drain. CPU live-owner peaks are two versus four. Whole-fixture
cycles are 56021→55802; this polling-driven fixture is a functional concurrency
gate, not an isolated DMA or CPU throughput comparison. Packet DMA/MAC/CDC are
outside its scope.

Both native selected exports pass. The hierarchy-weighted literal declaration
proxy increases by 1096 scalar register bits and 370 array bits (1466 total), all
within IntegerBackend. Two extra LSU instances contribute 1070 scalar bits; the
backend request FIFO contributes 362 array bits. The remaining control and owner
queues account for the balance. All ten fixed native-memory contract groups are
identical. External ROM IP and three BUFGCE clock-primitive instances are excluded, with
identical wrappers and multiplicities checked. These are declaration counts, not mapped FF/LUT/BRAM or
100 MHz timing results.

Entry receipt SHA-256 values:

- Representative: `3b0a4c62829e76d08faffead2c3b156d4f3ca83450044e294e4696262a4cd37d`.
- Denied data PMP: `7595eb217214aee46047b23817c6d67c86949e39b2411a5f629c23eebf266687`.
- Active DMA LSU2: `1c5354f59cd9126ce779a36a20a7b54709b356a234cc0aff6c6881e350f36fda`.
- Active DMA LSU4: `43a1824e3813d9c99b1ab6990f6fe3aa0e478431d4bef633c7e0fea149ea50de`.
- Corrected native declaration proxy: `1e0c0f40714067b83b281af10dfecad678eccfb5775424c695b578768aa4be14`.

### Fresh extension commands

`HOT_RECEIPT` is the completed source-matched six-case capacity receipt from the
fresh command above. `MODEL2` and `MODEL4` are its explicit model receipt paths.
Use fresh output directories; no historical workspace path is a default.

```sh
python3 -B simulator/gsim/cpu_mlp_representative.py --execute \
  --hot-receipt "$HOT_RECEIPT" --out build/gsim/capacity-representative-fresh
python3 -B simulator/gsim/cpu_mlp_data_pmp.py \
  --lsu2-model-receipt "$MODEL2" --lsu4-model-receipt "$MODEL4" \
  --out build/gsim/capacity-pmp-fresh
python3 -B simulator/gsim/fixtures/cpu_dma_execute/build_guest.py \
  --out build/gsim/capacity-dma-guest-fresh
python3 -B simulator/gsim/fixtures/cpu_dma_execute/run_fixture.py \
  --model-receipt "$MODEL4" --physical-flow 1 --lsu-entries 4 \
  --guest build/gsim/capacity-dma-guest-fresh --out build/gsim/capacity-dma-lsu4-fresh
python3 -B fpga/next/export.py --output build/capacity-native-lsu4-fresh \
  --lsu-entries 4 --physical-load-ingress-flow --dma-line-transfers \
  --dma-line-entries 4 --emit
```

Repeat the last two capacity-specific commands with LSU2 and separate output
paths for a pair. The existing pinned toolchain must already be available; these
runners do not install it. The representative runner builds guests and links host
observers only; it never elaborates or compiles a hardware model.

## Independent architectural extension

All twelve same-guest LSU2/4 hot executions and six PC/GPR/final-memory corruption
negatives pass with the unchanged historical independent NEMU observer and
reference client. The new runner instruments the corrected current hot observer,
compiling against the current four-owner headers rather than archived two-owner
copies. It pins the 671-file existing reference cache, exact compiler, every
model/object and guest artifact, and rehashes prior run products. No reference
resynchronization or speculative-request stepping is permitted.

Totals are 123444 guest-PC checks, all 32 GPRs across 79362 retirement edges
(including 44082 dual-retire edges), 2540736 individual GPR comparisons including
boot, and 50332416 final RAM bytes. Every original hot result, performance,
pipeline and lifetime distribution remains exact. Per-instruction PCs are checked
individually; dual retirement has one post-entire-edge GPR comparison, not an
intermediate per-lane snapshot. This is physical integer M-mode guest coverage,
not CSR/FP/VM/active-DMA NEMU qualification.

NEMU receipt SHA-256 is
`bbbb9380180bda9c68feebbf4f88e0ca7b17d2d772998082c44500e0b079f0ee`;
independently reparsed summary is
`95b5db3e61515f5c9c4d8524cdfec0052fd2a75585f2a253797a7ce9b7d29063`.
The failed first NEMU extension is preserved: a host receipt step-name shadow
caused a log-lookup failure after its first successful architectural case.
The corrected fresh r2 passes all gates; an AST regression guards the bookkeeping
bug. No hardware or architectural-checker relaxation fixed it.

The first native census also remains archived. Independent review found it could
omit unsupported instance syntax and did not list the unchanged BUFGCE primitives.
The corrected r5 rejects unbound RTL, unsupported generate/conditional/array and
state-declaration forms, counts unindented instances, explicitly handles the
supported BUFGCE parameterization, and binds both tools and fixed-storage receipts.
It also recomputes both fixed-storage reports from the bound exports before
accepting supplied geometry. Twelve host tests pass; all frozen declaration deltas
remain exactly unchanged.

```sh
# REF_CACHE must be an existing cache matching the tracked reference manifest.
# Preflight is read-only; adding --run enables serial host links and simulations.
python3 -B simulator/gsim/cpu_mlp_board_nemu.py \
  --flow-receipt "$HOT_RECEIPT" --reference-cache "$REF_CACHE"
python3 -B simulator/gsim/cpu_mlp_board_nemu.py \
  --flow-receipt "$HOT_RECEIPT" --reference-cache "$REF_CACHE" \
  --out build/gsim/capacity-nemu-fresh --run
python3 -B fpga/next/lsu_capacity_census.py \
  --two "$NATIVE2" --four "$NATIVE4" \
  --two-storage "$STORAGE2" --four-storage "$STORAGE4" \
  --out build/capacity-native-proxy-fresh.json
```

`NATIVE2/4` are completed native export directories; `STORAGE2/4` are the matching
`native_storage_census.py` outputs. The NEMU cache is an explicit external pinned
dependency, not silently downloaded or installed by this runner. The representative
runner pins its compiler/binutils entry points and resulting guest bytes; unlike
the hot guest builder, it does not separately attest every GCC child executable.
Its pair uses identical frozen guests. Four-owner cancellation mutations in the
pure host fixture do not constitute a directed four-live-owner RTL cancellation
test. These bounded results do not replace exhaustive ISA or physical timing
qualification, and leave release defaults unchanged.
