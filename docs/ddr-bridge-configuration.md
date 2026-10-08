# Explicit DDR bridge geometry

`DdrBridgeConfig` is passed through BoardSocTop, MachinePlatform, EthernetSocTop, BoardSocGsim and the managed/Ethernet exporters. Defaults select `Legacy` (one outstanding transaction). Performance profiles explicitly select `ReadOverlap4`; the pinned cache32k candidate's JSON now appends `4 16` to both GSIM and managed-export argument lists. Merely enlarging caches does not silently enable concurrency.

Fields:
- maxOutstanding: 1, 2, 4 or 8. The capacity is concurrent reads, not concurrent writes. AXI responses may arrive out of ID order; TL D completion remains acceptance-ordered.
- maxBurstBeats: generic buffer powers of two 2..256, subject to the selected TL size field. Present SoC accepts only 8 or 16 because cache lines require 8 beats and its TL fabric has sizeBits=3. Generic longer-burst support is not a claim that the current SoC can issue 256-beat transfers.
- axiIdWidth: generic 1..8, with enough IDs for all read slots. SoC elaboration rejects anything except 4, matching current board wrappers, clock converter and MIG. This avoids silently exporting a mismatched physical interface.

Every concrete bridge request continues to check natural alignment, full length, address-window translation, masks and the AXI 4-KiB boundary. Burst-size configuration does not waive those checks. There is no burst splitting or automatic TL size-field widening.

New optional positional arguments, appended after existing arguments:
- BoardSocGsimMain: `[ddr-read-slots] [ddr-burst-beats]`
- ManagedBoardSocMain: `[ddr-read-slots] [ddr-burst-beats]`
- EthernetTimingMain: `[ddr-read-slots] [ddr-burst-beats]`

Defaults are `1 16`; explicit performance setting is `4 16`. Existing two-issue, LSU2, RV64GC, 100 MHz, UART460800 and DDR2GiB choices are independent and unchanged. Native GMAC/posted-RX queue settings and memory ordering are not altered.

Verification planned for this separate patch: `mill -i IonSoC.test.testOnly ooo.DdrBridgeConfigSpec`. It checks 1/2/4/8 slots at 8/16 beats, actual instantiated lane counts, full SoC forwarding, ID/source capacity negatives, TL size encoding, and fixed physical-port rejection. Hardware functional coverage for the original four-slot candidate remains in its frozen receipt; new 2/8-slot behavior and this parameter plumbing require the separately granted focused batch. No physical timing claim.
