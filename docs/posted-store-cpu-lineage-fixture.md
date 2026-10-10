# CPU posted-store lineage fixture: source checkpoint

Initial source checkpoint on 2026-10-10 was unexecuted. The assigned serial gate
has now passed with the precise source/model/host identities and limits recorded
in [the qualification receipt](posted-store-cpu-lineage-qualification.md).
The coverage definitions below remain the contract, rather than a claim about
any other source version or about a real downstream cache/home composition.

## Scope and environment contract

`src/test/scala/ooo/PostedStoreCpuLineageGsim.scala` runs actual raw instructions
through `MappedMachineCore`, `MachineCore`, `IntegerCore`, `IntegerBackend`, the
parallel LSU, production request FIFO, `StoreBuffer`, response buffer,
`DataTranslationAdapter`, physical register router, and real APLIC. A real
`SvTranslationService` with sixteen entries and its Sv39 walker services data
translation. The external PTE memory returns independently authored PTE words;
separate programs exercise an invalid root and successful leaf translation.

The profile is `FpgaNextConfig.Selected` with sixteen data translation entries,
virtual RAM load precheck, prepared-store lookahead, checked store prefetch, and
store-prefetch MRU enabled. This follow-up additionally preserves the requested
high-performance configuration: `lsuEntries=4`, `physicalLoadIngressFlow=true`,
`loadOrderOlderRetire=true`, and `fetchPreviousPacket=true`, with elaboration
requirements for all four. `precheckedDataRequestFlow` remains false. Both
variants explicitly set `fastBufferedStoreRetire=false`: ordinary registered
LSU/request-FIFO/StoreBuffer retirement is mandatory. Only `postedStoreMerge`
changes between the ON/OFF variants; no default profile is changed.

The C++ host supplies an **external cache-retention contract**. It accepts real,
checked physical requests and returns ordered, successful RAM responses. After
an accepted store, it retains `busy` for 512 clocks, including clocks after the
CPU's acknowledgement. It retains `episodeActive` until the CPU produces an
aggregate end event. This tests CPU ownership extension, ordering and lineage;
it does not instantiate or prove a private cache, merge owner, cache SRAM,
refill/acquire engine, coherence home, DMA, or TileLink channel. Component-only
`PostedStoreMergeGsim` coverage remains separate and cannot fill those gaps.

The memory device initially holds requests for at least four clocks. After
observing the complete held request, it raises ready and offers the corresponding
zero-latency response together. The real register-router response-owner FIFO
holds that response until its owner exists. The host retains valid and every
response bit until ready. This is actual production return backpressure, not a
counter named “held” or an internal ready override. No internal force, injected
proof, retirement pulse, or authorization input is used.

## Independent oracle and observations

`simulator/gsim/harness/posted_store_cpu_lineage.cpp` contains raw RV64 encoders,
a small rejecting interpreter, a byte-array RAM model, a separate PMP model, and
an independent Sv39 walk over the authored PTE map.
It constructs the architectural trace and logical store intents before running
the DUT. It does not import DUT decode constants, generated decode tables, proof
verdicts, or the component fixture's expected outcomes.

Every actual rename binds the authored PC/instruction to its full ROB
`{tag,index}`. Every store launch must match that original binding, the actual
ROB head, raw address and source-register data, access width, effective privilege,
and the independently computed physical PMP result. Faulting and wrong-path
stores cannot populate an authorized posted-store witness. Every actual LSU
request is associated with its raw launch witness through the production
`requestOwner` full token, independently of posted proof. Accepted transfers
propagate that original memory owner through per-stage software queues; direct
passthrough offers retain their unaccepted upstream owner under backpressure.
No owner is recovered from a reused ROB index, physical address, or proof token.

Seven passive boundaries compare those witnesses:

1. LSU request output
2. Registered request FIFO output / StoreBuffer ingress
3. StoreBuffer external output
4. IntegerBackend external output
5. Translation adapter ingress
6. Checked physical output before the APLIC router
7. External memory output

