# Registered MAC CDC and physical epoch boundary

This batch is qualified by a short independent-clock RTL test of the actual
TriSpeedManagedGmac boundary. It is **not** CDC/RDC/STA, vendor gate timing,
FPGA bitstream or board qualification.

## Production changes

- Register mediaOpen in CPU/cold-reset, synchronize once per TX-managed,
  RX-managed and raw RX domain, and derive local abort as the same-state
  complement. Raw capture shares the raw RX open state. Abort is intentionally
  true during cold reset/startup; the runtime test checks no phantom events.
- Register ingressEmptySource and txWireDrainedSource in fixed raw125. The latter
  includes the phase-related managed TX owner; retain ordinary setup/hold timing.
- Register the complete original physical-epoch reset qualification as
  media/ingressResetSource (CPU, reset true). This fixes a reproduced inherited
  asynchronous reset pulse at releaseIngress→stable. The unmodified qualification
  reconverged state, activeLink and changed; both real endpoint releases were
  cleared while returnedReady remained high. This is RTL hazard evidence, not a
  measured physical pulse width.

The epoch register allows up to one CPU edge before assertion/deassertion.
Immediate CPU admission closure and FSM priorities are unchanged. Drain waits
for old returned-ready to clear; reopening still requires two real consumed-rate
ACKs and both returned endpoint-ready signals. Epoch assertion works while RXC is
halted. All complete packet, FIFO, counter and adapter owners remain cold-reset-only.

The source-level logical delta is +4 single-bit source FFs and -6 duplicate
synchronizer FFs, net -2. No data-bank or index mux change is introduced. This is
not a mapped utilization or timing result. The extra idle sample delays both
polarities; safety is established by owner/admission checks, not by calling the
latency unconditionally conservative.

## Short test entry

With the established Mill/Chisel/firtool toolchain and official Icarus/VVP already
installed, use a fresh directory:

    make native-mac-boundary-cdc MAC_CDC_OUTPUT=build/mac-boundary-review

The entry emits TXslots1 and2 sequentially, default maxFrameBytes2048 and four RX
banks. It uses supported disallowLocalVariables lowering and enables production
assertion layers inline. It verifies all source hashes around execution and
keeps commands, exact RTL/fixture hashes, real wait4 RSS/runtime, positive and
expected-failing negative logs. Reuse flags on fpga/next/check_mac_boundary.py
accept an exact export receipt plus RTL prefix and verify both source and RTL
before re-running only the independent host checks.

The wrapper instantiates the production MAC and real stop/wake policies. Only
PHY/watchdog discovery request inputs are bypassed in the bench. BUFGCE is an
explicit glitch-free digital pause model. No whole SoC, CPU, DMA memory engine,
long PHY initialization, Verilator or Vivado is invoked.

Coverage includes CPU100/rawTX125/AON50 MHz with phase offsets; RXC125/25/2.5 MHz;
absent/stopped RXC, startup abort, all six ordered rate changes, superseded
outstanding rate generations, a one-CPU-cycle speed pulse, first/last RX and TX
closure, data/status backpressure, complete RX drain during a later partial-frame
halt, stale embedded SFD rejection, managed stop/wake and first-frame wake.
Monotonic host generations identify reused physical banks. TXslots2 additionally
proves two simultaneous completed native owners and aborts both exactly once.
Final byte/keep/last/status/event/counter/CSR ledgers must agree. Payload, event
and false-stop negative corruptions must fail the ordinary independent oracles.

## Physical review inventory

fpga/next/mac-boundary-cdc-inventory.json names the new launch registers, five
level crossings, registered epoch path, retired duplicate chains and every one
of the nine mailboxes and three FIFOs. The emitted-RTL checker enforces the exact
mailbox/FIFO hierarchy and the unchanged scoped packet constraint recipe.

The source-bound board collector is **PREPARED_NOT_NETLIST_QUALIFIED**; it has
not been executed in Vivado. `make native-mac-netlist-contract` exercises only
the strict Tcl synthetic query model and Python staging/provenance checks.
The exporter stages the collector and five exact registered-level delay bounds
alongside the existing nine-mailbox/three-FIFO recipe. See
[the netlist review contract](mac-netlist-review.md) for the mandatory remaining
gates and the fail-closed checkpoint preparation entry. It inspects first-stage D fanin
from one registered Q bit, direct two-stage ASYNC_REG topology, no first-stage
functional fanout, correct reset polarity, all nine mailbox and three FIFO
scoped delay/skew constraints, related raw/managed timing and all media clocks
in report_cdc. An old hierarchy list or one-clock-pin count is insufficient.

Other legal frame sizes/RX-bank geometries, reset deassertion analog behavior,
metastability, routing, pad/PHY/vendor primitive timing and on-board behavior
remain unqualified.
