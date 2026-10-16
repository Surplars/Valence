# Isolated RGMII reset-distribution placement experiment

Default OFF: no production source, export flag, preset, build entry, or timing
constraint was changed. Sourcing `candidate.tcl` defines procedures only. This is
an unqualified candidate for the next authorized combined Vivado implementation.
Do not run a separate implementation or generate a bitstream for these fixtures.

## Why keep the existing state bit

Current `native_rgmii_trispeed_quarter.sv` uses one falling-PAD release FF for all
serializer resets. The previous-clock carry and other nineteen loads share its
physical release epoch. Cloning it would create two independently resolving
asynchronous-preset FFs and break the current topology proof. Ideal RTL equality
would not prove equal physical release epochs close to a PRE recovery/removal
window. No clone or reset-phase change is included.

Historical 223453b endpoint evidence places the original source at tile (63,43),
while all twenty loads are in tile x73–78/y120–137. Twelve symbol registers sit
at x73–76/y121–123, phase at (77,122), carry at (78,137), and six OSERDES loads at
(78,120)/(78,135). Source-to-load Manhattan tile distances are 89–109 (sum1888).
At the load median (76,122), distances would be 1–17 (sum94). Tile coordinates
are an unweighted geometric proxy, not physical distance, legal placement,
route delay, or timing improvement. Run `geometry.py LOGICAL_ENDPOINTS.tsv`
to reproduce the read-only calculation and input hash.

The follow-up matched DCP/EDIF input query establishes a real tradeoff: PRE is
canonical `tx_release/tx_reset_pipe[2]`, driven by the RAW125 reset stage
`tx_release/tx_reset_pipe_reg[2]/Q` at the **same SLICE_X95Y43/BFF2**. The release
FF is at EFF there, both in clock region X3Y0. All twenty sinks are X3Y2. Its
PAD clock comes from `network_clock/quarter_div/O`, BUFGCE_DIV_X0Y11 in X3Y2.
Moving only the release FF lengthens its previously colocated PRE path across
two clock regions. RAW125-to-falling-PAD PRE also has a nominal 2ns phase budget.
Thus this moves the long reset connection upstream (with fanout one on this
specific branch) rather than eliminating it. No timing win is established.
Do not enable the candidate until this tradeoff is evaluated in the authorized
combined physical run; source-PRE non-regression is an acceptance gate.

The three upstream `tx_release/tx_reset_pipe_reg[0..2]` stages are all
preset-high FDPEs with `ASYNC_REG=true`, colocated at SLICE_X95Y43 in clock
region X3Y0 (BELs DFF2, AFF2, BFF2). Their common clock is the RAW125
`network_clock/raw_div/O`, BUFGCE_DIV_X0Y9 in X3Y2, distinct from the inverted
PAD250 clock on the pad-release FF. Their D chain is GND → stage0 → stage1;
CE is VCC. All three PRE pins use the inhibit net driven by
`tx_release_i_1/O`, a LUT2 at SLICE_X106Y44/H6LUT in X3Y0.

Relocating all four FFs together could retain the interstage and stage2-to-pad
PRE locality, but would move the long boundary to inhibit-LUT-to-three-PRE
connections. It also requires auditing every upstream stage-Q consumer,
ASYNC_REG placement behavior, clock/control-set legality and all associated
recovery/removal paths. This is **not** part of this candidate: the recipe
continues to constrain only the existing pad-release FF, with no automatic
enabling. Four-FF relocation needs a separate reviewed consumer/proof scope;
no reset timing issue is claimed fixed by either geometric observation.

## Explicit invocation, after review

Before placement in an already bound and audited T1 design, an implementer may
source this file and explicitly call:

    valence_reset_distribution::apply u_rgmii SLICE_X109Y120:SLICE_X116Y139

This example follows the historical load cluster, not a universally approved
region. Reconsider it against the actual candidate placement and PRE-driver
location. The procedure verifies all sites exist and are SLICEL/SLICEM in one
clock region, but cannot pre-prove control-set packing or routing legality.
It adds only the original release FF to one hard region and leaves BEL/LOC
selection to the placer. It rejects preexisting placement ownership and requires
an exact twenty-load shared reset topology. No original sink is moved or pinned
by this recipe. Other cells can use the region; it is not an exclusive area.

The existing production topology audit is mandatory, then the procedure checks
FDPE, INIT1, falling edge, constant D0/CE1, 4ns clock/0–2ns waveform, PRE driver,
and exact reset loads. A postcheck requires unchanged control nets and clocks
and one-cell pblock membership. Existing clocks and reset checks are retained.
A postcondition error means discard the experimental build; do not route it.

## Qualification gates, still pending

1. Establish source identity for the full combined candidate. Capture the real
   upstream PRE driver, its placement/clock, PAD clock route and original
   release-PRE recovery/removal margins. The upstream path can become worse
   when moving the source toward the outputs. Historical output-load geometry
   alone does not settle that tradeoff.
2. Apply the optional region only in the next authorized combined run. Check
   legal placement/control sets/clock resources, placement and routing DRC,
   unchanged twenty-load reset topology, original FDPE polarity/INIT and all
   six pad DDR clocks/resets. No clone, new reset stage, phase change, clock
   exception, false path, or multicycle is allowed.
3. Compare before/after full-clock-expanded max/min timing for upstream PRE,
   all twenty downstream reset endpoints, falling-edge removal, clock pulse
   widths and all affected data paths. Report actual worst recovery/removal
   and clock skew, plus any newly limiting endpoint. Preserve the original
   setup/hold constraints, 1.250ns PHY budgets and 10/100/1000 scenarios.
   Candidate acceptance requires no regression of source PRE or the other
   nineteen receivers, not merely improved previous_clock recovery.
4. There is no RTL functional delta to qualify here; production RTL was left
   byte-identical. Host mocks are only recipe tests, not an executed netlist
   equivalence proof. Before a hardware/startup claim, retain or rerun an
   authorized GSIM or Yosys formal check bound to actual RTL, all rates and
   both selected-half modes, with an independent ODDR contract. Cover reset
   assertion/release in every raw/PAD phase class, repeated reset/relock, and
   the very first TXC/data/control symbol without a warm-up blind spot.
   Check asynchronous pin quiescence, first captured pair/half ordering,
   positive-edge TXC stability and first active TXC half-pulse policy. Include
   reset-epoch and previous_clock corruption negatives. Formal may quantify
   arbitrary input symbols (including every rate) and asynchronous reset
   event ordering via a multi-clock transformation; it does not prove analog
   metastability, recovery/removal, clock-to-Q, or vendor pad startup. Those
   remain physical/vendor/board gates. Do not use the historical Icarus flow.
5. The existing `fpga/next/tests/trispeed_quarter_pad_tb.sv` masks monitoring
   for 10–12 raw cycles after release and is not sufficient first-symbol
   coverage. Do not relabel historical behavioral receipts or this host test
   as current all-rate/startup qualification.

Local test: `python3 fpga/zu15eg/reset_distribution_candidate/test_candidate.py`.
Five host tests cover inert sourcing, one-cell region application, fifteen
pre-mutation negative modes, three invalid regions and a failed postcondition.
No Vivado, GSIM, hardware simulation, routing or bit generation was run here.
