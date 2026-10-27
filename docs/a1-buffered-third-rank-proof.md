# Optional staged third-rank load proof supply

Private experimental profile:
`full-r1-m3-checked-flow-store-row-elastic-proof-guarded-natural-pmp-split-tag-buffered-third-rank`
(`CommonA1RebuildProfile.FullR1M3BufferedThirdRankProof`). Its control is the
qualified split-tag profile at `cd606758d6e337f7591ed5df4eb98b601d780f6a`.
Only the default-false `bufferedThirdRankLoadProof` flag changes. The new explicit
`ExperimentalBufferedThirdRankProof` memory policy rejects the old profile, and
old policies reject this new flag. Public defaults and earlier delivered branches
remain unchanged; legacy board factories reject the experiment.

## Contract and purpose

The old two-rank D1/T1/R1 supplier cannot sustain more than one certified load per
two cycles under its retained information horizon and raw-empty credits. This
candidate preserves the two execution-preparation ranks and their `useSecond`
selection. It adds an independent third ready memory rank for advisory ordinary
loads, with one additional source1 PRF read, immediate-only issue-payload read and
64-bit AGU. It does not borrow an execution port or populate execution VA from a
saved certificate.

`BufferedVirtualRamLoadPreparation` holds D2/T1/R2. D remains an address register;
T remains a registered hit-only translation result; physical PMP/range/alignment
checks feed registered R. At most one descriptor is captured, one hit-only query
is offered and one T-to-R transfer occurs per cycle. There are no new LSU,
completion, walk, drain, cache, MSHR or bus credits. ROB16, PRF48, four LSU entries,
two-wide rename/completion/commit and existing cache capacities remain unchanged.

- D/R admission uses lowest-index **pre-edge empty** rows. Issue, negative expiry,
  stale/dead cleanup, eviction or D transfer does not grant same-cycle space.
- An exact current D has query priority; otherwise an uncovered current uses its
  existing execution-stage VA. When current is absent or already reserved, live
  D rows receive round-robin query service. D RR advances on accepted D query.
- T can advance and refill. There is no descriptor-input fall-through into the
  TLB and no actual-issue-to-credit path.
- When R is raw-full and current lacks an exact fresh R, one round-robin victim
  is clock-evicted. Noncurrent T is retained, rather than eagerly discarded.
  Space becomes usable only on the next cycle. Current in D, unrelated T and
  full R can need two evictions before current reaches R.
- Full index/tag, VA, size and epoch identify a reservation. Registered owner
  liveness, source conflicts, context/flush, exact issued token, old negative
  expiry and victim cancellation apply to tentative destination owners, not
  blindly to their old row indices. An old T cancellation cannot erase an
  unrelated new T.
- A negative exact-current R still reserves and publishes `valid` with
  `allowed=false` for its registered residence, then expires. Positive issue
  eligibility is distinct from raw certificate publication.

The final proof-use check still compares the certificate against independently
computed current execution VA/size/full token. Wrong current VA cannot publish.
A matching registered R may publish in the present cycle despite contradictory
lookahead data; that conflict cancels all matching tentative owners at the edge.
This explicit refinement preserves legacy current authority without adding a
lookahead AGU-to-issue combinational veto.

## Source lifetime and implementation guards

The profile requires the guarded-natural PMP and split-tag parent, LVT PRF,
banked immutable issue payload, parallel PRF readiness updates, owner-local ready
mirrors, compact memory operand selection, parallel memory payload and registered
head mask. Move alias, load-completion bypass, multiply-word preview bypass,
registered load-result readiness and fast-head-load retirement are disabled.

Third rank is the third owner of the original ready-qualified memory mask, then
ordinary-load-qualified. It does not silently skip a head store/AMO when assigning
rank. Original execution rank1/rank2 and their independent VA path are retained.
Ready source stability is checked using accepted PRF writes/reservations and
full-token metadata, not a new PRF read or a saved-VA self-comparison. Same-edge
killed owners do not make a surviving-source promise. Zero-source special
semantics are retained.

A passive CPU observer reconstructs source values from accepted producer writes
and binds source physical ID/immediate/size/class to accepted allocation tokens.
It checks candidate and held-owner VAs against that independent event shadow,
then applies current writes/wakes/reservations/allocations for the next cycle.
This verifies accepted-allocation lifetime/provenance, **not** independent rename,
ISA or producer-result correctness. The four focused CPU guests now pass this
observer; synthetic observer tests alone were not treated as integrated proof.

