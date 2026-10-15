# R16 shared-address lifecycle addendum

Fresh isolated component-only OFF/ON GSIM fixtures, exact TimingReady73Profile.on.coreParams with only sharedMemoryAddressState changed. No production, default, full-CPU, physical, Git, Vivado or Verilator work.

The wrapper suppresses host precheck-response input ports entirely and supplies one combinational hit-only response from the current public query. The only mapping is VA 0x80401000..0x80401fff to PA 0x80201000..0x80201fff. Hit requires query valid, explicit service enable, stable/equal epoch, matching page, legal size/alignment/page bounds and the matching R/W permission. The host enables this only after independently checking SATP, PMP and MPRV data privilege. This is a declared successful-hit service, not an Sv39 page-walker/TLB qualification.

Ordinary DataPort requests are accepted with periodic ready stalls and queued FIFO replies scheduled four host ticks after accepted requests in the pinned seed1 run. Once response valid is asserted it persists until ready. Each response echoes the accepted LSU return handle; outstanding handles cannot be reused. Canonical checked certificates are generated only from accepted actual ordinary virtual-store requests. Their full token, VA, PA, size and mask are checked against independent host expectations, separate from memory completion. The certificate echoes the accepted public request-origin epoch; query/proof epochs are independently checked against the stable external epoch. The accepted frozen request epoch is additionally checked offline against the settled expected epoch1 in positive-trace-evidence.json. This bounded stable-epoch service does not qualify stale or incorrect certificate-epoch rejection.

Four fresh directed benches:
1. DIV-dependent SW(VA+0), disjoint LW(VA+4): require write query, independently validated proof, actual relying start/bind/credit, later exact frozen store capture and request.
2. Same store with overlapping LH(VA+2): a write proof may be obtained, but no early-load bind/credit/frozen store is allowed.
3. Bare LD(RAM+1) plus younger stores: require real cause 4 and exact token/PC/tval, no faulting external request; track actual killed delayed preparation and legitimate later row allocations. Killed delayed preparation is a required report field; a zero count must be called unreached rather than forced.
4. DIV-dependent older BEQ, filler, younger accepted load: hold its owed response invalid through branch recovery and same-row/new-full-tag prepared-store reuse. Release original handle only then; require old-owner completion/forwarding/publication exclusion, new-row metadata preservation and eventual discard.

The host independently interprets the bounded instruction set and maintains architectural store bytes, accepted memory-service bytes, retirement values, full-token ownership and metadata effects. It is a directed component environment, not a general memory-order oracle or refetching CPU.

All original public outputs retain the corrected full-width serializer policy: every declared bit is emitted before narrowing, with only Valid/head-valid payload masking. Passive added lifecycle outputs are compared too, excluding only OFF/ON-specific store writer masks; each writer mask is checked independently where implemented.

Every driver execution uses a fresh attempt directory containing argv, cwd, exit code, raw log and hashes, including failed commands. No positive coverage or qualification is claimed until runtime and independent review complete. Source-mutant generation requires coordinator approval after positive witnesses are known.

Runtime uses always-stable, matching-epoch, RW-enabled service setup only. Circuit guards are independently reviewed, but no permission/epoch negative matrix is claimed. A relying bind must also observe the exact store data-readiness predicate false. Case3 with no killed delayed capture is explicitly partial/UNREACHED, never a blanket lifecycle PASS.
