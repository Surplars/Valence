# Second resource batch: ROB payload, fetch keys, MSU and PMP

Baseline: `17f1fadfd6bd6e5bb8af968a48f6ce04b04b7949`. Eleven production leaves change: RenameRob, new WriterBankedRobCompletionPayload, IntegerBackend, InstructionRom, new CompactFetchCacheKeys, MachinePlatform, MachineSystemUnit, PhysicalMemoryProtection, FloatingPointMemoryPipeline, PendingVirtualStoreProof and NextLineAuthorization. The InstructionRom changes are a three-way merge retaining the first batch's aligned-word PMP branch.

## Enable scope

The new ROB and fetch constructor options remain default OFF. Current board parameters explicitly enable them; other configurations retain the original implementations. Enable decisions use only Scala construction parameters, never runtime signals.

ROB requires ROB16, 64-bit tag, recovery width4, rename/completion/commit widths2, PRF48, retirementSlotIdentity, retirementIntent, registeredRobRetirement, parallelRecoveryAdmission, fastHeadTrapRecovery and fastHeadSystemRecovery. The generic payload helper was tested at additional sizes, but that does not qualify every complete ROB configuration.

Fetch requires 16 sets, rename width 2,16 PMP entries, compressed instructions, stable fault metadata, aligned fetch PMP, raw fetch presence, parallel tag lookup/alignment, registered window, independent payload capture, previous-packet lookup, aligned permission stage and address-before-PMP. Only MachinePlatform's qualified frontend opts in. Other callsites retain default OFF.

PMP high-bound sharing opts in only at the existing naturally aligned FP-memory and prepared-store-proof checks and the existing aligned next-line authorization branch. Full65-bit bound and address semantics, first match, locks and permissions remain. The four original aligned instruction-word checkers remain enabled.

MSU shares the selected raw54 PMP-address change comparison. The unconditional CSR read selector equals the selected pmpaddr even for rd=x0 and illegal access; original execute/legal/write, own lock and successor TOR lock gates remain. RW/RS/RC, zero masks and discarded high write bits retain their previous behavior. CSRRW change detection gains a CSR read-selector dependency, so timing improvement is not assumed.

## Qualification

One fresh 207-source production compilation and selected test closure produced one new 37-object CPU model with complete unchanged177/94/ordered73 configuration. Seven positives and eight negatives passed with all positive stdout/event TSV bytes equal to baseline. COPY Bare/Sv39 inclusive cycles remain179571/191618. The same model passed20 FP S/D W/WU retirement/flags/context anchors in 6151 cycles plus the expected-literal oracle negative. The actual backend CSR-reserve/retained-proof witness was reached at 823, completed in 1714 cycles, and passed two host-checker negative controls. Its positive log is byte-identical to prior R6. olderSystem is also true at that witness; it does not isolate reserveSystem's individual necessity. Exact held physical/ROB reuse remains NOT_REACHED.

Qualification SHA256: `65f44c3a702808a7c8fe33f6d26ff647bfe03b38d285498d7019a70ea891c6e5`.
Native supplement: `6d8747591b15b700a50c15982d35fc1e48b623d6c94923fcfbe3650b9d5c469f`.

Actual native board output confirms all new instances and unchanged top/MAC/JTAG/USER2 and parameter audits. First-batch FP shared64, home sharing and word-PMP module bytes are retained. ROB emits four 8×64 and two 16×64 synchronous-write/asynchronous-read memories plus 16 writer-map bits; its old 32 nextPc/tval register declarations disappear. This duplicates logical payload storage to 4096 memory bits versus 2048 original payload bits, trading representation/ports rather than proving an area reduction. Fetch emits 32 full64-bit base registers plus four 57-bit boundary-high registers. Neither declaration count nor generated SV size is mapped FF/LUT/LUTRAM/BRAM savings. No physical timing, route or board result is claimed.

## Focused tests and repaired entry points

ROB/fetch paired fixture commands accompany their component runner. PMP high-bound and word compatibility gates retain independent byte-range oracles and actual source negatives. `python3 simulator/gsim/msu_addr_change.py --tag UNIQUE --build-run` runs the real MSU registered16-entry CSR/consumer-boundary oracle, including all 16 selected-address identities,810 commands, RW/RS/RC/zero masks, illegal privilege, lock/TOR and stalls. For the historical wrong-old source negative in a separate source copy, replace only selected readValue54 with pmpAddr0; the unchanged consumer-boundary oracle must reject. Do not mutate shared production sources during a positive run.

The FP component public runner now uses FIR→GSIM→C++ only. Its122840 numerical vectors,4772 actual-Misc transactions,60 owner64 transactions and three source negatives passed with ASan/UBSan. Prior Icarus runs and old uncalled SV fixtures remain historical evidence; they are not relabeled as GSIM.

The six public word-PMP source mutants are regenerated from the new checker while preserving the strict source-derivation preflight. The original 31456-vector/188736-decision word gate and all six negatives passed again. The system-reserve runner now compiles its hash-checked host from the fresh output directory, preventing quoted includes from silently choosing an unqualified sibling board_boot.cpp instead of the verified service snapshot. The initial source-directory include failure is retained in test evidence; no DUT failure or service change is hidden.

All full-CPU hosts retain the qualified original service law and guest inputs. Test-only publication additions are separate from the frozen 3258-file CPU compilation input; they do not imply another production build or inherited qualification. Historical named-source entries remain historical and must not silently qualify this new source.
