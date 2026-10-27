# A1 guarded natural-aligned data PMP

Status: bounded functional and matched unsited resource checks passed. Candidate
remains **default off**; no profile/default promotion. Full-CPU depth is blocked;
no STA, Fmax, routed timing or board qualification is claimed. The separate
factored generic comparator remains a rejected-for-promotion experiment.

## Explicit contract and scope

`guardedNaturalDataPmp` is default false. The only new named recipe is
`full-r1-m3-checked-flow-store-row-elastic-proof-guarded-natural-pmp`, derived
from the old elastic high-throughput control by this flag alone. Every old
profile, public default and platform selection remains unchanged. It excludes
registered raw translation, generic range factoring, physical ingress, frozen
proof/posted shortcuts and delayed canonical publication.

The main legacy DTA checker reuses existing `naturalAlignedAccess = true` with
`sharedAlignedBounds = false`. No second checker, storage, owner, capacity or
pipeline edge is added. The existing checked register, raw-hit/certified/identity
routes, response ownership and drain rules remain. The separate next-line PMP
checker is unchanged and still checks the entire READ line independently.

Native `DataRequest.size` has two bits, hence sizes 0..3 (one to eight bytes).
The main checker's address input alone clears the size-selected low address bits
unconditionally. This ensures its assertion holds even for idle, stale or
malformed descriptors. The real request address, size, mask, data, owner,
original virtual address and page-fault bit are never normalized or rewritten.

Normalization alone would be unsafe. The new mode computes an alignment guard
from the original request selected into checked storage. It ORs the guard into
checked fault **after** identity/physical-ingress fault bypass selection. It also
ORs that guard after next-line fault bypass and explicitly clears the captured
hint for malformed requests, including deferred-hint modes. The resulting fault
placeholder retains ordered reply/drain ownership but cannot issue a physical
request or produce a canonical store certificate. Existing permission, epoch,
RAM interval, atomic and certified mask/form checks are not removed.

## Deliberate standalone behavior difference

Tested legal aligned standalone requests retain exact existing results and
latency. Misaligned raw standalone requests are newly rejected with an access
error; old generic DTA could accept some of them. This is a stricter opt-in
adapter contract, **not** arbitrary-domain equivalence. The adapter does not
synthesize an architectural AddrMisaligned cause. Existing pageFault priority
and original request/tval provenance remain unchanged.

In the integrated CPU, LSU misalignment handling already emits precise
Load/StoreAddrMisaligned without an external request. FP uses that LSU; separately
buffered fast stores require `fastAligned`. Successful translations preserve
VA low 12 bits, and elastic certificates verify offset equality. Thus successful
integrated requests are already in the restricted domain. This source invariant
is not a substitute for directed integration and malformed-input testing.

## Closed functional evidence

- **21 focused Scala tests passed** (seven suites), including default-off/profile
  isolation, unsupported combinations, actual elaboration and unchanged capacities.
- Corrected-GSIM **DTA r4: 23 cases per model, 12 negative checks total**. Legal
  results, bytes, ordered ownership, latency metrics and histograms match exactly.
  The **61 deliberate new raw-misaligned access faults** are separately allowlisted,
  not silently treated as equivalent architectural exceptions. Page-fault priority,
  physical-request suppression, hint/certificate denial and drain remain checked.
- Existing direct LSU and FP fixtures prove ordinary/FP load/store misalignment
  cause, original tval and no external request. **AMO and fast-store rejection are
  source-audit only**, not dynamically proved full-CPU misalignment coverage.
- Fresh corrected-epoch CPU comparison: **two newly built DUTs, eight guest runs**;
  all paired logs, traffic, owners and metrics match. Four work-cycle results are
  **681 / 1018 / 531 / 360** for each model. Historical control FIR/metrics bind
  provenance only; no historical executable substitutes for the fresh control.
- Generated component, untapped adapter and full-CPU structure checks pass:
  one natural main checker plus the unchanged separate next-line checker, original
  payload unmodified, selected alignment guard after identity bypass, and fault,
  hint and canonical vetoes. Ten checker tests and six generated-FIR negative
  mutations pass. These are bounded checks, not general formal equivalence.

### Simulator initialization correction

The original generated `memset` passed a `uint32_t` pointer-element count as a
byte length. An idle invalid RAM payload consequently carried an impossible
UInt2 size (64/192): the size-bound assertion failed while alignment was true.
The failure was retained and diagnosed; **no RTL size mask, assertion removal or
hardware workaround** was introduced. A separate, bound simulator build corrects
only the two initialization byte-span sites; fresh paired runs use that epoch.
An existing broader initialization patch already contained the repair but had
been retained without application during restoration. Current minimal patch and
default guards qualify **deterministic initialization only**, not random mode.

## Matched resource results

Actual untapped production DTA, including guard overhead, same ports/configuration
except the candidate flag; four xcup maps:

