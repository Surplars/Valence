# Interactive BootROM monitor

Build explicitly with `build.py --boot-menu --crc-mode byte --ddr --ddr-bytes 0x80000000 --netboot --netboot-posted-rx --cpu-hz 100000000 --uart-reference-hz 7372800 --uart-baud 460800 --out OUT`.
Run `setup_monitor_coremark.py --fetch` once if the pinned official source is absent. The archive SHA256 and official source revision are fixed in that script; no algorithm source is patched. The official archive's old `coremark.md5` header entry is stale; the pinned header was checked against its matching official raw GitHub URL. The five benchmark C files match the official MD5 inventory.

Without `--boot-menu`, the existing automatic network boot and memory layout stay available. Both builds now enforce the strengthened physical-RAM verification below; the automatic ROM binary therefore changes too. The monitor and recovery compile at `-Os`; an independent diagnostic RAM payload compiles at `-O3`. ROM must fit128KiB. Monitor globals must fit8KiB and leave8KiB stack. Diagnostic code/data must end before its independent16KiB stack. Linker assertions enforce these limits. They are reservations, not a measured worst-case stack high-water claim.

Plain text is the default. `a` toggles ANSI clear/home presentation; `h` redraws the menu. Keys:

- `n`/`1`: negotiated network download, verify, safely stop DMA, return to menu.
- `d`/`2`: existing checked UART download protocol. `uart_load.py --run` still sends `g`.
- `v`/`3`: independently read and CRC the current RAM image. `d` or Ctrl-C can interrupt between4096-byte chunks.
- `r`/`4` or `g`: validate metadata/range and full current RAM CRC, then run; an application return restores the monitor.
- `c`/`5`: standard2000-byte CoreMark one-iteration CRC selftest. No score is printed. Golden CRCs are checked in the port as well as by unchanged official algorithms.
- `C`: official CoreMark automatic calibration, requiring at least10seconds and all standard CRC checks before any result is valid. Never run this long mode in GSIM.
- `b`/`6`: CPU read/write/copy at8KiB and128KiB, including a hot read, independent data checks, and separately measured flush tails. Rates count payload bytes; copy does not double-count bus traffic.
- `m`/`7`: actual MemoryCopyDma CSR0x10001000 copy of128KiB, independently verify destination, report completion and flush tail. This is coherent DMA; the report is not a wire-speed claim.
- `t`: bounded512-byte DMA and small CPU correctness diagnostics, no bandwidth score.
- `i`/`8`: distinguish firmware compiler/ISA/clock/memory configuration from hardware CSR/MMIO reads. Firmware clock configuration is not an independent frequency measurement. The matched core supports time but not mcycle/minstret CSR reads, so the pages explicitly report those counters and IPC as unavailable. GSIM retirement-observer IPC is separate evidence, not a board CSR measurement.

## Memory and ownership

Menu images use explicit host profiles `--memory ddr-menu`, `ddr1g-menu`, or `ddr2g-menu` in both `netboot_host.py` and `uart_load.py`. They reduce the matching legacy image limit by512KiB. For2GiB, diagnostics use `[0xfff78000,0xffff8000)`; the monitor remains `[0xffff8000,0xffffc000)`. The fixed standard DTB relocation slot at0x80300000 is outside diagnostics. Other custom firmware layouts must respect this contract.

Within scratch: the first128KiB contains diagnostic code/data and its top16KiB stack; `[+0x20000,+0x40000)` and `[+0x40000,+0x60000)` are source/destination; the command mailbox is at`+0x7ff00`. Both CPU buffers are64-byte and8-byte aligned, disjoint, and lie within the DMA's full64-bit RAM aperture. The payload blob is copied from ROM and read back every invocation, followed by the real data/instruction flush; stale RAM code is never assumed valid. The loader rejects overlap with the accepted image limit or monitor.

This is boot-only scratch, reclaimable by Linux or another application; no additional permanent DTS reservation is implied and physical RAM capacity is unchanged. Returning external applications may have changed image, scratch and peripheral owners; all memory/execute operations therefore lock until board reset. Within trusted internal diagnostics, each invocation reloads its RAM code. Every first external execution after download still checks all RAM image bytes. A cold/button reset clears the BSS validity record; it does not preserve a trusted image record or promise DDR retention across MIG reset. No `.noinit` descriptor is used.

