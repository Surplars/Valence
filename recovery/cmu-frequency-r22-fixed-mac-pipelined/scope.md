# r22: opt-in held-response outer MAC transport

This stage follows r21 commit `ae8f1cd9bee1bbff50083a8da61283c0c16bc9cd`.
It does not select either the fixed-source MAC or the FIFO candidate in the
production CommonMachinePlatform. CPU/fabric frequency policy, default clocks,
CPU 300/fabric 250 performance constraints, clock resources and reset topology
are unchanged. No remote upload is part of this stage.

## Reused implementation and narrow change

The existing `HeldResponseCdcDataFifo` was audited against its original import
`a49a28b`. Its SHA256 is unchanged:
`2302decf7392cfd64fdec49a4c2b76470f45c98f736644c2ddb64d0cef21d126`.
Historical native TileLink tests already exercised this implementation; r22 does
not substitute their receipts for MAC-specific tests or rewrite the FIFO.

`heldResponseStorage: Boolean = false` is added to `FixedMacBoundary` and
`FixedSourceManagedGmac`. The option selects this existing implementation only
for their four outer 37-bit, RAM-depth 16 TX data/control and RX data/status lanes.
All CSR, command, consumed-receipt, observation, IRQ, owner joins and TX/park
fences are retained. Internal MAC frame bridges and all other FIFO instances are
unchanged. The emitter adds explicit `*-held` modes; all existing modes retain
the old implementation by default.

The held implementation can pop an output, capture a pending synchronous-RAM
response, and issue the next read on the same destination edge. The pending
response retains its RAM slot until output capture and re-reads its still-owned
address throughout a stall. This preserves true synchronous-read behavior.
Capacity is depth+1=17, not 18. Registered source-full waits for synchronized
capture credit, with no speculative full+remote-pop borrowing. sourceIdle alone
still excludes the remote held output; destinationIdle includes pending read and
held output. Physical Gray-bus delay/skew and held-data constraints remain
integration obligations, not established by these simulations.

## Actual RTL comparisons

- The default production I1 performance300-static export has 248/248 SV files
  byte-identical to the immutable r16 reference. No normalization is used.
- The standalone selection-OFF export has 50/50 SV files byte-identical to r21's
  real test-MAC export, again without normalization.
- The enabled real-MAC export has 48 unchanged SV files. `CdcDataFifo_3.sv` is
  replaced by `HeldResponseCdcDataFifo.sv`; `FixedMacBoundary.sv` differs only in
  the four instance type names. It is NOT claimed to be byte-identical.
- Production and balanced enabled compositions emit successfully, preserve
  the existing 0/1 continuous-clock buffer and 2 managed-clock buffers, connect
  both MAC source and outer fixed endpoints to the same existing continuous 125
  leaf, and retain the MDIO divider 50 fixed cycles. No extra MMCM/buffer is added.

## Transport coverage

`fixed_mac_pipelined_tb.sv` is a separate r22 extension of the r21 transport
fixture. It instantiates the actual boundary, FIFO, mailbox and CSR modules;
MAC admission/park endpoints and producer-closed witnesses are explicitly
fixture models, not real CPU/DMA/Home or whole-system proofs.

Independent clocks use fixed 125 MHz and fabric 50, 250, approximately 71.428571 MHz,
with distinct phases. All four stream payloads, keep masks, last flags and held
outputs are checked against independent generated accepted-traffic sequences.

- All lanes fill to exactly 17 owned words and refuse further acceptance, then
  deliver 16 preloaded words on consecutive destination edges: supplied II=1.
- A 1,920-word interior window counts 7,680 actual valid bytes on each lane.
  Measured throughput per lane is 200 MB/s at fabric 50, 500 MB/s at fabric 250,
  and 285.714286 MB/s at fabric~71.43. These are transport-only measurements,
  not Ethernet line-rate or timing-closure evidence.
- Random ready backpressure, nonuniform keep masks and packet-boundary flags
  run each lane to 6,146 accepted/consumed words before reset. This is 384 wraps
  of the 16-entry RAM index and 192 wraps of the complete 5-bit ring pointer.
- Both clocks independently pause low while all lanes are full/backpressured.
  Owners remain unchanged; resumption followed by randomized draining preserves
  every word. This is full-state digital retention, not active drainage while a
  clock is stopped or physical glitchless-gate qualification.
- The original source-empty/destination-held TX stop fence, exact command
  receipts, stalled observations, coherent false observations, early release
  before a stop applies, and retained old votes until actual release consumption
  remain covered. Persistent IRQ survives the drained-data fabric pause.
- Two coordinated common cold resets occur with accepted owners, first with
  fixed clock paused, then with fabric paused. Each deliberately discards exactly
  17 words per lane. The new generations deliver 64 and 96 words per lane with no
  stale replay. No unilateral-reset or lossless-across-reset claim is made.
- Four negative cases mutate observed data, held-owner observation, receipt tag,
  or a post-reset data observation before the ordinary checkers. They must fail
  those specific checkers, not an injection-specific unconditional fatal.

## Finite real-MAC RX burst and matched reference

The real `FixedSourceTestGmac` retains the r21 fixture-only PHY policy waits 256
and 512, while the entire source, MDIO divider, media, watchdog, CSR and datapath
run at actual 125 MHz. A independent PHY pin model completes 51 MDIO initialization
transactions. Fabric is 50 MHz and recovered RXC independently 125 MHz.

