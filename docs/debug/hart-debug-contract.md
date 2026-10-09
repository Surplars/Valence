# Hart debug reservation, version 1

Status: **interface reservation only**. The running CPU has no halt/resume/step,
debug CSR, trigger, or abstract-register implementation added by this change.
Neither production top instantiates the new port or unavailable terminator.
Existing RAM-download DMI addresses and the 64-bit BSCAN protocol are unchanged.

`src/main/scala/ip/debug/HartDebugContract.scala` provides a future integration
boundary without introducing halt fanout into a timing-qualified two-issue core.
The older `HartDebugReservationPort` remains an unused legacy declaration; new
work should use `HartDebugControlPort`. They are not implicitly interchangeable.

## Reserved contract

- One command channel serializes halt, resume, step and abstract register access.
  Acceptance is not completion. The response echoes its 8-bit token and 32-bit
  reset epoch, carries a distinct result code, and remains stable when stalled.
- Halt completes only at a precise architectural boundary. Resume completes only
  after the hart actually leaves Debug Mode. Step completes after it stops again.
  A watchdog must report an uncertain/incomplete operation, never synthesize an
  acknowledgement or replay an accepted command.
- Register requests carry a 16-bit abstract register number, read/write, aarsize
  and 64-bit payload. CSR and GPR encodings are reserved; optional unsupported
  registers/sizes must fail explicitly. A future adapter must enforce halted
  state, x0 behavior, CSR permissions/WARL, and materialize the committed rename
  map. It must not expose speculative physical registers.
- `preciseStop.valid` is independent from command acceptance. Its snapshot holds
  dpc, privilege, cause, epoch and retirement sequence, together with committed
  architectural state, younger-op squash, older-memory drain, and no outstanding
  CPU transaction evidence. All predicates must hold before reporting halted.
- Trigger observations reserve allocation sequence plus epoch, PC/address,
  execute/load/store classification, trigger index, timing and action. This is
  metadata for a future qualified trigger implementation, not a halt wire.
  Simultaneous matches require arbitration/aggregation before this single-event
  representation. There is no configured trigger count or comparator today.

