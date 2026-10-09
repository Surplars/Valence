# Reconstructed combined source checkpoint

This records the earlier d31 hardware freeze. The later deliverable composition
and its separate qualification boundary are in
[delivery-integrated-reconstructed-20261009.md](delivery-integrated-reconstructed-20261009.md).

This source composes public dev `926ea18ecab93364a1a7b1ae745fc674c275c2b1`
with prepared-store `94aff3f5a729a0ba131166c0e7d36b502e196f57`,
D-TLB `efc98484a87c97e2e1b6533e9dd6191abc0f12b7`, and checked-store PF
`72d44d90d4a6b9c71046dd363cfb13fce339ec8a`. All are new reconstructions.
Standalone archives remain separate. The production planner mask, translation
service, and PF implementation retain their corresponding input source bodies.
Only shared config/emitter option conflicts required composition.

Defaults remain prepared-store OFF, store PF OFF and D8, with I8 and selected
PTE4 unchanged. Public stage2/V4, DMA, MAC and JTAG sources are preserved.
This is not the lost `0e62d30` source. Posted merge, WB reservations and the new
S-mode BootROM diagnostic are absent. No historical performance or qualification
applies to this reconstructed composition.

Fourteen host methods passed before the PF addition (six policy/source boundary,
five prepared parser/preflight, three D-TLB CLI). They must run again after it.
The focused Scala gate covers FpgaNextConfigSpec, PreparedStoreReconstructedConfigSpec,
DataTranslationCapacitySpec and CheckedStorePrefetchSpec; its new receipt is the
authority for actual execution status. Source-only preparation claims no RTL,
CPU, native or FPGA qualification.

## Controlled model profiles

All three use selected read configuration, LSU4, physical ingress, virtual RAM
load precheck, unchanged store-history handling, older-load retirement, previous-fetch
packet and DMA line transfers with four owners.

- A: D8, prepared-store OFF, checked-store PF OFF.
- B: only D-TLB capacity changes to D16.
- C: B plus prepared-store ON and checked-store PF ON.

A/B can isolate D-TLB capacity using the same freshly frozen source and guest.
B/C Sv39 WRITE/COPY can isolate checked-store PF because reconstructed prepared
lookahead is physically restricted and inactive in that translated ROI. B/C
physical diagnostics measure only the combined effect. No posted merge or WB
reservation is present. Each actual run must bind new source, exact guest bytes,
installed tools, parameters and artifacts. Previous standalone PASS cannot be
combined into a combined PASS. Original missing immutable guests must be marked
unavailable; rebuilt guests have new identities.