## Resource geometry and conditional bounds

Source-level expected changes, not mapped FPGA resource measurements:

- Integer PRF: 14 to 15 logical asynchronous reads; 28 to 30 emitted bank reads
  across the existing two 48-by-64 writer banks. No new write port or logical
  register capacity. Actual untapped emission/port accounting is a separate gate.
- One additional immediate-only payload read and 64-bit AGU, plus parallel
  circular third-rank selection and exact-key row selection/deduplication.
- One extra D row (167 bits) and R row (232 bits): 399 additional logical payload/
  valid bits. Two arbitration bits make nominal proof-module state 1,033 bits,
  versus 632 before. This is not post-optimization FF or LUTRAM cost.

With mandatory D and two-rank visibility, the ordered certified information
horizon is at most 1/2 load/cycle. Three ranks raise that conditional horizon to
3/4. If the measured old six-cycle LSU residence persists, four execution slots
add a conditional ceiling of 4/6. These are feasibility limits, not an assertion
that the CPU now achieves 2/3 or that service latency remains unchanged.

No measured whole-CPU gain, mapped area result, STA, routed delay or 300 MHz
qualification is claimed by the component evidence below.

## Evidence and preserved failures

### Contract/model review

- `build/new-load-supply-contract-review-20261025-r1/REPORT.md`: source audit and
  alternatives, including why buffering alone cannot fix the two-rank horizon.
- `build/staged-proof-contract-model-20261025-r1/`: preserved but superseded. Its
  checker trusted model-provided conflict/cancellation masks, so a shared defect
  could evade the checker. Its earlier GO recommendation was withdrawn.
- `build/staged-proof-contract-model-20261025-r2/`: checker independently derives
  enabled, conflicts, bad full tokens, raw credit, cancellation and epoch rules;
  ten calibrated mutants rejected. 40,000 adversarial cycles and 6,184 positive
  owner/RR placements pass. The four-edge progress bound assumes live/fresh,
  positive held owners, stable current/context, hit/allow and no issue/cancel;
  finite random probes with stale/negative initial state observed up to six edges.
- `build/staged-proof-contract-model-20261025-r3/manifest.json`: explicit current
  publication and incoming epoch normalization refinement, with three additional
  publication mutants. Model SHA256
  `c34e19593d86e31b9094260171bc56409cd278490def3928037515bb5d71fdfb`.
  This is a finite abstract model, not complete formal hardware proof.

### Compile and focused hardware

Public bound compile receipt:
`build/buffered-third-rank-proof-20261025-r1/scala/compile-receipt.json`, SHA256
`d91c5d8e073c0e84aa73b57a3af372ff1b3168f6fecabf8f9e46328681610ef4`.
Nine focused Scala suites, 26 tests, pass; log is `focused-specs.log` in that
parent directory. Exact descendant allowlists and both-direction memory-policy
rejection are covered.

Corrected GSIM epoch receipt:
`build/gsim-init-bytefix-20261025-r1/receipt.json`, SHA256
`128c4853a6584cd1181cff863fc727a824fe132ad3c60f3ba323d46ea3b135fa`.
The deterministic byte-initialization repair is required; pristine or differently
patched GSIM is not silently substituted.

Final component receipt:
`build/gsim/buffered-third-rank-components-20261025-r2/receipt.json`, SHA256
`da5fdc93d2fa80e99f5f3e4f796d1feb770ca1090603c362867a6c8d5c632978`.

- Actual scalar proof fixture: 11,846 cycles, 59 independently byte-decoded PMP
  cases, 5,000 adversarial cycles, exact keys, cancellation, raw-full credits,
  stale responses, negative residence, index reuse and current-priority progress.
- Four ideal standalone runs: two ranks 0.5, three ranks 0.75, and approximately
  2/3 with three ranks plus conditional four-slot/six-cycle service. These are
  fixture rates, not CPU results.
- Actual production PRF/readiness phase fixture: seven directed cases establish
  post-step pre-edge observation, next-cycle accepted writes, higher-lane data
  priority, reserve-over-wake, zero/uninitialized and out-of-range reads. The
  test-only fixture has no connection to proof inputs and is excluded from PPA.
- Third-rank selector: exhaustive 65,536 masks times 16 heads (1,048,576 cases),
  both predecoded-head modes, independent circular scan, with original first/
  second ranks and late exclusion checked alongside it.