The burst fixture sends 64 standard 1518-byte frames including FCS, hence 1514
forwarded body bytes each. Frames contain unique identities, broadcast address,
EtherType 0x88B5, independently generated deterministic bytes and reflected CRC.
An independent raw-wire monitor checks preamble/SFD/body/FCS and all 63 actual
12-byte IFGs. Total offered body payload is 96,896 bytes over 787,360 ns, measured
123,064,417.801 valid body bytes/second. This is a finite, specific 1G-cadence test,
not universal Ethernet line-rate qualification.

Each accepted fixed-side 37-bit RX data/status word is recorded in an external
acceptance-ordered ledger and compared against each exact fabric consumption.
Every delivered frame is independently checked against the transmitted frame
identity/payload, final keep 3, length 1514, and six status words
`[0x50000000,0,0,0x40,0,1514]`. Separate lanes may overtake; their owners are joined
only after drain. Valid bytes are counted from keep masks independently of word
counts. Source/destination word and byte counts must match exactly.

The enabled candidate is tested with always-ready sinks and independently
pseudo-random ready sinks. Both must deliver all 64 frame identities exactly once
in order, 96,896 body bytes, 24,256 data words and 384 status words with zero drops.
The reference uses the exact old r21 outer FIFO and identical always-ready
stimulus: it delivers an ordered subset, with exact accepted-word conservation,
and must account every missing physical frame as a real bank-full drop.

MAC accepted/drop/badFCS/cause events are counted in their fixed domain. Bounded
CSR polling independently verifies accepted frames, total drops, badFCS, accepted
bytes, all 8 drop causes and zero physical-ingress overflow/skips. Counts may not
be inferred merely from a final FIFO-empty indication. The reference permits no
other drop cause. No arbitrary delay is treated as counter convergence proof.

The final exact-ledger reference delivered 54 frames, dropped 10 due to bank-full,
and consumed 81,756 body bytes, 20,466 data words and 324 status words. Both
candidate modes delivered 64 frames with zero drops. Random-ready candidate
observed 8,080 data-held cycles and 128 status-held cycles while retaining all
96,896 body bytes. Final receipts are `transport-r2`, `burst-r3`,
`reference-burst-r2` and `lifecycle-r1`; the aggregate checks all seven positive
cases and eight expected ordinary-oracle failures. The reference positive case
expects its explicitly counted physical frame losses, not lossless reception.

Four negative cases mutate a payload observation, status observation, CSR-byte
counter observation, or the observed 37-bit transport LAST bit. They reach the
ordinary independent oracles, whose exact expected failure markers are checked.
This RX-burst fixture sends no TX packets or epoch commands. Separately, the
original r21 real-MAC lifecycle smoke at fabric 50 runs with the enabled FIFO,
covering real CSR/TX/RX, stop/park/release, held reply/status owners, retained
configuration/statistics, two good frames each direction and exactly one
intentional stopped-admission RX drop.

## Reproducibility and intermediate evidence

Final matrix receipts, exact source/RTL/tool/binary/log hashes, command lines,
per-case wait4 exit/resource records, compile/export records and the independent
aggregate verifier are archived with this scope. The verifier additionally
cross-binds every behavioral matrix to the exact emission it checks, rehashes
all inputs and tool-chain files, confirms default comparisons, and checks that
FIFO owner assertions were not compiled out. Real enabled RTL has 23 inline fatal
sites; boundary-only enabled RTL has 6. Generated RTL, VVP binaries, preprocessed
RTL and waveforms are not committed.

Preserved intermediate results are not relabeled as final evidence:

- burst-r1 failed SV compilation because a hexadecimal literal immediately
  preceded the ternary question mark without whitespace. Only fixture syntax was
  corrected; the original fixture, runner, log and failure receipt are retained.
- transport-r1 passed but labeled 384 RAM-index wraps as pointer wraps. The fixture
  label was corrected to separately report 384 RAM-index and 192 full-pointer
  wraps, then the same full matrix reran as transport-r2.
- burst-r2 and reference-burst-r1 passed the external frame oracle and aggregate
  word/byte counters. Review found that reference-mode subset attribution needed
  exact source-accepted payload ownership, not only counts. Those weaker records
  remain unchanged. The final burst/reference fixture adds both 37-bit ledgers
  and a dedicated ordinary transport-observation negative case.
- The burst runner's inherited scope text was narrowed to RX data/status+CSR;
  it does not claim to drive TX or epochs. Earlier runner snapshots are retained.

## Limits and next integration boundary

The candidate removes the measured outer RX transport bottleneck at fabric 50
for the finite tested burst. It remains opt-in and standalone. Lower fabric
rates can still have insufficient transport capacity and need an explicit
traffic/admission/drop policy; no general 5 MHz-grid Gigabit-service guarantee is
made. This stage does not connect the fixed wrapper to the production platform,
replace fixture producer-closed witnesses with real owners, add full epoch
retirement/ACK, or validate DRP, physical clock stopping, CDC timing, synthesis,
routed CPU 300/fabric 250 timing, boards, minimum-size/mixed/configured-maximum 2048-byte traffic or
indefinitely sustained full-duplex line rate. No full GSIM, Linux, Vivado, bitgen,
Verilator, installation or remote push was run.
