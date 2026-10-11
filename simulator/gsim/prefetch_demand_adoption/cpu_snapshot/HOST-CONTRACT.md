# Same-board read-prefetch demand-adoption CPU replay

Status at source freeze: no DUT emission, GSIM generation, model/host C++ compilation, or execution has been performed for this replay. The parent has granted the single heavy-work slot after focused-r4 PASS; each executable stage still checks the focused receipt and source/host authorization hashes.

## Identity and immutable comparisons

- Candidate tracked tree: `cpu-source`, archived from test commit `507c81beefede7ecb806dc5219d65df8591ba5df`, with production checkpoint `0c4beee087d3d4de036406ce3312cc4ff01a1b8c` unchanged.
- Baseline: the independently qualified `read-prefetch-dirty-retry-candidate/cpu-ab-r1/on` model, runtime, and receipt. Its original identity remains separate. Bare COPY: 261697 ROI + 8058 flush cycles. Sv39 COPY: 273088 ROI + 8204 flush cycles.
- Six matching-board wrappers come from that qualified CPU source, including `PostedStoreBoardLineageGsim.scala`. Only the matching entrypoint allowlist gains `--read-prefetch-demand-adoption`; actual production option plumbing and configuration arity remain from the candidate tree.
- Both arms enable dirty retry. OFF omits the adoption flag, ON appends it. Full profile/cache/fabric JSON must equal qualified B plus the new adoption boolean; assembly-contract bytes must match.
- Fixed B: ROB16, PRF48, LSU4, DTLB16, DMA4, full peripheral population. Guest, 64KiB COPY twice, boot/host service harness, memory initialization, byte/checksum/trap/request/reply/drain oracles, and independent R32/B32 service laws remain pinned.
- Actual OFF must reproduce all original result/performance/oracle/fabric fields (105 fields) and complete Bare/Sv39 AXI traces before any same-source comparison is accepted. Constructor identity alone is insufficient.

## Attachment observation

The original ALLOC/REFILL accounting stays intact: an attached demand is an additional response obligation on an existing read-origin PF, never a fabricated demand allocation or resident useful-token event. Original PF/read/store and captured writeback origins are immutable.

The attachment ledger binds full PA, exact word address and offset, MSHR host allocation generation, current response ticket, and both halves of the complete 68-bit acquire/refill tag. The hardware PF tag intentionally uses a zero posted-generation field; host allocation generation distinguishes later reuse. Payload reads are guarded by accepted requests, live owners, issued-A events, or accepted refill/CPU-response events. Idle A/payload interpretation remains UNKNOWN.

Required observations and gates:

- One attachment to a live, issued, non-store PF with no known error and no occupied/reused response ticket.
- Stable attachment/full PA/word/ticket while live; exact acquired/refill tag including high bits; original PF and writeback kind retained.
- One refill, then one actual physical CPU response from the independent accepted-request queue. Retired attachment records survive MSHR/ticket reuse until that physical response is observed.
- No duplicate A issue or source reuse before old acquire completion; at most one external AR per matching live full-PA owner generation. Original full AXI and per-PA data histories remain archived.
- Known-error lifetime is checked when observed; zero error activity is labeled NOT_EXERCISED. The component suite supplies denied/corrupt/held-E coverage. The full CPU observer does not manufacture an E handshake cycle; `cache_e_cycle=UNKNOWN` until an actual valid/fire signal is available.
- Successor allocation and A issue record the prior attached owner and distinct full PA before its refill, both-owner lifetime, and first external R timing. Analysis also compares to the actual CPU response timestamp.
- Physical live/WB facts remain separate from effective read candidate owner/release blockers. Blocked and no-offer intersections are recorded without assigning unobserved causes.
- Attached fills must not create a resident token. Original `pf_useful` retains its resident-use meaning; attachment totals are separate.

## Controls and bounded work

Preserve original passive controls, original byte/trap/memory negatives, and the four corrected posted refill/install controls: wrong PA, duplicate refill, generation mismatch, and missing install. Add attachment wrong PA, wrong ticket, duplicate attachment, and lost-binding negatives. Only the existing applicable controls and the two requested COPY cases per arm run. No 54-case/full-suite or 25M peripheral warmup is authorized here.

## Tool/build plan

Freeze every source, wrapper, host, guest and tool hash before emission. The runner rejects additions, removals or changed bytes and binds the focused receipt to the production/config source hashes. Parent authorization must contain the focused receipt hash, matching production checkpoint, frozen source-manifest hash and a granted slot.

Use official GSIM split output (`--threads=1 --cpp-max-size-KB=1024`) and serial Clang compilation. Compare actual generated CPP/header hashes, complete flags, compiler/tool identities, current resolved dependencies and old object hashes before considering exact-byte TU reuse. No normalized/semantic object reuse. A changed header forces every affected model object to compile fresh. Original qualified system-header historical hashes are unavailable; current dependency resolution cannot fill that historical gap. Default is fresh compilation unless a precise reuse authorization is supplied.

Source preparation and static syntax checks do not establish DUT behavior, throughput, hardware cost, or physical timing. Performance remains unmeasured until actual OFF/ON execution passes all gates.
