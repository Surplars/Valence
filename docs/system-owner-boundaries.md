# Protected SYSTEM owner boundary probes

This is a separate test-only increment after the published memory-domain-selector
stage. One single-clock fixture instantiates the real `ProtectedSystemOwner` and
`MemoryDomainSelector`, with 16 ROB entries, 64-bit tags, two commit lanes and an
untagged H+FP component parameter set. No production source, actual-core H+FP
admission guard, public default, two-issue setting, ISA/firmware declaration or
actual dual-FS hookup changes. The prior two-lane 64-case model, entry, tests and
evidence remain separate and unchanged.

## Accepted-event contract

Inputs are already-accepted start/completion events and synthetic commit lanes.
The fixture is not a ROB, MSU, LSU, executing guest CPU or trap handler. It exposes
the production owner's active bit, complete ROB token, context/H/FP epochs,
combinational retire-match mask and selector domain. It also exposes every
request/response handshake and payload, with unused guest metadata tied to zero.
One real selected native request/response pair is driven for each owner, with
independent backpressure and response delay. No replacement owner register,
queue, cancellation behavior or test RTL state machine is added.

The narrow dynamic probes cover:

- Accepted exceptional completion after the native response and a full quiet
  drain-observation cycle. Active and epochs clear while the token is retained.
  No exceptional token is put on a valid matching commit lane.
- Successful matching retirement plus simultaneous new capture, in both H-to-FP
  and FP-to-H directions. Pre-edge matching belongs to the old token; the captured
  new token and classification win the edge.
- Accepted exceptional completion plus simultaneous new capture in both
  directions, again only after drain. This tests the helper's assignment
  priority. `MachineSystemUnit` accepts start in idle and completion in finish;
  these simultaneous helper inputs do not establish actual MSU reachability.
- Inactive matches against reset-zero and a retained *successful* token. The
  production `retired` output is an OR of valid full-token matches, without an
  active gate. These are intentional interface probes, not duplicate live-ROB
  retirements. Invalid lanes, wrong index and differing top tag bit do not match.

Every owner has exactly one accepted completion. Successful completion retains
ownership until matching retirement. Nonaccepted completion payloads keep their
exception bit set, proving that validity qualifies release. Eight distinct tags
have nonzero upper halves and their top bit set; handoff tokens share their low
32 tag bits. Both index and all 64 tag bits are independently compared.

Actual FP and counter retirement consumers remain **source-only** scope here.
Their completed-state, authorization, pending-write and exact-token gates are not
instantiated or simulated by this fixture. An inactive match pulse is therefore
not evidence of an FP/counter effect or architectural retirement.

## Frozen schedules and evidence

The eight owner domains A through H are H, FP, H, FP, H, H, FP, H. A/B release
exceptionally alone; C/D retire while capturing D/E; E retires alone before the
retained-token probes; F/G complete exceptionally while capturing G/H; H retires
alone. C/E match commit lane 0 and D/H match lane 1. Inactive valid probes use each
lane separately, never both matching at once.

Each schedule has two initial idle-reset cycles, six reset-token probes, four
standalone starts, eight native pairs, twelve completion/release edges, six
retained-token probes and two final quiet cycles. Every pair includes one quiet
post-response drain cycle. For request stalls, response delay, response stalls
and post-drain holds respectively, baseline uses 1/1/1/1 and staggered uses
2/3/2/3. The exact totals are 88 and 136 cycles, not runtime-derived tolerances.

Each schedule requires:

- 8 starts, 8 requests and 8 responses, split integer/H/FP as 0/5/3.
- 4 successful completions, 4 exceptional completions and 4 active successful
  retirement releases.
- 2 retirement/capture edges, 2 exception/capture edges and 4 inactive match
  probes. The `retired` output pulses 8 times, only 4 with an active owner.
- Baseline/staggered request stalls 8/16, response stalls 8/16, response-delay
  cycles 8/24, quiet drain cycles 8/8 and hold cycles 8/24.
- Wrong-tag and wrong-index probes 10/26 each, plus 2 invalid-matching-token
  probe cycles. These count component stimulus, not architectural events.

Schema-1 raw JSONL has one exact header, contiguous phase-labelled cycle rows and
one exact summary footer. Every row records input, pre-edge output and post-edge
owner/domain. GSIM's step exposes pre-update outputs: a row's post state is copied
from the **next actual observation**, then independently linked to that next row
by the Python replay. Only the final quiet row has `post: null`, because there is
no sampled successor; no extra edge or fabricated post state is claimed.

The native ledger and separate Python replay check accepted events, full-token
matches, owner/epoch transitions, capture priority, exact selector handshakes,
full payload routing/stability, one native response per recorded request, prior
quiet drain, completion uniqueness and exact summary totals. Numeric fields
reject booleans, overflow and malformed widths. Unknown schema or fields,
duplicate JSON keys, missing/reordered/truncated rows, extra `PASS` output,
sanitizer output, incomplete coverage and non-drained final states fail closed.

