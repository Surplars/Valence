# DMA benchmark error-stage diagnostics candidate

## Scope and provenance

Diagnostic-only candidate. No claim of root cause or FPGA/kernel/board validation.
Local base commit `9e35ddeb3d26ebfab5ce32cb1381ef25f71ab5d7` has tree
`2de655f9667dc6cde07bbe33511b0ce7f811830c`; parent established that this is
identical to published remote `75a056e758397436c678bbf1a68854def4e05144`.
The base `valence_dma.c` is byte-identical to the supplied V4 source with SHA256
`1914c7ca1afe7bd9aa124fd91ed254b669077734a59b6cc11d21bb5e68fb4ae4`.

Observed board state: benchmark bytes=8388608 iterations=4 elapsed_ns=0,
faulted=0; DMA status=0 interrupts=0 completed=0 faulted=0. Shell printed
`printf: I/O error`. This is a generic dash builtin stream-error message,
not proof of errno=EIO: ENOMEM and other write errors can produce it.
This does not identify an ordinary completed transfer or pinned timeout.
Without a run identifier it also cannot establish that every observation
belongs to the same attempted write.

## Additions

Existing benchmark sysfs fields and timing label remain in their original order.
New fields: run_sequence, last_stage, last_reason, last_errno, last_cookie,
last_result, last_iteration. Each accepted, mutex-serialized call increments
run_sequence, including a call rejected for latched fault. Iteration is one-based;
0 means no iteration reached. Result -1 means no completion result observed in
the current iteration; cookie 0 means no submit result observed.

Parse rejection and concurrent lock rejection are logged, but intentionally do
not overwrite a different active/previous run's fields. A driver failure after
locking is logged with the same diagnostic fields exposed by sysfs. No retries.

Stages: fault_check, request_chan, allocate, fill, prepare, submit, issue, wait,
verify, complete. Reasons distinguish channel_request, source_allocation,
destination_allocation, prepare_rejected, submit_error, timeout_stopped,
timeout_pinned, completion_result, data_mismatch, fault_latched and pass.
The allocation stage retains the original two allocation calls and identifies
which allocation failed. A failure in both is reported as source_allocation.

No changes to provider code, MMIO, IRQ, coherency, allocation order, buffer
ownership, timeouts, cleanup, release, or reset policy. Timeout with unsuccessful
termination still pins channel and buffers, and rejects subsequent writes.
Result-check and memcmp short-circuit behavior is preserved when splitting
reasons. Diagnostic writes add minor CPU overhead and are not performance-neutral.

## Actual V4 module audit

Supplied 18624-byte module SHA256:
`e75bd11b4265ace3f55d53f91724b7a31c2caff19b430cd181f30adef68b32b8`.

The audit below enumerates actual errno=EIO paths; the shell wording alone
does not select them. Allocation failure (ENOMEM) is now the leading source-level
explanation, subject to measuring the real board syscall errno.

Machine code confirms:
- Direct -EIO constants at benchmark_store 0x9fe and 0xc44: fault latch or
  completion-result/data comparison. Error-valued request/submit returns are
  separately propagated.
- vbench offsets agree across store/show/callback: ns=88, bytes=96, rate=104,
  finished=112, iterations=128, result=132, faulted=136.
- Descriptor tx_submit at +24 is assigned vchan_tx_submit in prep and called
  at submit; callback_result +48 and callback_param +56 are assigned by bench.
- Prep clears tx_result at +88; no evidence of uninitialized completion result.
- Frozen virt-dma.c vchan_tx_submit assigns a cookie and moves the descriptor;
  no ordinary explicit -EIO return exists there.

Reference linux.config SHA256 matches the V4 manifest artifact:
`02c3ca98daa9e874c79b4a498baf0e4043418f5609458d948c1fa9fdd1c00218`.
CONFIG_MODVERSIONS is disabled. CONFIG_VALENCE_DMA=y is mapped to obj-m by the
external module Makefile; it does not establish an in-kernel built-in driver.
Original compile .cmd/cache is missing. The supplied evidence lacks the complete
kernel include tree and running kernel ELF. Thus the module-to-running-kernel
DMA structure ABI is not fully proven; matching vermagic alone is insufficient.

## Validation

Run `python fpga/firmware/linux_net/test_dma_benchmark_diagnostics.py`.
The test extracts the actual candidate vbench/callback/store code, compiles it
with host stubs and ASan/UBSan, and injects 13 cases: pass, request failure,
source and destination allocation failure, prepare failure, submit failure,
timeout stopped, timeout pinned, latched retry after pin, result error, data
mismatch, parse rejection, lock rejection. It checks stage/reason/errno,
selected counters, ownership, and absence of retries/releases after pinning.

LeakSanitizer is disabled because the execution environment's tracing prevents
it from working; ASan/UBSan remain enabled. Host stubs do not model kernel ABI,
cache coherency, interrupts, hardware or actual DMAengine behavior. Injection
of request/submit -EIO only tests diagnostics, not that these are reachable on
real hardware. No kernel module build or installation was performed.


## Allocation ceiling: leading source-level explanation

Frozen Linux commit `551c722f40809618230001baccf219193e22fc5a` was inspected
through the official torvalds/linux repository. Relevant sources:

- [mmzone.h](https://github.com/torvalds/linux/blob/551c722f40809618230001baccf219193e22fc5a/include/linux/mmzone.h):
  MAX_PAGE_ORDER defaults to 10 absent CONFIG_ARCH_FORCE_MAX_ORDER. This is
  distinct from PAGE_BLOCK_MAX_ORDER (migration grouping); that latter setting
  alone would not prove an allocation ceiling.
- [dma-map-ops.h](https://github.com/torvalds/linux/blob/551c722f40809618230001baccf219193e22fc5a/include/linux/dma-map-ops.h):
  dma_alloc_contiguous returns NULL when CONFIG_DMA_CMA is absent.
- [direct.c](https://github.com/torvalds/linux/blob/551c722f40809618230001baccf219193e22fc5a/kernel/dma/direct.c):
  __dma_direct_alloc_pages tries dma_alloc_contiguous, then
  alloc_pages_node(node, gfp, get_order(size)). dma_direct_alloc returns NULL
  when no page is returned.
- [page_alloc.c](https://github.com/torvalds/linux/blob/551c722f40809618230001baccf219193e22fc5a/mm/page_alloc.c):
  alloc_order_allowed rejects order > MAX_PAGE_ORDER and allocation returns NULL.
- [swiotlb.h](https://github.com/torvalds/linux/blob/551c722f40809618230001baccf219193e22fc5a/include/linux/swiotlb.h):
  is_swiotlb_for_alloc is false without CONFIG_DMA_RESTRICTED_POOL. The general
  64MiB SWIOTLB setting does not supply a coherent allocation escape route here.
- [mapping.c](https://github.com/torvalds/linux/blob/551c722f40809618230001baccf219193e22fc5a/kernel/dma/mapping.c):
  dma_alloc_attrs checks any device-declared coherent pool before direct/other
  allocation. The Valence driver does not declare a pool; supplied DT generation
  has no DMA reserved-memory association. IOMMU support is disabled in config.

Reference V4 config: PAGE_SIZE_4KB=y, no ARCH_FORCE_MAX_ORDER, CMA disabled,
no DMA_CMA, COMPACTION disabled, DMA_RESTRICTED_POOL disabled. Thus the ordinary
direct allocation maximum is order 10 = 4MiB per contiguous buffer; 8MiB needs
order 11 and exceeds it regardless of otherwise free RAM or fragmentation.
The benchmark asks for TWO independent 8MiB buffers and returns ENOMEM if either
allocation fails, before prep/submit/IRQ/time measurement, exactly fitting the
observed idle engine and zero ns. Source evidence is strong; board errno and
actual runtime allocation route are not measured, so this is not yet a confirmed
board diagnosis. ABI mismatch is not the leading explanation on this evidence.

The allocator uses a WARN_ON_ONCE_GFP guard. Reference V4 config also has
CONFIG_BUG disabled. Frozen [mm/internal.h](https://github.com/torvalds/linux/blob/551c722f40809618230001baccf219193e22fc5a/mm/internal.h)
returns the failed condition regardless of warning emission and calls WARN_ON(1)
for a first warning. In [asm-generic/bug.h](https://github.com/torvalds/linux/blob/551c722f40809618230001baccf219193e22fc5a/include/asm-generic/bug.h),
!CONFIG_BUG makes WARN_ON only evaluate/return its boolean, without logging.
RISC-V's asm/bug.h does not override HAVE_ARCH_WARN_ON. Thus this configuration
can reject order 11 silently, consistent with no new dmesg error. No board errno
or warning has been observed by this audit.

## Minimal next board observation (not executed)

If strace is already available, tracing the existing command reports the syscall
errno without changing the driver: `strace -e trace=write dma-bench 8388608 1`.
This DOES initiate a benchmark and is not a read-only status query; use only in
a later authorized board session. Inspect the sysfs write result, not merely the
shell's stderr write. Do not install tools or rerun automatically.

An optional 128KiB, one-iteration comparison (`dma-bench 131072 1`) needs order 5
and matches the ROM test's normal payload size. It could distinguish the 8MiB
allocation ceiling from later transport/IRQ/verification problems, but success
is not guaranteed by being below the ceiling. This test has not been run.

The stage candidate remains useful: allocate/source_allocation or
allocate/destination_allocation with last_errno=-12 would directly confirm the
error class. Other errno values/stages remain visible rather than being forced
into the EIO hypothesis.

## Shell wrapper/recommendation companion change

The wrapper now invokes absolute `/usr/bin/printf` after checking it is executable,
instead of dash's generic-error builtin. This reports the underlying write-error
text; it does not expose numeric errno. Existing `set -e` stops before status or
throughput output on a failed write. No fallback writer or retry is introduced.
The source bootstrap package list explicitly includes coreutils, and packing
requires the external executable to exist and be executable. This ensures future
candidate images fail packaging if this dependency is missing; it does not claim
the original V4 rootfs binary was inspected (it was not supplied in the bundle).
No packages were installed and no image was built during this task.

The script's existing 1MiB default is unchanged. All firmware-generated example
recommendations are now 1MiB rather than 8MiB. Explicit 8MiB arguments remain
unchanged and may fail; a smaller test is not silently substituted or scored as
an 8MiB test. Rootfs source assets are copied by build_rootfs.py into the image;
these edits do not update an already deployed board.

`test_dma_bench_errors.py` passes five host-only tests: defaults, explicit 8MiB,
128KiB comparison, `/dev/full` write failure, and recommendation/dependency
checks. The `/dev/full` case produces “No space left on device”, returns nonzero,
and never calls cat or emits a throughput report. This is an ENOSPC host test,
not an ENOMEM measurement on the board. Existing rootfs-content tests pass (5),
and the driver host-injection tests remain passing (13).