| Policy | LUT control → guarded | FF | RAM32M16 | Whole sequential-cut cone |
|---|---:|---:|---:|---:|
| Default | 7,806 → 6,560 (−15.96%) | 2,465 unchanged | 26 unchanged | 52 → 44 |
| No-wide-LUT | 7,563 → 6,196 (−18.07%) | 2,465 unchanged | 26 unchanged | 39 → 32 |

Cones are unweighted conservative primitive connectivity, not time. The default
PMP-bound-input cone **increases 22 → 24** (no-wide: 20 → 20); improvement is not
universal. FF/RAM write boundaries are cut; asynchronous RAM addresses remain.
See `build/guarded-natural-dta-mapping-20261025-r1/REPORT.md` and `cone-depth.json`.
Its functional gate was r3; the later r4 closes current functional evidence.

Actual full production CPU, matched **alternative low-memory no-SAT-sharing
policy**, resource PASS:

| Resource | Control → guarded |
|---|---:|
| LUT | 197,175 → 192,877 (−4,298; −2.18%) |
| FF / LUTRAM primitive instances | 58,960 / 573, unchanged |
| BRAM36 / BRAM18 / DSP | 16 / 0 / 30, unchanged |
| CARRY / MUXF | 5,947 → 5,914 / 41,881 → 35,357 |

The authorized alternative omits generic SAT resource sharing and SAT memory-port
consolidation; normal non-SAT memory, DSP, BRAM and LUTRAM inference remain. Both
models use the same policy and unchanged production capacities. This is **not a
successful default-policy pair**. The original default control map was externally
SIGKILLed after 1,116.19 s at 6.91 GiB peak RSS; memory pressure is indicated but
kernel/cgroup attribution is unknown. Its candidate map was not launched.

Full-CPU sequential depth remains **BLOCKED** pending parameter-aware DSP48E2 and
BRAM cut validation; neither all-input combinational assumptions nor blind register
cuts are accepted. No full-CPU depth number, STA/Fmax or physical qualification.
Reports: `build/guarded-natural-full-cpu-mapping-20261025-r1/REPORT.md` (failed default)
and `build/guarded-natural-full-cpu-mapping-20261025-r2-no-sat-sharing/REPORT.md`
(closed alternative pair).

## Reproducible receipt bindings

Paths below are repository-relative; SHA-256 binds the closed artifact, whose
commands, source/tool hashes and child artifacts provide the reproduction details.

| Artifact | SHA-256 |
|---|---|
| `build/guarded-natural-data-pmp-20261025-r1/focused-specs.log` | `5a1536db7dbf55f25cce64f335b43a89869e0700e75070f27f8d2740710a2572` |
| `build/gsim-init-bytefix-20261025-r1/receipt.json` | `128c4853a6584cd1181cff863fc727a824fe132ad3c60f3ba323d46ea3b135fa` |
| `build/gsim/guarded-natural-dta-20261025-r4/receipt.json` | `b72af2cdb0f81716abbc793419053a74b1579dbd5dde16e5d68c79a2c6d99056` |
| `build/gsim/guarded-upstream-alignment-bytefix-20261025-r1/receipt.json` | `505c84ec71188ea384649ad9b9c895e192d8e0039ee9bd2f04c97e17d1aa69b3` |
| `build/gsim/guarded-natural-fresh-cpu-20261025-r1/receipt.json` | `8fe91bc51639e0766c9f6cc48b47c90d9d31ec9ecf86459bc67ad758c0a3abeb` |
| `build/guarded-natural-dta-mapping-20261025-r1/receipt.json` | `8533f65b781ea3632f441c82962b80a50353ec5a4b8f9a133509b96f72a9f739` |
| `build/guarded-natural-full-cpu-mapping-20261025-r1/receipt.json` | `9900830c2b2a09a5e5a48d3b20e89fb6ba328f3bc917327723c3a80dd77669dd` |
| `build/guarded-natural-full-cpu-mapping-20261025-r2-no-sat-sharing/receipt.json` | `b0768e0375eca4d1b114d987952e2bf9faef55f0ebb3dc6a05f816f109c99eb4` |

Independent structure/negative receipts reside in
`build/guarded-natural-data-pmp-20261025-r1/independent-authority-review/`.

## Bare ROM non-regression and scope boundary

The bounded host-only production copy/CRC comparison passes on both freshly
built repaired-epoch CPU objects, with no new DUT or guest build and no oracle
or interface change. Both complete logs match: 7,192 cycles, 8,570 retired,
1,221 loads, 39 stores, 1,260 replies and 640 validation byte reads. Actual proof
offer/accept counts are zero in M/Bare. This is non-regression, not a ROM speedup
or Ethernet/DMA/board measurement.

Receipt: `build/gsim/guarded-bare-rom-20261025-r1/receipt.json`.
SHA-256: `1d4f237c285c0ade757276d8414ec951333543abc9bab86f9cfe60b1f8fd4d0c`.
Report: `build/gsim/guarded-bare-rom-20261025-r1/REPORT.md`.

No public push, local-machine validation, profile/default promotion or board run
is implied by this document. Bounded tests and unsited mapping do not establish
universal ISA equivalence or timing closure.
