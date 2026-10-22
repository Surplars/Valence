# R13 real architectural owners during three-clock epochs

This isolated native-Icarus stage extends test fixtures only. Production source files, clocks, backend-present settings and the empty runtime whitelist are unchanged. The old runtime fixture retains its default 64-word ROM; a dedicated test factory uses 256 words and a fabric subclass interposing protocol backpressure at real atomic request/reply boundaries. No response is fabricated and no internal CPU state is forced.

## Independent IRQ oracle

The dedicated guest enables actual M-APLIC/IMSIC delivery and M external interrupts, handles trap entry, reads mcause/mepc/mstatus, claims MTOPEI, performs an independently checked memory service and executes MRET. The TB computes its expected architectural PC from assembled guest instructions and known control flow, not the DUT next-PC output. An asynchronous trap must match that independent PC and cause 0x800000000000000b; MRET resumes the saved PC. Claims use architectural returned identity values. Source episodes are serialized to respect IMSIC bit coalescing; a continuously held level is not treated as a queue of interrupt events.

Scenarios cover service before prepare, a physical source asserted during held then serviced after resume, epoch prepare during a real handler, and cancellation while a real MSI reply remains accepted and blocked. This stage does not force a core-to-IMSIC CSR response stall; that distinct serial CSR-owner backpressure case remains unqualified.

## Independent atomic oracle

The common I1 routes RV64A instructions to the fabric's shared AtomicMemory. Real AMO ownership persists through read, write and final CPU response, even when the physical request counter is temporarily zero. Four coordinated-reset scenarios hold an actual AMO read request, write request, final result, or physical read response. An epoch is requested while that real owner exists; no held or terminal proof may appear before the owner is released and retired. Independent architectural old/new values and physical request/reply counts check conservation.

LR/SC expectations follow the actual reservation contract, not a guessed first-attempt success. Probe, accepted ordinary store, runtime flush and context/trap-related clears can invalidate a reservation. The guest's LR is intercepted before its physical read, a real epoch and precise external stop are requested, then LR completes and runtime maintenance clears reservation before resume. The following SC must fail with result1, perform no physical access, and leave memory unchanged. This demonstrates required post-maintenance failure, not proof that a reservation survived all earlier coherence probes. Uninterrupted LR/SC success coverage remains separate.

An upper-half AMO.W additionally checks sign-extended old return, modulo-32-bit write result and unchanged neighboring lower word. The guest assembler, explicit instruction words and independent expected data are the oracles, not a copied DUT calculation.

## Boundaries and remaining work

No real gate/DRP transition, arbitrary stopped-clock IRQ capture, complete system drain ACK, DDR physical behavior or timing/board signoff is claimed. Default50MHz/direct BootROM-to-Linux/optional U-Boot goals and CPU300/fabric250 performance constraints remain unchanged. Source/RTL/tool/guest hashes and failed attempts are preserved with completed native results. Upload remains pending the earlier explicit receipt permission request; local commits are not remote publication.

## Completed validation

Both independently clocked IRQ positive cases pass (CPU/fabric/AON half-periods 5/7/11 and 11/5/7 ns). Each records exactly four trap entries, architectural TOPEI claims, service-store/load pairs, MRET retirements, MSI requests/replies and terminal epochs. The interrupted ordinary-memory loop also preserves its independent previous-store oracle (20 loops first ratio,18 reverse). The handler-triggered prepare is required to reach held before its MRET; both ratios meet this coverage condition. Wrong EPC, claim and service independent negative monitors all reject their altered expectations.

Both atomic positive ratios pass all four real-owner stall scenarios. Each reset scenario records exactly four atomic requests/results, three physical reads, two writes, four reservation-clear pulses and two completed epochs. AMO.D old7/new12, post-maintenance SC1/no physical access, and upper-half AMO.W old0xffffffff80000001/final0x800000033456789a all match the independent guest/TB oracle. Wrong old value, final value and post-epoch SC expectations each fail at the intended monitor. No failed positive attempts or DUT fixes occurred.

Fresh shared Scala compilation and RTL emission pass. All181 emitted SV files for the original default64-word runtime fixture are byte-identical to its saved r10 emission; no production source files changed. Both final receipts'319 source files,181 RTL files,11 tools,4 guest artifacts, logs and simulator binaries were independently rehashed in addition to the runners' drift checks. These results qualify the stated digital architectural-owner scenarios only.
