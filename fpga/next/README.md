# Valence FPGA-next

An independent FPGA-first RV64GC SoC integration. The selected v2 profile combines
explicit RAM payloads/ports, shared floating-point arithmetic and shorter control
cones at the same architectural capacity. The original repository checkout and
remote `main` are not the implementation workspace.

## Recommended performance preset

The recommended `posted-performance-v1` preset enables physical posted-store
merging with the exact qualified DMA4/LSU4/D16 selected profile. Original Bare
WRITE throughput improves 91.23%; COPY throughput falls about 15.25% (17.9973%
more cycles). This recommendation accepts that measured tradeoff.

```sh
python3 -B fpga/next/performance.py --output build/fpga-next/performance-on --emit
python3 -B fpga/next/performance.py --output build/fpga-next/performance-off --disable-posted --emit
```

Omit `--emit` for a complete preflight. Hardware overrides are rejected; the
second command changes only posted merging. Generic defaults remain unchanged.
See the [measurements, costs and scope](../../docs/posted-store-seal-performance.md)
and [preset qualification](../../docs/posted-performance-preset.md). Posted/PF
coexistence, translated-response flow and prechecked request flow remain OFF.

## Fixed contract

One RV64GC hart; two-wide issue/commit; 16 ROB entries; 48 integer physical
registers; two LSU owners; 32 KiB two-way instruction/data caches; 100 MHz CPU;
2 GiB DDR at `[0x80200000, 0x100200000)`; UART 460800 baud. The DDR bridge retains
four shared slots, two write owners and sixteen-beat bursts. MMIO/interrupt and
DMA descriptor layouts remain compatible except explicitly capability-gated
media extensions. No ISA subset, cache-capacity reduction or relaxed timing
constraint is used to create a resource improvement.

## Build the selected project

Reuse the approved existing tool cache; generated models belong to this checkout.

```bash
export VALENCE_CLOUD_ENV=/path/to/verified/Valence/simulator/build/cloud-env
export VALENCE_GSIM_SOURCE=/path/to/verified/Valence/simulator/build/gsim-src
source scripts/cloud/env.sh
python3 -B simulator/gsim/fpga_next_board.py --tag selected-v2 --variant selected
python3 -B fpga/next/export.py --output build/fpga-next/selected-rtl --emit
```

The native exporter and `FpgaNextSocTop` default to `FpgaNextConfig.Selected`.
`--storage-candidate` on the exporter / `--variant candidate` on the board runner
select the earlier storage-only control. `--reference` / `--variant reference`
select a register-topology control with common correctness fixes. The immutable
historical baseline is its recorded Git revision, not a label on a newer build.

Use fresh output directories. `--resume` is allowed only for identical frozen
inputs/profile and revalidates recorded artifacts before reuse. Do not substitute
Verilator or treat GSIM as an independently clocked native PHY/TAP simulator.

## Architecture changes

| Block | Selected change | Measured scope |
|---|---|---|
| Issue queue | Six immutable fields in explicit parity RAM; small owner/ready state stays local | Independent read/write/collision/reset oracle; four-way core NEMU counters and load timing equal |
| Protected completion | Shares already-read head PC/raw/expanded instruction under full-token lifetime assertions | Per-bank read ports 8→7, 4→3, 2→1; numeric/precise-memory/recovery equality |
| Fetch hints | Two writer-owned 32×162 banks with owner/valid state | Arbitrary same-parity writes, lane collision priority, full-PC/instruction matching |
| FP state | Unreset 32×64 memory plus 32 validity bits and committed forwarding | Native three reads/one write; independent context/reset/flush proof |
| FP execution | Shared format rounders and common multiply/FMA products | Eight→two arithmetic rounders, four→two products; exact SoftFloat results/latencies and cancellation |
| I/D tags | Per-way 256×19 tag RAM | Native I 1R/1W, D 2R/1W; crossing-4GiB, probes, dirty releases and seeded backing oracles |
| I-cache data | Eight 512×64 banks instead of two 256×512 ways | Same 262144 bits, one read/one write per bank, one-cycle hit and II1 |
| I-cache held hits | Captures first stalled hit into the existing reply register | Fixes inherited undefined SRAM-output contract; cross-set stalls, prefetch/invalidate, reset and negatives |
| Frontend capture | Removes late invalidate from payload enables; validity and stale-owner checks remain | Native 32 payload enable groups lose the dependency; behavior unchanged |
| Issue readiness | Uses existing exact owner mirrors while retaining wake promises | Native global-ready indexed selects 33→1, same register declarations; NEMU/ownership equality |
| Fetch PMP | Shares high address relations, preserving first overlap, full width and wrap semantics | Exhaustive reduced-width and directed/random full-width oracles; real priority/wrap source mutants reject |

