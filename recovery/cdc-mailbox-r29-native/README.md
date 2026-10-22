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