- Seven calibrated sampled-output/protocol negatives reject for their intended
  reasons. These are not RTL mutant builds; direct original-hardware stimuli
  separately exercise the associated hazards.
- ASan/UBSan and actual generated-header syntax gates pass; source, compile,
  contract, tools and raw artifact hashes remain bound and unchanged.

The component r1 attempt is preserved. Its positive hardware checks passed, but
its sampled wrong-VA mutation fired during correct-VA setup and therefore was
not rejected. The trigger was corrected to require an actual same-token changed
VA/size; no RTL, Scala or oracle expectation changed. Fresh r2 passes all gates.

Passive observer synthetic receipt:
`build/buffered-source-lifetime-observer-20261025-r1/receipt.json`. Eight synthetic
shadow mutations pass, and the separate actual component phase test now grounds
its clock convention. Actual CPU generated-header compilation and lifetime
coverage now pass in the focused CPU runs below.

### Independent source/structure eligibility

`build/buffered-third-rank-independent-structure-20261025-r1/receipt.json`,
SHA256 `fce3d9b3c0a3acada908330b9fab0f3b9e0bd1d7770e004a1d26d05a5e9aa6ce`,
passes 11 proof-subtree and four targeted backend cone checks under the same
compile receipt. The review checks r3 current authority, separate third-read
supply and independent execution VA. This qualified the short candidate CPU test below; the structure receipt itself
is not CPU performance, comprehensive timing closure or physical PPA evidence.

## Focused CPU and Bare ROM results

CPU receipt:
`build/gsim/buffered-third-rank-cpu-20261025-r3-host-recovery/receipt.json`, SHA256
`98ef619db33d8ea546802c4fa3480b492bf9cf2e9ec1469b8052998419608c05`,
status `PASS_FOCUSED_BUFFERED_SUPPLY_WITH_HOT_GAIN`.
The control is the current qualified split-tag candidate (`cd60675`), not the
older guarded-natural profile. All original functional, route and latency guards
pass unweakened; old hosts remain immutable, with narrowly checked candidate
adapters adding passive observations. The preserved host-packaging recovery used
one candidate GSIM generation and one DUT compilation in total, not a new RTL
revision or a fresh model for each host.

| Focused guest | Control ROI cycles | Candidate ROI cycles | Control work cycles | Candidate work cycles |
| --- | ---: | ---: | ---: | ---: |
| Hot loads | 531 | 402 | 1253 | 1118 |
| VM store stream | 513 | 509 | 681 | 677 |
| VM dependencies | 850 | 799 | 1018 | 967 |
| Delayed cold loads | 360 | 360 | 906 | 906 |

Hot ROI cycles fall 24.3%, equivalent to 32.1% higher throughput **at an equal
clock**. This is a measured focused ROI improvement, not an Fmax, whole-application
or universal load-throughput claim. Of 255 hot ROI owner-start gaps, the control
has 253 two-cycle gaps; the candidate has 128 one-cycle and 126 two-cycle gaps
(the remaining gap is seven cycles). Cold ROI does not improve despite changed
start spacing and a candidate proof age reaching 74 cycles.

Traffic and latency observations are not all numerically identical. Across the
**whole 512-load hot workload**, translation requests/replies rise 2 to 11,
prechecked starts fall 510 to 501, DTLB-hit observations rise 1 to 10, and drain
cycles rise 7 to 10. These translation requests are not a page-walk count and
must not be confused with the 256-load measured ROI. Both VM guests have physical
fetch requests 136 to 135 and drain cycles 7 to 9. Retired/canceled load ownership
has no differences; numeric owner tokens happen to remain unchanged. Absolute
start/retirement times do change. The full differences and scope are sealed in
`build/buffered-third-rank-host-recovery-preparation-20261025-r1/comparison-summary.json`
(SHA256 `8f2ce1f25477686a306951e64abbd6bb0713d3576dbc5f1d64749e40e623baa4`).

The actual source-lifetime observer passes all four guests. For hot loads it
checks 2,493 candidate VAs, 1,959 live held-owner VAs and 4,973 protected-source
conditions; 501 descriptor captures include 482 rank3 captures. All 521 observed
produced-source captures/direct queries follow their producer. These counters
include setup/drain, not just ROI. The live CPU runs do **not** observe zero-source
checks or simultaneous same-address writes; directed component phase and synthetic
observer tests cover those cases separately. The scope remains accepted-allocation
source lifetime and independently reconstructed VA, not a complete ISA/rename proof.

