# Ready-store query77: qualified evidence and source staging

## Status and dependency order

Apply corrected74, then qualified opt-in76, then this combined 40-leaf77 overlay.
This overlay already includes the frozen nine-file77 production/profile delta plus
the compatibility, test and tooling changes; do not apply the nine-file delta separately. Defaults remain OFF. The deliverable contains source only. Its test-tool compilation, focused pure
compatibility tests, source staging, guest-byte regeneration and held-binding
parity checks passed. No hardware was elaborated, regenerated or executed during
packaging. It does not provide a one-command fullCPU build/link/runtime runner.
Existing frozen qualification and failure receipts remain unchanged.

The opt-in runner supports explicit config checks, focused compatibility tests,
component emission, fullCPU emission and GSIM C++ generation. Each is a separate
stage; printing a command is the default. Neither staging nor generation starts a
model. The runner does not offer fullCPU links or runtime; source/input recipes are
complete and validated, but executable/dependency review is still required for
any new build.
No default Make target changes. Broad Scala regression and older native exporters
are outside this scoped compatibility repair.

## Existing measured qualification (not rerun by packaging)

- Component: independently reviewed 16 directed case markers across OFF/ON and
  six triggered exact-oracle negatives. Exact constructor arguments, 178 core
  fields, ROB16/PRF48/LSU4, two proof rows, two credits and 64-bit tags were checked.
- Fresh ready nonhead absent-proof case: OFF had 63 eligible-resource windows and
  no admission; ON had one admission, one write query and one early load.
- Exact physical alias/overlapping bytes blocked early load; disjoint words and
  adjacent bytes admitted it. Ready-head missing-proof veto and progress passed.
- A real published PMP epoch change requery and precise PMP write denial passed.
  ON retried a denied write query 16 times; this policy is not uniformly faster.
- Matched fullCPU: seven positives and eight exact negatives on77, plus two COPY
  positives on historical76. Bare inclusive cycles were 173171 on both. Sv39
  inclusive cycles fell from 184440 to 175072 (5.079% fewer cycles; 5.351% more
  payload throughput). The 65536-byte, two-repetition accepted traffic was
  unchanged. Kernel and inclusive denominators are distinct.
- Held causality retained capture edge780 and acceptance781. NEMU architectural
  checks used an independent reference and independent initial state; no
  DUT-derived resynchronization. ASan address and UBSan checks were enabled;
  leak checking was disabled.

These are functional simulator results. They do not qualify routed timing,
resources, physical area, FPGA board behavior, FP paths or known-error adoption.
Component coverage does not establish inflight/bound epoch cancellation, universal
query fairness, all physical-address bits/sizes, or fresh-path full-token reuse.

## Qualified source selection and initialization

The component host is the **later ready-head scheduling repair**, not the original
fixture-r2 host that failed its head witness. The independent reference header is
byte-identical to fixture-r2. No component host/oracle adaptation was made.

The reviewed fullCPU host constructor clears the whole trivially-copyable model,
restores cycles=0, LOG_START=1 and LOG_END=0, then calls activateAll before the
unchanged public reset. The generator's original constructor confused an element
count with a byte count; reset alone is not evidence of full initialization.
Common board_boot.cpp and the qualified posted-join host have different bases:
only the exact reviewed initialization hunk is applied to the common harness.
The common harness does not acquire FabricIdleService. The staged posted-join
host preserves its exact FabricIdleService/DDR law and matches the reviewed host
hash. Both before/after identities are in inputs.json. Historical manifests are
not rewritten to hide this new layer.

Matched initialization validation rebuilt the76 COPY host and all four77 hosts
against their unchanged model objects. The76 Bare/Sv39 inclusive results reproduced
173171/184440 exactly, then77 passed the original seven positives/eight negatives.
This establishes the recorded workload comparison with common deterministic
initialization; it is not an allocator-pattern stress-test claim.

## Files and exact include topology

inputs.json inventories 19 COPY host leaves and the exact25-leaf qualified held
source closure, repaired76 supply/passive policy, guest-source identities and
additional NEMU/resolver leaves. prepare.py verifies hashes before writing a
fresh output, then verifies staged hashes. It never copies generated bindings,
guests, object files, models or reference binaries.

- COPY: one host/ root owns harness/board_boot.cpp and repaired supply_ledger.h.
- Held: one held/ root owns its exact host/ subtree. Fresh semantic bindings must
  be placed beside the held host; never add another historical held include root.
- NEMU: auxiliary/nemu/host/ supplies the exact qualified adapter/observer;
  include only the staged host/harness and the selected model as additional roots.
- PMP: auxiliary/pmp/ contains the repository host; its generated symbol header
  must come from verified regenerated guest symbols, not a copied old header.

The NEMU adapter/observer are byte-identical qualified sources. The two held
resolver files retain binding logic unchanged; only implicit workspace/model and
output defaults were removed. The explicit bind.py wrapper rejects any missing
required semantic binding and leaves results pending independent review. It
never treats a missing member as optimized-away evidence. Review accepted C/E/ACK,
full-token lineage, physical address and actual canonical-handoff semantics
before using new bindings in a host link.

