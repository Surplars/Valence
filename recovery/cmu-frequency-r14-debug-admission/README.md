# R14 isolated fixed-debug DMI admission barrier

The production debug endpoint is a boot-only RAM loader, not a RISC-V architectural Debug Module. dmstatus.version remains0; nonzero DMCONTROL halt/resume writes remain failures. This stage does not implement hart halt/resume. The new barrier's `resume` means reopening DMI admission only.

## Real missing boundary

The original DebugDmiClockBoundary transparently forwards two mailboxes without an admission hold. A loader DMI SBA trigger returns its DMI response before its RAM request completes. Consequently a zero request-minus-response count is not proof of no debug-originated memory ownership. JtagRamLoader deliberately preserves a presented request (`offered`) and accepted request awaiting reply across DTM link loss, abort or timeout.

The new standalone DebugDmiAdmissionBoundary is not instantiated in CommonMachinePlatform. Existing modules receive only default-false observational options: crossing local sourceIdle/destinationIdle, and loader dmiOwnersIdle = !offered && !awaiting && !responseValid. The latter explicitly excludes CPU-control response owners and is not whole-loader or fabric quiescence. No existing arbitration, memory request, DMI payload or default throughput logic changes.

## Protocol and reset contract

The controller runs in the fixed DMI source-clock domain, not AON. A nonzero strictly increasing epoch owns one admission stop until terminal consumption or common cold reset. Prepare acceptance wins against a same-edge new source request. New offers remain backpressured outside the boundary; requests already accepted into the mailbox and all old responses continue normally.

Source acceptance/response-consumption accounting and both source-local mailbox idle observations must clear before an epoch-tagged probe is sent. The destination then requires both destination-local mailbox idle observations and real loader DMI/RAM-owner idle before returning a matching proof. Thus the proof follows source closure and actual response consumption; it is not an asynchronous AND or a fixed source-cycle wait. A loader with autonomous new work would need additional retained/revalidated owner proof: this narrow contract relies on the actual loader creating RAM work only from admitted DMI commands.

Matching cancel is accepted during pending drain or held, but does not discard requests or memory work. Matching resume is accepted only after held; cancel wins simultaneous eligible commands. Either decision waits for actual drain, then a release/acknowledgment round trip. Terminal remains backpressured with source admission still closed until the consumer accepts it. New prepare cannot steal the previous epoch. Wrong, zero, stale and duplicate tags are rejected; epoch numbers do not wrap/reuse until common reset.

Active-epoch link loss is a deliberate observable, indefinitely retained fault. A local asynchronously asserted, synchronously released transport-reset witness catches a short link pulse even between source edges. Held, terminal and admission are immediately suppressed, then sticky fault remains until coordinated cold reset. Existing loader RAM work continues through genuine memory handshakes; the DMI transport reset is never used as a bus-owner reset or a completed drain. Terminal.valid may therefore be revoked by a link fault while backpressured; this is an explicit fault condition, not ordinary irrevocable terminal behavior. Fault recovery requires coordinated reset of controller, endpoints and external transaction models, not a unilateral live-domain reset.

A canceled epoch may briefly expose held while its drain/release cleanup progresses. Held is only debug-originated owner evidence, never permission to gate clocks. Consumers must honor the cancellation and fault state.

## Validation scope

Native tests use the real loader, DMI request/response mailboxes and admission controller on two independently phased clocks. RAM responses are an explicit external test model; no CPU, full downstream Home/DDR path, AON control crossing or physical gate is included. Independent source/destination/RAM ledgers check accepted work and payloads, including offered-not-yet-accepted RAM ownership. Original loader Scala checks and fresh default performance RTL equivalence are also recorded.

Remaining integration must combine this boundary with actual downstream accepted-owner proof, CPU-control response consumption, other network/MMIO admission, DDR CDC ownership, stopped-clock interrupt capture and real gate/DRP witnesses. The four new control mailboxes also require scoped physical CDC constraints and native timing validation before a platform integration can be qualified. Do not wire this one-entry PASS into a complete system ACK.

Production backend-present/whitelist remain unchanged, as do default50MHz/optional U-Boot/direct BootROM Linux goals and performance CPU300/fabric250 constraints. Upload still waits for the earlier explicit receipt permission request; local commit does not mean remote publication.

## Completed results

Both native ratios (source/fabric half-periods5/7 and11/5ns, fabric phase1ns) pass the complete fixture. Directed checks cover ARM/SBA early DMI response versus real offered/awaiting RAM work, source and destination response backpressure, accepted mailbox requests held at the loader, pending cancel, normal resume, terminal backpressure, same-edge prepare priority, paused fabric clock, wrong/stale/zero/duplicate epochs, and cancel/resume collision. New requests remain unaccepted through held and terminal wait, then complete exactly once.

Long link loss while RAM is offered and a1ns pulse entirely between source edges while RAM is awaiting both preserve actual memory completion but retain observable barrier fault. A separate final case presents terminal under backpressure, then applies a short link pulse while setting terminal.ready: no terminal retirement or reopening occurs; common reset restores operation. Unsupported architectural debug commands still fail truthfully.

Both wrong-data and wrong-drain independent oracle controls reject at their designated markers. All native positive attempts passed; r1/r2 precede additional edge coverage and remain in the cloud output directory with their exact TB versions. Final r3 source/RTL/tool/log/simulator hashes were independently rechecked. Both original JtagRamLoaderSpec tests pass, and all248 default performance300-static SV files remain byte-identical to the r12 baseline. This is native digital DMI/loader-owner qualification only, not whole-system or physical signoff.