The authority-stage oracle requires head/PMP/physical/integer authority from the
real head launch, legacy-accepted authority only from StoreBuffer egress onward,
and final-checked authority only at checked physical egress onward. Proof
eligibility always comes from original raw instruction/privilege/translation
intent. A successful virtual store must retain no proof at every boundary,
including after its request address becomes a valid cacheable physical RAM
address. The numerical
epoch is an opaque production context identity captured at the original launch;
the test checks exact retention and prohibits a context identity change while
an external owner or local return owner remains. It does not claim an independent
implementation of the epoch counter's numerical increment policy.

All seven boundaries check complete held request and proof immutability. Their
real response channels check held valid/data/error/page-fault immutability.
Ordered response-owner queues at all seven boundaries derive from accepted
software memory witnesses and check exact data/error/page-fault results. Stores
cannot retire before their corresponding original LSU-facing acknowledgement
and full-token LSU completion. The completion also retains precise cause/VA for
faults; ordinary retirement is exercised with fast store retirement disabled.
Every commit's PC, raw instruction, destination, value, next PC and original
rename token is checked. Final physical bytes and exact store counts must equal
the independently interpreted result, including overlapping byte/halfword/word
writes and the untouched wrong-path store location.

## Directed programs and required coverage

- Physical stores with byte/halfword/word/doubleword masks. Sixty-four dependent
  arithmetic instructions force ROB slot reuse while external ownership remains;
  a nonzero `robReuseWhileBusy` count is mandatory. More than sixteen commits
  must occur while busy, and the index of an actual retired, externally
  acknowledged store must be reused with a different full tag while that exact
  store still has an external retained owner.
- Separate retained-owner episodes place an ordinary RAM load, an actual APLIC
  domain-configuration load, FENCE, a memory-context CSR write, and FENCE.I at the
  head. Each class must accumulate real wait cycles; none may launch across the
  retained owner. The APLIC reply is checked against its architectural reset
  domain-configuration value.
- A dependent arithmetic chain delays a taken branch until a previous store has
  reached external memory. Recovery must overlap retained ownership. A wrong-path
  store is independently absent from the architectural trace and physical bytes.
- A misaligned doubleword store must produce precise cause 6 and the original
  effective address, with no proof or physical store.
- A raw CSR program installs locked read-only NAPOT PMP protection. Its denied
  store must produce precise cause 7, with no proof or physical store.
- A raw CSR program enables Sv39 and MPRV/S privilege with a TOR PMP aperture.
  The actual walker must read the independently calculated root PTE address once.
  The invalid PTE yields precise store page-fault cause 15 and the original VA;
  no proof or physical data request may result.
- A distinct successful virtual-store program uses a root at `0x80202000` and
  next-level table at `0x80203000`, outside the 4 KiB data array. The read-only
  PTE map contains a valid nonleaf pointer and an aligned 2 MiB R/W/A/D leaf.
  It maps VA `0x40000080` to PA `0x80200080`; any unexpected PTE address rejects.
  Exactly two independently predicted walker reads, one virtual-origin request
  and response at each of the seven boundaries, one original-token completion,
  and zero traps are mandatory. Every virtual-origin proof must be absent.
  After restoring MPRV, an architectural physical load checks the stored bytes.

This checkpoint does not include directed atomic or floating-point store
origins, trap-vector execution, response errors
for guaranteed-success physical stores, generation exhaustion, cache/home/DMA
interleavings, NEMU, timing, performance claims, or a board qualification.

The successful-translation/no-proof property is now a separate authored gate,
not inferred from the virtual-fault program. It passed in the frozen CPU
lineage gate described above; the combined delivery source is unexecuted. FP/atomic origins still require separate
raw programs and appropriate architectural interpretation before claiming their
no-proof coverage; this source follow-up makes no such claim.

## Verification entry points

Emitter: `ooo.PostedStoreCpuLineageGsimMain OUTPUT_DIRECTORY on|off`.
Top: `PostedStoreCpuLineageGsim`.
Harness: `posted_store_cpu_lineage.cpp`.
Runtime: `--on` or `--off`, matching the separately emitted model.

Use the existing `simulator/gsim/run.py` focused `test` helper with explicit
`defines={}` when passing emitter parameters; otherwise that helper interprets
the parameters as legacy ROB/PRF geometry. Preserve separate fresh output paths
for ON and OFF, compiler/GSIM logs and source hashes. No new full-suite target,
alternative simulator, Linux run, or hardware implementation is needed for this
source checkpoint.

