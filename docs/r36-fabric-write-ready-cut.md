# R36 fabric setup: write A occupancy boundary

## Measured target

R36 native final: fabric250 WNS -2.536 ns, data 6.206 ns (logic 1.486,
routing 4.720), skew -0.135, 16 levels. Actual report path:

maintenance[0] -> tag-bank address mux / RAM read -> needsProbe -> ordinary
Home downstream request valid -> data/TL bridge A.valid -> outer arbiter source
selection -> line-transfer arbiter writer A.ready -> activeData[17] CE.

This is a backward READY dependency, not the CoherentWriteDispatch empty bypass.
An initially considered dispatch-register change was withdrawn before compiling;
CoherentWriteDispatch and all its fixtures remain byte-identical to HEAD.

## Candidate

TileLinkLineTransfer gains optional isolatedWriteA (default false). Mixed Home
selects it. Two registered-occupancy, nonflow/nonpipe A beat slots sit between
the writer and the line-transfer arbitration. Writer A.ready depends solely on
local capacity, not ordinary-directory lookup or external arbitration readiness.
All A fields, including source, mask, address, opcode and data, cross together.
The read path and upstream write-descriptor acceptance policy are unchanged.

Capacity is two additional transport beats, not additional Home transactions.
The first external write beat gains one edge of transport latency. Continuous
accepted A beats retain II=1; a full queue starts draining on downstream readiness
without waiting for a new producer acceptance. There is no combinational ready
bypass even when full. State holds stable while the external consumer stalls.

Writer advancement now records acceptance into the transport queue. This is
not a posted completion: the real external D AccessAck is still required before
line response, release acknowledgement, maintenance advancement or owner freeing.
The existing downstream-manager contract in this implementation requires D only
after the eighth external A acceptance, which necessarily follows eighth enqueue. Home drain remains blocked
by the original maintenance/release transaction owner until that real response.
Coordinated reset clears both queue occupancy and original writer ownership.

## Verification scope

Use one existing HomeTagRamGsim mixed fixture (2 acquire entries, 512 directory
lines, compact tags crossing 4 GiB), with its unmodified independent protocol and
byte oracle. Includes dirty writeback/probes, stalled A/D/GrantAck, ownership,
competing release/acquire, errors, tag aliases and reset. The helper-dispatch
baseline checks stay unchanged because that module was not modified.

Compile and GSIM results are recorded by the combined batch; this document is
not proof of routed improvement. CPU/fabric target constraints remain unchanged,
and final physical setup/hold, CDC and board qualification are still required.

## Executed focused result (2026-10-23)

Combined Scala compile passed. One fresh sanitizer-enabled GSIM model and the
independent `--inject-data` negative completed in 32.64 seconds, source hashes
unchanged. `HOME_TAG_RAM_PASS mixed=1 lines=512 entries=2` covers aliases (3
writes), concurrent E/C/upstream (2), release saved recheck (1), disjoint release
saved recheck (2), and held-reset (2). Injected corruption was rejected by the
independent Grant data mismatch oracle. Receipt:
`build/gsim/r37-fabric-write-ready/fabric-cut-receipt.json`.

No additional full-system simulation or physical implementation was run here.
