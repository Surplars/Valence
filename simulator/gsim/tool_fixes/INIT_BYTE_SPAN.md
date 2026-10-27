# Minimal deterministic initialization repair

Pinned upstream: `93b8cd23edd3228807c4f2a08c19c3936a463cb2`.
`init-byte-span.patch` changes exactly two emitter statements. Their old
`uint32_t*` difference supplies words to byte-count `memset`, leaving state and
tail RAM uninitialized. The repair subtracts `uintptr_t` addresses, which gives
byte length on the qualified Linux flat-address ABI without subtracting pointers
to unrelated member objects. The half-open interval excludes `_var_end` and
preserves cycles/logging fields and activation. No RTL or assertion changes.

Only deterministic, non-`RANDOMIZE_INIT` model execution is qualified here.
Random initialization's separate memory width masking is not fixed or qualified.
This minimal patch is separate from the broader historical
`input-vector-init.patch`; never stack those patches.

Source the approved pinned environment, then run `build_init_byte_span.sh`
with the pristine upstream source and a **new absolute** output directory.
It archives the pin, applies only this patch, builds all objects afresh and runs
original/repaired actual generated tiny-model tests under ASan/UBSan. Original
seeded-state rejection is expected; the repaired model must clear every state
byte including a 64-entry UInt2 RAM and preserve external sentinels. No original
binary, source or objects are overwritten. Restore means select the original
path for historical diagnosis only, not new qualified hardware runs.

Hardware runners must explicitly validate the epoch receipt with
`gsim_initialization_epoch.tool_binding(receipt_path)` and use its `gsim.path`.
Regenerate both control and candidate; no cached objects from the broken epoch.
The helper verifies all archived source against upstream plus exactly this patch,
tracked regression/helper inputs, generated regression artifacts, and executable
identities. Qualified receipt also records compiler/dependency provenance.