The ON executable also accepts `--inject-oracle-token-mismatch` and
`--inject-oracle-byte-mismatch`. Each deliberately perturbs the independent
expected witness and must exit nonzero on its first real physical store. These
are authored oracle-sensitivity checks, not executed source-mutation evidence.
They do not alter the DUT or prove resilience against every possible defect.

A future pass requires both normal variants, both rejecting ON oracle controls,
all mandatory counters, precise faults, exact commit traces and exact final RAM
bytes. A source-only checkpoint, component-only pass, or a manually inspected
proof waveform is not that pass.

### Strict serial launcher

`simulator/gsim/posted_cpu/run_lineage.py` provides a lightweight `bind` command
and a separately authorized `run` command. Invoke the copy inside the final,
clean merged repository. Binding requires explicit expected HEAD/tree and the
SHA-256 of the existing recovered tool receipt. It hashes every tracked file,
the receipt's installed GSIM/Clang/Mill wrapper/Mill distribution/firtool files,
the Python interpreter, and relevant inherited environment settings. It does
not invoke any compiler, Mill, setup, make, or download. The resulting binding
must be reviewed against the intended merged freeze; its SHA-256 is mandatory
when starting the heavy run.

Example after sourcing the existing verified tool activation, with the final
merged source values supplied by the coordinator:

```sh
python3 -B simulator/gsim/posted_cpu/run_lineage.py bind \
  --repo /absolute/path/to/frozen-cpu-repo \
  --expect-head EXACT_MERGED_COMMIT --expect-tree EXACT_MERGED_TREE \
  --tool-files /absolute/path/to/toolchain-recovery/tool-files.json \
  --tool-files-sha256 0743301bca2da57ef871ab1cbc1184c831341269d1e4db377cb1628e29ea0512 \
  --output /absolute/fresh/path/cpu-binding.json
python3 -B simulator/gsim/posted_cpu/run_lineage.py run \
  --binding /absolute/fresh/path/cpu-binding.json \
  --binding-sha256 EXACT_RETURNED_BINDING_SHA256 --slot-granted \
  --output /absolute/fresh/path/cpu-lineage-attempt
```

The run rechecks source and tools before and after every subprocess. It first
runs `ooo.PostedStoreCpuConfigSpec`, including actual shared board-wrapper
ON/OFF elaboration. It then invokes the existing focused `run.test` helper with
`defines={}`, separate fresh `models/off` and `models/on` namespaces, and the
existing pinned GSIM and Clang binaries. Mill is forced to one build job. No
generic setup or alternate diagnostic tool is called. The emitted CPU FIRRTL
must contain four LSU slots, the complete 64-bit tag/4-bit index, and the correct
optional CPU/StoreBuffer/adapter proof ports and state. It must contain no real
cache owner because this fixture's downstream remains synthetic.

Every one of the five programs runs in a separate process for each mode, followed
by separate token/byte oracle controls using the ON executable. The driver uses
`--case NAME --trace PATH`; each flushed JSONL trace contains the independent
expected architectural trace, original token bindings, launches, all seven
request/proof/response boundaries, commits, precise traps, context changes,
page-table accesses, and retained ownership events. A failed case preserves its
trace prefix, runtime log, exit status and hashes in its own result receipt.
Independent cases continue after an ordinary case assertion; failed builds mark
dependent cases blocked. A timeout, signal, sanitizer report, generic nonzero
exit, or absent coverage row cannot count as a successful negative control.
Each negative must exit exactly 1 with the original full-token/epoch/payload
lineage diagnostic and its matching case identity.

The aggregate receipt records the binding, profile, tool identities, actual
commands, per-case counters, trace-event census, generated-model/binary hashes,
failures, and all blocked cases. It claims a CPU lineage pass only if both modes
and both controls complete. The 512-cycle external delay and ordinary registered
retirement profile are correctness conditions, not throughput measurements.
This launcher and trace extension were checked with lightweight Python tests
before their first assigned hardware run; those host tests are not DUT evidence.

