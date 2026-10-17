# B0 ON/internal-line-grant result

Five focused protocol positives and three exact engine assertion negatives passed on the isolated historical50cb Home extension. This is Home/acquire-engine/AXI evidence, not CPU/cache integration, full-mask policy correctness, synthesis timing or throughput evidence. Production defaults/files remain unchanged.

## Observed results

- Basic delayed standard Perm D/E and delayed internal Block grant:57cycles,2requests/grants/E/completions; Perm4096 zero target reads, Block4160 exactly64B requested and returned.
- Denied shim:24cycles, one permission transaction, zero reads, error completion after E. The test shim changes only the engine's received denied bit; Home still published its successful grant. Separate ledgers deliberately retain that distinction. This does not test a Home internally denied permission allocation.
- Concurrent mixed held grants:39cycles,2transactions, one64B read. Both selected transports retain their held identities.
- Future dirty victim, B late:127cycles; C-first17, future Perm A21, unrelated Block A31/E47, C-last53, new Grant54/E55, old B111/ReleaseAck114. New target read bytes remain zero throughout complete drain.
- Future dirty victim, E late:129cycles; same C-last53/Grant54; old B111/ReleaseAck114 precede new E115. All64 old dirty bytes match C and backing W; old acknowledgement does not erase the reused abstract directory owner.

Totals:13accepted requests/A/grants/E/results; four64B native/AXI reads (4AR,32R beats,256B returned); two dirty writebacks (16C,2AW,16W,2B,2ReleaseAck). Successful permission allocations and the denied-engine-shim transaction generate zero target reads, including after engine completion and through12extra drained cycles. Host byte memory validates complete512-bit internal grant and result data; independent AXI write matching uses accepted AW ID/address and ordered W bursts, then exact B ownership.

Actual corrupt permission Grant, wrong Grant opcode and cap3 tests each exited1 with its specific model assertion and no sanitizer diagnostic. The assertion stderr files and hashes are recorded individually; generic Python failure alone is insufficient.

## Measurement/reproduction boundaries

One GSIM step per driven edge; returned public pins describe the current logical edge and compute the following NEXT state. Accepted event ordering is explicit in host/cases.py. Full pre-edge payload snapshots validate held offers. No private model state is read or written. Engine512-bit response and internal lineGrant are read only through generated public getters. The synthetic coherent client's dirty C payload is test traffic, not a real cache store/installation proof.

E transport hold suppresses Home-side E.valid before delivery; the test waits for the actual grant, checks absence of result while delivery is delayed, then checks real E and completion. It does not falsely claim to have observed the engine's unexported held E.valid.

Existing ReleaseAck priority remains strict when unlocked, with rotating grant selection. Tested finite traffic/eventual-ready completion is not a general continuous-release fairness proof. Home denied directory-publication suppression, OFF default equivalence, standard-D data grants and real cache/full-mask integration remain outside this first-arm result.

## Cost and artifacts

Compile9.924s, emit2.015s, GSIM generation0.505s, two objects4.284s+2.020s, host link4.041s. Positive0.310s; three negatives0.109/0.108/0.106s. Runtime sampled/after allocation stayed below7.5MiB, well below48MiB inclusive cap; minimum sampled free2351419392B, above838860800B floor. Use max(sampled,final-after) for the early compile/emission receipts whose sampled peak excludes the final snapshot.

Runtime executable SHA256 ce2d96cca3bafe872fddcc3d06ded95a6d5704d6c3d924567e19b6a2c3190a20. Inputs, command vectors, source deltas, independent gates, model/object outputs and exact per-case event traces are retained. The generated files are not a source-only publication package. No additional model arm has been emitted or run at this report revision.
