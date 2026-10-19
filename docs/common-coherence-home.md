# Bounded common coherence Home

`CoherentLineHomeModule.build` now has an opt-in two-client mixed Home path. The existing
single-client default and its exact scheduling/lookup/future-way optimization guards remain
selected as before. This change supplies a shared boundary; connecting a complete I1/A1
platform and proving a CPU swap are separate integration gates.

## Geometry, ownership, and service targets

- The two-client proof uses the full 1024-line, four-way, 256-set directory. It can represent
  two 32 KiB private caches with two ways per client. The directory's way is independent of
  each cache's physical way.
- Two Acquire entries and two writeback entries are independent. Each Acquire retains its
  client, local source, address, reserved directory slot, line data, error, and phase until E.
  A full directory set backpressures admission; no silent victim replacement is introduced.
- An admitted A is at most one per cycle. Up to two disjoint-set Acquires can remain live;
  the generic path conservatively serializes new Acquires to the same set through E.
  This is not a single-outstanding fallback. Writebacks can coexist with both Acquires.
- Source uniqueness is `(client, source)`. The two clients may both use Acquire source zero
  or voluntary Release source zero. A sink is the globally unique Acquire-table index;
  E must match both that sink and the recorded client.
- One global C burst is locked to its client from first accepted data beat through last.
  Standard D Grants lock their entry, destination, and beat through backpressure. In the
  two-client whole-line mode, Grant and standard D ReleaseAck have independent locks and
  may transfer on the same cycle. The one-client exact transport cut is retained.
- There is one global probe/maintenance context. A competing Acquire reserves the old slot,
  probes its recorded owner, and waits for any dirty writeback's backing response before
  enqueueing a refill in the existing Acquire queue. A racing voluntary Release can finish;
  a not-yet-issued probe can be canceled, while an issued probe still receives its response.
  Already-live unrelated fills, Grants, and writebacks retain their own owners.
- The new owner is installed only on matching E. Drain closes new admission and waits for
  outstanding Acquire/E, writeback/ReleaseAck, C bursts, probe/maintenance, direct-held
  requests, scalar read credits, and DMA line ownership. Cache-local flush must precede
  Home drain, as before.
- Native upstream owner lookup keeps the existing `!upstreamRequestCpu` policy. A platform
  with CPU-origin uncached/atomic requests that need probes must classify those requests
  appropriately at this boundary; this patch does not change the DataPort ABI.

The two-client path uses its Acquire tag lookup functionally, in addition to release and
maintenance lookups. No inherited two-tag-read-port, timing, BRAM, or FPGA resource claim is
made for this opt-in geometry. Latency and sustained bandwidth require later matched full
platform measurements; the following cycle counts describe only short protocol fixtures.

## Focused validation

The installed-tool runners do not install/rebuild GSIM or invoke another simulator. They
check the GSIM qualification receipt, use ASan/UBSan, stop below 4 GiB free disk, and save
source hashes, commands, logs, and results under `build/gsim`.

```sh
python simulator/gsim/common_home_clients.py --tag RUN \
  --gsim-source "$GSIM_SOURCE" --qualification "$GSIM_QUALIFICATION" \
  --mill "$MILL_JAR_OR_SCRIPT" --cxx "$GSIM_CXX"
python simulator/gsim/common_home_compatibility.py --tag RUN \
  --gsim-source "$GSIM_SOURCE" --qualification "$GSIM_QUALIFICATION" \
  --mill "$MILL_JAR_OR_SCRIPT" --cxx "$GSIM_CXX"
```

The first runner drives independent protocol clients and a backing byte oracle. Backing
writes become visible only at the accepted write response, and any same-line read before
that completion is rejected. It checks:

1. Two distinct sources on one client, held Grant, and reverse E.
2. Source zero live concurrently on both clients, distinct global sinks, and drain before E.
3. Dirty client 1 to client 0 same-line handoff with real backing completion before refill.
4. Held B racing a source-zero voluntary Release.
5. Two live writebacks plus two live Acquires with backing responses withheld.
6. All four ways in one set, fifth-line backpressure, and fourth-way dirty release/reuse.
7. Native upstream dirty-owner lookup.
8. Independent whole Grant/ReleaseAck progress and simultaneous transfers.
9. Negative controls that corrupt expected Grant bytes or return E from the wrong client.

The compatibility runner reuses the established 512-line one-client M2/W2 oracle and the
existing exact optimized `HomeSharedLookupGsim` frozen shadow. It runs only the latter's
short protocol mode, not its CPU or board paths.

Local result receipts and final measurements are recorded in the integration evidence.
No CPU execution, real board, asynchronous platform clocks, physical DDR, synthesis,
place-and-route, or full-system performance result is implied by these boundary tests.

## Cold-start arbitration regression

The first native I1/A1 platform boot attempts exposed a coverage gap in the original
GSIM-only proof. Chisel's previous `RRArbiter` instantiated an unreset `lastGrant` register.
With client 1 alone valid after cold reset, four-state RTL made the chosen output and its
`fire` known while client 1 input `ready` remained X. The Home consumed E without the CDC
FIFO consuming that item; the following cycle repeated E against the already-free sink.
The original full-guest trace and the original Home ownership assertion are retained.

Only the opt-in multi-client Home A/E arbiters now use `ResettableHomeClientArbiter`:
reset-defined round-robin turn, one shared selection for valid/payload/input ready, and a
source lock through backpressure. Both independent channels remain combinational II=1;
no new transaction-credit limit or payload pipeline is added. The one-client path does
not instantiate this helper. Held-source validity and input/output acceptance accounting
are asserted in addition to, rather than instead of, the existing Home assertions.

`CommonHomeArbiterGsim` instantiates the actual production helper, or the original
`RRArbiter` in legacy mode. Its native four-state driver uses installed tools with no
random initialization or forced registers:

```sh
python simulator/gsim/common_home_arbiter_native.py \
  --classpath "$COMPILED_TEST_CLASSPATH_FILE" --output "$NEW_RECEIPT_DIRECTORY" \
  --java "$JAVA" --firtool "$FIRTOOL" --iverilog "$IVERILOG" --vvp "$VVP"
```

Both client-1-first A and E cases must pass on the production helper and fail on legacy
RTL with the selected-input-ready mismatch. Each positive case additionally checks 65
cycles of held offers with a late competing source, 96 continuous simultaneous A/E
transfers with 48 grants per client, and common reset while both channels are held.
This is a four-state arbitration boundary test, not a CDC synchronizer or full-CPU proof.

The full 1024-line Home GSIM driver separately replays client-1-first Grant/E with an
80-cycle delayed E, three simultaneous A/E acceptance edges, cross-client source zero,
reverse E, and exact released-sink reuse. When both sinks are live, a held A is not
admitted on the first E release edge; that sink becomes available the following cycle,
including when the other sink's E is accepted on the same cycle. Original M2/W2,
four-way, dirty handoff, held-Grant, Release/probe, data-corruption, and wrong-client-E
checks still run for both Grant transports.
