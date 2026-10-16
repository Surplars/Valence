# Integrator contract and physical handoff

## Mode selection

The PAD-domain candidate is a separate local commit a58e8a0d72dbc405143ab5aeea2281ddd008de20.
This RX candidate is independent and based on the same3554932 board source.
Neither adapter is a full native emitter. Do not run one after the other and
assume the second preserves the first: each currently starts from original
board bytes. Combined integration must apply their disjoint, exact substitutions
to ONE board source and then validate all selected properties together.

Modes:
- OFF: original board bytes; original exact physical gates remain applicable.
- PAD only: explicit t1-selected profile; serializer parameters1/1 with override
  guard; native_gmac_pad_reset_clock enabled1. RAW125/PAD250/REF500 fixed.
- RX only: original TX selection unchanged; two direct same-pad RX BUFGs;
  capture-domain reset3FF and enabled10-bit falling-pair stage.
- BOTH: require every PAD and RX invariant above. Neither physical receipt nor
  native source receipt from3554932 can be relabeled as this combined design.

Expected unchanged external interface:76 board ports, DDR/PHY pins and input
constraints, core178/profile95 and resident-rank/shared-PMP/cache-overlap flags.
These are checks to repeat, not evidence inherited by new RTL. Fresh export
must inventory every actual SV/resource, including both new modules if BOTH is
selected; never assume a fixed SV count. Existing legacy modules may remain
as source definitions even if a selected generate branch removes their cells.

New board contract must explicitly record padDomainReset, rxCaptureSibling,
serializer1/1 selection, emitted source/module hashes, native inventory and
source/tool closure. Reuse neutral external run-root tooling only with a new
exact topology audit. Existing board_controls/trispeed audits expect the old
quarter_div hierarchy and one RX clock; their rejection is intentional. Do not
silently widen those checks or make old qualification authorize this candidate.

PAD new audit: PLL VCO/input/dividers/phases/duty/feedback, independent REF500
buffer, PAD BUFG and RAW /2 sibling input, exact3FF reset clock/connectivity,
CLR stage1, functional locked stage2, CE1, pin inversions, and all reset fanout.
RX new audit: one physical RXC IBUF drives both preserved distinct BUFGs;
capture loads only IDDRE1 C/CB, reset chain and pair stage; decoder stays fabric
clock; IDDRE1 SAME_EDGE_PIPELINED with actual polarity; exactly10 atomic falling
FFs, no bypass. Both branches retain one related source clock. Every endpoint
and reset path must remain timed and present in reports.

## Composition with unchanged source-side ingress

Actual355 TriSpeedManagedGmac feeds decoder data/valid/error/byteStep and raw
rise[4] physicalValid to EthernetPhysicalIngress; captureEnable is rawRxOpen.
Both decoder and ingress source clock remain clk_rx (fabric), and the ingress
reset expression commonReset|media.ingressReset is unchanged. Its sourceRelease,
clock bridge and downstream packet owners are unchanged.

EthernetIngressPacker uses physicalValid only when captureEnable is open and
waitIdle is set; otherwise closed capture forces waitIdle. Data/error are
consumed with valid; byteStep/valid control end handling. The focused decoder
harness therefore compares all always-consumed control outputs, data/error
when valid, and physicalValid when rawRxOpen. Its bound actual integration and
packer source supports this deterministic composition given the SAME ingress
reset epoch and downstream readiness. It does not newly prove the unchanged
FIFO/CDC/mailbox or complete MAC implementation. Existing matched downstream
tests remain relevant; their prior failures cannot be converted into passes.

Separate IDELAY-ready loss is not the common-reset harness episode. Actual
board behavior there also depends on PHY reset duration, watchdog and media
admission. Keep that board-level recovery check open. Do not waive it based on
common-reset equivalence.

## Numerical qualification targets, not predicted slack

Old355 reset path:2.000 -0.079 Q -1.241 net -1.293 adverse skew -0.053
uncertainty -0.081 recovery = approximately-0.747ns (reported-0.748).
PAD candidate's nominal cycle is4ns. Measure the NEW Q/net/skew/check terms;
require their worst-case sum below4ns with the desired positive margin.
Copying old terms to claim a new positive slack is invalid.

Old355 RX extrema: hold-0.313ns, setup+0.383ns. Let r_late/r_early be reductions
of effective capture insertion at hold/setup corners; d_min/d_max the added
effective data delays. Ignoring no other changed terms, target margin m needs:
  r_late+d_min >=0.313+m ns
  r_early+d_max <=0.383-m ns
Every pin/edge requires its own actual terms. A common uniform shift leaves
only70ps total window, at most35ps symmetric margin. The historical223 hold
clock-net reduction0.447ns is not automatically safe at the setup corner.

For retime→decoder, nominal windows are T/2+s (setup) and T/2-s (hold), with
s=fabric insertion-capture insertion. At the illustrative s=+0.447ns, T=8ns,
these are4.447/3.553ns before actual data/check/uncertainty. This s is NOT a
measured sibling skew. T is8/40/400ns for1000/100/10Mb/s; both signs of skew and
all relevant min/max corners must close. IDDRE→falling-pair and reset recovery
have their own half-cycle checks. No false path, asynchronous grouping or
external timing-budget relaxation is part of the candidate.

Full355 per-pin/per-edge/per-rate reports and current resource occupancy are
not present in the cloud. The supported source topology and formal checks do
not establish dedicated-route legality, pulse widths or physical margins.