These are structural counts and cycle measurements. They are not mapped FPGA LUT,
BRAM, DSP or frequency results. In particular, asynchronous issue RAM ports may
require physical replication. Final native census and source-matched physical
implementation are separate gates.

## Performance and choices

Selected-v2 at `b4e0e1b7dffa5f46ad7158449ac0ffe72013de8a` passes the full board
suite and preserves all four raw workload logs of corrected ControlCandidate: RV64GC context 33411 cycles, six steady DDR regions
3183262 total, independent-line guest 522116 total, Sv39 context 13676 total.
The independent-line ROI takes 114346 cycles and uses both MSHRs; the ordinary
stream loops issue several words from one line and do not establish dual demand
miss occupancy. These figures use a controlled host DDR model, not a physical
memory-bandwidth measurement.

The inherited optional virtual-load precheck is requalified on the latest
Selected profile with identical source inputs. It changes the warm independent
Sv39 ROI 4422→1809 cycles, cold 512→538, and leaves the dependent chase 2311
unchanged. See the [matched optional-profile proof](evidence/precheck-requalified-selected-32775e2.json).
Passive timing shows warm gain comes from issue spacing 8/13→3/4 cycles, while
post-start load latency remains 7 cycles. The extra cold cost is 25 cycles of less
instruction-refill overlap plus one service cycle. It stays explicit:
`--virtual-ram-load-precheck`. A separate directed guest proves physical accept
before cancellation and later drain without a result/retirement; its token/data/
zombie-result mutations reject. It is coverage, not a throughput benchmark.

The exploratory cache completion/merge/store overlap flags are not selected.
Short directed examples improve 1.6–2.1%, but longer mixed traces regress in some
seeds and worsen aggregate cycles by 0.149%. Earlier acceptance also changes queue
residence distributions. Extra response credits were not justified by measured
backpressure in the CPU warm workloads.

## Read-oriented prefetch option

`--prefetch-candidate-cycles 3` retains an already authorized next-line token for
up to three allocation attempts, only while victim capture/send is the sole
blocker. It cancels on demand/protection/ownership exclusions or its deadline.
The default remains one attempt. Cache/MSHR/response/DDR capacities are identical.
The [paired board/native evidence](evidence/prefetch-retention-71dae69.json) binds both variants.

| Same guest region | One attempt | Three attempts | Cycle change |
|---|---:|---:|---:|
| 64 KiB sequential read, three passes | 279718 | 181647 | −35.06% |
| Copy kernel | 641791 | 644683 | +0.45% |
| Write kernel | 344151 | 344151 | unchanged |
| Dependent chase | 231188 | 231188 | unchanged |
| Independent-line read | 114346 | 114346 | unchanged |

The sequential-read region follows one complete traversal outside the timing
markers. Its working set is twice the 32 KiB cache capacity; it is not a cold-only
or all-hit microbenchmark. Read-region AXI requests fall 3075→2334; copy requests
rise 6149→6402. Those counts include instruction traffic. The gain therefore
includes changed residency/external traffic as well as overlap. The copy workload
exposes unused speculation, so this remains an explicit workload choice.

Existing tracked-consumption events are 2244 in the retained read region and zero
in copy, with 252 copy prefetch allocations. This event alone does not prove an
immediately available hit: a demand may have waited for that prefetch, and the
inherited event does not itself check resident-hit status on an invalidation edge.
The independent data, cycle, miss and traffic checks are the decision evidence.
Native output adds a two-bit countdown and combinational retention logic; no
mapped LUT/FF/frequency result is claimed. The [passive token/address proof](../../docs/fpga-prefetch-board-attribution.md)
checks 49152 ordered source-load values per model. Each read pass reuses the same
246 lines that were resident in way 1 before timing, explaining exactly 738 fewer
source-line reads across three passes; the other three fewer ROI requests are
outside the source range. The 2244 consumed tokens cover 748 unique addresses.
Of those tokens, 2202 are consumed one cycle after fill and 42 after 32 cycles; this
is fill-to-consumption timing, not a measured fraction of fully hidden misses.
All 252 unused copy tokens (250 addresses) are evicted by the exact conflicting
destination store. The existing first-clean-way policy and LRU insertion remain
unchanged; retention makes that behavior active in this workload.

