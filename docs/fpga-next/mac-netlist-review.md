# MAC netlist collection and review contract

Status: **PREPARED_NOT_NETLIST_QUALIFIED**. No Vivado, synthesis, implementation,
checkpoint queries or local desktop work was performed for this preparation.
The synthetic Tcl model tests script control flow and exact scope rejection;
it is not a Xilinx primitive model or evidence about an actual mapped design.
The production Scala and previously qualified native emitted RTL are unchanged.

## Reproducible staging

`fpga/next/export.py --experimental-trispeed-ethernet` already invokes
`media_integration.stage`. It now copies the following with source and artifact
SHA-256 identities into the matched export's `board/` directory:

- `audit_mac_netlist.tcl`, read-only queries and report generation
- `mac_registered_level_constraints.tcl`, five exact bounded level crossings
- `mac-boundary-cdc-inventory.json`, contract version 1 within inventory version 2
- `mac_netlist_review.py`, preparation and byte-identity verification
- Generated `mac-netlist-binding.json` and `mac-netlist-binding.tcl`

The existing `require_trispeed.tcl` applies the reviewed packet constraints,
then the five new scalar bounds. All five source Q identities, clocks,
destination two-stage chains, asynchronous reset wiring and first-stage fanout
are validated before any new bound is applied. Each bound is an 8 ns
`set_max_delay -datapath_only` from a specific source FF **C** pin to one first
stage **D** pin. There are no new false paths, asynchronous clock groups,
multicycle paths, reset exceptions or related raw/managed functional exceptions.
The read-only collector does not apply or repair any constraints.

The exporter includes these dependencies in its existing complete source
closure. The media manifest binds all staged artifacts. Before a future
authorized collector run, on the machine holding the actual export and DCP:

    python3 EXPORT/board/mac_netlist_review.py prepare-job \
        EXPORT CHECKPOINT.dcp IMPLEMENTATION/provenance.json FRESH_JOB --rate 1000

This command creates a job receipt and `FRESH_JOB/collect.tcl`; it **does not
launch Vivado**. Use one independently matched checkpoint and fresh job for
each 10, 100 and 1000 Mb/s scenario. The generated Tcl verifies bytes again
before opening the DCP, then collects facts from the exact matched design.
Prepare the job on its consuming machine: it records that machine's Python
executable and absolute paths. A relocated package must be prepared again.

The separately produced implementation provenance JSON must contain:

- `schema`: `valence-mac-checkpoint-provenance-v1`
- `export_receipt_sha256`, `checkpoint_sha256`, and numeric `rate_mbps`
- Exact `source_sha256` and `rtl_sha256` maps copied from that export receipt
- Nonempty `implementation_log_sha256` and `constraint_files_sha256` maps of
  implementation-directory-relative files and their actual hashes

The latter maps are verified on disk. They must include the exact staged
packet, CDC helper and registered-level recipes. This attests recorded input
identity; it does not independently prove that the implementation tool read
those files. The implementation command/log and DCP provenance still require
review. The preparer never fabricates provenance for an arbitrary checkpoint.
Missing export receipts, stale staged scripts, changed RTL, changed DCPs,
missing logs or omitted recipes fail before opening Vivado.

## Exact scope and rejection rules

The only supported current board root is `u_soc/board/nativeBank/gmac`.
The old `u_soc/nativeBank/gmac` collector and its five-mailbox/two-FIFO census
are rejected. The native module census must match exactly:

- Nine mailboxes: `txRate`, `rxRate`, `txConfig/mailbox`, `rxConfig/mailbox`,
  `txStats/mailbox`, `rxStats/mailbox`, `rxDiagnostics/mailbox`,
  `rawDiagnostics/mailbox`, and `rxStop/command`
- Three FIFOs: `txFifo/fifo`, `rxFifo/fifo`, and
  `physicalIngress/crossing/fifo`
- Five source-registered level chains: `txLink_sync`, `rxLink_sync`,
  `rawRxOpen_sync`, `ingressEmpty_sync`, and `txWireDrained_sync`

`mediaOpen_reg/Q` must feed precisely the three corresponding first-stage D
pins. Each first D has one exact expected source FF Q driver, not merely one
clock pin somewhere in combinational fanin. Both synchronizer stages must be
ASYNC_REG, positive-edge FDCE, INIT/reset zero, tied-enabled, in the destination
clock, directly cascaded, with no intermediate functional fanout. Source reset
and destination reset must come from the correct release bank; each asynchronous
reset must have one actual leaf driver. Retired independent abort/capture chains
are rejected. Asynchronous release banks are three positive-edge FDPE stages,
INIT/reset one, direct zero-shifting, with no intermediate fanout.

