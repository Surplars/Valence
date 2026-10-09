# Executed CPU + coherent copy-DMA fixture preparation

Portable fixture under `simulator/gsim/fixtures/cpu_dma_execute`. It adds no
production source, Scala file, or top-level harness header and does not expand
the selected model's source inventory. Its own files are separately fingerprinted.

## Scope and exact distinction

`MachinePlatform.dma` always instantiates `MemoryCopyDma`. `ethernetDma` enables
`EthernetPacketDma`, which uses a separate scalar path. The selected production
line engine's depth four / yield zero is **copy DMA**, not packet DMA. Therefore
this fixture uses the already-merged `BoardSocGsim`, actual ROM-executed RV64I,
and the existing production coherent CPU/copy-DMA path. It does not qualify
Ethernet packet DMA, MAC, CDC, Linux, NEMU, physical FPGA timing or a board.

Production `BoardSocTop` rejects the simulated Ethernet configuration. Do not
relax that requirement just to enlarge this bounded executing-core check. Packet
STOP/restart and line-copy coexistence remain covered by the existing separate
`dma_packet_stop.cpp` fixture. Copy DMA has no hot STOP/abort ABI: accepted and
irrevocable owners must drain before reuse. This guest tests error/drain/restart,
not an invented STOP command.

## Inputs and intended profile

- CPU source: `2835556` (`Valence-cpu-bandwidth-next`).
- DMA source: `d39d80fe6aeff2306dfa826c1c6adfc4c4a75210`.
- Prepared against merged source checkpoint `19bb50e`; the runner validates the
  current exact source inventory rather than trusting a checkout name or commit alone.
- Reuse each newly generated source-matched selected model, physical ingress
  OFF and ON. Shared options: `--selected --dma-line-transfers
  --dma-line-entries=4 --dma-line-yield-cycles=0`.
- Preserve 32 KiB I/D caches, 2 ways, 2 read MSHRs, 2 response entries,
  2 writebacks, 4 AXI reads, 2 AXI writes, full scalar CPU ownership probes.
- The new driver has no runtime DataPort request injection. Every CPU RAM and
  MMIO request is an executed instruction. Existing full-generation backend and
  physical-flow ledgers check queue counts, payloads, permission metadata,
  request ownership and response lineage.

## Guest and oracle

The ROM guest initializes a 4 KiB source at `0x80210000` and a disjoint 4 KiB
old-dirty destination at `0x80211000`. Host backing starts stale. Ordinary FENCE
orders stores before DMA start, without flushing the private cache. It programs
copy DMA through `0x10001000`: source +0, destination +8, length +16, control +24,
status +32. START is bit0, clear-done/error bit1, IRQ enable bit2. Status is
busy/done/error in bits 0/1/2.

While the copy is active, the CPU runs 128 rounds of eight scratch LD/SD pairs,
checks each loaded value, and writes its independently predictable increment.
The host requires **both scratch reads and writes while DMA busy in each of the
two 4 KiB generations**, plus actual commits. It checks every source/destination
initialization store and every intermediate scratch store, including overwritten
values. It independently shadows RAM physical requests and compares load replies
without using a DUT read as the expected value. The guest reloads source and
DMA-updated destination through the actual CPU cache and checks every word.

The second generation reuses the descriptor and buffers with a new pattern.
The third descriptor reads a cold 512-byte source whose first real AXI R burst
is denied by the existing host DDR model. It must report failure only after
owners drain. The host then removes the read denial, and the guest restarts the
same descriptor and checks the complete result. Partial writes before error are
allowed; outstanding work after idle is not.

A final FENCE.I occurs only after all dirty-source/destination cases. It exposes
scratch and source backing for the final independent RAM oracle and requires
all external AXI and CPU owners to drain.