```bash
python3 -B simulator/gsim/fpga_next_board.py --tag read-oriented --variant selected --prefetch-candidate-cycles 3
python3 -B fpga/next/export.py --output build/fpga-next/read-oriented-rtl --prefetch-candidate-cycles 3 --emit
```

Sixteen attempts are a module-qualified experiment, covering longer dirty victim
bursts. They have not received the selected-board performance comparison and are
not recommended from the three-attempt result. Retention can extend prefetch busy
and context-drain time; its deadline bounds only an unallocated token, not an
accepted memory transaction under arbitrary external backpressure.

## Final policy comparison

Each table cell is **host ROI cycles / accepted AXI read requests**. The
[source-bound scorecard](evidence/prefetch-policy-scorecard.json) also preserves
exact AR/AW requested bytes, AW counts, accepted R/W beats, retired counts and
prefetch events. These are controlled DDR-model measurements, including possible
non-source traffic and transactions split by ROI markers.

| Region | Default 1 | Retain 3 | Retain 3 + clear on store |
|---|---:|---:|---:|
| Sequential read | 279,718 / 3,075 | 181,647 / 2,334 | 181,647 / 2,334 |
| Write kernel | 344,151 / 3,076 | 344,151 / 3,076 | 344,151 / 3,076 |
| Write flush | 17,754 / 2 | 17,756 / 2 | 17,756 / 2 |
| Copy kernel | 641,791 / 6,149 | 644,683 / 6,402 | 641,855 / 6,150 |
| Copy flush | 9,217 / 2 | 9,215 / 2 | 9,042 / 2 |
| Dependent chase | 231,188 / 3,074 | 231,188 / 3,074 | 231,191 / 3,074 |
| Independent lines | 114,346 / 3,073 | 114,346 / 3,073 | 114,346 / 3,073 |
| Mixed: store every 16 lines | 306,585 / 3,081 | 189,016 / 2,343 | 195,765 / 2,414 |
| Mixed: store every 64 lines | 305,577 / 3,081 | 188,611 / 2,343 | 188,971 / 2,343 |

The selected default remains one attempt with history clear disabled. Three
attempts are an explicit read-oriented choice. Adding `--prefetch-break-on-store`
removes the measured copy speculation, but costs 3.57%/0.19% cycles relative to
three attempts in the two mixed workloads. It remains opt-in. Both mixed kernels
execute exactly 24576 source loads and 192/48 scratch stores; every intermediate
store's address/value/size/mask is checked, including overwritten-store mutations.
There is no workload-independent winning policy or new physical-bandwidth claim.
Mixed scratch writeback occurs after the timed kernel, so zero in-ROI AXI writes
does not mean zero executed stores or zero total write traffic. Kernel and flush
rows are separate marker intervals; their simple sum omits intervening overhead.

The [matched store-policy proof](evidence/store-history-integrated-543daf3.json)
checks six guests per variant. The [default mixed baseline](evidence/retention1-mixed-baseline.json)
reuses its exact qualified model with the same new guest bytes and host oracle.
The native default/read/copy labels identify prefetch policies; all three
comparison exports enable experimental tri-speed media. The
[final native comparison](evidence/final-native-policy-comparison.json) shows
byte-identical default/read RTL versus earlier qualified exports; store-history
clear changes only the data-cache module and adds no register or memory capacity.

```bash
python3 -B simulator/gsim/fpga_next_board.py --tag copy-policy --variant selected --prefetch-candidate-cycles 3 --prefetch-break-on-store --mixed-store-stream
python3 -B fpga/next/export.py --output build/fpga-next/copy-policy-rtl --prefetch-candidate-cycles 3 --prefetch-break-on-store --emit
```

## Tri-speed Ethernet option

