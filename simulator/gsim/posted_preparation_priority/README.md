# Posted preparation priority: tracked qualification sources

This is a tracked source/evidence record, not a self-contained replay bundle or a
new DUT run. Production candidate aa37b6a00666ee9be4284ea1793cd376c0775344 remains
default OFF. Its 23-file change is copied exactly except the experiment document
which adds an explicitly dated review snapshot, and the CLI source-invariant test
which uses published tree 20831b2ee236504cbcfb3536af70d4f9d62f84f5 instead of its
unpublished tree-equivalent recovery commit. The actual source comparison bytes
are unchanged. The recommended v3 is unchanged.

## What belongs in the integration

The dedicated `src/test/scala/ooo/PostedPreparationPriorityGsim.scala` is the exact
executed wrapper (SHA256 6022d5e7140a999e0d2d9ec9558c04816bd5cfb4988d89458497584a1de557f0).
The `source_snapshots` tree preserves original tool filenames and bytes:

- Focused: final raw-decoder C++ host, independent raw instruction/byte/PMP/Sv39
  reference, fixed r3 validator, exact negative-control contract, r4 source freeze,
  original runner/assembler and scoped generic-OFF bridge builder.
- CPU: all custom host/observer headers, parsers, host-only controls, strict
  terminal/pair/compressed-control/storage validators, source/profile/guest pins,
  full-model/GC runner and object-identity verifiers. No generated model C++, FIR,
  SV, objects, ELF, guest binary, trace or log is copied.
- Warm0/warm6/WRITE18: the separately frozen `close_pair.py`, exact controls,
  contract and freeze are also retained. Their functional-only pair schema does
  not require a gain or a nonzero translation witness; original oracle/trap and
  exact case19 authorization remain mandatory. Its preparation freeze correctly
  retains its historical zero-qualified-pairs count.
- Native: actual profile fixture, constructor/census/control analyzers and five
  semantic negative controls, plus their small source helpers.

Some snapshots are executable historical scripts, including import-time writes.
Do not import them for discovery or run them directly from this snapshot tree.
No new Makefile hardware target is advertised before a separately verified path
adapter exists. The dedicated Scala class is available through the existing Mill
test source layout; integration compilation of that added class is still pending.
Only the wrapper in `src/test/scala/ooo` is a compiled test source. The identical
`.scala` copy below `simulator/gsim/.../source_snapshots` is provenance evidence,
outside the Mill `IonSoC.test` source directory; do not add the snapshot tree to
Scala source roots or compile both copies of the class.

## Immutable history versus portability

Original snapshot paths and SHA256 values are tracked in source-origins.json.
Run `python -B simulator/gsim/posted_preparation_priority/verify_sources.py`
from a repository checkout for source hash/AST checks only. The separate final publication manifest
binds every changed repository path, mode and raw blob.
Existing receipts, commands, logs, failures and archives remain unchanged. The
final focused host is r4, SHA256
494e402d41c67caf15f9599afc7eb774b9414297c48d55a4336339fe876f6d36;
its fixed validator remains r3, SHA256
1c60825f2bb06eb4dcc24a6386eaaeb163bec6bbe1a52a359bb0532da0163971.
Do not replace it with the earlier r1/r2 validators or repair old failed receipts.

Historical focused replay requires restoring the recorded recovery workspace.
`run_step.py` locates sibling implementation/config-source, toolchain and the
resource monitor. It compiles the wrapper there, generates two real models and
uses ASan/UBSan; `--slot-granted` is a real resource admission, not a cosmetic flag.
The assembler reads sibling tool receipts and absolute trace paths. The strict
validator compares absolute runtime argv, binary/host hashes, all 26 cases per
side, exact poison failures, full constructor products and generic-OFF collateral.
The bridge builder also needs several historical Git objects and native exports.

CPU scripts similarly depend on sibling prep/object/original-reference trees,
exact tool/environment profiles, all selected source and passive wrapper files,
the unchanged guest/ELF, original full models and all raw artifacts. `pair.py`
checks the actual parser process argv (including Python executable and
stage_measure.py path), result digest, nine parser hashes, original oracle set,
real trap-negative and applicable seven precise proof mutations. Some archived
positive raw files require their existing raw-storage sidecar; editing receipt
paths or restoring only a summary cannot satisfy the fixed verifier.

Native scripts require their frozen source/classes, planned output layout,
historical baseline exports and tool receipt. A few analyzers write result
directories or create mutation copies; none was executed during source integration.

For a fresh portable run, make a new adapter and fresh output namespace; bind the
new absolute paths, selected source, exact guest, tools, full profiles, host and
validator identities before execution. Preserve these old snapshots and receipts.
Repeat all required positive and exact negative gates for the new binding.
Do not transplant a PASS or rewrite an old source freeze to match the adapter.

## Evidence recovery index

The adjacent `evidence-index.json` identifies confirmed durable archives and their
whole-file hashes, plus original local result/contract anchors. These references
do not grant a new execution result. In particular, the old full54 matrix belongs
to older source and is excluded. Full raw closure is deliberately external to
this tracked source-only record.

After restoring original artifacts and validating archive hashes, use the
original focused verifier's `verify(aggregate, digest, production_head=...,
tool_receipt_sha256=...)`, and original CPU pair.py `verify(pair_path)` at their
original paths under the recorded tool environment. Restore original raw files
or supply only the already-accepted sidecar mechanism. These are historical
revalidation instructions, not commands executed by this source integration.

## Closed qualification and remaining limits

The new priority candidate's five original CPU pairs are closed: Bare19 is a
measured gain; Sv39 case21, warm0, warm6 and WRITE18 have equal primary performance.
Original pair statuses are preserved, including NO_CASE21_GAIN_AND_STRUCTURE.
The earlier parent's frontier/LRU five-case results are separate evidence.
Exact pair identities and primary cycles are in
`../../../docs/experiments/posted-preparation-priority-evidence.json`.

For Sv39, equal primary ROI/tail does not imply identical physical-boot or passive
owner-observation diagnostics. Bare19 read-owner cycles remain 159,869 on both
sides; a higher occupancy mean from a shorter ROI does not establish faster DDR.
The main 266→265 gain and final-drain 291→293 regression both remain documented.
Native state equality is not mapped PPA/STA or zero-cost logic. This opt-in
candidate's Bare total cycles remain about 4.19% above original v3.

The integration's source/host checks pass in their stated scope. The preexisting
prepared-store native metadata assertion failure was reproduced on the unchanged
published-equivalent baseline and retained. No all-repository pass or newly
executed hardware result is claimed. Source snapshots retain their historical
statuses; the warm analysis freeze's zero-qualified-pairs count refers to its
preparation time, not the later terminal pair records.