Before external entry, memory-changing menu transitions require Ethernet producer/DMA quiet and idle memory-copy DMA. After external return, the lock refuses such transitions before attempting quiescence. MemoryCopyDma has no cancellation CSR. A2-second software timeout pins its buffers and later menu actions refuse while BUSY remains set; they do not clear a live descriptor or reuse its memory. Error completions are not reported as successful bandwidth. Download, run, diagnostic load, and recovery retain the production fences and independent RAM CRC.

## Evidence boundaries

`check_monitor.py --out OUT` runs native ASan/UBSan monitor tests, fake-MMIO tests of the actual diagnostic C kernels, unchanged official CoreMark CRC and negative presentation-oracle checks, host/firmware profile checks, and an RV link/layout audit. LeakSanitizer is disabled only because the executor uses ptrace; address/undefined sanitizers remain active. Native elapsed time is not reported as SoC performance.

A new combined CPU/native-MAC GSIM run and real board execution remain separate delivery gates. The prior21,352-byte automatic ROM's tests do not certify this menu ROM. Full Linux/kernel-driver testing, physical clock-domain behavior, and routed timing remain outside these short tests.

Official rules: https://github.com/eembc/coremark (fixed source revision1f483d5b8316753a742cbf5590caf5bd0a4e4777).

## Physical RAM verification boundary

An ordinary ordering fence does not empty the data cache. Before every UART/network full verification and menu v/r, networking is quiet and memory-copy DMA must be idle. The SoC-specific fence.i first writes back and invalidates dirty private lines, then waits for the coherent home drain. Clean lines are not invalidated by that RTL operation. The ROM therefore reads two complete64KiB sweeps, one consumed volatile64-bit word per64-byte line, in `[monitor-64KiB,monitor)`. The sweep performs no writes and requires no additional auto-mode reservation. A static guard requires at least128KiB below the monitor.

The supported firmware contract is64-byte lines,1 or2 ways, at most32KiB private D-cache, matching the selected512-line hardware. Both implementations use direct replacement or two-way LRU (`touch` marks the other way). Each sweep presents at least two cache capacities of distinct tags, replacing all older lines outside its window. If a large image overlaps the sweep window, CRC starts at the fixed image base and consumes at least64KiB of preceding lines before reaching it, evicting sweep-resident tail lines first. Stack/table accesses can evict image lines sooner; the generated sweep leaf loop has no stack/data accesses beyond its designated reads. No stale clean image line is used as physical-backing proof. Larger or different cache geometries require a new matched firmware contract/proof.

Flush, sweep and CRC ticks are reported separately. TFTP's fixed final ACK/dally finishes before the optional preparation callback closes network ownership; EOF ACK still does not mean RAM verification or execution succeeded. Failure after quiet cannot restart TX DMA. Ordinary MMIO fences elsewhere are unchanged. Native cache-state tests cover small resident images, repeated downloads, overlapping large tails, and a missing-sweep negative. Real GSIM backing-only corruption after a clean-resident verification remains a required hardware-model gate.

Legacy automatic mode also records the expected image CRC and checks metadata plus physical RAM before the first UART `g` after download. Any external return then locks further downloads/verification/execution until reset. Initial network auto-run directly follows its full physical-RAM verification. The new verification changes the auto ROM binary; old byte-identical auto receipts apply only to the earlier menu-only revision.

## External application return safety lock

Before entering any external RAM image, the monitor pre-arms a BSS lock. A normal return or trap therefore cannot restore trust merely because BootROM's own network-active flag is clear. After return, image validity is cleared and n/d/v/r/g, c/C/b/m/t and their numeric aliases are rejected before peripheral quiesce attempts or memory work. The lock requires a real board reset; no command clears it. Read-only h/i remain available with an explicit unknown-peripheral-ownership warning, and network MMIO is not inspected in locked state. The monitor does not clear busy owners, reset FIFOs, or pretend to retake an external driver's descriptors.

Trusted embedded diagnostics use a separate entry path and never set the external lock; consecutive diagnostics remain supported. The lock is pre-armed so ordinary external trap recovery preserves it. As with the existing memory contract, external applications must respect the monitor's reserved16KiB; this is a fail-closed ownership policy, not protection against malicious code overwriting arbitrary physical monitor RAM.

The lock only refuses subsequent BootROM operations. It does not stop DMA already started by the external application, isolate memory, or promise arbitrary Linux/M-mode applications can return safely. A returning application must preserve the documented return ABI and monitor stack/BSS; Linux normally does not return. Hardware acceptance deliberately requires an external DMA owner to remain retained while later commands are refused.
