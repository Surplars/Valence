# Timer stream IRQ fixture

These four files are byte-exact promotions from the reconstructed r2 gate,
previously executed against d31 B/C models. The original archive is Library
`libfile_fb5c66459b0c81919ba6de3155b19f48`; `source-provenance.json` binds each
file and the comparison receipt. No old result is attributed to this source.

The guest raises two real M-mode mtimecmp interrupts during a 64-KiB store
stream, then reads back all 8192 words. The host checks cause, mepc, trap returns,
actual data and two consecutive all-zero 18-component terminal drain samples.
C requires IRQ-pending overlap with live prefetch ownership. The original pair
used one immutable guest SHA256
`26d2f2a63ff36f55f45c05043f8594077194198e47f9247988aee769ddd89c8a`.

The handler saves t0 through t6, but only t0 through t4 and sp are live in the
interrupted loop; this is not an all-GPR context test. The live-prefetch mask
includes any origin, not specifically store-prefetch ownership at trap entry.
No simultaneous DMA/IRQ or Sv39 IRQ behavior is covered. Cycles are recorded
without a performance attribution.

The original recovery-layout `run.py` is retained in its immutable external
archive. It hard-binds d31 source, recovery model paths and installed-tool
receipts. It is deliberately not advertised as a runner for this new source.
A new invocation needs an explicit new source/model/tool/guest binding, the same
independent oracle and all existing negative controls. Do not remove its old
source assertions to reuse a historical runner.
