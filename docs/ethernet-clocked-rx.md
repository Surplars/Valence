# Isolated Ethernet clocked RX qualification

This is the user-authorized network-only Icarus exception. CPU tests remain GSIM; do not use Verilator. The fixture is the actual GmiiFrameRx at 125 MHz, unchanged EthernetFrameClockBridge(16), EthernetDmaFrameAdapter and EthernetPacketDma at 100 MHz. It excludes physical PHY/CDC timing, DDR, coherent Home and Linux.

The checked-in Scala wrapper and SystemVerilog testbench are byte-identical to the independently reviewed, executed fixture. The new portable orchestration script has only been checked with `--help` and `--dry-run`; its repository Mill entry point has not been executed as part of packaging. No hardware behavior is rewritten by this packaging.

## Existing tools only

Supply existing executable paths via MILL, FIRTOOL, IVERILOG and VVP, or corresponding flags. No tool acquisition/setup is performed. The original emission used firtool 1.135.0 and Chisel 7.3.0. Dependencies must already be available to Mill. The active repository entry point is IonSoC.test.runMain; this compiles the normal repository test module but elaborates only the isolated fixture. Budget that compilation separately from the small emitted models. No whole-SoC elaboration is requested.

Example plan, with no compilation or simulation:

    python3 scripts/run_ethernet_clocked_rx.py --repo . --out /tmp/ethernet-clocked-results --dry-run

Example execution after supplying installed tool paths:

    python3 scripts/run_ethernet_clocked_rx.py --repo . --out /tmp/ethernet-clocked-results --mill "$MILL" --firtool "$FIRTOOL" --iverilog "$IVERILOG" --vvp "$VVP"

The output directory must not already exist. Default free-space floor is 800 MiB; default per-stage wall timeout is 3600 seconds. Timeout/interruption kills and reaps the stage's own process group; an incomplete case never counts as PASS. Runs are sequential and each case has a unique cwd/log. The runner does not automatically resume or rerun completed cases.

## Frozen behavior and coverage

Source hashes are verified before building and after all runs; a mismatch requires requalification, not silently updating the manifest. No hand RTL rewriting is used. Exact approved firtool options are `--lowering-options=disallowLocalVariables` and `--default-layer-specialization=enable`, with all verification assertions retained. Expected production-assertion counts are 9/14/12/17 for old/old, DMA-only, MAC-only and both. A separate negative control actually trips the MAC bank-limit assertion in every variant.

The full matrix is unchanged:

- 16 principal cases: four prefetch combinations ×60/1514-byte bodies ×always-ready ACK 1 or deterministic ready/reply stalls ACK 64. Each offers 4096 measured frames after 16 warmup frames with legal 12-byte IFG, then drains all accepted work.
- 28 positive smoke cases: four clock phases, coordinated partial-capture reset, response/backpressure cases and all seven tail-byte masks.
- 16 negative controls: corrupt byte, early completion accounting, duplicate generation and the actual production MAC assertion.

Independent CRC/frame, posted-generation/order/address, packet/status, write-response/committed-memory and CDC beat ledgers are preserved verbatim. Stable blocked offers and final storage/ownership drain are checked. Rates use real picosecond timestamps and body bytes excluding FCS/preamble/IFG; fixed-window and including-drain rates remain separate. Occupancy and aggregate stall counters include warmup/drain. `empty_stalls` only observes rxOffer-empty cycles. Reset smoke has no accepted memory transactions outstanding.

All emitted source, tool/fixture hashes, exact commands, logs and completion receipts are retained. The original execution passed all 16 principal,28 positive smoke and 16 expected-negative cases; portable-runner dry-run validation is not a new hardware test result.
