# Bounded RX capture-clock split proposal

Independent of PAD250 TX reset candidate. Default OFF source adapter must copy
3554932 board bytes exactly. ON preserves fabric rx_clock_buffer and adds a
DONT_TOUCH rx_capture_clock_buffer driven by the SAME rx_pad IBUF output. It
moves the existing3FF rx_reset_pipe to capture clock and sends capture clock to
the five SAME_EDGE_PIPELINED IDDRE1 C/CB inputs. No PLL, mux, divider, gated RXC,
new pad or input-delay assumption is introduced.

A10-bit falling-capture-edge register holds {fall[4:0],rise[4:0]}, including
both control bits. It receives exactly the common capture reset and feeds the
existing decoder-facing rise/fall wires. Reset deasserts from a capture-rising
FF, leaving a nominal half-cycle to the new falling-edge register. This new
recovery path remains timed. Stop at either clock polarity retains state;
asserting reset while stopped clears the whole pair asynchronously. Release
requires capture clock restart, as before.

Baseline IDDRE1 SAME_EDGE_PIPELINED emits a complete pair after capture rising
k. Baseline intended downstream decoder sampling is rising k+1. Proposed pair
register samples at capture falling k; fabric rising k+1 sees the same pair if
the half-cycle timing contract holds. Thus no additional decoder cycle is
expected, but a source-bound proof must establish this exact event relation.
All pair bits are arbitrary; DV/ER are never independently pipelined.

Let s = fabric rising insertion - capture rising insertion. The retime-to-
fabric setup nominal window is T/2+s; hold is T/2-s. The capture IDDR-to-retime
window is T/2 minus same-tree skew. With illustrative s=+0.447ns and T=8ns,
these are4.447/3.553ns before Q/net/check/uncertainty. This number is an old-
versus-new clock-net observation, NOT measured sibling skew or a signoff bound.
Use a formal event-order contract -T/2<s<T/2 for cycle-equivalence; physical STA
must establish a sufficiently guarded actual skew interval at each corner.

External pad capture timing is still the critical open gate: earlier capture
improves hold but consumes setup. Required early/late shifts differ. Require
all5 pins, both edges and all3 rates to pass; do not treat the0.447ns historical
hold improvement as safe setup reduction. No exceptions between sibling clocks.

Vendor capability: AMD UG572 Global Clock Inputs and Clock Buffers permit GC
inputs to drive the adjacent PHY global buffers. The ZU15EG database places
AA7 and24 BUFGCE resources in X3Y2. UG572 recommends placement by Vivado because
buffers share24 tracks; resource existence does not prove current occupancy,
legal simultaneous routes or reduced insertion. No hard LOC or dedicated-route
waiver is proposed. One additional BUFG, ten pair FFs and unchanged reset-chain
FF count are the source structural cost, not a mapped resource guarantee.

https://docs.amd.com/r/en-US/ug572-ultrascale-clocking/Global-Clock-Inputs
https://docs.amd.com/r/en-US/ug572-ultrascale-clocking/Clock-Buffers
https://docs.amd.com/r/2023.1-English/ug974-vivado-ultrascale-libraries/IDDRE1

## Source adapter and bounded proof

`export_board.py OUTPUT` is OFF and copies the original board bytes.
`--enable-rx-capture-sibling` emits the explicit source-only alternative. This
is not a complete native export or compatible with the old exact topology
audit. Integration must bind the new source inventory and audit this topology.

`formal_check.py --yosys PATH --output FRESH_DIRECTORY` snapshots actual pair
RTL and source-extracts the existing3FF reset block with only its clock name
changed. It models IDDRE1's complete paired output availability on capture
rising edges; it does not simulate the vendor primitive or the serial RX input.
The independent reference is the original decoder-facing prior pair sampled
on rising k+1. The candidate is sampled on corresponding fabric rising edges.
Offsets-3,-2,-1,0,1,2,3 of8 phase steps are separate bounded checks (both relative edge orders, absolute skew less than half a cycle). Arbitrary advance permits clock stalls at
any modeled phase. Reset/inhibit and10-bit payload are unconstrained. Negative
mutations drop pairs, swap the two control bits and break reset-to-zero.
Actual downstream decoder state and its separate reset logic are not proved.

## Required paired timing audit before promotion

Keep a single related `phy_rx` source clock at the physical RXC port. Both BUFG
branches must inherit it. Existing8/40/400ns rate scenarios,2ns external launch
phase and +/-1.050ns input delays remain untouched. Do not declare sibling
branches asynchronous or false-path their data/reset paths.

For each fresh rate scenario, require all min AND max paths for:
- each of ten IDDRE1 Q1/Q2 outputs to its falling-pair D endpoint;
- each falling-pair Q bit to every reachable sequential decoder data endpoint;
- capture reset-pipeline Q to each IDDRE1 R and each pair-register async reset;
- all five external data/control ports to both capture clock edges.

