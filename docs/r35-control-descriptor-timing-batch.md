# R35 control and TX descriptor timing candidate

## Measured motivation

The r34i2 routed reports identify two synchronous setup cones, rather than the
older GMAC CSR ready loop:

- CPU300: `memPacket_address[32]` through translation/cache quiescence,
  `privateDrained`, and maintenance-resume FIFO ready to `fifo_11/issueBinary[1]/CE`.
  Slack -1.949 ns; data 4.771 ns (logic 1.305, routing 3.466).
- Fabric250: `packetDma/txQueue/stageLength[3]` through rounded-length and endpoint
  arithmetic, descriptor legality, write admission, and STOP inhibition to
  `packetDma/txSent[7]/CE`. Slack -2.167 ns; data 5.835 ns
  (logic 1.776, routing 4.059).

## Changes and contracts

Cancellation-enabled I1 admits one matching acknowledged resume token into a
local pending owner. FIFO ready depends on registered ownership and epoch only.
Actual release still requires live `privateDrained`; a saved drain observation
never substitutes for it. Home remains closed until `maintenanceResumed`, whose
existing two-real-CPU-edge proof starts at actual release, not token acceptance.
Pending ownership blocks duplicate admission, and coordinated reset discards it.
The non-cancellation endpoint is unchanged. Management release gains one CPU
edge when already drained; normal requests gain no stage or throughput limit.

TX LENGTH writes capture both full-width legality and a bounded rounded word
count on the same edge as the original staging field. POST uses bounded endpoint
and overlap arithmetic, while retaining full-width address/length rejection and
an endpoint carry for the top-of-address-space case. No descriptor, launch,
completion, or STOP handshake gains a cycle or changes credit ownership.

## Verification scope

The focused Scala constructor/elaboration check covers small, unaligned, and
top-of-64-bit-space apertures. The Python resume test checks bounded temporal
properties and source guards; it is **not RTL simulation**. Hardware acceptance
uses the freshly emitted real three-clock I1 runtime native fixture and focused
TX GSIM queue-event, word-count, and high-address packet tests. Receipts and logs
are retained under `out/r35-control-descriptor-batch` and `build/gsim`.

Recorded functional results (2026-10-23):

- Combined Scala compile and descriptor constructor test: PASS.
- Resume bounded model/source checks: 5 PASS, explicitly not hardware evidence.
- Fresh real I1 runtime RTL: both 5/7/11 ns and 11/5/7 ns half-period clock
  cases PASS; normal release, explicit cancellation, three real watchdog paths,
  stopped CPU clocks, backpressure, stale epochs, and coordinated reset.
  All three independently corrupted data/store/interrupt oracles were rejected.
- Supplemental `test_runtime_resume_owner_native.py` uses the same qualified
  RTL, with an explicit internal live-drain stall. Pending ownership, late
  cancel/duplicate rejection, no early release, exactly two post-release CPU
  edges, and reset while pending: PASS. This deliberately injected state is not
  a claim that normal traffic creates that stall.
- TX GSIM: queue-event checks including 17 adjacent-cycle staging/POST cases;
  28 word-count cases including nine invalid descriptors with zero memory
  effects; 158 high-aperture packet cases: PASS. Queue negative oracle rejected
  its deliberate mismatch. Arithmetic equivalence: 78,650 cases, separate from
  hardware qualification.

Reproduction (source `scripts/cloud/env.sh` first):

```sh
mill -i -j 1 IonSoC.test.testOnly ip.EthernetTxDescriptorQueueSpec
python3 simulator/cdc/test_runtime_resume_owner.py
python3 simulator/gsim/common/i1_runtime_cdc_native.py --out <fresh-runtime-dir> --emit
python3 simulator/cdc/test_runtime_resume_owner_native.py \
  --runtime-out <passing-runtime-dir> --out <fresh-probe-dir>
```

TX invocations are retained in `build/gsim/r34i3-tx-evidence/run_checks.py`, and
per-model hashes in its neighboring `receipt.json`; the three model directories retain
their elaboration, compilation, and independent driver logs.

No routed timing, hold closure, CDC waiver, board boot, or throughput improvement
is claimed by these functional tests. RGMII RX hold and asynchronous reset
recovery findings are separate work; no false paths or clock relaxation are
introduced here.
