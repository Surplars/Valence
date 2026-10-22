# r29 mailbox recovery and scoped query reuse

The r29r2 mailbox checker passed all 32 source-known dynamic mailboxes against
the original native raw DCP. This is structural evidence only. Full post-only
CDC bounds, timing and later implementation remain required. CPU300/fabric250
targets and the boot50 hardware configuration are unchanged. No RTL, ROM or
frozen input inventory is changed by this stage.

The precise correction is an internal literal proof for hierarchical outputs
with no external net or consumer. Vivado's full/all-arcs fanin from that PIN
returned only itself; from its explicit LOWER_NET it returned the real GND/G.
The checker requires one literal lower net/segment, one actual leaf driver,
and the same single full-cone driver, with exact primitive/pin/polarity and
net TYPE agreement. It never treats an empty proof or missing FF as constant.
The active mappings, captures and original timing scopes are preserved.

Native source/evidence hashes and the prior 25/7 failure are retained in
`functional-receipt.json`. Large raw local logs/DCPs are not copied into Git.
The targeted script is `fpga/common/check_dynamic_mailboxes.tcl`; its five
arguments are original raw DCP, original frozen root, checker, exact cache,
and a new report path. It calls the actual mailbox checker, never full collect,
never creates clocks or exceptions and never writes a DCP.

## Original-raw full post-only continuation

Export the current committed `fpga/common` tools into a fresh external overlay.
Do not change the original frozen root, inventory, raw DCP, IP or provenance.
Preserve previous failed post reports/logs separately before reusing the existing
stage entry. Do not use the failed post-stage DCP as the input.

1. Verify raw SHA256 is
   `a425a8e2833df7366b00e82bdd874cffb5eb12dd5dcd6ec71946882382aaa6fe`.
2. Run the overlay's `resume_diagnostic.py ORIGINAL_FROZEN_ROOT synthesis`.
   It must return `mode=post-only`; inspect its new `recovery_tool_sha256`
   map, original manifest/IP/project checks and exact checker hash. Preserve
   this new preflight record; do not overwrite or relabel an older receipt.
3. Run Vivado 2025.2 with a fresh external log/journal:
   `vivado -mode batch -source OVERLAY/resume_diagnostic.tcl -log NEW/post.log -journal NEW/post.jou -tclargs ORIGINAL_FROZEN_ROOT/diagnostic-run/config.tcl synthesis`.
   This opens the verified original raw and reexecutes all post proofs. It
   does not resynthesize or regenerate IP. Keep the existing requested thread
   count and original CPU300/fabric250 target constraints.
4. Continue only after the complete post flow passes and its output is bound by
   the normal diagnostic record. A 32-mailbox PASS is not this full acceptance.
   No signoff admission, frequency whitelist, bitstream or board test is granted.

## Combined query-reuse stage

`query-reuse-receipt.json` binds the final checker and focused test results.
The functional checker was first committed separately as `ff06eeb76cd8bdf5f9d2e303d1266d35257c728b`.
The combined change modifies only `common_cdc::payload`; the other 42 procedures,
including the native-passed lower-net helper and mailbox width proof, have
identical arguments, defaults and bodies. Native 32-mailbox evidence belongs to
the functional checker; the combined full post-only run is still pending.

Reproduce the new mock suites from a Git checkout with:
`python3 -m unittest fpga.common.test_mailbox_internal_constant fpga.common.test_payload_query_reuse`.
The payload wrapper retrieves the immutable functional Git blob
`5a1a0ba012cae678d0562101251d53d4907ab529` and verifies SHA256 `7da9f0426195377447a5918af7432ffd4e32f45be04e0c2a8677ad65b31d89a7`.
Preserve that functional content as an earlier delivery commit before the final
payload commit. Aggregated delivery commit IDs may differ; Git blob and SHA256
identities must not. The oracle is never regenerated from the candidate.

The wide-520 mock retains all 520 endpoint fanin traversals. Segmented-net
queries drop from 2608 to 528, owner queries 5374 to 11, property queries 37146
to 17084 and clock queries 5902 to 539. These are modeled API call counts,
not a measured Vivado runtime improvement. No endpoint proof or budget is
removed and no result is cached across calls or stages.
