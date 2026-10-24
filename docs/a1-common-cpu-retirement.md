# Bounded CommonA1 CPU retirement bench

## Contract and configuration

This bench instantiates the actual `CommonA1CpuTile`, not a decoded-input backend
or the `BoardSocGsim` factory. Instructions enter through the tile's physical
instruction TileLink manager interface. Commit/trap outputs and committed GPR
inspection come from the actual core; passive fetch/owner taps do not drive it.

All three variants use the fixed `CommonA1RebuildProfile.CombinedBranch` base:

| Variant | `fetchTransactionSlots` | `alignedFetchSinglePage` |
| --- | ---: | --- |
| `legacy` | 1 | false |
| `single-page` | 1 | true |
| `dual-slot` | 2 | true |

`legacy` is the fetch control on this **CombinedBranch/B2 backend base**, not the
old production A1 baseline. No variant is automatically promoted to a production
preset. The runner permits only `--base combined-branch` and checks that actual
config/core fields differ only by the two listed fetch controls, with identical
other fields and derived geometry.

Retained resources include two-wide rename/issue/completion/retirement,
ROB16/PRF48 with full 64-bit ROB tags, LSU4/SB2, DTLB16, two-way 32 KiB L1I and
32 KiB L1D, two cache read/response/writeback owners, the selected FPU, Sv39 and
16-entry PMP. The configured RAM aperture remains 2 GiB at `0x80200000`.
There is no board, shared Home/fabric, DDR controller, CDC or peripheral model.

Sources:

- `src/test/scala/platform/CommonA1CpuRetirementGsim.scala`
- `simulator/gsim/harness/a1_common_cpu_retirement.cpp`
- `simulator/gsim/a1_common_cpu_retirement.py`

## Guests and fixed service

Three raw 32-bit integer guests each run in ROM and RAM, for six cases:

- `independent_alu`: fixed-source ALU work, 482 architectural retirements.
- `dependent_chain`: serial ADDI/XORI dependencies, 481 retirements.
- `branches`: a bounded loop with taken/not-taken branches and an always-skipped
  wrong-path write, 452 retirements.

ROM guests start at reset PC `0x80000000`. RAM guests start with the same two ROM
bootstrap words, `0x00200f97` / `0x000f8067` (AUIPC/JALR), then enter
`0x80200000`. Their checked full streams include two additional retirements.
Each ends in EBREAK; EBREAK raises the terminal trap and is not counted as a
retirement. There are no data-memory, floating-point or VM-configuration guest
operations. Each case uses a fresh reset/model instance, not warmed state from
another case. One compiled model executable is reused across all six cases.

The host provides immutable instruction bytes in 128 KiB ROM and 128 KiB RAM
instruction windows; unused words are known NOPs for speculative fetch. This
bounded host image does not reduce the tile's configured RAM/cache geometry.
The bytes, bootstrap, service law and zero-initialized oracle state are identical
across variants; there is no PRNG or seed and no profile-dependent host define.

The physical manager accepts only legal Get requests of size 2, 3 or 6 (4-byte,
8-byte or 64-byte transfers), with aligned addresses and the matching byte mask.
A is ready while fewer than 16 transactions are pending. Accepted requests enter
a FIFO and become reply-eligible at acceptance cycle + 3. Older replies and DUT
backpressure may delay service further. D supplies one 64-bit AccessAckData beat
per cycle when eligible; a 64-byte line requires eight beats. A live source
cannot be reused until its last D beat transfers. Held replies remain stable.
There is no randomized A/D throttling and no artificial fetch/commit throttling
during work. This is a deterministic test manager, not a real ROM/DDR timing model.

Coherent A/C/E traffic is forbidden and asserted; B/D and whole-line grants are
legally inactive. Scalar memory operations are also forbidden. The real terminal
trap creates one reservation-clear request on scalar lane 1; the host accepts its
actual owner, returns that same owner and clear kind after the fixed latency,
and checks exactly one request/completion. It never substitutes a dummy data
response for a memory operation. Lane 0 has no clear capability.

## Cycle and acceptance accounting

- `work_cycles`: first cycle after reset release through the accepted terminal
  trap cycle, inclusive. The two reset steps are excluded.
- `bootstrap_cycles`: RAM work through the cycle retiring the final bootstrap
  instruction. It is zero for ROM.
- `roi_cycles`: cycles after the final bootstrap retirement through the trap;
  all work cycles for ROM. Thus work = bootstrap + ROI.
- `drain_cycles`: subsequent cycles until four consecutive fully drained
  observations. Accepted TL/scalar obligations, frontend/private/cache owners,
  backend execution owners and ROB occupancy must all be drained.
- `inspection_cycles`: the subsequent 32 GPR-inspection cycles. They must not
  reopen an owner or change architectural/service state.

`work_ipc` uses all retired instructions including RAM bootstrap over work cycles;
`roi_ipc` excludes the two bootstrap retirements and uses ROI cycles. A branch
boundary may divide phases differently from a cold ROM start, so compare only
matching guest **and placement**, not ROM against RAM as equivalent warm starts.

