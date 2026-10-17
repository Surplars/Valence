# OoO source directory migration — 2026-10-17

## Scope and baseline

149 production Scala files moved from the flat `src/main/scala/core/ooo` directory
into responsibility directories. See the [directory guide](../src/main/scala/core/ooo/README.md)
and [complete old/new/SHA256 manifest](ooo-layout-migration.json).

The audited local baseline is `bb1bce154ed7efd40b746eb5398d53285b1a4b3f`, tree
`4461ecd7fde7028ca621559c4df3a414f1a2d628`. Published `main` baseline
`97fb7a260dda28992adfaf2dd4b8f45b378dca50` has that same tree. This change does not
include unpublished performance candidates or the separate JTAG work.

All 149 Scala files are byte-identical, including package names, comments,
private visibility, algorithms, parameters, interfaces and defaults. No production
Scala/resource file outside those paths is modified. No legacy source is moved.
The split is intentionally physical: preserving `soc.core.ooo` prevents import
churn and keeps the future in-order merge separate from package/API redesign.

## Build and current references

- `build.mill` uses `SbtModule` through `CommonNS` and does not override source
  discovery: the complete `src/main/scala` subtree remains in `IonSoC`.
- Three FP inventory scripts previously used flat `ooo/*.scala` discovery; they
  now use `rglob` and include all moved files.
- Current source gates, mutation inputs, focused runners and current documentation
  point to explicit responsibility paths. Loops that use class names retain the
  class names and map only the physical path.
- Make, shell and Tcl entrypoints contain no explicit affected production Scala
  leaf paths. Resource copy uses `src/main/resources` separately and is unchanged.
- Package-based Scala imports, emitters and `soc/core/ooo/*.class` classpath checks
  remain unchanged. A filesystem directory rename is not a classpath rename.

## Historical evidence is not migrated qualification

Historical reports, JSON qualification/receipt/profile manifests, frozen source
snapshots, patches, hashes and exact-source compatibility bridges are preserved.
Their old paths still refer to their original source commits/snapshots. The move
manifest is evidence of byte identity only; it does **not** relabel any old PASS,
prove equivalent generated RTL/diagnostic paths, or certify new synthesis, timing,
GSIM execution or board behavior.

Exact-source loaders that require an old full path inventory deliberately remain
fail-closed on the reorganized tree. Reproduce their old result from the recorded
commit; do not translate their keys or rewrite their SHA256 values to make the
new tree pass. In particular this applies to `fpga/next/*source_bridge.py`,
`fpga/zu15eg` frozen staging/release audits, retained-receipt checkers, frozen model
reuse/comparison scripts, and all `source_snapshots`, `reproduction`, `fixtures`,
`evidence` and dated report paths. Their old references are intentional.

Fresh current runners may create new receipts with the new paths. Optional
baseline comparisons require a baseline whose source inventory matches their
contract; they must reject old-path receipts rather than silently normalize them.
The current posted-preparation host test explicitly reads historical `git show`
paths separately from the relocated working-tree paths, preserving its original
comparison and byte hashes.

[Reference audit](ooo-layout-reference-audit.json) records all pre-move `core/ooo`
mentions and their disposition. History-only scripts and reports are not current
qualification of this layout.

## Verification

Run `python scripts/audit_ooo_layout.py` on this migration snapshot. It compares
all moved bytes against the pinned Git tree, verifies unique old/new sets, SHA256,
unchanged package/API text and all other production inputs, checks the three
recursive inventories, and parses changed Python scripts. Subsequent functional
changes should fail this historical identity check; it is not a permanent CI
constraint on future development.

Compilation and short host-check outcomes are recorded with this migration's
commit review. No full GSIM, Vivado, new RTL model, routed timing or board run is
claimed by the directory move.

### Host checks on the migration snapshot

- `python scripts/audit_ooo_layout.py`: PASS, 149 exact byte-identical moves,
  unchanged other production inputs, complete recursive inventory and syntax.
- `git diff --cached --find-renames=100% --name-status`: exactly 149 `R100` moves;
  no added/modified/deleted production Scala content. `git diff --cached --check`: PASS.
- `python -m unittest discover -s simulator/gsim -p test_lane1_owner_match_cli.py`:
  3/3 PASS.
- `python -m unittest discover -s simulator/gsim -p test_head_drain_cli.py`:
  4/4 PASS.
- The same command for `test_prf_address_clear_cli.py`: 2 PASS, one existing
  `test_old_profiles_remain_explicitly_off` source-string failure.
- The same command for `test_posted_preparation_priority_cli.py`: 2 PASS, one
  existing `test_launch_seal_payload_and_prepared_store_qualification_are_unchanged`
  frozen-source-prefix failure.
- The same command for `test_timing_batch_cli.py`: 4 PASS, one existing
  `test_frozen_bank_and_final_complete_field_counts` frozen-bank SHA256 failure.

All three failing suites were rerun with the **same full commands** in a temporary
complete `git archive bb1bce1` baseline snapshot (original scripts, original flat
paths, original source bytes). They reproduced the same three failing assertions
and the same other eight passing tests. No expected hash, count, assertion or
baseline was changed to hide those pre-existing failures. This is 15/18 passing
host checks, not an all-green regression claim. Baseline and migration full logs
were retained for review outside production sources.

### Scala compilation

`mill -i IonSoC.compile`: PASS (exit 0). A fresh, independent `out` compiled all
215 current Scala sources and 18 HardFloat dependency sources using the existing
pinned tool/dependency cache; no previously compiled DUT classes were copied.
Elapsed time was 114.4 seconds, peak observed aggregate RSS 1.80 GiB, final `out`
size 25 MiB. No test elaboration, RTL generation, simulator model or synthesis was
run for this move. The Scala source-discovery result includes all relocated files.
