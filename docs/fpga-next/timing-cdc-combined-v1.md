# Combined timing/CDC board candidate v1

Status: combined Scala configuration, four complete constructor reports, native
export and the single matched CPU replay passed on source `b37d8f1`. The complete
results and limitations are bound in [the evidence record](../experiments/timing-cdc-combined-evidence-v1.json).
Vendor primitive, physical clocks, CDC/RDC, STA and board behavior remain
unqualified. No Vivado or local board restart was performed.

The explicit entry is `fpga/next/board_timing_cdc.py`. Its default action is
source-only preflight. `--print-native-options` returns the one frozen option
list shared by native `FpgaNextMain`, pure `FpgaNextProfileMain` and the actual
full-population `CpuMatchingBoardProfileGsimMain` CPU emitter. `--emit` exports
native RTL only when the coordinating task grants the shared build slot.

The versioned manifest selects the complete previous physical board B perimeter
plus dirty retry, read-prefetch demand adoption and registered PMP regions. The
rollback `board_profile.py`/`board_release.py` manifests and their generic policy
defaults remain frozen. Their complete constructor checks require explicit false
for the added PMP profile/core fields; a missing or true actual value fails.

The complete retained geometry is RV64GC, two-wide, ROB16, PRF48, LSU4,
DTLB16/ITLB8, four entries in each PTE cache, I/D 32 KiB each, two ways, 64-byte
lines, read MSHR2/response2/writeback2, four DMA line owners with line transfers,
four DDR shared slots/two write slots/16-beat bursts/four AXI ID bits/2 GiB.
CPU/AON/DDR UI clocks are 100/50/250 MHz and UART is 460800 baud. The physical
assembly keeps the two-slot tri-speed MAC and USER2 JTAG RAM downloader. ROM must
retain its ANSI boot menu, netboot and JTAG download menu. Before physical staging,
bind the actual local ROM contract and bytes, including its existing netboot and
CRC settings; the tracked firmware test contract is only an ABI reference.

No ROB64, memory-proof frontier, translated-response empty flow or unrelated
resource selection is added. The active running or stopped local source is not
modified by this isolated candidate.

## Exact source boundary

[The source integration record](../experiments/timing-cdc-integration-source-v1.json)
contains old/new hashes and semantic conflict resolutions. All eight changed
production files are byte-identical to their independently reviewed PMP, cache,
BSCAN and MAC candidates. The only three cherry-pick text conflicts were PMP
integration into the export CLI, native CLI help and matching board wrapper.
The actual six-file matching envelope remains present. BoardSocGsim still
requires an explicit configuration, instantiates MatchingManagedBoard, checks
the additional named PMP argument against the actual core flag, and compares
complete core/cache/DDR geometry. The native BSCAN helper import and staging are
retained alongside the CLI additions.

The local adoption review base and public adoption publication have the same
full tree. The latter is the intended future CAS parent, not fabricated local
Git ancestry. Publication belongs to the coordinating task.

The MAC collector-only increment is integrated. The native export and CPU model
executed on `b37d8f1`; an exact dependency bridge preserves all production,
configuration, wrapper, host, guest and tool bytes that built them. The later
full tracked tree was not dynamically re-executed.

## Executed combined gate and remaining physical work

The granted combined run compiled the settled production source once, checked
the exact pure constructor and matching actual instances, emitted one new CPU
model and ran the qualified adoption-ON host for Bare and Sv39 COPY, each 64 KiB twice,
with the unchanged R32/B32 DDR service law. Compare full architectural, byte,
reply, owner, fabric and traffic records against the qualified adoption-ON
references (Bare 251815 + 8053 clean-tail cycles; Sv39 250604 + 8187).
Both cases reproduced all 105 fields and complete AXI and supply traces exactly.
All three actual-model read, memory and trap negatives failed as expected.
No new OFF model was built. Retain the historical adoption zero-reload failure
and its later bounded-traffic result without rewriting either verdict.

Reuse unchanged individual PMP, cache-route, MAC and BSCAN fixtures only by exact
source bindings. The three adoption exclusions passed on both independently
tested cache models, and the raw-manager B tests passed. Real home-generated B
remains `UNREACHED`; see [the supplement scope and source bindings](../experiments/prefetch-adoption-supplement-integration.json).
The later authorized native/physical batch must establish source/profile/ROM/
constraints identity, vendor tests, setup/hold/pulse, CDC/RDC, DRC, utilization and
congestion. Physical and vendor qualification remain open, so these cloud gate
passes do not authorize a bitstream or board release.

The initial config gate passed 44 tests and rejected three stale test contracts.
A test-only repair updated remaining Product arities and changed two obsolete
small/generic GSIM test invocations to the actual full matching configuration,
with strict verification enabled and the original functional assertions retained.
Only the three failed tests were rerun; all passed. The original failures and
44 prior successes retain their original identities, with an exact test-body
and unchanged-production bridge. Native and CPU construction then passed.

The later MAC collector-only commit adds nine-mailbox/three-FIFO source-bound
review and five narrow registered-level recipes. It changes no executed Scala,
configuration, wrapper, host, guest or generated model bytes. Its separate
staging overlay has no mapped-netlist or physical qualification. The native
export from `b37d8f1` is preserved and is not relabelled as a newer export.