`--experimental-trispeed-ethernet` selects hardware-managed full-duplex
10/100/1000 media and two TX frame banks. It preserves the native DMA ABI with
capability/version-gated status/counters and CAP-aware firmware/Linux ownership.
The driver exposes supported diagnostics through ethtool; reserved registers are
not read on unsupported capability combinations.

The production-DMA model with four posted descriptors measures steady frame-start
intervals 115→84 cycles for 60-byte bodies, 2297→1538 for 1514 bytes, and 3096→2072 for
2048 bytes, with the same read traffic and memory credits. The packet RAM grows
512×32→1024×32 with one synchronous read and one write. These are single-clock
protocol/model results, not on-board IP/TFTP goodput.

`soc_top_fpga_next_ddr.sv` is the prepared native wrapper. TX logic uses continuous
125 MHz, with a phase-related 250 MHz pad serializer for a fixed ideal 2 ns skew.
Recovered RXC uses direct IBUF/BUFG at 125/25/2.5 MHz; the old fixed 125 MHz RX MMCM
is unsuitable for slower rates. The autonomous PHY manager is the sole MDIO
configuration writer. Completed RX/DMA ownership remains in fixed-clock domains
when recovered RXC disappears. Native reset/CDC/pad simulation, per-rate both-edge
setup/hold, routing and board qualification remain separate pending gates.

The [native integration recipe](../../docs/fpga-next/native-media-integration.md)
now stages that wrapper whenever tri-speed is explicitly enabled, freezes its
pad/clock/reset/constraint dependencies, and separates the unchanged carrier
pins from the legacy fixed-1G clock constraints. `board-synthesis-files.f` and
`board/trispeed-integration.json` describe the extra native inputs. The optional
BSCAN USER2 combination retains its separate mandatory chain-allocation gate.
The three-rate scoped timing/packet-CDC recipe is prepared, not a mapped or
routed result; complete board/control/reset/JTAG constraints still need review.

## Debug reservation

`FpgaNextSocTop` reserves TCK/TMS/TDI/TRST, TDO/output-enable and independent debug
POR. Disabled transport emits tied outputs and no TAP/CDC state. The experimental
`--experimental-jtag-stub` has a fail-only DMI endpoint, not an architectural DM;
there is no halt/step/register access claim. No board pin mapping is invented.
Native TAP/CDC tests remain pending; a future DM integration requires separate
qualification.

## Evidence and remaining signoff

The [final qualification manifest](evidence/final-qualification.json) is the entry
point for current source, profile choices and source-bound receipts. The selected
default remains conservative; optional combinations beyond the recorded scopes
need their own qualification. The exact all-default legacy-media top also passes
RTL export and the selected storage census; it is bound separately from the
tri-speed policy exports.

[Selected-v2 qualification](evidence/selected-v2-b4e0e1b.json) binds board, native
and selected FP CPU results. The FP CPU fixture separately checks 1212 numerical
cases, 61865 commits and precise 57-trap memory seeds with its explicit 4 KiB test
aperture. Current native geometry confirms the differential ports above.
The [address-refined selected source](evidence/selected-address-54bcc75.json) at
`54bcc7508a0f0dd05fd6004d96f4f6649fb4da0b` also passes identical board logs; only
its native InstructionLineCache module differs. Late invalidate and aperture qualifiers are
removed from the RAM address expression; all read-enable permission and
invalidation guards remain.

`module-matrix.json` indexes per-module scope and remaining gates. Checked-in
`evidence/` contains compact source/receipt bindings; generated C++/RTL binaries
and long logs remain under ignored `build/` or the handoff archive. Negative
controls and failed/insufficient attempts are retained. A separate
[fixed one-million-tick firmware prefix](evidence/firmware-prefix-1m.json) preserves
579223 identical retirements and the complete cycle/lane/PC trace, 36 firmware-range
allowed cause 2 traps, backing memory and monitor sentinel. It produces no UART
banner or U-Boot-range retirement and is not a complete U-Boot boot result. Original immutable
sources: dev `ea5406ea15d2d0797ce2c5ef7a4951827c55145e`, hardware
`3cb4298532ba28c732e7f88cef45cc9697eb7fa2`; NaxRiscv reference
`9f452d50560d02fb391bc8039f5453c54e0911af`.

