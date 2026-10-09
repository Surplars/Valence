# BootROM S-mode MMU diagnostic

The boot menu accepts `u` or `9` to run the RAM-resident MMU diagnostic and
return to the monitor. It shares the existing 512-KiB boot scratch reservation;
it does not enlarge that reservation, change the image limit or change automatic
boot. The existing DMA-quiescence and external-image-return restrictions also
apply to this menu action.

## Measurement contract

The 54 rows are three modes (S-Bare, S-Sv39 with 4-KiB data leaves, and S-Sv39
with 2-MiB data leaves), six working sets and READ/WRITE/COPY. All modes use the
same production kernel and physical buffers. This is a real `mret` into S mode,
not merely a `satp` write while executing in M mode. Code, metadata and stacks
retain an identity mapping through one 1-GiB leaf. The 128-KiB buffers use distinct
VA aliases for the translated modes; A and D bits are preset.

The working sets are an 8-KiB warmed stream, a 128-KiB stream and sparse touches
on 4/8/16/32 pages. Sparse offsets advance by 4160 bytes, distributing cache-set
indices. Sparse rows measure translation-sensitive access throughput, not DDR
wire bandwidth. The page count is per stream; COPY, stack and metadata create
additional translation keys. These rows alone do not measure a TLB miss rate.

`ticks` uses the board TIME CSR and reports the timed loop after warmup. A fence
precedes each timestamp. `flush_tail` separately reports the WRITE/COPY flush
after the loop; compare both the kernel and kernel-plus-tail. COPY payload bytes
count each copied byte once, not its combined read-plus-write bus traffic.
The complete two buffers are verified after every row. Different compiler
settings, privilege modes or benchmarks cannot be used as an MMU-only A/B.

## Privilege and restore contract

The entry helper preserves the M caller's stack, GP, TP and callee-saved
registers, switches to the reserved S stack, and returns through the M trap
entry. The C helper saves/restores 21 CSR fields and checks restored SP/GP and
CSRs. It enables S TIME access, clears delegation during the test, installs a
RAM-only PMP TOR grant, and uses `sfence.vma` around translation changes.
The caller must have MIE=0, MPRV=0 and SATP=0, with no locked PMP entry. A rejected
context has a defined sentinel result and is not modified.

Before timing, three directed faults check unmapped-load page fault 13, D-clear
store page fault 15 with no data mutation, and denied PMP/PTW/fetch access fault
1. Normal S returns use ecall 9. An unexpected restore failure requires reset;
there is no independent watchdog guarantee against an arbitrary hardware hang.

## Tests and recovered-source provenance

Run `python3 fpga/firmware/check_monitor.py --out <fresh-directory>` with the
pinned firmware tools and official CoreMark dependency available. It checks
menu dispatch/refusals and terminal layout, native MMU algorithms and negative
oracles, page tables for 512-MiB/1-GiB/2-GiB layouts, context rejection predicates,
then links the full ROM and verifies capacity. Native tests do not execute
RISC-V privilege transitions or prove FPGA behavior.

`tests/mmu_working_sets.c` selects 24 representative rows by two words at
`DIAG_BASE+0x64000`: [0,18) READ across all modes/sets and [18,24) the six 128-KiB
WRITE/COPY rows. [6,12) selects 4-KiB READ; [20,22) selects 4-KiB WRITE/COPY.
Each independently reset segment performs its own setup, selfchecks, warmup,
verification and final flush. Segment boundaries have a different cold-start
context than the uninterrupted 54-row menu command.

`tests/mmu_alias_capacity.c` and `mmu_alias_loop.S` instead isolate D-TLB capacity:
4/7/8/9/15/16/17/32 virtual pages map to the same physical page and word. The timed
loop is register-only, with one load and no stack/metadata access. The passive
host observer checks complete owner tokens, actual banked PCs, VA-to-PA mapping,
translation request/response handshakes and walker starts. A current source-bound
model schema and independently generated guest symbols are required. Never run
an old receipt-bound runner against a new model just because it links.

After the 2026-10-09 executor replacement, production C/entry assembly, alias
assembly/observer and representative working-set C/observer were recovered with
their historical source SHA256s. The header and menu integration were rebuilt
on public commit `926ea18ecab93364a1a7b1ae745fc674c275c2b1`. Old lost models and
their PASS results are historical only. New firmware linking reproduced the
1472-byte production supervisor kernel SHA256
`f5a152ca2779ee567a9f864bc29d524bd91a935dab0323f21353ae9c9af0fec5`.
Each new actual-CPU run must bind its own source, model, tools, guest and results.
