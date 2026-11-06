# Production A1 CDC + fabric export fixture

This opt-in Python 3.10+ standard-library utility projects **source-bound production
CHIRRTL**, without building, lowering or simulating anything. It is outside all
Make/test/GSIM defaults. It does not change production configuration or board
admission. Keep generated outputs outside the source tree.

## Supported input

Only the generic static A1 `CommonMachinePlatformMain` experiment is supported:
CPU100 MHz / fabric250 MHz, ROB16 / PRF48 / LSU2, issue2, 32 KiB two-way private
caches, Home1024×4 with two Acquire/two writeback owners, DDR4 slots/two writes,
and CPU/fabric CDC depth16. Static A1 fabric connects directly to MIG UI250; this
fixture does not add a DDR AXI clock crossing.

`read-baseline` is OFF and `probe-acquire` is ON. Both enable completion flow and
read overlap; only Probe overlap changes. OFF is **not** the unselected default.
The complete identity and configuration pins reject other or expanded profiles,
including W16 ROB32/PRF64, CPU-spec/CPU-experiment selections, SoC configuration
files, runtime clock profiles, I1 and Vivado-memory exports. Changing a pin is a
contract review, not a way to bypass a failed check.

Use a successful `valence-scala-compile-v1` receipt with the actual production
emitter. The existing supported receipt producer is:

```sh
python3 fpga/common/scala_compile_receipt.py --out /absolute/fresh/compile
```

It compiles via Mill; this exporter never calls it automatically. A properly
bound, independently recorded current-class reuse is also possible. A source
freshness inventory must not be represented as evidence that every listed test
was newly compiled. Do not manufacture an exit-only receipt or silently reuse
old classes.

Invoke `platform.CommonMachinePlatformMain` through that receipt's **exact
runtime classpath and order**, with `-Dchisel.project.root` set to the checkout.
For example, after constructing `CLASSPATH` from `runClasspathEntries` using the
host's path separator:

```sh
java -Dchisel.project.root="$REPO" -cp "$CLASSPATH" platform.CommonMachinePlatformMain \
  "$OFF_EMISSION" a1 --programmable --emit-chirrtl-only \
  --compile-receipt="$RECEIPT" --experimental-fabric-dma=read-baseline
java -Dchisel.project.root="$REPO" -cp "$CLASSPATH" platform.CommonMachinePlatformMain \
  "$ON_EMISSION" a1 --programmable --emit-chirrtl-only \
  --compile-receipt="$RECEIPT" --experimental-fabric-dma=probe-acquire
```

Both emission directories must be distinct and fresh. Do not substitute an older
Home body into ON to manufacture OFF. Retain source/resource files, classpath
files, the receipt and its source manifest. The producer records absolute input
paths: inspect emissions in their original location while those pins remain
available. This utility has no path-remapping, archive-discovery or stale-input
bypass. “Fresh” means the complete current source/class sets still match, not a
wall-clock age heuristic. Receipts are provenance records, not signed compiler
attestations against a party who deliberately forges every record.

## Export and check

From the repository root:

```sh
python3 simulator/qualification/a1_cdc_fabric/export_fixture.py \
  --emission-dir "$OFF_EMISSION" --paired-emission-dir "$ON_EMISSION" --check-only
python3 simulator/qualification/a1_cdc_fabric/export_fixture.py \
  --emission-dir "$OFF_EMISSION" --paired-emission-dir "$ON_EMISSION" --out "$OFF_FIXTURE"
python3 simulator/qualification/a1_cdc_fabric/export_fixture.py \
  --emission-dir "$ON_EMISSION" --out "$ON_FIXTURE"
```

`--check-only` writes nothing. `--out` requires a nonexistent directory whose
parent already exists. Existing destinations, including symlinks, are rejected.
An I/O failure can leave an incomplete new directory; it is never silently reused.
`BINDING.json` is written last. Both modes rehash inputs before and after projection.
Errors return nonzero, with no compilation, lowering, simulator or tool search.