Accepted instructions, virtual fetch packets, physical cache-fetch packets,
external TL requests/beats and dual-commit cycles are separate observations.
Work-window counters exclude drain/inspection; `all_tl_requests` and
`all_tl_beats` also cover the drain. Speculative accepted instructions/fetches
need not equal architectural retirement counts. ROI acceptance counters use the
same cycle-phase boundary as ROI, not instruction-PC attribution.

The host leaves `hold=false` until the trap is observed and checked. `hold` also
disables `commitEnable`, so it must not be asserted early merely because EBREAK
has been fetched. After trap acceptance, already-started rollback and return/clear
service continue while new fetch/retirement is held. Work plus drain has a hard
30,000-cycle limit per case, followed only by the 32 inspection cycles.

## Independent checks and their limits

The unchanged `isa_model.h` executes raw guest bytes completely **before the DUT
instance is constructed**. No DUT result, redirect, decoded instruction or prior
RTL model supplies expected semantics. Every retirement checks PC, raw
instruction, integer destination/write-enable, architectural write data and next
PC. Non-writing completion payload data is unspecified. Full ROB tokens must not
retire twice. The final trap must have cause 3, the exact EBREAK PC and `tval=PC`;
all 32 final GPRs must match the independent execution.

An independent manager ledger learns accepted A requests, checks source lifetime,
metadata, byte/beat contents, earliest reply time, held A/D stability and final
request/completion conservation. Its owner state is separate from the service
queue.

Two required negative controls reuse each compiled model:

- `--inject-retirement-data`: corrupts sampled retirement write data; the
  independent checker must reject at `A1_RETIREMENT_NEGATIVE_REACHED`.
- `--inject-manager-source`: corrupts the sampled offered D source; the
  independent manager ledger must reject an unowned source at
  `A1_MANAGER_NEGATIVE_REACHED`.

These are checker-sensitivity tests on sampled observations, not mutated RTL
implementations or exhaustive fault coverage. The software-only oracle mode also
exercises both rejection paths, but cannot establish actual DUT behavior.

## Reproduction and evidence

From the repository root, use the already prepared pinned toolchain. In the
current validation workspace it is selected with:

```sh
source /workspace/shared/valence-a1-toolchain-r1/env.sh
python3 simulator/gsim/a1_common_cpu_retirement.py
python3 simulator/gsim/a1_common_cpu_retirement.py --oracle-only --tag a1-common-oracle-FRESH
# Only after the shared source freeze and authorization for the bounded run:
python3 simulator/gsim/a1_common_cpu_retirement.py --build-run --tag a1-common-tile-FRESH
```

Replace `FRESH` with an unused evidence label. Existing output directories are
rejected. Default invocation is preflight only. Oracle-only compiles no hardware;
`--build-run` elaborates/builds exactly one model per variant and runs six cases
plus two negatives on each. It does not install tools, invoke Verilator, run
Linux or launch a full regression. The default host-invocation timeout is 300
seconds (`--timeout 180` is also supported).

Evidence is written under `build/gsim/<tag>/`: per-variant logs, actual
`effective-config.json`, `effective-parameters.json`, `effective-geometry.json`,
FIR/model artifacts and `receipt.json`. The receipt binds source inputs,
compiler/tool state, host/model/artifact hashes, results and all three pairwise
per-case cycle deltas. Source/tool drift fails the receipt; do not silently patch
or reuse a failed run as a clean one. Preserve failed receipts and document any
separately authorized model-reuse continuation with its new host/input hashes.

## Recorded qualification: 2026-10-24

`build/gsim/a2-common-cpu-retirement-20261024-r2/receipt.json` records
`PASS_BOUNDED_COMMON_A1_CPU_RETIREMENT`: all three profiles completed six guests
(18 case executions), with both sampled negative controls rejected per profile
(six rejections). The positive logs agree with the receipt and expected
architectural retirement counts; each case completed exactly one trap-clear
request/reply and all 32 GPR inspections. Source/tool manifests remained unchanged
through this recorded run. This is bounded architectural/checker qualification,
not a general performance claim; per-case cycle comparisons remain in the receipt.

The preserved `build/gsim/a2-common-cpu-retirement-20261024-r1/receipt.json` records
the earlier host compile failure: three C++ model-type references omitted GSIM's
`S` prefix. Only those three identifiers were corrected. The r2 continuation
reused and relinked the existing legacy model; its generated FIR/header/C++ files
are byte-identical to r1, rather than a silently rebuilt DUT. The two remaining
profiles were then built and all three completed. The corrected host SHA256 is
`f5091b10dbae4ccf6ccc7d58fdf811cc82dfdd1e43ae0e14c3a9c0f4403a8107`.

In **every one of the six dual-slot cases**, total external TL requests and total
D beats are 1–2 higher than the matching single-slot controls, including drain.
Thus identical program bytes and service laws do **not** mean identical external
transaction traces. Do not infer an across-the-board bus-efficiency improvement
or hide the additional traffic by reporting only the work window.

Passing this bench qualifies only these bounded M-mode/Bare integer streams under
this service law. Retaining VM/PMP/FPU hardware does not qualify its semantics.
Board/CDC, coherence/data-memory behavior, ISA compliance, general workloads, PPA,
routed timing and MHz/Fmax remain outside this bench's claim.