The internal operation/result encodings are **not** DMI commands, `cmderr`, or
`dcsr.cause` encodings. A future DM must perform explicit translation and qualify
its own register behavior. Standard abstract GPR numbers start at 0x1000; dcsr
and dpc are 0x7b0 and 0x7b1. The architectural requirements are defined by the
[RISC-V Debug Module specification](https://docs.riscv.org/reference/debug/v1.0/debug_module.html).

## OoO implementation obligations before enabling an adapter

These are Valence integration requirements, not claims of existing behavior:

1. Establish one ordered stop boundary in the two-wide retirement packet. The
   younger slot cannot commit when stopping before it. Squash wrong-path work;
   invalidate stale completions with non-reused ownership/epoch. Frontend empty
   and ROB empty alone do not prove memory or architectural quiescence.
2. Stop new architectural admission, but keep clocks and response consumers
   running. Drain accepted loads, stores, MMIO, page walks, atomics and cache
   writebacks under their existing ownership. Never abandon a presented stalled
   bus request or reuse a timed-out tag. Define coherent DMA/probe behavior while
   halted; debugger access cannot silently bypass permissions or caches.
3. Capture the correct next PC, trap state and privilege. Register writes must
   update committed and speculative maps consistently before restart. Resume
   must serialize I-cache/TLB changes and handle interrupts and WFI correctly.
4. Step means an instruction **or a trap boundary**, not necessarily one instret
   increment. Enforce it across both retirement slots, compressed instructions,
   branch redirects and exceptions. No trap-handler instruction may escape the
   stop boundary. EBREAK/debug cause priority and dpc are architectural rules.
   [Sdext](https://docs.riscv.org/reference/debug/v1.0/Sdext.html).
5. Trigger matches must be tied to surviving instruction identity. An execute
   breakpoint before an instruction forbids its side effects. Data watchpoints
   need explicit before/after semantics and must not allow speculative MMIO.
   Implement trigger WARL/enumeration and dmode/action permissions before claiming
   a hardware breakpoint. Do not convert all EBREAK exceptions into Debug Mode.
   [Sdtrig](https://docs.riscv.org/reference/debug/v1.0/Sdtrig.html).
6. The future hart reset controller owns `resetEpoch`, incremented before new
   commands after a coordinated reset and never reused while an older response
   can exist. TCK/TAP reset only invalidates transport association; it must not
   reset a halted hart, resume it, discard fabric ownership, or masquerade as
   CPU cold reset. Reset while a command is accepted requires an explicit stale
   completion or a documented coordinated cancellation handshake.

`HartDebugUnavailable` is the only module supplied here. It accepts one request,
returns `Unavailable` after one cycle, retains its echoed identity under response
backpressure, and advertises available=halted=preciseStop.valid=0. It cannot access
CPU registers, memory, reset control or DMI. Capacity is one, throughput at most
one command per two cycles. No area/Fmax or connected-CPU behavior is claimed.
Both participants must suppress transfers during module reset. That reset
cancels a pending unavailable response; an eventual transport adapter must treat
it as coordinated epoch cancellation, not promise response retention across reset.

## Download candidate and remaining qualification

The smallest enabled source candidate retains the existing media path, explicitly
selects `--experimental-jtag-bscan 2`, and builds a matching BootROM with
`--jtag-download`. A separate MAC+JTAG candidate additionally selects
`--experimental-trispeed-ethernet`; that combination requires its own final
export/ROM/hash receipt, not a union of two old PASS labels. The hart reservation
has no enable switch because there is no working hart debug adapter yet.

Required gates, in order:

1. Cloud source tests: host/config/USER-allocation mocks, port-binding checks,
   Scala interface elaboration, focused endpoint tests, and source hash checks.
   Repeat the real-CPU coherent download smoke on the chosen integrated source.
   Its old PASS is historical: ten source bindings differ at base 66c06d7.
2. Execute the exact production C BootROM's CRC/epoch/CLAIM/autostart path on the
   selected CPU/cache geometry; the earlier assembly-ROM smoke does not do this.
   Check network DMA quiescence, clean/dirty cached lines, denied regions, timeout
   and late responses, abort/re-arm, bad CRC, stale COMMIT, and no failed launch.
3. Native independent-clock HDL: `simulator/jtag/run.py` (TAP, CDC, phase-aligned
   completion race, widths), `mutations.py`, and `bscan_run.py` (USER frame,
   DRCK/UPDATE/TCK phases, pause, short/long/malformed scans, reset and stop-clock
   recovery). Icarus/vvp are absent and installation is not authorized. Existing
   GSIM synchronous tests cannot substitute for these tests.
4. In a separately authorized desktop task, use installed Vivado simulation for
   the real BSCANE2/UNISIM path and compile the handwritten blackboxes. Source
   `bscan_user_tb.sv` is a behavioral pin model, not an AMD primitive model.
5. Run one combined enabled-image synthesis. Source the exported
   `board/require_jtag_chain.tcl` in the new netlist and retain its PASS. Offline
   checkpoints put dbg_hub on USER1; this does not certify new-image USER2.
   Guard must reject any second USER2 owner or unknown chain property.
6. Implement target-specific BSCAN clock/reset constraints. The existing
   `fpga/constraints/jtag-reservation.xdc.example` is for a standalone external
   TCK pin and is **not** a BSCAN constraint set. Constrain DRCK-to-UPDATE held
   data, UPDATE event/ack, negedge-TCK consumption and bundled mailbox data;
   inspect CDC/RDC, clock interaction, timing and exceptions on actual hierarchy.
   No broad asynchronous false-path waiver is acceptable. No such signoff exists.
7. Only after those gates, qualify configured-image SMT2/OpenOCD with board
   access authorization. Verify actual TAP order, all IR widths, observed ID,
   reset wiring and conservative TCK. Use the official SMT2 FTDI configuration;
   preserve the user's Vivado USB driver. Driver rebinding requires separate
   approval. Run actual Jim/OpenOCD parsing and the real USER capability exchange.
8. Initialize the adapter before arming ROM download. Verify small binary full
   readback, independent ROM CRC and CLAIM, then an observable guest marker;
   repeat failure/recovery tests and measure throughput. COMMIT is not proof
   that code ran. Do not promise Ethernet-class bandwidth.

The exact offline part profile remains IR12, USER2=0x903, ID fixed bits
0x04750093/mask0x0fffffff, configured FPGA required. It says nothing about other
TAPs or board scan order. See [BSCAN transport](bscan-user-transport.md).

No stage above licenses `target create ... riscv`, GDB register/step support, or
native OpenOCD `load_image`: these require a real architectural Debug Module.