The host schema-checks named generated registers for DMA busy/done/failed,
descriptor, four resident phases and held offer. It requires multiple resident
DMA slots. For dirty probes it reads named registered `probeState`, `probeBeat`,
`probeAddress`, `probeDirty`, and `probeWords`. The source `pSend=2` state can only
advance its beat or return to idle after C handshake. The driver therefore
checks each observed accepted dirty C payload against its independent RAM shadow
using consecutive state snapshots. Occupancy cycles and checked accepted beats
are reported separately. No guessed generated temporary names or new ports.

## Build and run from the repository root

Build with the existing repository toolchain helper (never installs tools):

    python3 simulator/gsim/fixtures/cpu_dma_execute/build_guest.py \
      --out build/gsim/cpu-dma-guests-r1

The builder uses `build_cpu_hot_bandwidth.toolchain()` and records/verifies the
exact GCC, assembler, linker, preprocessor, objcopy and nm executable hashes and
versions. It guards source, helper, lock, tools, copied input and already-produced
artifact/log hashes before each command and at completion. Guest outputs are
portable: source copies, manifest, ELF/bin, and plain-text symbol map.

Once a source-matched model has completed its required board smoke receipt:

    GSIM_CXX=clang++-19 python3 simulator/gsim/fixtures/cpu_dma_execute/run_fixture.py \
      --model-receipt build/gsim/fpga-next-board-cpu-flow-on-integration-r1/receipt.json \
      --guest build/gsim/cpu-dma-guests-r1 \
      --out build/gsim/cpu-dma-executed-on-r1 --physical-flow 1

Use the matching OFF receipt and `--physical-flow 0` for the other model. Both
scripts accept `--repo` for an explicit repository root when needed. They require
fresh output directories rather than trusting an ambiguous resume.

The replay runner itself invokes
`cpu_bandwidth_flow_board.validate_model(..., dma_line_transfers=True,
dma_line_entries=4, dma_line_yield_cycles=0)`. The exact current model source
inventory, completed smoke status, full shared/physical-flow profile, pinned GSIM
lock, current compiler version, and complete hashed model artifact/object set
must match. It revalidates these plus fixture/validator sources, compiler
executables, guest manifest/source/artifact/log hashes and already-produced run
artifacts/logs before and after every step and again before the terminal result.
There is no parent-validation exception.

It compiles only the new standalone driver and links existing model objects,
then runs one bounded positive (300,000-cycle ceiling) and three checker negatives:

1. Alter one expected destination word: reject the generation byte oracle.
2. Alter the observed ingress route: reject independent route prediction.
3. Alter a full return tag: reject full-token response lineage.

Those are observer-only checker mutations. The denied R response in the positive
is real protocol error injection. No heavy model jobs are started by this runner.

Header schema-only mode permits an in-progress receipt and is explicitly
**nonqualifying**; it checks neither source/profile/toolchain nor runtime results:

    python3 simulator/gsim/fixtures/cpu_dma_execute/run_fixture.py \
      --model-receipt build/gsim/fpga-next-board-cpu-flow-on-integration-r1/receipt.json \
      --physical-flow 1 --schema-only

## Preparation verification and remaining qualification

- Python builder/runner syntax passed.
- C++ glue syntax passed against an accessor stub; this is not compilation of
  the real generated GSIM model.
- Both fresh merged OFF/ON generated-header field/array/accessor schemas passed.
- Patch apply-check passed without modifying the repository.
- Guest assembly, real host compilation, positive runtime and negative executions
  remain to be run; this preparation alone is not a functional pass.
- No installs, pushes, synthesis, Vivado, board or MAC/CDC work.

## Integrated admission strengthening

RAM loads are restricted to the fixed source, destination, scratch and cold
destination regions, plus exact aligned one-past scratch/cold-destination guards.
Every load still uses the independent value and full-token ownership checks;
all speculative traffic remains in raw counters and elapsed cycles. A fourth
observer-only negative moves a RAM load to an unrelated region and requires
`unexpected guest RAM read region`.