No new FPGA implementation, bitstream or board result is implied by these cloud
proofs. The physical target remains the same 100 MHz constraint and must pass
both setup and hold without broad timing exceptions. NaxRiscv's published small
integer-core area is not comparable to this full RV64GC SoC. The useful design
principles are explicit memory ports, small owner state and registered ownership
boundaries, not substituting another core's benchmark numbers.

### Rebuilding versus replaying archived artifacts

This is a source-only delivery. Absolute paths inside immutable evidence JSON
identify the historical environment and remain unchanged for provenance. They
are not downloads or locations expected on another machine. Generated models,
executables, firmware images and long logs are excluded from Git. Use the source
runners to rebuild, or obtain the separately preserved artifact archive to
replay a particular frozen executable and verify its recorded hashes.

The selected FP composition runner accepts explicit `--qualified` (protected-head
behavior) and `--fpu-qualified` (independent vector) directories. A fresh source
build needs the externally supplied official SoftFloat archive at pinned revision
`a0c6494cdc11865811dec815d5c0049fba9d82a8`; the runner verifies SHA256
`90493f9ad6c9760b2b1ca91251b8e7a3bb616b2935808d243e158a432a514f98`.
After loading the tool environment above, run this chain with unused tags:

```bash
export SOFTFLOAT_ARCHIVE=/path/to/pinned/softfloat-source.zip
python3 -B simulator/gsim/floating_point_resources.py --tag fresh-vectors --cpu --memory
python3 -B simulator/gsim/protected_head_payload.py --tag fresh-protected-head --vectors-root build/gsim/fpga-fpu-fresh-vectors --build-run
python3 -B simulator/gsim/selected_fp_cpu.py --tag fresh-selected-fp --qualified build/gsim/fresh-protected-head --fpu-qualified build/gsim/fpga-fpu-fresh-vectors --build-run
```

The `--memory` prerequisite generates `memory-vectors.txt` alongside the numerical
vectors. This chain rebuilds models from tracked source; no historical model or
vector archive is required. Complete archived files may instead be restored for
an explicitly requested frozen replay. The runner binds the actual vector files in the supplied
directory to the immutable vector hashes and corresponding FPU receipt, so the
archive may be relocated without trusting or accessing its old absolute paths.
Compact checked-in JSON alone is not a substitute for those vector/model files.

The runners have different prerequisites:

- `fpga_next_board.py` rebuilds the current board model and all four guests from
  tracked sources. `rob_ledger_qualification.py` also builds its paired models.
- `issue_frontend_storage.py --phase core` needs an explicitly built pinned NEMU
  reference and its receipt. This is an independent ISA reference, not a saved
  DUT executable.
- `floating_point_mixed_stream.py` and `floating_point_iterative_cancel.py` consume
  models produced by `floating_point_resources.py`; preserve their receipt and
  generated output layout when running these follow-on checks.
- `issue_independent_board_baseline.py` and
  `protected_head_contract_recheck.py` and `prefetch_board_ledger.py` with its
  `prefetch_board_ledger_report.py` reducer are historical replay helpers with exact
  prior-receipt/model contracts. Use the current board and protected-head runners
  for a new source build.
- `fpga_next_firmware_replay.py`, `fpga_next_firmware_prefix.py` and
  `compare_firmware_prefix.py` require the separately preserved, hash-pinned
  OpenSBI/U-Boot image and ELF plus a compatible qualified board model. That exact
  image is not reproducible from this source-only tree alone; it is an optional
  archived workload, not a prerequisite for the four-guest board suite.

The historical board source inventory omitted the directly included
`fpga/firmware/ddr_bench.c`. Its unchanged baseline content and exact rebuilt
steady/independent guest binaries are bound by the
[dependency closure supplement](evidence/guest-dependency-closure.json).
Old receipts remain immutable; future board runs inventory this included source
explicitly. This correction does not change the executed guest or DUT.

Published source history may be squashed. Intermediate commit IDs in immutable
receipts identify the original test checkouts; they are not promises that those
Git objects exist on the public branch. Exact archived replays need their original
source/artifact layout and, where a helper requires it, the original Git objects.
Fresh board/module runners rebuild the current source without those DUT archives.
