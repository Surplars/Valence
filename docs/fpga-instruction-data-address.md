# Packed instruction RAM address qualification

The independent-address variant passes six A/B pairs against the frozen qualified-
address packed layout. Both use the same eight 512×64 synchronous memories and the
held-hit snapshot correction. Every positive, seeded and held-prefetch log is
cycle-identical; enabled-read way equality and all corruption controls pass.

Only the way bit driving the RAM read address changes. It is chosen from way1's
resident valid bit and tag comparison. Aperture/PMP/invalidation qualification
continues to guard the actual read enable. On every enabled read, the new way bit
must equal the original fully qualified `hitWay`; the test assertion checks that
identity. Disabled reads have no payload ownership, and multi-cycle held replies
already reside in the independent `replyData` snapshot.

The selected native audit checks all eight instantiated bank address and enable
connections, recursively following local combinational wire definitions and stopping
at registers and memory outputs. Reference address cones include `io_invalidate`
and aperture comparisons reaching request bit63. Candidate address cones exclude
invalidation and use no request bits above32, while every read-enable cone retains
PMP and invalidation. Restoring invalidation in the address or removing read-enable
qualification causes the audit's negative controls to fail. This is a scoped native
logic dependency result, not physical timing or a universal transitive-path claim.

The exact source/model/native hashes are in
`docs/evidence/fpga-instruction-data-address-20261008.json`. A roster interruption
stopped the batch after nine completed models. Resume preserved the old progress and
incomplete model, verified every completed source/artifact hash, and rebuilt only the
three unfinished models. The only changed source was resume support in the runner;
all hardware and oracle sources remained byte-identical.

The proof uses a default-off trailing `independentDataReadAddress` switch for exact
A/B attribution. For production integration, the tested true branch can be placed
directly inside `bankedData` without introducing another top-profile knob. The
previous packed implementation remains frozen at `2b06f9b` for PPA comparison.
Whole-profile validation and physical timing/resource measurement remain separate.

The hardened follow-up audit also rejects unresolved internal aliases and cycles.
Legitimate leaves must be declared parent inputs/registers or wires bound to an actual
child-module output, verified against the exported child port directions. A missing
read-index definition is rejected by an additional negative control. The existing
frozen native files were rehashed and re-audited without rebuilding hardware; that
supplement is `docs/evidence/fpga-instruction-data-address-closure-20261008.json`.