First-launch evidence is preserved separately. Attempt r1 rejected an inherited
`JAVA_TOOL_OPTIONS` hash change before invoking tools (the shell's proxy port
changed); bind and run must share one activated shell. Attempt r2 compiled all
191 production and 230 test Scala sources, then failed the OFF board census:
the initial whole-module substring check confused the passive line-write
observation's `posted` field with optional `io.posted`. The follow-up checks the
actual IO declaration and saves both emitted board FIR files under the run's
`board-census` directory. This fixes the evidence check without changing any
production source. Neither failed attempt supplies a CPU runtime pass.

Attempt r3 passed the actual board census and emitted/generated both real CPU
models. Native host compilation then rejected two reads of the PTE
`request.ready` input: GSIM provides its setter only. The follow-up uses one
named, unchanged constant input value for both the setter and the sampled
handshake/trace. No instruction, memory timing, or readiness stimulus changes.
The failure logs and both original generated models remain intact.

For this narrow host correction, `run --reuse-attempt PREVIOUS_DIRECTORY
--reuse-receipt-sha256 EXACT_DIGEST` explicitly validates the previous terminal
receipt, all FIR/header/generated-source hashes, the tool receipt, and equality
of every tracked file except the declared host/launcher/test/document paths.
Any RTL, Scala fixture, build, or tool change rejects reuse. Both actual headers
must pass host syntax checks before compilation. Generated model objects are
compiled separately and retained, permitting a later host-only correction to
reuse them only with exact object/tool/flag hashes. The new receipt carries both
the original model binding and the new host binding and explicitly says their
full source inventories differ. Fresh per-case trace/result paths remain
mandatory. This mode does not claim a fresh RTL emission or inherit a CPU
runtime pass from a previous failed attempt.

Attempt r4 passed all five OFF programs, all three ON precise-fault programs,
and both ON oracle controls. The remaining two ON programs stopped in the host
epoch check: the loop inserted a newly accepted request carrying the new epoch
before checking whether the previous epoch had drained. Raw traces show the
previous context CSR retired and no retained external owner at either failure.
The correction snapshots all previously accepted full-token LSU and seven-stage
transport owners before sampling the current tick. A context change still
requires that entire older set and external ownership to be empty; a new request
cannot enter its own older-drain predicate. Exact old tokens are recorded if the
check rejects. Original guest bytes, hardware, and input timing remain unchanged.
The exact runtime epoch checker also runs host sensitivity controls: an old
token with delayed response rejects, retained external ownership rejects, and
an old token replying on the sampled tick still rejects because its pre-edge
responsibility is nonempty. Empty old responsibility allows a new-epoch start;
every subsequent real proof is still compared against that start's immutable
epoch. The hardware boundary uses pre-edge `aggregateDrained && adapter.idle`,
so clearing the host set after a same-tick old reply is not an allowed shortcut.

Attempt r5 passed all five ON programs and both controls. The strengthened final
LSU ownership check exposed a host omission in the OFF branch case: accepted
speculative load token 115 drains its response after branch token 112 redirects,
then the real LSU discards the cancelled result without a completion. The host
now uses the observed redirect's full token and original rename order to mark
only younger readonly owners cancelled. It retains every request/response
transport owner until all seven stages actually drain. A committed store or
authorized token reaching that cancellation path rejects. This follows the
existing LSU cancellation contract and does not change recovery or traffic.
Cancellation permission additionally checks the original raw integer LOAD
opcode, physical/nonfaulting origin, and unchanged epoch. It is intentionally
limited to this guest's executed physical speculative load; no Sv39 late-cancel
qualification follows. The runtime's same owner validators have mandatory host
negative controls for store cancellation, older-load cancellation, wrong full
tag, wrong epoch, omitted late response, fake completion, and fake retirement.
Real response data and all seven accepted stage queues remain independently
checked. Actual completion and retirement must retain their original token,
and cancellation cannot manufacture either event.

The source schedule holds the synthetic external owner for 512 cycles to leave
room for the current four-LSU profile's dependent instruction chains before
required reuse and recovery observations. This is an adversarial correctness
delay, not a measured hardware latency. The 12000-cycle case timeout and all
coverage assertions remain mandatory. Observed events are recorded only for
the exact frozen gate in posted-store-cpu-lineage-qualification.md.