Bare ROM receipt:
`build/gsim/buffered-third-rank-bare-rom-20261025-r1/receipt.json`, SHA256
`3803363cdc16748ccfae436f9e0491c217b308be9c2c737c7851bdf627f8fb06`,
status `PASS_EXACT_BUFFERED_BARE_ROM`. Both runs take 7,192 work cycles and their
full logs match exactly. It reuses the already built candidate DUT and guest;
a relative-path preflight retry was not a guest failure or a DUT rebuild.

## Combined full-CPU resource prescreen and conservative depth

The cloud resource prescreen is sealed at
`build/buffered-supply-full-cpu-mapping-20261025-r1/`. Resource receipt SHA256:
`5e235cabbe0093e26be016e1107371ac59273385608c65a5f06fdb1edf652a70`;
final manifest SHA256:
`20934156799e0c8c8020599cccbef93fe7d482071126d0eef46d32ccf6af280d`.
One new untapped full-CPU candidate map reused the immutable older guarded-natural
`e48` baseline after fresh 177-SV byte equality. **Two flags differ**: split-low
tag arithmetic and buffered third-rank supply. This is not an isolated buffered
flag area comparison, unlike the one-flag CPU comparison above.

| Resource | Guarded-natural baseline | Combined candidate | Delta |
| --- | ---: | ---: | ---: |
| Logic LUT | 192877 | 192606 | −271 (−0.141%) |
| FF | 58960 | 59361 | +401 (+0.680%) |
| LUTRAM primitive instances | 573 | 627 | +54 (+9.424%) |
| BRAM36 | 16 | 16 | 0 |
| DSP | 30 | 30 | 0 |
| CARRY | 5914 | 5951 | +37 |
| MUXF | 35357 | 26538 | −8819 |

The logic-LUT reduction is **not a total-area reduction claim**: LUTRAM is a
separate cost, reported as primitive instances rather than LUT-equivalent physical
area. Extra PRF/payload reads, third-rank selection, AGU and buffering are included.
Untapped accounting confirms 15 logical PRF reads / 30 bank reads versus 14 / 28;
all 23 memory-array module geometries remain unchanged. Candidate top-level port
geometry remains 256 ports / 4,482 bits. Independent mapped cell counts agree,
and no residual memories/processes or unclassified cells remain.

This uses the exact saved no-SAT-sharing synthesis policy, not default synthesis:
manual coarse processing with `memory -nomap -nosat`, followed by mapping. Baseline
and candidate warnings match (32 each). CARRY counts are Yosys proxies, not
Vivado/device-native utilization; this flow uses CARRY4 chains. The run took
2,187.3 seconds with sampled owned-process peak 4,464.6 MiB; all owned descendants
have exited. No new baseline synthesis was performed.

Separate conservative-depth receipt:
`build/buffered-supply-full-cpu-mapping-20261025-r1/depth/receipt.json`, SHA256
`e912565215f44a5dcb124760fadfd25ce8e75ac846a67a8ded88d0a8e1dc8642`.
The unchanged qualified finite primitive model accepts all candidate primitives
and exact DSP/BRAM modes. Unweighted connectivity depth rises **58 to 60**: a
+2 structural-bound regression, not a demonstrated physical timing regression or
improvement. The selected maximum witness runs from
`queue_0_renamed_token_index[2]` through `memoryIssued` to
`core.responses.responses_responses.head_error`. The proof module's issued-valid
alias is a consumer on that net, not evidence of an issue-to-credit feedback path.

Allocation appears to constrain valid queue slot 0 to token index 0, potentially
restricting the witness's start bit. This is a source inference only: sensitization
or impossibility was not proved, nor were all tied maxima enumerated. It does not
erase the reported 58-to-60 result or establish a lower true bound. The depth
analysis reused the sealed mapped netlist; it did not rerun synthesis.

## Qualification limits and next boundary

Focused CPU, Bare ROM, source-lifetime and cloud resource/depth evidence are now
recorded. They are not complete formal ISA/rename proof, physical STA, placement/
routing, Fmax, 300 MHz or board qualification. No public default promotion or
public Git push is implied. The user's latest direction is to continue cloud
work first; **no local A1 run has started, and local work is paused**. Any local
implementation/timing stage remains a separate authorization and validation step.
