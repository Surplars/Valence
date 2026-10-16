# PAD-domain reset candidate (default OFF)

Source-only experiment based on 3554932. The original board and clock files are
unchanged. `export_board.py OUTPUT` copies the original board bytes exactly;
`--enable-pad-domain-reset --serializer-profile t1-selected` explicitly selects
the new module and the proved1/1 serializer mode; ON without this profile fails.
An elaboration guard rejects overriding either serializer parameter away from1. This is not a
complete native exporter or a physically qualified board contract. Existing
clock/reset physical audits are not relaxed and must not qualify this topology.

## Architecture and actual failing path

The old network uses PLL REF500 -> BUFG -> RAW /4 and PAD /2 dividers. The
phase-reset pipeline is on REF500, and its stage1 clears both dividers. The
3554932 placed RAW CLR recovery path had Q 0.079 ns, net 1.241 ns, clock skew
-1.293 ns, uncertainty 0.053 ns and recovery 0.081 ns. Its nominal 2 ns cycle
therefore gives approximately -0.747 ns, matching -0.748 ns reported slack.

This candidate keeps UI250 *4 /1 = VCO1000 and REF500 on CLKOUT0 /2, and adds
PLL CLKOUT1 /4 = PAD250. PAD BUFG and RAW BUFGCE_DIV /2 are siblings on that
same PLL250 output. The reset chain runs on buffered PAD250; stage1 clears
RAW and stage2 qualifies locked. The nominal release cycle becomes 4 ns and
one divider is removed. The exact recovery budget is still 4 ns minus C-to-Q,
net, recovery, uncertainty and adverse sibling insertion skew. It is **not**
valid to copy the old skew/net to claim a positive new slack. All functional
CLR/PRE arcs remain timed. Cold reset and lock loss asynchronously reassert
both protocol and divider reset. Hot rate changes already do not clear the
fixed clocks; they continue to affect protocol state/symbol enables only.

PLLE4 divider and phase attributes are supported by
[AMD UG572](https://docs.amd.com/r/en-US/ug572-ultrascale-clocking/PLL-Attributes).
The unchanged VCO/input operating point is not a new device-speed qualification.
[BUFGCE_DIV](https://docs.amd.com/r/en-US/ug572-ultrascale-clocking/BUFGCE_DIV)
provides the ideal first rising edge after clear used by the bounded proof.
Physical acceptance of that clear release still requires recovery/removal.

## Bounded actual-source check

`formal_check.py --yosys PATH --output FRESH_DIRECTORY` uses source snapshots,
Yosys SAT and explicit ideal PLL/BUFG/BUFGCE_DIV/ODDRE1 contracts. The actual
phase chain, actual common word reset, and actual T1 selected-half serializer
are checked with LOCAL_PAD_RESET_RELEASE=1 and REGISTER_SELECTED_HALF=1.
The explicit ON profile sets both serializer defaults to1 and guards against
other overrides. OFF preserves original0/0 board bytes. A future integrated
exporter must audit the selected profile against this exact proof configuration.
The serializer snapshot excludes its unexercised RX primitive
cone and appends assertions; transmit RTL is copied without rewriting it.

Properties cover release age; RAW rising only at PAD rising; RAW/PAD ratio;
common reset outputs; preset phase; complete low/high word pairing; TXC holding
the preceding half during positive PAD and applying the new half on negative
PAD. Arbitrary RAW word bits include all legal tri-speed symbol patterns, but
this does not verify the upstream rate encoder or MAC. Coupling uses alternating
PAD half-cycle steps and arbitrary reset/ready/lock values. The clock-only check
allows arbitrary clock steps. First complete pairs are checked after two active
PAD rising edges; reset-truncated partial traffic is not advertised as valid.
Cold-reset-to-nonzero-data reachability and early-release, wrong-ratio and
wrong-preset negative mutations guard against vacuity. The receipt seals runner,
source snapshots, ideal contracts and logs. This is neither GSIM nor UNISIM
execution and does not prove analog PLL acquisition, actual duty-cycle error,
metastability, pulse-width/recovery/removal or physical I/O timing.

## Remaining RX hold architecture

Actual RXD3 hold was -0.313 ns with IDELAY1100 already at this source's limit;
RX setup was +0.383 ns. Adding 313 ps blindly consumes almost all setup margin.
RXC AA7, RXD3 AB11 and TXC AC8 lie in X3Y2 according to the installed ZU15EG
RapidWright database. RX BUFGCE_X0Y67 is already in that CMT, so simply moving
it into the I/O region is not a new correction. Site existence does not prove
occupancy or legal routing; no speculative LOC is supplied.

A native I/O source-synchronous capture architecture could avoid part of the
RX global-clock insertion, but AA7 is in T1U while RXD3 is in T0L. Cross-byte
clock legality and all receive pins must be established before replacing the
IDDRE1 path. An RX MMCM approach must handle 125/25/2.5 MHz and stopped RXC;
a fixed 1G-only MMCM is not a tri-speed solution. The current candidate changes
no RX source. Physical RX timing can nevertheless move due to clock resource
placement and congestion. RX hold is still an independent blocker.

Before any promotion: new native export and source inventory; topology/config,
feedback and reset-chain audit; actual synthesis/placement legality; all reset
recovery/removal and pulse-width paths; RX/TX setup and hold for both edges and
all rates; reset/lock-loss and first-frame board behavior. No local run is
authorized by this experiment or its receipt.
