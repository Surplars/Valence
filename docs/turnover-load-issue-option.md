# Typed turnover + registered load-issue option

`BoardSocConfig.boardParams(..., loadIssueForwarding = Some(true))` enables the existing `registeredLoadIssueForwarding` mechanism while preserving the selected timing profile. For `staged-fetch-turnover`, both fetch turnover/identity controls remain enabled. This is configuration composition, not a new bypass datapath.

The optional argument is forwarded by BoardSocTop, EthernetSocTop, BoardSocGsim and the managed/Ethernet exporters. MachinePlatform already takes a typed OooParams; it receives the configured parameter without a duplicate override. None preserves the profile's previous setting, Some(false) explicitly disables it, and Some(true) explicitly enables it. No default is silently enabled. Existing `staged-load-issue` profile behavior is preserved.

CLI fields are appended after DDR/cache-concurrency fields:
- BoardSocGsimMain index18: `[load-issue-forwarding:0|1]`
- ManagedBoardSocMain index15: `[load-issue-forwarding:0|1]`
- EthernetTimingMain index11: `[load-issue-forwarding:0|1]`

Omitting the field means None. Invalid strings fail closed. The option still requires registeredIssueExecute and rejects broad loadCompletionBypass. It does not change issue width, LSU slots, MSHRs, response ledgers, cache geometry, clocks, UART or DDR bounds.

The selected LSU result is already registered. It may wake/capture an ordinary ALU or branch's operand register on the same edge as PRF writeback. It does not feed memory-address operands, store preparation, M-unit readiness or same-cycle execution. Ownership/kill/fault/x0/atomic guards remain those of the existing independent forwarding proof.

Configuration-only tests: `ooo.LoadIssueCompositionSpec`. This new composition has not yet run hardware verification. Prior proof of the existing mechanism is documented in registered-load-issue-forwarding.md; its old-platform tiny CoreMark gain must not be projected onto the current32KiB/turnover/MSHR candidate. Include the opt-in composition only in the already planned combined candidate run, with exact architectural/PC-trace oracles and actual forward-use witnesses. A combined MSHR+forwarding result cannot attribute a gain to either feature separately.