The reader is deliberately bounded, not a complete FIRRTL parser or verifier. It
accepts FIRRTL 6.0.0's current annotated module/dependency/public-port syntax,
finite UInt/Clock/Reset/AsyncReset types, bundles, vectors and flip propagation.
It rejects duplicate/missing/recursive modules, malformed instances, unsupported
annotation targets/classes, missing verification layers and unknown statement
kinds. Internal node expressions and bodies are opaque: their meaning is not
reproved by Python. Dependency bodies, including all assertion logic and source
locators, are copied byte for byte and independently reparsed/rehashed.

Checks bind the full microarchitecture identity, all resolved metadata, compile
receipt, Git commit, complete Scala/resource/build input sets, source manifest,
classpath entry order and every runtime classpath file. Public leaf schemas pin
all names, widths and directions, not just counts. The selected production
startup/reset/empty/readiness/direct-AXI connections must exactly match the
supported assembly after removing source locators.

## Output contract

- `fixture.fir`: 374 exact dependency definitions plus the existing explicit
  `ProductionRealA1CdcFabricFixture` wrapper, 375 total.
- `TOP.fir`: wrapper alone, with 612 flat public/observation ports.
- `PORTS.json`: name, type, width and input/output direction of every flat port.
- `ASSERTIONS.json`: each original CHIRRTL definition assertion's module, line,
  exact statement/hash and layer path, plus all retained layer blocks. These
  definition-site counts are not lowered-instance counts or runtime coverage.
- `BINDING.json`: body hashes, root closures, instance edges, complete connection
  ledger, supported production assembly, annotations retained/excluded, layer and
  wrapper hashes, full input identity/provenance digests and output-file hashes.
  Emission/receipt references are relative to this output directory. The referenced
  producer records remain absolute and are not rewritten.
- `PAIR.json`, when requested: separately validated OFF/ON comparison. CPU-private
  identity and all non-Home bodies, wrapper, annotations, layers and ports must
  agree. Only `MixedCoherentLineHome` differs; combined identity digests must differ.

The wrapper retains common-cold-reset release, sticky `started` on bootEnable AND
DDR ready, startup reset until started, CPU reset release, CDC startup reset,
CPU hold=false, both transport-empty feedbacks, and complete CPU/CDC/fabric bus
wiring. Every instance input has exactly one wrapper driver. It retains the DDR
readiness assertion. `core__inspectRegister` deliberately exposes the read-only
GPR selector that production ties to zero. Other core outputs and CDC bus taps
are observations, not a private flattened-internal ABI.

The managed peripheral bank and board/vendor assembly (including BUFGCE/MIG)
are omitted. **All** fabric external ports remain exposed, including peripheral
register/stream endpoints, interrupt sources and timerTick. A caller must supply
those inputs; this is not a complete production-board testbench.

## Qualification and limits

Run the cheap tests without any external inputs:

```sh
python3 -B -m unittest discover -s simulator/qualification/a1_cdc_fabric -v
```

Add explicit fresh production emissions for paired provenance and real-file
negative controls (still no hardware execution):

```sh
A1_CDC_FABRIC_OFF_EMISSION="$OFF_EMISSION" \
A1_CDC_FABRIC_ON_EMISSION="$ON_EMISSION" \
python3 -B -m unittest discover -s simulator/qualification/a1_cdc_fabric -v
```

Tiny tests cover nested/vector flips, grammar/dependencies, layers/annotations,
assertion inventory, complete/wrong-direction wiring, collision/overwrite and
pin checks. Optional tests validate the real pair and reject altered identities,
ports, startup/readiness/empty wiring and layers, including mutations with repaired
outer artifact hashes. Source/class freshness is separate from behavioral proof.

There is **no assertion adapter or simulator command** here. A future approved
adapter must independently preserve every assertion predicate, enable and trigger,
reject unsupported flavors/domains and avoid whole-design clock conversion. A
successful export or a count of assertion tokens is not assertion execution.
GSIM remains the standard supported hardware flow; no alternate runtime is added.

The historical 669→606 CPU-cycle guest result belongs to its frozen model, guest,
service and clock phase. This fresh separately emitted pair closes a provenance
gap but does not rerun or relabel that runtime. Broad ISA/MMU/FPU/IRQ, physical
CDC/RDC/metastability, full-top SV/shell, MIG, routed timing and board qualification
remain separate. See [the source/qualification map](../../../docs/a1-optimization-source-status.md)
and [the fabric candidate's evidence limits](../../../docs/dma-probe-acquire-overlap.md).
