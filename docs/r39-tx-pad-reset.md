# Single PAD-domain TX reset-release candidate

## Why the physical-only attempt was not accepted

The exact three-stage RAW125 release-chain move preserved logic and clock roots,
but nine of thirteen mapped functional reset paths remained negative (worst
-0.600 ns). It fixed the old worst sink while worsening others. This is not a
qualified placement and is not the basis for a timing waiver.

The existing `native_rgmii_trispeed_quarter.LOCAL_PAD_RESET_RELEASE=1` option is
the bounded RTL candidate. One ordinary negative-edge PAD250 FF has D=0 and
asynchronous PRE from the **complete** RAW125 release chain. Its Q resets all
serializer payload, phase, carry and ODDRE1 state. There are no independent
release chains or duplicated ASYNC_REG stages. The source default remains 0;
the common top is not changed by this test-only checkpoint.

At ideal related-clock edges, RAW release t0 is followed by local release t2,
phase transition t4 and the first complete pair capture t6. The original mode
also skips capture at t2 because phase is still preset high. Thus the candidate
moves eleven mapped falling-edge functional reset consumers from an inter-tree
2 ns window to a same-PAD falling-to-falling 4 ns window. Phase and previous_clock
remain positive-edge consumers. The **new RAW-to-local PRE still has a 2 ns
window** and must pass actual recovery/removal. Every downstream reset arc stays
timed; no new exception is permitted. Physical improvement is not yet measured.

## Focused executable proof

Generate the unpruned production codec using the existing emitter:

```
source scripts/cloud/env.sh
mill -i IonSoC.test.runMain ip.TriSpeedNativeRtlMain out/r39-tx-pad-reset/rtl
python3 fpga/zu15eg/run_tx_pad_reset.py \
  out/r39-tx-pad-reset/rtl/tx/TriSpeedRgmiiTx.sv \
  out/r39-tx-pad-reset/behavioral --mode behavioral
```

The independent packet checker covers 10/100/1000 Mbps, TXEN/TXER, first frames,
three explicit frame aborts, paired-clock pauses, idle RDY loss, and cold reset.
The old/new boundary pin comparison runs on **every PAD edge starting before the
first reset release**, including serializer startup. No monitor warm-up is used.
Current behavioral result: 8 frames, 73 bytes including one pre-abort byte,
3 frame aborts, 3 paired pauses, 5 releases, 11036 pin comparisons and 2743 whole
pair captures. Ordinary corruption negatives for payload, control, phase and
reset are all rejected. Logs and source hashes are in the generated receipt.

Icarus requires only eight emitted `automatic logic` temporaries to become block
static declarations followed by assignments on every entry, retaining expression
and assignment order. This is explicitly recorded; native simulation uses the
unmodified emitted codec. The behavioral ODDR substitute does **not** implement
the vendor reset hold and cannot establish native startup equivalence.

Run the same test using the official installed Vivado 2025.2 tools:

```
python fpga/zu15eg/run_tx_pad_reset.py rtl/TriSpeedRgmiiTx.sv simulation \
  --mode unisim --vivado-bin "E:/Xilinx/2025.2/Vivado/bin"
```

Use the actual installation path. The native package contains no behavioral
primitive substitutes or vendor files. Compile, elaborate and positive simulation
warning/error text is fail-closed. AMD UG571 describes ODDRE1 as mapped to
OSERDESE3, with reset release holding SRVAL for four cycles. Both old and candidate
release before the same first t4 positive PAD edge, but this expectation must be
verified by UNISIM, not inferred as a native PASS.

Source: https://docs.amd.com/api/khub/documents/kFbaUC5HGcXyGNauhgU6Gw/content

## Limits and integration prerequisites

- First GMII admission in the fixture waits six PAD positive edges after release;
  continuous pin comparison does not prove immediate t0 traffic acceptance.
- Normal cold-start source has PHY initialization wait `cpuHz/20`, initial
  `initialized/link=0`, media `stopNewTraffic` and TX abort. This is separate from
  the pad-only fixture, not a measured whole-platform startup proof here.
- Running `delay_ready` loss resets pads and external PHY immediately, but is not
  wired directly into internal MAC admission. Existing watchdog/PHY handling is
  delayed. The fixture's explicit admission clamp/abort is **not** proof that no
  whole-SoC owner is accepted during that interval. No fault-recovery improvement
  is claimed by this candidate.
- Paused clocks preserve the RAW125/PAD250 phase relationship. Arbitrary independent
  stops are not supported. Mid-frame clock stretching is hostile phase testing,
  not an Ethernet-compliant running clock claim.
- RX450, CPU/fabric 300/250 optimization targets, actual-mode constraints, clock
  roots and all existing ownership/reset interfaces remain unchanged.
- Before a new native candidate: explicitly enable the common top parameter,
  retain RX cascade450, check the mapped one-local-driver topology and all reset
  arcs, then route and inspect setup/hold/recovery/removal/DRC. Do not reuse the
  old nineteen-load physical relocation helper on this changed topology.
- No STA, bitstream, board, metastability or complete SoC qualification follows
  from behavioral or UNISIM pin tests.

Native attempt r1 compiled successfully but stopped at xelab `XSIM 43-4099`
because the emitted codec has no timescale directive. No simulation ran. The
r2 runner supplies xelab `--timescale 1ns/1ps`; it does not alter emitted RTL,
primitive models, warning severity or the preserved failed receipt.

Native r2 compiled/elaborated and its positive pin oracle passed with the same
8-frame counters. The runner correctly stopped before negatives because unused
RX IDELAYE3 cells printed twenty generic TIME-mode reset notices. The actual
Vivado 2025.2 IDELAYE3.v lines 441–443 print that notice on every asserted RST in
TIME mode, without checking a reset-sequence violation. Therefore the old
stimulus is not classified as an invalid sequence from this notice alone.
For r3, only the two unused RX `delay_reset` testbench inputs are held at 0;
TX common/local resets, cold/RDY inhibit stimuli and every oracle are unchanged.
RX calibration/reset is deliberately outside this TX-only test. No production
RTL, warning filter or primitive substitute changes. This is not an RX or whole
board native qualification.

## r3 native result and common-shell opt-in

Actual Vivado 2025.2 UNISIM r3 completed in 26.137 seconds, exit0. Compile,
elaboration and all runtime logs had zero warnings. The positive run checked
8 frames /73 bytes /3 aborts /3 paired pauses /5 releases /11036 pin comparisons
/2743 pair captures; all four ordinary negatives were correctly rejected. This
establishes the TX-only primitive/pin scope above, not RX or STA qualification.

The common shell now exposes `TX_LOCAL_PAD_RESET_RELEASE=0` and passes it to the
existing boundary option. Default behavior is unchanged. The next diagnostic
synthesis must explicitly select both generics:

```
RX_CASCADE_STAGE_DELAY_PS=450 TX_LOCAL_PAD_RESET_RELEASE=1
```

`test_tx_pad_reset_integration.py` reverses only this exact parameter/connection
delta and compares all remaining shell bytes with pre-change commit c1457f6.
Default-on, bypassed-hook and unrelated RX/clock mutations are rejected. The
existing TX RTL bytes are pinned unchanged. No old frozen input inventory or
receipt is rewritten. A new production emission is necessary because the last
R37 emission predates the already-reviewed CPU reset distribution source fix;
this is one incremental emit, not another functional redesign.
