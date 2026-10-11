# Exact raw-PMP change publication candidate

## Source identity and scope

Prepared from local frozen 4469c903a3efe2b16893666075cbdaad250ffae4; its production files match tested b37d8f1bffb1e053a1ed7dd0a3d81c4aec8ceb70. The coordinator subsequently published documentation-only completion as remote development 6b27c67153709f5d2ddd1bc46b6f2a824a8551df (tree d793961ee08bb2f7c9e77c0ea081ba89798253cb; local 6cedacc). Preserve that newer development tree when applying this candidate's minimal patch. Main is untouched.

The optional `publishedPmpChanges` flag defaults false. The effective parameter is true only with machine CSR ownership, implemented PMP, VM, and an adapter precheck or posted-epoch consumer. No new producer state/port exists in other profiles. Official native/GSIM profile and board plumbing carry the flag; historical arity guards now explicitly require it false. Existing release manifests are not rewritten.

## State and phase

At the actual execute/legal/non-IMSIC/write branch, each implemented cfg byte is compared after the existing reserved-bit/W-without-R filter and own lock. Each address comparison is qualified by its own lock and successor locked TOR, without the narrower active-permission predicate. The producer's default-false raw-change wire is registered every edge. No-op, invalid, read-only, unexecuted, locked and held completion cycles clear it. An OFF-address change still sets it. The narrower permission/refetch predicate retains its original semantics and shares these local comparisons.

Immediately after the raw CSR write edge E, the registered level is 1, matching the old raw-snapshot comparator over E to E+1. Adapter authorization and posted epochs consume that level at E+1. Same-cycle contextChanging, CPU blockNew and cache seal are unregistered. On consecutive changed edges, levels remain 1,1 and both increments occur. No complete-image producer comparator, delayed PMP state, request pipeline stage, backpressured event receiver, or handshake gate is introduced.

The adapter's previousVm remains the same 68-bit unconditional snapshot initialized to zero. Producer privilege resets to M=3, so startup total authorizationChanged may be high despite unchanged reset PMP. The explicit adapter opt-in defaults false independently of OooParams; arbitrary raw-state fixtures retain their full raw cfg/addr fallback rather than trusting an implicit zero sideband.

## Clock/reset integration audit

Current source chain is BoardSocTop ordinary `Module(new MachinePlatform(...))` at line 321; MachinePlatform ordinary `Module(new MappedMachineCore(...))` at line 231; MappedMachineCore ordinary MachineCore plus DataTranslationAdapter; MachineCore ordinary IntegerCore; IntegerCore ordinary IntegerBackend; IntegerBackend ordinary MachineSystemUnit. None of those chain files wraps either producer or consumer in withClock/withReset/withClockAndReset. Both inherit the same CPU clock and common reset. The source hold signal controls CPU frontend work, not these register clocks. The withClockAndReset sites in BoardSocTop and MachinePlatform serve peripheral CDC, outside this chain. Registered producer level and fallback history both update unconditionally on every CPU edge. Native common-clock evidence is additionally recorded in the earlier read-only audit manifest; no independently gated/reset consumer is supported by this contract.

## Qualification plan and limits

Four real CSR -> paired old/new adapter models cover 8/16 entries, registered PMP ranges off/on, precheck-only, posted-only and both. Existing independent architectural CSR/filter/range oracle remains the source of expected raw and decoded image each cycle. Expanded host checks compare full authorization phase, epoch/stable phase, immediate contextChanging and adapter memory owner/request/response handshakes. Held physical requests, held responses, reset with an owner, current/stale prechecked requests and all existing legal/illegal CSR/MPRV/TOR tests are included.

One separate real-adapter abstract-image fixture tests consecutive atomic changes, same-value and intervening no-op changes, return to a prior image, idle/ready suppression and resets. The capacity-one actual CSR producer cannot execute writes on adjacent cycles; no such throughput is claimed.

Event-source negative controls route an early combinational condition, a late registered level, permission-only level, unfiltered write enable, or readiness-gated history. These are test-only mutations; the positive path uses the producer's public registered output. Native mapping, scalar counts, same-board performance and physical timing remain unqualified until run and reported explicitly. Prospective declaration savings are 495 bits for eight entries and 991 bits for sixteen, not mapped FF/LUT savings.

## Qualification completion

See [the matched-board result and explicit ON entry](../fpga-next/pmp-change-publication-v1.md) and [the pinned evidence summary](pmp-change-publication-evidence-v1.json). The original design and reset contract above remain unchanged.
