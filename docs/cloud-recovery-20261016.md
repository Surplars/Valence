# Cloud reconstruction, 2026-10-16

The executor workspace was replaced. The remote `dev` baseline
`223453bae0185dcc59b9ea5414ddb266e1f5af93` was cloned anew. The former unpushed
`685400dd` candidate and same-disk bundle were not recovered. These changes are
new implementations with fresh validation, not byte-identical restoration.

## Scope

- Combine all enabled registered request sidecars in one typed FIFO. Preserve
  native request/metadata fields, queue depth, non-flow/non-pipe behavior and
  physical response ownership. Canonical/frozen metadata is independent of
  posted authority.
- Add default-off shared two-word fetch PMP checks and guarded callers.
- Add default-off split cacheable aperture bounds; unsupported geometries retain
  the old arithmetic.
- Retain a source-only patch and focused tests for pinned GSIM input width,
  padded Vec interfaces and byte-range state initialization. Use it explicitly
  in an isolated GSIM checkout, without replacing the original pinned binary.

## Evidence and limits

Fresh baseline compilation passed (209 main sources). Reconstructed main
compilation passed (210 sources); focused Scala suites cover queue optional
configurations, PMP guards and cache range structure. Cache interval-partition
checks and an endpoint mutant establish mathematical-model evidence, not
emitted-RTL SAT equivalence.

GSIM fixes passed six focused normal/RANDOMIZE_INIT sanitized executions and
seven upstream FIR emissions with six runtime harnesses. Final tested binary
SHA-256: f00067c6158db342927ad0d746109ad745298fd4ebe9707fd951998069587116.
RANDOMIZE_INIT retains upstream final zeroing; this is not a claim of randomized
initial-state behavior. LeakSanitizer was disabled for ptrace compatibility;
ASan and UBSan remained enabled.

No new Vivado synthesis/place/route, full SoC cancellation/boot qualification,
board result, LUT reduction or timing gain is established for this reconstruction.
Previous lost-work measurements must not be attributed to these new bytes.
Default-off PMP/cache options are experimental. Queue transport checks do not
replace integrated LSU cancellation and response-drain tests.

Dynamic test results will be appended only after completion. Generated models,
binaries, dependency caches and large logs must not be committed.

## Completed focused dynamic checks

- Atomic queue: 16,094 cycles; 11,244 accepted, 11,243 consumed, one reset
  discard; 7,774 simultaneous transfers. Four host-oracle negative controls
  (stale token, permission, canonical, frozen) rejected. Flush/quiesce stimuli
  are queue-harness observations, not integrated cancellation qualification.
- Shared two-word PMP: 53,450 independent-byte-oracle trials; 18,737 cases
  with differing lane outcomes. Active-granule and misaligned-packet negative
  controls rejected. Raw54 maximum NAPOT is explicitly bounded to the existing
  56-bit decoder contract; unbounded architectural range equivalence is not
  asserted.
- Both used the explicitly selected repaired GSIM binary above, ASan/UBSan,
  and stable source inventories. Enabled caller end-to-end behavior remains
  unqualified.