`media/ingressResetSource_reg` must be a CPU FDPE reset by CPU cold release. The
only admitted physical epoch implementation is a single LUT2 OR, INIT `4'hE`,
with this Q and the direct common cold-reset net. Both physical endpoint release
banks and both physical FIFO release banks must share that OR, and the epoch Q
must terminate only at those twelve asynchronous preset pins. Completed packet,
configuration, counter and stop owners must retain the common cold-reset input.

Mailbox request/ack toggle crossings receive the same direct-chain checks.
Each current-width held bit must directly drive its same-index captured bit;
source/destination clocks and capture enable fanin are retained as facts. FIFO
Gray buses have widths 5, 5 and 7 respectively. Each bit must launch from its
corresponding Gray FF, permitting only a same-index binary-MSB merge, with two
marked stages and no first-stage fanout. Each FIFO has 38 captured payload bits
and a nonempty, exact RAM write-clock scope. Every payload/crossing endpoint is
queried separately so duplicate timing paths cannot satisfy coverage by count.

**Mapping policy:** these are deliberately strict expected mapping shapes.
Synthesis may trim unused config bits, merge reset banks, rename FFs, or choose a
different equivalent reset LUT. Such changes fail closed. Review the actual
mapping and supply a narrowly reviewed contract update with bit/constant/owner
correspondence; never replace a missing bank with a broad wildcard or reduce the
required census to make a checkpoint pass. The current contract is preparation,
not a claim that these expected shapes were observed in Vivado.

## Timing evidence and mandatory review

CPU must be 100 MHz, raw TX and both managed clocks 125 MHz, RXC exactly the
chosen 125/25/2.5 MHz scenario. The BUFGCE input must be the real raw TX net;
managed clocks must be that same propagated clock object, not an unrelated
125 MHz declaration. Every real sequential fanin of `txWireDrainedSource_reg/D`
must retain both max and min paths. Representative ordinary paths from encoder
to TX and from raw wake-delay ingress to RX are also required. This does not
prove that every other functional path is uncut; complete exception and clock
interaction review remains mandatory.

The collector writes endpoint timing facts, exact start/end scope lists,
per-bundle exception coverage, full CDC, clock interaction, ignored/coverage
exceptions, unconstrained timing summary, and the MAC's bus-skew report.
It rejects missing paths, relaxed/invalid requirements and negative slack on
its queried paths. It does **not** interpret successful report generation as
proof that a scoped skew constraint exists or covers all intended bits.

AMD [UG835 report_bus_skew](https://docs.amd.com/r/2025.1-English/ug835-vivado-tcl-commands/report_bus_skew)
has no `-from`/`-to` switches. The collector uses supported `-cells` reporting
and saves the exact expected scopes separately. Review every nonscalar bundle
against active 8 ns skew and datapath-only delay constraints, including missing,
ignored and overridden exceptions. Scalar bundles require no skew. See also
[report_exceptions](https://docs.amd.com/r/2025.1-English/ug835-vivado-tcl-commands/report_exceptions)
and [get_timing_paths](https://docs.amd.com/r/2025.1-English/ug835-vivado-tcl-commands/get_timing_paths).

Even successful collection ends with
`FACTS_COLLECTED_REVIEW_REQUIRED_NOT_NETLIST_QUALIFIED`. There is no automatic
physical acceptance state. Required remaining gates include complete CDC/RDC
classification, held-bundle enable/ownership correspondence, reset recovery and
removal, clock gating/stop-wake behavior, every actual raw/managed path's ordinary
setup/hold coverage, per-rate routed timing/skew, and pad/vendor/board evidence.
No source check or mock can discharge those gates.

## Short host-only check

    make native-mac-netlist-contract

This executes Python unit tests and the explicit Tcl query model, including
three rate models, malformed/old census and mapping, missing/multiple/reset
drivers, first-stage fanout, missing ASYNC_REG, wrong clock/INIT/reset polarity,
wrong held/Gray bits, cut/relaxed/invalid/negative timing, source/staging/DCP
drift, incomplete provenance, and five-bound scope/zero-partial-application
negative controls. No Scala compilation, RTL emission, hardware simulation,
Vivado or implementation is invoked.