## Commands and intentionally incomplete stages

From the repository root, use a fresh output for every stage:

    python3 -B simulator/gsim/ready_store_query77/prepare.py --output build/query77-sources
    python3 -B simulator/gsim/ready_store_query77/run.py config --output build/query77-config
    python3 -B simulator/gsim/ready_store_query77/run.py component-emit --enabled 1 --output build/query77-component
    python3 -B simulator/gsim/ready_store_query77/run.py fullcpu-emit --output build/query77-cpu

run.py prints the command unless --execute is explicitly supplied. GSIM generation
requires --model pointing to a FIR-only directory and --kind component or fullcpu.
The Mill interfaces use ordinary test sources, without shadow classes. The changed test tools and their unchanged compile dependencies passed one
focused27-source compilation batch against the frozen77 production classes.

prepare_guests.py pmp requires explicit gcc, objcopy and nm paths. It uses the
unchanged repository fetch_fault_precision_cpu assembly/linker script, the
original guest-only command law, and rejects both guest-byte and symbol-header
hash drift. It does not build or execute a host/model. The original generation
recipe was tied to an old workspace; its guest-only logic is now explicit.

The source/input recipe closure is now explicit, without qualified-directory
runtime dependencies:

- COPY: prepare_guests.py copy isolates the unchanged guest-only command law from
  cpu_sv39_bandwidth.py. It assembles the repository cpu_sv39_bandwidth.S with
  cpu_hot_bandwidth.ld, preserves nm symbol order, and checks both original byte
  and symbol-header hashes.
- NEMU: prepare_guests.py nemu assembles repository cpu_hot_bandwidth.S with
  HOT_BYTES=64, HOT_OP=2, HOT_REPS=1. The additional compressed_call_return.py
  source serializer retains the qualified instruction constants and emit body;
  only its CLI output directory changed. Both guest byte hashes are mandatory.
  --nemu-reference must name a separately supplied independent reference binary
  with SHA-256 c7c91e002909228a897657362603908c40a9ab28cbff694b77a578d4e588092f.
  The tool checks that hash without loading, copying, executing or rebuilding it.
- Held: prepare_guests.py held reuses the repository pure generated_guests and
  generated_controls functions, selecting corrected.bin and D1-bare-p0-x2-gated.
  It checks the exact qualified guest and control hashes before reporting success.

All assembly recipes require explicitly supplied gcc/objcopy/nm paths; identities
are recorded and rechecked. Byte checks remain mandatory across toolchain changes.
All four guest-generation recipes were executed during bounded packaging
validation and matched the original qualified bytes, including COPY/PMP symbol
headers and the held control file. The supplied NEMU reference hash was verified
without loading or executing it. The independent reference remains a required
caller-supplied input; these checks do not constitute new DUT runtime qualification.

No two-worker object-build, link or short-case command is offered. The sources,
regenerated guest bytes, reference identity and existing-model binding parity are
validated, but a new host build must still establish its exact link dependencies
and review new-model semantic bindings. A future build must
limit object concurrency to two, retain all sanitizers and DDR/stall flags in
inputs.json, enforce one include closure, and validate all positive and negative
anchors. Current77 OFF is not a reconstruction of historical76. The17 matched
cases require separately identified76 and77 model inputs.

## Packaging checks and boundaries

Packaging validation passed:

- One27-source test-tool compilation batch; unchanged production77 classes reused.
- All nine historical report layouts,22 designated malformed-projection controls,
  exact live-witness preservation and six unchanged historical JSON hashes.
- Original73/corrected74/75/76/TimingClosure config positives and negatives,77's
  seven config negatives, and the focused load-ready shape/prerequisite spec.
- Exact19-leaf COPY and25-leaf held staged source closures, preserving the repaired
  supply policy, common deterministic initialization and single include roots.
- All four guest recipes reproduced original byte/symbol/control identities;
  NEMU reference identity was checked without execution.
- Fresh held resolver adapters produced byte-identical headers and identical
  semantic proof fields against the already-qualified77 FIR/header.

Current/generic77 outputs retain the full178/95 ABI. Only named historical
entrypoints receive the explicit177/94 view. Every dropped query switch must be
literal false, full retained values must match the frozen document, and exact
live output bytes are retained in sibling .live77.json files. Old175/92-or-earlier
configuration paths that were already stale before77 are outside this repair;
this is not a claim that make test-scala or older Python native exporters pass.

Source files and preparation-stage status labels in inputs.json are pinned;
validation receipts are external build evidence and are not publication payloads.
No frozen production tree, runtime evidence, generated model, object, original
guest or historical contract was modified. The final package adds test tooling
and the documented host-only initializer; its four hardware source changes and new77 profile contract are byte-identical
to the frozen candidate. Test-layer compatibility changes are inventoried separately. No model execution, physical tool, broad regression,
reference rebuild, Git mutation or upload occurred during packaging.
