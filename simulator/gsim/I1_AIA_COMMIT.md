# I1 committed IMSIC and external FENCE.I completion

## Contract

`FiveStageConfig.withAia` is default-off and requires RV64 S/U. It adds the
M/S selector, indirect and top-external-interrupt CSR accesses (0x350/351/35c
and 0x150/151/15c). It does not implement H, guest files, Sstc or advertise
unimplemented ISA bits. `FiveStageCachedCore` uses the existing shared
`Imsic(ImsicParams(identities=127, guestFiles=0))`: M page 0x24000000, S page
0x28000000. Its optional `msi` RegisterPort belongs to the CPU clock domain;
platform crossings must use a complete request/response CDC adapter.

MachineState owns the 12-bit M/S selectors and the architectural privilege
check. The external indirect access is not performed in EX. The existing
serial instruction admission drains older backend owners. Only the resulting
non-faulting WB owner can offer an IMSIC request. One sent bit prevents repeat
requests under backpressure; one completed bit records the registered result
before a single retirement. While held, WB neither writes architectural
registers nor increments instret. IRQ commit waits for this owner to finish.
No new instruction queue, LSU owner, or global ordinary-instruction stall is
introduced.

The request carries the raw CSR source, not an EX read-modify-write result.
CSRRS/CSRRC with rs1=x0 (or immediate zero) carry operation=read; a non-x0
register containing zero retains write intent. Thus a read cannot accidentally
claim topei. Existing IMSIC logic resolves bitmap updates and concurrent MSI:
claim/update first, incoming MSI second. Invalid indirect selectors return an
error without a side effect; WB turns it into a precise illegal-instruction
exception with the original instruction in tval and no destination write.
The shared IMSIC's registered response is required; speculative or cancellable
requests are forbidden on `I1AiaCsrPort`.

The irrevocable architectural authorization point is the WB request handshake.
Visible retirement follows its response. No older operation or interrupt may
cancel an accepted access, and a responder must never return an error after
applying a side effect. This is an explicit safety invariant of this boundary.

## External FENCE.I completion

`externalFenceICompletion` is a separate default-off option. It exports
`fenceIFlush`, `fenceIFlushReady` and `fenceIFetchDrained` on Core and
CachedCore. A non-faulting serial WB FENCE.I holds `fenceIFlush` high until
both `fenceIFlushReady` and `fenceIFetchDrained` are high.
During preparation Core stops creating new fetch offers, preserves any existing
held offer until acceptance, marks old/new pending fetches killed, and consumes
their replies even if IF/ID were full. `fenceIFetchDrained` means neither an
offer nor an accepted response owner remains. The completion redirect resumes
fetch from the architectural successor. The platform must wait for fetch drain
before starting D-cache maintenance, or an I-side PTW could deadlock behind it.

The platform must then publish dirty instruction data, drain all relevant
private/downstream owners, and finish its cross-domain maintenance epoch.
Only then may it assert ready. Core does not fabricate that completion.

WB recovery metadata is retained during the wait, but no retirement, I-cache
invalidation or recovery redirect occurs until completion. The existing
single-cycle invalidation and redirect then accompany one retirement. A
faulting FENCE.I cannot request maintenance even if ready is high. Existing
memory channels are untouched, so the platform must continue draining prior
accepted/MMIO responses while admitting maintenance work. Reset follows the
existing synchronous owner-reset contract across both endpoints.

End-to-end `store -> FENCE.I -> fetch` visibility, D-cache dirty flush, Home
drain, maintenance CDC and epoch ownership are integration responsibilities
of the common CPU platform. A core handshake test alone cannot prove those.

The legacy standalone SoC wrappers do not consume the new optional MSI and
maintenance ports. Keep their defaults off; the common platform must explicitly
wire the enabled ports. Bare/cached emitters accept `--aia --supervisor` and
`--external-fence-i-completion` for focused integration.

## Validation

`inorder.I1AiaCommitMain` connects the real Core and shared IMSIC. Its transport
gates add independent request and response stalls. The C++ oracle uses explicit
instruction/retirement/request ledgers and per-identity pending/enable bits;
it does not inspect generated internal registers or reuse DUT control encodings.

Run with a pre-existing qualified GSIM/C++ toolchain:

```sh
python3 simulator/gsim/inorder/aia_commit_acceptance.py \
  --output build/gsim/i1-aia-commit \
  --mill 'mill -i -j2' --gsim /path/to/gsim --cxx /path/to/clang++ \
  --profiles compact5 fpga8
```

2026-10-19 evidence: `evidence/i1-aia-commit-r2/receipt.json`, status
`PASS_FINITE_I1_AIA_COMMIT`. The receipt freezes source/tool/artifact hashes,
records every command, and monitors the 4 GiB disk floor and finite timeout.
The installed GSIM is the previously qualified restored patched build, not a
claim of pristine upstream GSIM. ASan/UBSan were enabled.

- Configuration checks: 19/19 passed.
- Each of compact5 and fpga8: 25 cases, 360 retirement events, 110 CSR requests
  and 110 responses, three same-edge MSI collisions, 365 request-stall cycles
  and 587 response-stall cycles.
- Each profile: four completed FENCE.I instructions and one reset cancellation;
  held fetch offers, delayed poisoned fetch replies, completion backpressure,
  ready initially high, and faulting FENCE.I with ready high were checked.
- Both profiles checked M/S files, S/U privilege denial, all read/write/set/clear
  register and immediate forms, x0 write suppression, non-x0 zero-valued claim,
  selector truncation, illegal selectors, exact fault cause/tval, no faulty rd
  write, default-off CSR illegality, and older load fault/branch cancellation.
- fpga8 ordinary-load trace retained 31 acceptances overlapping older load
  retirement, demonstrating that the new serial owner did not globally serialize
  ordinary LSU traffic in this fixture.
- Both deliberately corrupted retirement-value oracle runs failed as expected.
- The first run's fpga8 FENCE.I case exposed an outdated internal reply-capacity
  assertion: it omitted the newly authorized maintenance-time killed-reply
  drain. The exact reference equation was extended with that condition, without
  disabling the assertion; both profiles were regenerated and rerun in r2.

The production CachedCore also passed a SystemVerilog elaboration combining
AIA, external FENCE.I completion, 16-row banked TLBs, Sv39/PMP, C/A, coherent
two-way caches and all existing bounded bandwidth/retirement optimizations
(`evidence/i1-aia-cached-tlb16-elab-r1.json`). This checks connections and
elaboration, not behavior of a full platform.

This finite core/IMSIC test does not establish platform CDC/Home maintenance,
end-to-end self-modifying-code visibility, physical frequency or board boot.
