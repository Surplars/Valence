# Canonical full-address packet keys (candidate)

Source-only acceptance assets for `canonicalFetchCacheKeys`, default OFF. Supported
candidate is exactly sixteen sets, two ways, compressed/two-wide parallel-tag,
registered aligned fetch with two accepted owners. No added edge, changed owner
credit, shortened address comparison or permission/context authority.

- `canonical_key_model.py`: pure arithmetic model. Run with Python; 64-bit original
  address oracle, all sets/ways/offsets, wrap and inactive writes. Its mutations
  are model sensitivity checks, not RTL negative controls.
- `ooo.CanonicalFetchCacheKeysGsimMain <output-dir>` emits the standalone helper.
  Host `canonical_fetch_cache_keys.cpp` uses the existing compact-key independent
  uint64 subtraction oracle with only top/result names changed; no candidate-tag
  reconstruction in the oracle.
- `ooo.CanonicalFetchFrontendGsimMain <output-dir> <true|false>` emits a paired
  candidate/baseline old-key-path frontend. Boolean controls third-packet horizon,
  NOT canonical-key selection. Match host `IDENTITY_HORIZON_ENABLED=1|0` to it.
  Host `canonical_fetch_frontend.cpp` preserves the existing identity-horizon
  independent full-address/old-owner oracle; only the generated top name differs.
  Host negative observations `address`, `third`, `held`, `data`, `fault` must fail
  (third only when horizon enabled). Internal paired assertions check cycle-wise
  requests, masks, response readiness, quiescence and valid instruction/fault data.

Compile/elaborate/GSIM only in the parent-owned combined batch after all source is
ready. No test execution or hardware correctness claimed from the source assets.
Paired frontend covers held payload, same-edge OLD-head response/new-tail request,
context/stale/invalidate, selective faults, instruction straddle, high-address
aliases, XLEN wrap and aperture boundaries, and both horizon modes. It is not a
CPU trap, ISA/MMU, whole-core performance or timing proof.

Resource model: 32*57 tag bits + 4*57 borrowed-high bits = 2052 unreset logical
address-state bits. Compare actual combined synthesis against frozen 5824 mapped
address FF; do not treat the difference as measured implementation savings.

Test-only helper fault injection: append `wrong-borrow` or `truncate-high` to
`CanonicalFetchCacheKeysGsimMain` emission arguments. Run the SAME unchanged
full64 host and require nonzero exit. These inject incorrect fill-boundary inputs
(no production source edits): wrong-borrow supplies unborrowed high; truncate-high
clears incoming address bits63:32. They qualify sensitivity of compiled helper
plus oracle to those faults, not comprehensive production-RTL mutation coverage.
`ooo.CanonicalFetchCacheKeysSpec` checks default-off/no helper, preserved old
compact elaboration, and rejects unsupported selected configurations.