Nine controls corrupt local checker observations, never RTL inputs or expected
counts: `exception_release` (cycle 18), `retire_capture` (37),
`exception_capture` (70), `inactive_match` (3), `high_tag` (6), `index_match` (7),
`valid_qualification` (5), `epoch_clear` (18) and `domain_switch` (37). Each must
exit exactly 1 with only `SYSTEM_OWNER_BOUNDARIES_CHECK[name]: cycle=N` and a
newline. A crash, timeout, sanitizer report, wrong diagnostic or unexpected pass
is a failure. These prove checker sensitivity, not RTL mutant coverage.

## Reproduce the focused entry

Use the already installed, verified pinned repaired GSIM/compiler toolchain.
`common.setup(False)` disables GSIM tool fetching and verifies the tool/compiler
binding. The supervisor separately sets `COURSIER_MODE=offline` and preserves
the verified Scala dependency cache in place. The entry does not itself enforce
Scala offline resolution. There is no fallback simulator or unverified
model-reuse route.

```sh
export COURSIER_MODE=offline
python3 -m unittest discover -s simulator/gsim -p test_system_owner_boundaries_entry.py -v
mill -i IonSoC.systemOwnerBoundaries.compile
mill -i IonSoC.systemOwnerBoundaries.testOnly \
  ooo.SystemOwnerBoundariesConfigSpec ooo.MemoryDomainSelectorConfigSpec
GSIM_CXX=clang++-19 make gsim-system-owner-boundaries-test \
  SYSTEM_OWNER_BOUNDARIES_ARGS="--output /absolute/fresh/workspace-output/model"
```

The default output is `build/gsim/system-owner-boundaries`. Even an empty existing
directory or dangling symlink is rejected. The focused Mill module includes all
unchanged production and HardFloat dependencies and exactly three test sources:
the new fixture, its new configuration suite and the prior unchanged
`MemoryDomainSelectorConfigSpec.scala`. The suites contain 3 + 5 checks; this
module does not compile the broad test source set.

The entry builds exactly one fresh model. It executes baseline, then staggered,
then all nine baseline named controls using that same newly built executable.
ASan and fatal UBSan stay enabled, with 120-second native timeouts, a 256-cycle
native cap and a 1 MiB raw trace cap. No old native matrix is rerun.

Artifacts include `SystemOwnerBoundariesGsim.h`, generated native sources, `run`,
elaboration/generation/compile logs, `test.log`, `staggered.log`,
`raw-baseline.jsonl`, `raw-staggered.jsonl`, `negative-*.log` and
`entry-summary.json`. Each positive native log is exactly one
`SYSTEM_OWNER_BOUNDARIES_SUMMARY` JSON line. The entry emits
`SYSTEM_OWNER_BOUNDARIES_STANDARD_PASS` only after both traces/summaries and all
nine controls validate. Keep external source/tool identities and phase receipts
with these artifacts; a summary alone is not a source-bound validation result.

All **47 Python tests are mock-only**: tool setup, model generation/compilation
and native executions are mocked. Their synthetic packets live in explicitly
mock-only temporary paths, and successful mocked entry output is captured.
Passing host tests proves orchestration/replay behavior, not hardware behavior.
The commands above are reproduction instructions, not a claim of validation for
this source revision. Report native and configuration results only after actual
execution and independent review of their retained evidence.

## Resources, preservation and exclusions

The supervising run, not this entry, measures capacity and terminates on budget
limits. Route new Mill output, HOME/XDG, native temporary files and JVM
`-Djava.io.tmpdir` into fresh workspace-local directories. Reuse verified tools
and dependency artifacts in place, never old model outputs or compiled classes.
Run only one heavy phase at a time.

Admission requires 336 MiB workspace free, 128 MiB `/tmp` free and 3.5 GiB
MemAvailable. Aggregate new workspace output is capped at 192 MiB, including
failed attempts, logs and archives, with at most 16 MiB `/tmp` spill. Preserve
hard reserves of 128 MiB workspace, 96 MiB `/tmp` and 1 GiB available RAM. Sampled
process-tree RSS must stay below the smaller of 3.5 GiB and launch MemAvailable
minus 1 GiB; the total supervised wall cap is 1,200 seconds. Reserve at least
32 MiB for reports/packaging until a post-build inventory permits refinement.
These are abort budgets, not a guarantee of fit. Preserve partial outputs on
failure and stop for reassessment; do not delete, relocate or rewrite old
archives, historical Mill trees, models, caches or Git alternate stores.

This increment does not qualify actual CPU scheduling, architectural retirement,
producer drain/trap precision, real FP/counter consumer effects, guest F/D,
HS trap CSR execution, all-32-FPR/fcsr software context isolation, OS boot,
ISA-wide compliance, throughput, PPA or board behavior. IRQ/fault cancellation,
reset with a live owner, independent clocks, Yosys, Verilator and the restricted
M-origin guest-fault review remain excluded.