Missing/disabled paths are failure, not a pass. Require both BUFG inputs to
be the same original IBUF output, distinct preserved BUFG primitives, exactly
ten falling-edge pair FFs and no data/control bypass. Verify all capture loads
(IDDRE C/CB, pair FF clocks and reset chain) use capture clock, while decoder
clock remains fabric clock. Record all clock insertion extrema, measured skew,
Q/net/check/uncertainty terms, clock roots, fanout, pulse widths, min period and
clock resource legality. Placement and mapping may optimize source estimates.
Current355 full per-pin/per-edge/per-rate reports are unavailable here.

## Historical reference and alternatives

The source-bound old223 summary has RXD1 setup+0.162ns and RXD3 hold+0.134ns,
both8ns; it is not a complete matrix. Its RXD3 AB11 data delay1.459ns matches
the parent-supplied355 path exactly. BUFGCE_X0Y67 and X3Y2 match as well; clock
net1.150ns became1.597ns, explaining0.447ns hold degradation to-0.313ns. Old
report SHA256:7efe8d471923e48d45328ebb2d6ff5151feefbefad86f4dcd84878689363975b.
Current355 rows are parent-supplied, with no cloud report bytes to hash. Do not
claim exact provenance for unavailable current files or combine versions as
one implementation.

A uniform delta based on355 extrema allows only0.313..0.383ns at zero margin,
or at most35ps symmetric margin. Real early/late clock changes differ and need
per-path checks. A full447ps clock reduction is not automatically setup-safe.
The split may or may not reduce the physical capture tree; no slack is claimed.

A calibrated IDELAY/ODELAY cascade is another supported alternative beyond
1100ps, but paired TIME elements need equal settings and have added intrinsic
insertion. Native BITSLICE capture requires valid BITSLICE_0 strobe entry,
inter-byte resources and calibration/rate analysis; AA7 being GC alone is not
proof. PHY RTL8211F initialization intends RX delay enabled, but current board
identity/register readback is unavailable. No PHY or external timing change is
made. RX timing remains an open physical qualification blocker.

## Focused decoder harness (separate evidence)

`check_decoder.py` consumes an explicitly supplied, inventory-verified3554932
native export. It uses the actual emitted CdcResetRelease, CdcLevel and
TriSpeedRgmiiRx after pinned sv2v translation, and binds the actual managed-MAC
integration source. The test reconstructs its rawRxRelease/rawRxOpen/abort
wiring around baseline and candidate decoder instances. Media-open and rate
commands are arbitrary. It compares accepted data/error, valid, byte-step,
odd-nibble and rate-ready at corresponding decoder edges.

This adds actual decoder state coverage beyond the pair proof. The paired
serial-input availability/stability contract remains explicit; no analog
IDDRE1 behavior is inferred. PHY/IDELAY readiness loss separate from common
reset is not modeled as a complete board episode. A valid-byte burst is not
an entire Ethernet MAC/CRC acceptance test. Any receipt's exact offset/stall
coverage controls the claim; absence of a receipt is not a pass.

The final pair proof has unconstrained initial datapath/reset state and gates
assertions after a real sampled inhibit. Only event phase/proof bookkeeping
initialize. Its cover reaches nonzero data, a stalled clock phase and restart.
No unreset power-up claim or arbitrary rate-transition edge-waveform proof is
made. All register state changes are still subject to physical timing.

Vendor references for the paired-output and cascade contracts:
https://docs.amd.com/api/khub/documents/kFbaUC5HGcXyGNauhgU6Gw/content
(UG571 v1.16, IDDRE1 modes; IDELAY/ODELAY CASCADE attributes; native-mode
BITSLICE clocking.) Same-site cascaded TIME elements must have equal delays;
fixed cascade insertion is additional to the programmed delay.

## Recorded cloud checks

- Four export/source tests pass.
- Pair r4: seven offset orders,48 steps, arbitrary stalls and unconstrained
  datapath initialization after reset qualification; restart cover; three
  rejecting mutations. Source/exporter/IDDRE1 bindings included.
- Decoder r3: seven offset orders,80 steps, continuous phase advance.
- Decoder r5:24 explicit stop/restart cases (offset-3/0/+3 × all8 phases),96
  steps; actual physicalValid equality when capture is open; accepted-byte
  restart cover and two rejecting pair-corruption mutations.
- Decoder r2 arbitrary-stall80-step case timed out after180 seconds at offset+1.
  It has no PASS receipt. Its run directory and timeout observation are kept.
  The explicit stop matrix does not relabel that timeout as an arbitrary-stall
  decoder proof. Generated evidence stays outside Git.
