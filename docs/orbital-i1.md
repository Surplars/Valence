# OpenIon Orbital-I1: FPGA-first parameterized in-order core

**Batch44 routed STA pass and bit generated, 2026-10-18:** re-time parcel alignment across the existing
raw-word register, prepare only unowned fabric payload slots, and compute trap
vector upper carry candidates before late cause/delegation. No new pipeline edge,
owner, RAM or queue slot. All37 affected checks and13 performance gates pass;
six real-CPU streams, CoreMark ROI646056 /345517 instructions, trace and CRC are
identical. Audit rehashes395 sources/136 artifacts;6999 register declarations,
89 memories and four directory writers are unchanged.52 tool tests pass.
New independent queue stress and768 vector carry/wrap checks supplement the parcel
oracles. Fresh real-CPU BootROM/UART and exact synthesized/routed4096-byte ROM pass.
One full-board implementation and one bounded postroute attempt achieve **CPU300
WNS0.000ns, TNS0, WHS+0.007ns, pulse+0.081ns**: setup is at the limit, not generous
margin. DDR UI250 setup/hold+0.454/+0.010ns; AON/UART50+2.478/+0.024ns.
All136473 routable nets route without errors and all20 bus-skew checks pass
(minimum+2.512ns). Same nine reset CDC Critical endpoints, structural audit only;
no full CDC signoff is claimed. Final resources92908 LUT/
55016 FF/63.5 BRAM36 equivalents/31 DSP. No original OoO, shared IP, clocks or slots changed.

Retimed endpoint STA separately checks actual storage rather than the removed shadow
instruction register: BRAM-to-word+0.107ns, word-to-IF instruction+1.678ns,
word-to-firstHalf+1.828ns. Home phase+0.198ns, PC+0.006ns, JTAG+0.045ns.
Bit: `E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261018-batch44-r1/bitstream/
orbital_i1_rv64gc_cpu300_i32k_d32k_uart460800_jtag65_nomac_bootrom.bit`.
SHA256 `bb974f17ec03bd5d51eb5df56bc858beb7a5e9051cffedcce4b4c95fe2c0aea7`.
Evidence there: `batch44-result.json`, `bitstream/delivery.json`, `postroute-r1/`,
`retimed-path-audit/`, and `source-batch44-frozen.tar.gz`. UART460800/8N1/no flow control;
reset should print `Valence Orbital-I1 BootROM V0.1`, then wait for JTAG. MAC absent;
F/D, Sv39, TL-C and fixed USER2 65-bit transport remain enabled.

**Subsequent user-reported board smoke:** CAP0x564c0101 / STATUS0x00000021;
the109-byte JTAG binary readback CRC0xe2925e20 passed, COMMIT was accepted and
UART program output appeared. This qualifies that reported download/launch smoke,
not Linux, long-term board stability or full CDC signoff. Immutable delivery JSON
retains its original pre-board-test status. The external host helper
`valence_wait_claimed` failed on a missing `committed_generation` variable and
is not claimed fixed; it does not perform the launch. Current image/link/entry
requirements and the64MiB JTAG aperture are documented in
`fpga/inorder/README.md`. Generated RTL, bit, DCP and build caches remain outside Git.

**Batch43 final outcome, 2026-10-18:** the PC payload
no longer includes late request FIRE in every candidate mask; bank-local XOR
corrections avoid global default-PC qualification. Home uses native ownership
selection and local per-phase equations checked against the previous transition
priority every cycle. Read-only cache payload and parcel selection are prepared
independently of response authorization, without changing any handshake or edge.
All33 affected checks,13 performance gates and49 tool tests pass. Six real-CPU
Bare/Sv39 streams, O3 CoreMark ROI646056 /345517 instructions (IPC0.5348), trace
and CRC are unchanged. Source/storage audit:392 sources,115 artifacts,6999
register declarations,89 memories, four single-write directory banks, zero new
control or payload state. Fresh real-CPU BootROM/UART and its negative controls
pass. CPU300/UI250/AON50/UART50, I/D32KiB and original OoO/shared IP remain unchanged.
One fresh full-board route and one bounded postroute attempt finish at
**WNS-0.059ns, TNS-5.477ns, WHS+0.009ns**, resources92756 LUT/55090 FF/
63.5 BRAM36 equivalents/31 DSP. This improves on batch42 but still fails CPU300;
no bit. DDR250 and AON/UART50 pass, all20 bus-skew checks pass, the same nine
reset CDC Critical endpoints remain (no full CDC signoff). Synthesized and routed
ROM4096 bytes match exactly. Final evidence: `E:/VM/Share/Valence-rtl/
orbital-i1-cpu300-board-20261018-batch43-r1/batch43-result.json` and `postroute-r1/`.
Sources were archived there as `source-batch43-pre44.tar.gz` before batch44 edits.

**Previous batch42 outcome, 2026-10-18:** Home one-hot/control ownership reads,
prediction/redirect candidate selection, cache probe-resume decoding and JTAG
error preparation were changed together. CPU300/UI250/AON50/UART50, I/D32KiB,
existing transaction slots and original OoO/shared IP sources remain unchanged.
All 27 affected short checks and 13 performance gates pass. The six real-CPU
Bare/Sv39 streams, retired trace, CRC and O3 CoreMark ROI remain cycle-identical;
ROI IPC is345517/646056=0.5348, not a formal CoreMark score.
Fresh BootROM/UART and exact synthesized/routed4096-byte ROM checks pass.
However the fresh full-board route regresses to **WNS -0.379ns, TNS -163.774ns /
1695 endpoints, WHS +0.009ns, pulse +0.081ns**. Resources:95004 LUT/55299 FF/
63.5 BRAM36 equivalents/31 DSP. **No new bit; this is not a qualified300MHz board.**
JTAG sbError improves to+0.025ns, but PC request, Home state and fetch alignment
remain-0.376/-0.277/-0.253ns respectively. The overall worst endpoint is desiredPc
at-0.379ns. The short-model equivalence did not imply better physical timing.
DDR250 and AON/UART50 pass; all140200 nets route without errors and all20
bus-skew checks pass. The same nine reset CDC Critical endpoints remain;
structural checks are retained, without claiming full CDC signoff or board testing.
Evidence: `E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261018-batch42-r1/`,
especially `batch42-result.json`, `reports/paths_max.rpt` and the six targeted
reports listed in `reports/target_timing.tsv`. No unbounded physical retry was run.
See `fpga/inorder/README.md` for the complete comparison and exact proof inputs.

**Previous batch41 outcome, 2026-10-18:** the new Home probe preparation and
free-tail metadata FIFO preserve CPU300/UI250/AON50/UART50, I/D32KiB and existing
slots. All 63 affected short checks and 13 performance gates pass; six real-CPU
Bare/Sv39 cases and O3 CoreMark match the previous results exactly (ROI646056 cycles,
not a formal score). The fresh CPU BootROM/UART proof and both physical RAMB content
gates pass. One full-board implementation and one bounded post-route attempt finish
at **WNS -0.103ns, TNS -4.219ns /137 endpoints, WHS +0.010ns, pulse +0.081ns**.
Resources:94088 LUT/55125 FF/63.5 BRAM36 equivalents/31 DSP. No new bit is generated.
Targeted final-DCP STA confirms Home probeAddress +0.995ns, metadata RAM WE +1.986ns,
and PMP upper bounds +0.177ns; the remaining worst paths are Home admission/state,
I-cache return/alignment and the predicted-PC loop. JTAG sbError remains -0.041ns.
DDR250 and AON/UART50 pass; all137145 routable nets are routed without errors.
The nine existing reset CDC Critical endpoints remain unchanged; no new exceptions
and no full CDC or board qualification are claimed. Original OoO sources are untouched.
Evidence: `E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261018-batch41-r1/`,
especially `batch41-result.json`, `postroute-r1/` and `target-audit/`.
See `fpga/inorder/README.md` for the complete comparison and frozen proof inputs.

**2026-10-17 BootROM delivery correction:** the dev2-r4 bit's no-output failure
was traced to the board synthesis flow omitting `ENABLE_INITIAL_MEM_`. Its final
DCP has no ROM BRAM and disconnected ROM data outputs. The routed figures below
are historical evidence for that defective netlist, NOT qualification of a board
with working BootROM. Preserve the old bit/DCP for diagnosis. The repair keeps
CPU300/UI250/AON50/UART50, I/D32KiB and all CPU RTL unchanged. New gates require
real-CPU GSIM boot/UART decode plus exact post-synthesis/post-route RAMB INIT and
address/data mapping comparison. A new bit requires fresh physical qualification;
see `fpga/inorder/README.md` for the corrected entry and bounded evidence.

**Repair result, 2026-10-17:** real-CPU GSIM BootROM/UART and exact 4096-byte
post-synthesis/post-route RAMB checks PASS. Fresh full-board implementation plus
one bounded post-route optimization finished at CPU300 WNS **-0.116 ns**, TNS
-12.386 ns / 251 failing setup endpoints, hold +0.010 ns, pulse width +0.081 ns.
DDR UI250 and AON/UART50 setup/hold pass. Resources: 94750 LUT, 55618 FF,
63.5 BRAM36 equivalents, 31 DSP. The nine baseline reset CDC Critical endpoints
remain unchanged; this is not complete CDC signoff. **No new bit generated.**
The 136 exported RTL files, clocks, I/D32KiB and original OoO core are unchanged.
Evidence: `E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261017-bootrom-r1/`,
especially `repair-result.json` and `postroute-r1/`; the historical results below
do not supersede this repair outcome.

Working branch: `dev2` (organized baseline `e0415d2`; original feature branch retained).
Worktree: `/home/openion/Valence-inorder`.
Base: `1e90af966c15d871d2544469174acba78473113b`. The existing OoO core,
`/home/openion/Valence`, and dot's separate worktrees are not switched or overwritten.
This is new current hardware under `src/main/scala/core/inorder`, not resurrection of
`legacy/hardware` and not an OoO backend with renamed stages.

Historical defective-ROM physical status (batch40,2026-10-17): the no-MAC board with
MIG/AXI CDC, CPU300/UI250/AON50/UART50 andI/D32KiB has completed routed STA
withWNS0.000ns(MET),TNS0,WHS+0.010ns underan80ps CPU hold guard. Setup is
borderline, not comfortable margin. Existing nine reset CDC Criticals and
documented I/O boundary exceptions remain; this is not full CDC/board signoff.
No bit generated. Historical foundation status below is chronological; see
the final batch40 section andits immutable short/physical evidence.

## Contract and honest status

The initial user contract required a five-stage in-order core, parameterization, FPGA RAM-based storage,
and NaxRiscv-aligned performance/frequency/resource goals. NaxRiscv is an OoO reference,
not the architecture to copy. Its published RV64 configuration reports 4.94 CoreMark/MHz,
17.9 KLUT, 12.5 KFF, 12 BRAM and 16 DSP at 137 MHz on Artix-7 speed grade 3. Its benchmark
uses special compiler/source options, and its caches/issue width differ. These are reference
numbers, **not promised Orbital-I1 results**, and cannot be compared directly to an entire ZU15EG SoC.
Source: [official NaxRiscv performance](https://spinalhdl.github.io/NaxRiscv-Rtd/main/NaxRiscv/performance/index.html).

The default profile remains RV32/RV64 I, optional M, Zicsr, Zifencei and M-only state.
The 2026-10-14 batches add optional S/U, delegation, PMP, Sv39/Svade, PLIC S context and
integer C/A, with independent and actual-CPU short acceptance in the final sections below.
Optional parameterized I/D cache and branch-prediction prototypes exist.
A separate RV64 bare-metal `FiveStageSoc` now connects the core through TileLink to the
existing DDR AXI bridge, UART, machine timer, PLIC and M-mode interrupts. It now boots a small
M-only BootROM, with optional boot-owned FPGA shared-JTAG download or explicit preloaded DDR;
it is not a replacement for the released VL100 board top or its RV64GC/Linux firmware.
Optional RV64 F/D now has independent numerical and actual-CPU short acceptance, including
the parameterized five/seven/eight-stage profiles; see the final F/D batch section.
AIA, architectural hart debug and production board integration
are **not implemented or advertised by this core**. The later batch12+ sections add
experimental real TL-C private I/D and DMA coherence; this is not the original
uncached foundation's qualification. Optional RV64IMAC now boots untouched
stock OpenSBI v1.9 and a small S-mode diagnostic, not Linux. Existing RV64GC Linux firmware cannot
be assumed to run. No formal benchmark score, maximum frequency, routed full-SoC or board qualification
is claimed. The preceding **uncached, unpredicted foundation snapshot** passed standalone internal
routed timing at 200 MHz under the external-BUFGCE context recorded below. That result does not
qualify the current cache/predictor configuration or establish its maximum frequency.

Latest user direction (2026-10-14): five stages are no longer a hard limit; provide selectable,
FPGA-first pipeline profiles and evaluate 7/8 stages toward 300MHz or higher, while optimizing
frequency x IPC and resource use. The latest batch implements actual selectable compact5/balanced7/fpga8
profiles; their short qualification and same-binary performance costs are recorded at the end.
The original 200MHz target has NOT been met by this protected IMAC SoC. The accidental 100MHz
synthesis constraint is only a reference, not an acceptance-target reduction; see final timing results.

This branch stays independent until its actual core and adapters pass their own tests.
No change is made to the VL100 default CPU, existing cache/MSHR parameters or release scripts.

### What the NaxRiscv reference actually measures

Checked against the official performance page and upstream benchmark port on 2026-10-13.
The documentation first specifies an RV32IMASU Linux-capable OoO configuration, then states
that its RV64 result uses a similar configuration. The detailed common reference comprises:

| Component | Documented configuration |
| --- | --- |
| Frontend / retirement | 64-bit fetch; 2 decode, 3 issue, 2 retire |
| Scheduling / RF | Shared 32-entry issue queue, 64 physical registers |
| Execution | Two integer/shift/branch units, one shared load/store/mul/div/CSR/environment unit |
| LSU | 16 load and 16 store queue entries, store-to-load bypass, 3-cycle load-hit prediction |
| Caches | 16 KiB I + 16 KiB D, four ways; D-cache has 2 refill and 2 writeback slots |
| Translation | ITLB and DTLB each 6-way / 192 entries in the detailed RV32 profile |
| Prediction | Direct-mapped 512-entry BTB, 4 KiB GSHARE, 32-entry RAS |

These detailed counts are explicitly published for RV32; the RV64 page's "similar"
description is not a separately frozen RV64 elaboration manifest. RV64 reports 4.94
CoreMark/MHz and 17.9 KLUT / 12.5 KFF / 12 BRAM / 16 DSP at 137 MHz on Artix-7 speed grade 3.
This is a cache/MMU/predictor-equipped processor comparison, **not a complete VL100-like
SoC resource bill including MIG, Ethernet, DMA and board clocking**. The page does not
bind that historical result to an exact RTL commit, FPGA part or routed timing report,
and does not establish that F/D or debug were included in that measured build.
See [official performance/configuration](https://spinalhdl.github.io/NaxRiscv-Rtd/main/NaxRiscv/performance/index.html).

The published benchmark procedure loads bare-metal ELF into its RTL simulator and measures
the workload region, not a Debian/Linux process on a production board. Compiler conditions
differ: `-O3`, loop unrolling/inlining/alignment options, and the port changes `ee_u32` to a
signed integer. The current upstream port confirms those choices, but is not a proof of
every option used in the historical 4.94 result. Our unchanged pinned CoreMark uses `-O2` and `-O3`
and standard unsigned types; a direct division of the two scores would be misleading.
See [benchmark procedure](https://spinalhdl.github.io/NaxRiscv-Rtd/main/NaxRiscv/performance/index.html#how-to-run-the-benchmark),
[compiler port](https://github.com/SpinalHDL/NaxSoftware/blob/main/baremetal/coremark/naxriscv_sim/core_portme.mak)
and [type definitions](https://github.com/SpinalHDL/NaxSoftware/blob/main/baremetal/coremark/naxriscv_sim/core_portme.h).
No NaxRiscv simulator is installed or invoked by this project; GSIM remains the hardware test flow.

### SoC integration gates, not an unqualified calendar estimate

SoC integration does **not** have to wait for complete RV64GC or Linux. The default RV64IM
and optional M/S/U profile have completed preloaded-DDR bare-metal SoC adapter batches after the throughput
gate, while remaining an independently selectable CPU. A complete Linux-capable replacement
is a later milestone, not the present core's status.

| Milestone | Required work / acceptance |
| --- | --- |
| First bare-metal SoC | Ordered TileLink, DDR/UART/timer, PLIC, BootROM/startup reset and logical JTAG short tests pass. FPGA shell is elaborated; physical clock/MIG/CDC/USER-chain qualification remains. Preserve the OoO default. |
| FPGA-qualified cached SoC | Cache-aware RAM leaf/resource audit; one coherent physical run after short acceptance, including bus, clock/reset and I/O/CDC boundaries. Then board diagnostics and formal >=10-second CoreMark with recorded compiler/frequency. |
| Linux-capable SoC | S/U, Sv39/Svade, PMP, C/A and stock OpenSBI -> S-mode have short acceptance. Optional RV64 F/D instruction/state tests now pass; kernel/OS floating-context, board and architectural debug qualification remain separate. |
| DMA/network-ready platform | Cache ordering/coherence or an explicitly uncached DMA window plus a real invalidation contract. Current prototype D-cache has no external snooping; GMAC/DMA must not silently modify its cached buffers. |

The first milestone is the next integration batch, not a promise of a new full board bit or
Debian image now. RAM mapping and physical timing remain prerequisites to advertising the
new cached SoC's operating frequency. Existing SoC peripherals can be reused; existing OoO
pipeline control must not become this new core's implementation or correctness oracle.

## CPU replacement boundary: common protocol is not yet a drop-in platform

On2026-10-14, byte hashes match the original OoO worktree for9 audited
shared files: TileLink.scala, RegisterPort, AXI4 memory port, UART, machine
timer, register CDC, two-master TL arbiter and both original TL/AXI burst
bridges. I1 timing-cut AXI implementations are deliberately independent
local variants; their current qualification must not be transferred to
the original bridges without an explicit integration test.

| Boundary | Current commonality / remaining difference |
| --- | --- |
| Physical bus | Same TL A/D protocol and64-bit data, with I1 Get/PutPartialData adapters. Source-ID geometry/credits differ; I1 has no TL-C cache permission/probe implementation. |
| DDR pins/PHY | Same AXI64 -> asynchronous converter -> MIG family can remain outside the CPU tile. Address-offset, reset and actual clock parameters still require matched integration. |
| UART/timer | Actual reusable IP bytes match. Their clocks, MMIO decode and IRQ routing belong to the platform, not the CPU pipeline. |
| Interrupts | I1 uses M/S PLIC; released OoO board uses APLIC/IMSIC. Standard M/S external/timer/software interrupt wires exist, but controller/firmware contracts are not interchangeable. |
| DMA/MAC/CMU | Not present in the I1 assembly. Its noncoherent cache and exclusive-writer LR/SC contract cannot safely inherit active runtime DMA by changing only a core selector. |
| Boot/debug/software | I1 ROM/reset and boot-only USER2 loader differ from the released platform. Firmware, DTB, ISA and timebase must match the selected tile/platform. |

The intended replaceable unit is a CPU TILE: core, optional MMU/caches,
atomic ordering and CPU-native-to-TileLink adapter together. Freeze its
external TL client ports, source/capability negotiation, IRQ/time/reset,
cache-maintenance/reservation invalidation and debug contract. Then select
`OrbitalA1Tile` or `OrbitalI1Tile` while leaving the common address
map, memory fabric, interrupt controller, peripherals and FPGA pins outside.
These wrapper names describe the proposed boundary, not implemented modules.
Current `MachinePlatform` still constructs the OoO core/frontend directly,
and `FiveStageSoc` is a separate integration fixture. No single shared
production-platform `cpuKind` selector or full peripheral replacement
qualification is claimed. A coherent adapter or explicitly enforced DMA
cache-maintenance/uncached-buffer contract is a prerequisite, not optional polish.

## Default compact5: exactly five stages

```text
IF                 ID                EX                 MEM                WB
fetch/response --> decode/RF read --> bypass/execute --> data owner ------> retire/RF/CSR
                     |                 ^                 |
                     +-- sync RAM -----+                 +--> ordered ack
```

| Stage | Responsibilities and FPGA boundaries |
| --- | --- |
| IF | One accepted fetch owner and a stable offered request; original PC retained until response; killed requests drain without being decoded. |
| ID | Own independent decode; issue synchronous register reads at ID transfer. Serial CSR/fence instructions first drain older pipeline stages. |
| EX | RAM read results, bounded MEM/WB forwarding, ALU, branch/address generation, alignment checks. Multicycle M operations hold EX rather than add architectural stages. |
| MEM | Naturally aligned byte/half/word/double transactions, exact byte mask, one request owner through error/ack; no duplicate writes, no posted-store success. |
| WB | Single in-order retirement point, architectural register and CSR writes, traps, MRET and FENCE.I. No ROB, physical register map or out-of-order completion. |

An external cache's internal lookup/refill latency is a memory stall, not an unnamed sixth
architectural stage. This does not allow calling an extra register-read stage “five stages”.
ID -> EX synchronous RF latency is explicitly included now.

## RAM and execution choices

- Register file: two 32 x XLEN synchronous 1R1W banks. Each receives the same WB write;
  each services one source read. RV64 payload is 4096 physical bits including replication.
  `ram_style=block` is the default; `distributed` and `auto` are explicit implementation options.
  The current RV64 block profile has been checked as two RAMB36E2 primitives in Vivado;
  every future width/resource change must repeat the mapping check.
  Current CIRCT splits `bank_32x64` into a nested module. The official export entry point
  propagates the selected resource attribute onto that exact RAM leaf (no logic changes),
  rejects shape/instance drift, and retains pre/post hashes and raw RTL. Do not bypass it.
  See [AMD RAM_STYLE semantics](https://docs.amd.com/r/en-US/ug912-vivado-properties/RAM_STYLE).
- No reset loop over memory payload. A 32-bit initialized bitmap supplies zero for unwritten
  registers. x0 writes are ignored. Same-edge read/write collisions explicitly bypass, independent
  of RAM read-during-write mode. Read responses are held during EX stalls.
- Wide stage payload uses enable-qualified registers, not blanket reset. Valid/owner state is reset.
- Default multiplier: registered inputs/product/result intended for DSP inference. The optional
  `dsp-tiled` mode uses unsigned 32-bit partial products and carry-save recombination, then
  registered high-half sign correction; RV64 adds one held-EX cycle versus `dsp`. Its physical
  resource reduction is a candidate to measure, not an established DSP count.
  The optional
  iterative multiplier uses shift-add and no `*` datapath. Division is restoring/iterative, not
  a combinational synthesizable `/` operator. All RV64 W results are sign-extended.
- Loads forward from WB only; an arriving RAM response does not traverse a second EX carry chain.
  Optional non-load MEM bypass trades local mux area against dependency stalls.
- Only implemented parameters are accepted. Disabled M removes the unit and makes its opcodes
  illegal. Future F/D and MMU switches must not produce placeholder “legal” results.

LUTRAM still consumes LUTs, but is much cheaper than a multiported FF array with wide muxes.
BRAM is for deeper payload storage, caches and refill/eviction buffers; valid/dirty bits and small
control pointers may remain FFs. UltraRAM is not automatically suitable for small register files.
The NaxRiscv RAM approach is described in its
[official memory architecture](https://spinalhdl.github.io/NaxRiscv-Rtd/main/NaxRiscv/memory/index.html).

## Request and precise-state contract

Both ports use ready/valid and require at least one cycle between accepted request and response.
Responses are ordered and must retain their payload until accepted. The instruction port returns
one 32-bit instruction at an aligned byte PC. The data port receives a byte address and size;
load response data is the containing aligned XLEN word; store data and mask select that word's lanes.
A store, including an MMIO store, is not completed until its actual error/ack response.

Redirects do not retract an offered fetch under READY backpressure. They mark its owner stale
and drain it; a stale access fault cannot become an architectural exception. Synchronous faults
are carried to WB, cancel younger instructions and suppress their side effects. External/timer/software
interrupts inhibit ID, drain older EX/MEM/WB instructions and resume at the last retired next-PC.
M-only state does not imply Linux-compatible privilege support.

## Isolated build and short validation

```sh
cd /home/openion/Valence-inorder
mill -i OrbitalI1.test.testOnly inorder.FiveStageConfigSpec
GSIM_CXX=clang++-19 python3 -B simulator/gsim/inorder/acceptance.py --tag UNIQUE_TAG
mill -i OrbitalI1.test.runMain inorder.FiveStageRtlMain build/fpga/orbital-i1-UNIQUE_TAG 64
```

That last command is diagnostic raw RTL, not an FPGA resource-qualified delivery. Production
bare-core export uses `python3 -B fpga/inorder/export.py --receipt CURRENT_RECEIPT --output FRESH_DIR`.
Only it binds CIRCT RAM leaf attributes and current GSIM evidence. `synth_ooc.tcl` then checks actual
BRAM/DSP mapping in the three explicit RV64 configurations; it performs no placement/routing or bit generation.

`OrbitalI1` compiles the new core, shared `soc.isa`, TileLink and explicitly selected reusable
bus/peripheral sources. Three existing DDR bridge files still reside in `core/ooo`, but they are
CPU-independent IP: neither `IntegerCore` nor the existing board top is instantiated or modified.
No legacy/HardFloat/difftest dependency is introduced. `IonSoC` can also see the new sources.
The pinned GSIM binary is read from the existing toolchain without modifying/rebuilding it.
No Verilator, ChiselSim, long full-platform regression or Linux simulation is introduced.
The new integrated bare-metal SoC has its own bounded short GSIM target below.

The short gate freezes source hashes, tests RV64 DSP/iterative/interlock profiles, RV32 DSP,
RV64 M-disabled and RV64 LUTRAM profiles, and rejects an independent register-result mutation in every
profile. It uses a procedural software ISA oracle not generated from the Chisel decoder.
It checks the entire intended mixed workload reaches its EBREAK, matched low/high-latency
retirement, forwarding, x0, byte masks, branch flush, fetch/data errors, CSR ordering, counter
retirement, precise misalignment, MRET and M arithmetic corners. A separate RF oracle checks
12,000 randomized collision/hold/warm-reset cycles. An independent ALU stream must not
contain avoidable bubbles. This remains bounded acceptance, not complete ISA certification.

## Recorded acceptance: 2026-10-13

Foundation source gate (before the cache/predictor batch):
`build/gsim/five-stage-five-stage-20261013-r8/receipt.json`.
Status: `PASS_FIVE_STAGE_INTEGER_FOUNDATION_ONLY`. Six parameter profiles passed;
each independently rejected the register-oracle negative control. Scala configuration checks
(3), RAM export checks (2), report parser checks (4) and the pure route-script mock also passed.
The mock is a software entry-point check, not a hardware simulation or timing result.

The independent RF gate covered 12,000 cycles, including 1,298 same-edge collisions,
4,057 held-read cycles, 255 x0 writes and a warm reset. Both independent and dependent ALU
streams execute 800 ALU instructions plus a terminal EBREAK in 810 cycles at one-cycle memory
service. Steady-state ALU throughput is 1 instruction/cycle; this is **not** CoreMark or workload IPC.
The busy-unit interrupt test verifies pipeline draining, vectored entry, MRET and exact resumption;
M-disabled configurations inject the interrupt during a memory wait instead.

| Matched profile | Low-latency mixed cycles | Backpressured mixed cycles | Trace retirements |
| --- | ---: | ---: | ---: |
| RV64 DSP | 19,692 | 24,198 | 1,244 |
| RV64 iterative | 33,518 | 37,739 | 1,244 |
| RV64 MEM interlock | 19,725 | 24,198 | 1,244 |
| RV32 DSP | 8,567 | 13,253 | 992 |
| RV64 M disabled | 1,136 | 5,871 | 676 |
| RV64 LUTRAM | 19,692 | 24,198 | 1,244 |

Different ISA profiles execute different M/W coverage, so these rows are configuration acceptance,
not a cross-profile speed ranking. Trace counts include exceptions, unlike architectural `minstret`.

### Bare-core synthesis (not routed timing)

Vivado 2025.1, xczu15eg-ffvb1156-2-i, 5.000 ns clock, Default synthesis directive.
Frozen RTL: `build/fpga/orbital-i1-20261013-r3/manifest.json`.
Hash-bound results: `build/fpga/orbital-i1-20261013-r3/synthesis-evidence.json`.
Windows reports: `E:\VM\Share\Valence-rtl\Orbital-I1-five-stage-20261013-r2\synthesis-r1`.

| Historical bare-core profile | LUT | FF | RAMB36E2 | DSP48E2 | Estimated setup WNS |
| --- | ---: | ---: | ---: | ---: | ---: |
| RV64IM, BRAM RF, DSP multiply | 4,861 | 2,745 | 2 | 34 | +0.255 ns |
| RV64I, BRAM RF, M disabled | 3,560 | 2,291 | 2 | 0 | +0.069 ns |
| RV64IM, LUTRAM RF, DSP multiply | 4,921 | 2,755 | 0 | 34 | +0.691 ns |

The LUTRAM profile includes 80 memory LUTs. All profiles have zero synthesis-estimated setup
failing endpoints. These figures exclude caches, MMU, FPU, memory fabric, debug and peripherals;
they cannot be compared directly to the complete VL100 or NaxRiscv's cache-equipped reference.
The 34-DSP multiplier is still an area/latency optimization opportunity, not an assumed optimal mapping.

The preceding RV64IM/BRAM synthesis had 4,641 LUT, 2,735 FF and WNS -1.050 ns. This batch
changed low-bit alignment checks, separated late instruction/address fault reporting from common
EX capacity, and killed speculative younger ID/RF work at the redirect edge instead of passing
branch operands through frontend READY. The architecture still has five stages and EX branch
resolution. Setup estimate improved by 1.305 ns at a cost of 220 LUT and 10 FF; the matched
mixed program costs just one additional cycle (19,691 -> 19,692), with no ALU-stream loss.
Thus the change is not a frequency gain obtained by adding an architectural pipeline stage.

`route_ooc.tcl` performs one standalone default-profile placement/routing, with an explicit
`HD.CLK_SRC` external-BUFGCE site assumption. Its interface nets and external memory/clock/CDC
are outside qualification. Always distinguish its **internal routed timing** from whole-SoC or
board timing. See [AMD OOC context constraints](https://docs.amd.com/r/2022.1-English/ug905-vivado-hierarchical-design/Context-Constraints).
No bit is produced by either bare-core script.

### Standalone internal routed result

The default RV64IM/BRAM profile completed placement, one physical optimization and routing at
200 MHz. Clock context: an assumed external `BUFGCE_X0Y48`; no board clock or interface-net
qualification is implied. Final results, not intermediate placement/route estimates:

| Metric | Actual routed result |
| --- | ---: |
| Setup WNS / TNS | +0.265 ns / 0.000 ns |
| Hold WHS / THS | +0.011 ns / 0.000 ns |
| Pulse-width WPWS | +1.958 ns |
| LUT / FF | 4,896 / 2,744 |
| RAMB36E2 / DSP48E2 | 2 / 34 |
| Fully routed / routable internal nets | 8,435 / 8,435 |
| Nets with routing errors | 0 |

The worst setup path is `rf/bank_ext/Memory_reg/CLKARDCLK` to `desiredPc_reg[37]/D`,
4.541 ns data path, 14 logic levels. Branch/redirect logic remains a future optimization
candidate. The small positive hold margin is not a promise of unchanged timing after integration.
There has been no frequency sweep, no 300 MHz validation, and no board bit generation.

Complete useful RTL, source/GSIM hashes, synthesized/routed checkpoints, reports and logs are
archived in **WSL** at `build/fpga/orbital-i1-evidence-20261013-r2/` (12 MiB):

- `qualification.json`: hash-bound synthesis plus `standalone_routed_default_profile`;
  `internal_ooc_timing_met=true`, with SoC/board/boundary qualification explicitly false.
- `physical-r3/timing_routed.rpt`, `setup_routed.rpt`, `hold_routed.rpt`, `route_status.rpt`,
  `context.txt`, `routed.dcp` and `drc.rpt`.
- `synthesis-r1/`: all three synthesis configurations and their mapping/resource evidence.
- `rtl/manifest.json`, `gsim-receipt.json` and actual synthesis/route logs/scripts.
- `startup-failures/`: two early script guards wrongly compared project/design object names
  with the RTL top. They failed before placement and are retained. The checkpoint metadata was
  checked as `FiveStageCore`; the corrected script validates exact RAM hierarchy and clock.
  There was only one actual placement/routing, not three physical optimization experiments.

Windows counterpart: `E:\VM\Share\Valence-rtl\Orbital-I1-five-stage-20261013-r2\physical-r3`.
This branch's code, tests and docs remain uncommitted; no merge into the existing OoO branch
or remote push was performed. Generated evidence remains ignored by Git.

## Performance/resource qualification plan

1. Record independent ALU and dependency-chain IPC, branch/load penalties and accepted memory
   request duty before adding large structures. Single issue has an architectural ceiling of 1 IPC.
2. Use identical CoreMark/Dhrystone/Embench binaries and compiler options for the baseline and new
   core; keep ISA, cache geometry, memory service and measurement windows matched. Do not present
   a one-iteration functional CoreMark run as a formal benchmark score.
3. Focused bare-core OOC synthesis after the batch's short tests; prove RAM/DSP mapping and
   resource removal in optional profiles. One standalone default-profile route measures internal
   paths under explicit clock assumptions. Separately report core-only and full-SoC resources.
4. Initial design target: 200 MHz on xczu15eg-2, with 300 MHz only a stretch goal. Physical routed
   setup/hold/pulse checks, I/O/CDC and SoC integration are required before promising a frequency.
5. Design the new I/D caches from synchronous banks rather than importing the current OoO
   ownership/selection chains. Add branch prediction, C, A, precise Sv39/PMP, S/U and F/D in
   separately verifiable batches; prefer existing independent IP datapaths, not old pipeline controls.

Do not scale queues/cache/issue width merely to claim comparable performance. No hidden sixth
stage, fake RAM mapping, unqualified CoreMark score or “NaxRiscv-equivalent” claim is permitted.

## Parameterized cache and prediction batch

`FiveStageCachedCore` wraps the unchanged five architectural stages with two
`FiveStageWordCache` modules. The original ordered instruction/data ports remain available
for independent core-only checks. This is an independent prototype, not the VL100 cache/MSHR
implementation and not a coherent/DMA-ready TileLink adapter.

- `instructionCacheBytes` / `dataCacheBytes`: 0 disables each cache independently; enabled
  power-of-two capacities range from two lines to 64 KiB. The measured comparison uses 2 KiB each.
- `cacheLineBytes`: power of two from XLEN/8 to 256 bytes; comparison uses 64 bytes, direct mapped.
- Payload is synchronous byte-bank RAM with masked writes. Tags are separate synchronous RAM;
  valid bits are reset, not payload. No FF line array or 512-bit refill mux is introduced.
- Accepted read hit -> response in one cycle. The IF-specific hit-replacement mode sustains one
  read hit/cycle; data-cache admission is state-only, so downstream store scheduling cannot close
  a combinational request-READY / response-READY loop. Neither mode adds an MSHR or payload queue.
  Misses issue one actual ordered burst and receive XLEN-sized beats, with first-response latency
  distinct from burst-transfer latency. Partial/error refills never expose a valid old or new line.
- D-cache is **write-through, no-write-allocate**, with no posted success. An errored external write
  does not update the cache. This intentionally preserves precise store errors; write-back and
  nonblocking refill overlap are future work, not silently assumed benchmark features.
- `cacheableBase` / `cacheableBytes` explicitly bound allocation; MMIO bypasses. There is no
  cache coherence or external DMA snooping. This interface must not be placed into a production
  coherent system without its own coherence/invalidation/ordering adapter.
- FENCE.I at WB invalidates instruction-cache valid bits and BTB metadata. In-progress refills
  retain their response owner but cannot resurrect an invalidated line.
- `branchPredictorEntries`: 0 disables prediction; powers of two 2..1024 enable a tagged BTB
  with 2-bit saturating conditional counters. Targets/counters are small distributed RAM, with
  valid bitmap reset. No RAS, speculative training or hidden extra processor stage is present.
- Prediction is captured with the accepted fetch owner, retained through IF/ID/EX, and repaired
  in EX if the actual successor differs. Training is restricted to nonfaulting WB retirement.
  A false prediction on a nonbranch is also repaired; stale fetches remain killed and drained.

For the 2+2 KiB RV64/64-byte-line profile, exact logical cache storage is 32,768 payload bits,
3,392 tag bits and 64 valid bits. The 64-entry predictor has 7,872 logical payload bits plus
64 valid bits; asynchronous read-port replication can increase its physical LUTRAM storage.
These are capacity calculations, **not measured RAM primitive, LUT or FF counts**. CIRCT's
RAM leaf attributes and actual Vivado mapping still need a cache-aware export audit; the
existing bare-core export/mapping script must not be treated as a qualified cached delivery.

Short batch entry point:

```sh
GSIM_CXX=clang++-19 python3 -B simulator/gsim/inorder/cache_predictor_acceptance.py --tag UNIQUE_TAG
mill -i OrbitalI1.test.runMain inorder.FiveStageCachedMain build/gsim/cached-core 64 \
  --icache=2048 --dcache=2048 --predictor=64
```

The matched image is compiled once from pinned CoreMark using RV64IM/Zicsr/Zifencei, LP64,
`-O2`, performance seeds and standard 2000 bytes, with **one fixed iteration** and no UART.
It is deliberately not a formal >=10-second CoreMark score. Each run checks all retired
PCs/instructions/register writes against a procedural independent ISA oracle, validates the
four standard CRCs and final RAM, and rejects a deliberate register-result mutation.
The final CRC and retired PC/instruction stream must also match across configurations.

The OoO comparison instantiates the **unchanged** existing `IntegerCore`: 2 issue/commit,
ROB32/PRF64, four memory/store-buffer slots, 64-entry branch predictor, M-state enabled,
no C/F/D/Sv39. A synchronous 64-bit instruction word supplies two instructions when aligned
or one contiguous instruction otherwise. Both cores use **the exact same cache RTL and
shared 64-bit round-robin I/D memory service**. Accepted requests pass through one capture /
arbitration cycle, then 1 or 12 first-response service cycles; contention adds queueing behind
the other master. Subsequent burst beats arrive at one beat/cycle. These service parameters
are not an assumed 1/12-cycle complete request-to-response latency. This is a controlled bare-core comparison, not the best-performance
RV64GC board configuration or a claim about NaxRiscv. The blocking write-through adapter
also limits the OoO memory subsystem; it is disclosed rather than credited to the new core.

No synthesis, placement, routing or bit generation is included in this batch. New frequency
and area must stay unqualified until one later coherent cache-aware physical run.
The 2+2 KiB / 64-entry profile also passed static CIRCT RTL lowering via
`inorder.FiveStageCachedRtlMain`; diagnostic split SystemVerilog is at
`build/fpga/orbital-i1-cache-diagnostic-20261013-r1/`. It contains explicit
`data_256x64`, `tags_32x53`, `entries_64x123` and `bank_32x64` memory leaves.
This is a lowering/structure check, not proof of Vivado RAM mapping or timing.

### Final short acceptance and matched performance

Receipt: `build/gsim/five-stage-cache-20261013-r13/receipt.json`.
Status: `PASS_CACHE_PREDICTOR_MATCHED_SHORT_COREMARK_ONLY`.
Pinned GSIM: `93b8cd23edd3228807c4f2a08c19c3936a463cb2`;
CoreMark: `1f483d5b8316753a742cbf5590caf5bd0a4e4777`.
The shared binary is 12,040 bytes, SHA-256
`a4c47879b49348ffca0887959541a78f86314794912f86e2d91d2a3cd71b1f59`.

All four profiles passed both service settings, self-modifying-code/FENCE.I/branch smoke,
and independent architectural/result checks. Every profile rejected the deliberately corrupted
register result. The final metadata-only receipt reran the tests with source/tool/artifact-hash
checked model reuse; **test results were not reused**. Configuration tests (4), randomized
RV32/RV64/disabled-cache cases, 12,000-cycle predictor checks and the predictive/nonpredictive
integer-core checks also passed. A warmed IF-cache check completed 16 reads in 17 cycles.

All CoreMark runs retired the same 384,801 nontrap instructions, with 360,420 instructions
in the measured region and retired PC/instruction trace hash `8225deb11e7dfaae`.
Standard seed/list/matrix/state CRCs were `e9f5/e714/1fd7/8e3a`; the one-iteration final CRC
was `e714`. The measured region is bracketed by the same two guest timer reads, excludes
startup, and includes the loop's actual cache/memory stalls. The table reports **cycles and
workload IPC, not a formal CoreMark score**.

| Profile | Service 1: ROI cycles | ROI IPC | Service 12: ROI cycles | ROI IPC |
| --- | ---: | ---: | ---: | ---: |
| I1, caches/prediction disabled | 1,873,332 | 0.192395 | 7,333,704 | 0.049146 |
| I1, 2 KiB I + 2 KiB D, no predictor | 703,084 | 0.512627 | 873,544 | 0.412595 |
| I1, same caches + 64-entry predictor | **576,209** | **0.625502** | **746,669** | **0.482704** |
| Frozen two-issue OoO reference, same caches | 469,952 | 0.766929 | 630,546 | 0.571600 |

Prediction improves I1 throughput by 22.0% / 17.0% for the two service settings without
larger caches or another pipeline stage. Whole-run control-flow repair events fall from
43,148 to 7,852; these counts are not restricted to the ROI. The OoO misprediction counter
is not observed by this wrapper and is explicitly `null`, not a claimed zero.

At equal frequency the predictive I1 achieves about 81.6% / 84.4% of this frozen OoO
reference's measured throughput. Matching it requires about 1.226 / 1.184 times the
reference frequency. For example, 122.6 MHz I1 would mathematically match a 100 MHz
reference under service 1, **only if the new configuration actually passes timing**.
The old uncached/unpredicted 200 MHz result is not evidence that this cached configuration
can run at 200 MHz. No current cache-equipped LUT/FF/BRAM/DSP result exists yet.

### Priority after this batch

The user has frozen the OoO comparison at this result. Subsequent development focuses on
the five-stage I1: low resource cost, high sustained throughput and high achievable frequency
together, rather than repeating or expanding OoO benchmark runs. Retain the frozen image,
memory law and reference receipt for comparisons.

First instrument and classify IF starvation, load-use waits, write-ack waits and accepted bus
request/transfer duty. Then batch changes that reduce avoidable ownership/admission bubbles
and read/write serialization, while keeping synchronous RAM payloads, precise errors and
five architectural stages. Do not make queues or cache capacity the default solution.
The current blocking write-through/no-write-allocate D-cache is explicitly a starting point,
not a claim of high store throughput. Any buffering/write-back option needs its own precise
error, ordering, fence and future DMA/coherence contract before it is enabled.

Keep predictor/redirect and memory READY chains bounded; improvement in simulated cycles
is not sufficient if it lengthens a clock-critical path. Audit cache RAM-leaf attributes before
the next infrequent physical run. Evaluate the existing 34-DSP multiplier's decomposition
against area, latency and timing rather than assuming that DSP use is already minimal.
Early memory admission and a tiled multiplier were not implemented in that cache/predictor
batch; they are introduced by the subsequent throughput batch below. A return-address predictor
and nonblocking/write-back cache remain unimplemented.

## I1-only ownership / write dispatch / tiled multiplication batch

Final receipt: `build/gsim/five-stage-cache-20261013-throughput-r4/receipt.json`.
Status: `PASS_I1_THROUGHPUT_BATCH_SHORT_ONLY`. No OoO hardware model was run;
the prior matched receipt is a hash-recorded, read-only reference. The unchanged I1 baseline
also reproduced its prior cycles, ROI, instruction stream and CRC exactly. All comparisons
use the same pinned binary, cache capacities, 64-bit memory server and service law as above.

### Structural changes and configuration

- `earlyMemoryIssue=false` by default, enabled with `--early-memory-issue`. An EX memory
  operation may launch on transfer into an empty MEM slot, or when the older MEM packet is
  fault-free, non-memory and non-serial. It **cannot** launch behind an old memory response,
  since a late access error must suppress younger irreversible stores. If READY is low,
  the exact EX offer transfers to MEM and remains held; if accepted, the same edge installs
  `memSent`. No additional owner, request queue or architectural stage is added. This puts
  address generation on the RAM-input path and therefore requires later physical timing checks.
- `overlapWriteLookup=false` by default, enabled with `--overlap-write-lookup`. A write-through
  burst starts dispatch while synchronous tag lookup finishes. A single pending bit captures
  that tag result exactly once even if the burst is backpressured. Cache data updates only on
  a successful real write ack; the controlled server in this historical batch rejected errored
  writes without an external side effect. The later real AXI integration conservatively invalidates
  a cache hit on an error, since a subordinate may already have changed RAM. Read
  policy, cache capacity, hit latency and state-only D-cache admission remain unchanged.
- `multiplyMode="dsp-tiled"` / `--dsp-tiled` is optional. RV64 uses four unsigned 32x32
  partial products, carry-save cross-term reduction and registered high-half sign correction.
  MUL/MULH/MULHSU/MULHU/MULW preserve their independent arithmetic results. One extra held-EX
  cycle is deliberately spent on RV64 recombination; RV32 does not add that phase. This is
  **not** a measured 16-DSP claim: LUT/FF/DSP mapping and maximum frequency remain unqualified.
  The original `dsp` and no-DSP `iterative` choices remain available, and M can still be removed.
- Diagnostic outputs expose overlapping fetch/load-use/memory/store-ack/MDU stall events and
  native data request offers/acceptance. Counts are kept by the test driver, **not new 64-bit
  hardware counters**. Bus active time and arbitration wait are also host observations. These
  are whole-program counts, not an additive decomposition of the timer-bracketed ROI.

Speed-first profile:

```sh
--icache=2048 --dcache=2048 --predictor=64 --early-memory-issue --overlap-write-lookup
```

Resource-candidate profile adds `--dsp-tiled`. Do not silently choose it as the fastest profile.
Both new Boolean optimizations remain explicitly selectable, not enabled globally.

### Matched results and remaining bottleneck

| RV64 I1 profile | Service 1: ROI cycles | ROI IPC | Service 12: ROI cycles | ROI IPC |
| --- | ---: | ---: | ---: | ---: |
| Previous cache + predictor baseline | 576,209 | 0.625502 | 746,669 | 0.482704 |
| Early MEM ownership only | 525,594 | 0.685738 | 696,060 | 0.517800 |
| Write dispatch overlap only | 561,814 | 0.641529 | 732,274 | 0.492193 |
| Tiled multiplication only | 585,605 | 0.615466 | 756,065 | 0.476705 |
| **Speed-first: both memory optimizations, original DSP** | **511,198** | **0.705050** | **681,664** | **0.528736** |
| Both memory optimizations + tiled DSP candidate | 520,594 | 0.692325 | 691,060 | 0.521547 |

Speed-first throughput improves **12.72% / 9.54%** at fixed simulated service/frequency, with
no cache or queue expansion. The resource candidate remains faster than the old baseline but
costs 9,396 ROI cycles versus speed-first; choose between them only after area/timing measurement.
Every run retains 384,801 retirements, 360,420 ROI instructions, trace `8225deb11e7dfaae` and
all standard CRCs. Native data requests remain 74,409 and external stores 18,023. The low-service
whole-run accepted bus-beat count differs by one (27,918 -> 27,917) at the terminal speculative
IF drain boundary; this is not a reduced data-traffic or burst-capacity claim.

| Whole-run stall observation, service 1 | Previous | Speed-first |
| --- | ---: | ---: |
| Memory wait | 155,914 | 82,327 |
| Load-use dependency | 43,333 | 23,975 |
| Store acknowledgement wait | 72,370 | 54,379 |
| MDU wait | 28,575 | 28,575 |

Thus the gain comes from request/ownership and dispatch bubbles, not larger storage or a
changed instruction stream. Under service 12, store-ack wait is still 253,050 whole-run cycles
(memory wait 290,267), so write-through serialization remains a major limiter. No posted success,
write-back cache or hidden parallel memory owner has been introduced. Cache policy and bus
integration are the next structural throughput work; these observations are not real MIG
bandwidth measurements or a formal CoreMark score.

Against the frozen matched OoO result, equal throughput now requires an I1/reference frequency
ratio of about **1.088 / 1.081**, previously 1.226 / 1.184. This is conditional arithmetic, not
a new board timing result or a comparison with the best VL100 configuration. Against the prior
I1 profile, the low-service cycle improvement would tolerate at most about an 11.3% frequency
loss at the same cycle-based memory law before its throughput benefit disappears; the actual
physical run must determine whether the address/RAM-input path preserves the intended clock.

### Verification and preserved failed experiment

Five Scala configuration cases passed. Necessary short checks cover RV32/RV64 cached partial
writes, store errors, refill errors, invalidation, MMIO and backpressure; RV32/RV64 early-MEM
integer streams and M-disabled operation; 10 explicit older-fault/load-error/store-error/ALU-
forwarding/CSR-FENCE prefix cases in each of those three core profiles; and independent tiled
MDU checks (2,300 RV64 plus 1,800 RV32 transactions, 53 mid-operation kills in each, held results,
signed/unsigned high halves, W operations, division zero/overflow and warm reset). Register,
store-intent and MDU negative controls were rejected. All six cached CPU profiles passed
self-modifying-code/FENCE.I smoke, both CoreMark service settings and register negative controls.

The earlier `20261013-throughput-r2` experiment failed an old harness assumption: it compared
external memory to only already-WB-committed stores at every retirement, although a legitimate
younger store can reach the bus before its own WB. The final oracle maintains at most one
unretired external store intent, overlays only those exact bytes for every memory comparison,
and independently checks its ISA-derived address/data/mask plus real ack/error at store
retirement. A trap/interrupt cannot overtake such an intent. A deliberately corrupted store byte
is rejected. This is not a skipped memory check or a CRC-only relaxation. The failed receipt/log
is retained, and `r3/r4` use the same final hardware; `r4` adds explicit prefix and M-disabled
coverage while reusing only hash-identical models and rerunning all checks.

Both final profiles passed static split-SystemVerilog lowering:
`build/fpga/orbital-i1-throughput-diagnostic-20261013-r1-fast/` and
`build/fpga/orbital-i1-throughput-diagnostic-20261013-r1-tiled/`.
There was **no Vivado synthesis, placement, routing or bit generation**. Old bare-core 200 MHz
and 34-DSP figures remain historical only; no cached speed/resource candidate is FPGA-qualified.

Reproduce the bounded I1-only batch without rebenchmarking OoO:

```sh
GSIM_CXX=clang++-19 python3 -B simulator/gsim/inorder/cache_predictor_acceptance.py \
  --tag UNIQUE_TAG --inorder-throughput \
  --reference-receipt build/gsim/five-stage-cache-20261013-r13/receipt.json
```

## Next development batches

1. With the bare TileLink adapter now implemented, complete the cache-aware RAM-leaf export audit
   and physical board clock/MIG/reset/USER-chain integration. The ROM/PLIC/logical JTAG batch below
   is complete. Measure
   branch/load/cache-miss penalties and accepted memory duty before enlarging anything. Keep
   the current direct native ports for independent core verification.
2. Extend measured FPGA-friendly branch prediction with return prediction as justified, using the same compiled
   CoreMark/Embench binaries and memory/cache contract; keep this round's OoO reference frozen. Compare actual
   throughput (`frequency * workload IPC`) and complete configuration area, not ALU peak IPC.
3. If Linux capability is selected, implement C/A, S/U, precise Sv39/PMP and debug, then F/D
   through explicit separately tested switches. Do not advertise a configurable but incomplete
   extension; do not import old legacy pipeline control or the OoO ownership chains.
4. Reduce the multiplier's current 34-DSP mapping if a tiled/registered implementation improves
   the measured frequency/area/latency tradeoff. Further 300 MHz work must preserve the five
   architectural stages and include the actual cache/bus configuration in timing claims.

## TileLink / preloaded-DDR bare SoC / standard O3 batch

This section records the earlier r6 snapshot. Its direct-MEIP/preloaded-DDR boot contract is
historical; the current PLIC/ROM/reset/JTAG contract is in the following batch section.

Final evidence: `build/gsim/five-stage-soc-20261013-r6/receipt.json`.
The preceding `r5` passed the initial SoC/O2/O3 gate; `r6` adds late-write-error cache recovery
and accurate embedded O3 flag text. Neither snapshot changes the original OoO CPU or its board defaults.

### Integration contract and resource intent

- `FiveStageTileLink` implements Get and single-beat PutPartialData, one source/owner per
  existing cache. An entire cache-line Get uses one A request and the exact number of D beats;
  response error/metadata, stable offers, backpressure and final ownership are checked. This is
  noncoherent TL-UH-style read bursting, **not TL-C/AMO/AIA support**. No extra cache owner,
  posted write acknowledgement or request/payload FIFO was added by this adapter.
- Backend payload addresses stay word-aligned, but new `size`/`byteOffset` metadata preserves
  byte/half/word MMIO accesses. Stores retain native aligned byte lanes; the register boundary
  right-justifies data/strobes and shifts read data back to the correct lane. IF explicitly aligns
  its word request and uses its separate PC half selector; uncached PC+4 fetches are legal too.
- `FiveStageSocConfig` selects cache/predictor/MDU options independently and can remove UART,
  timer and M-mode interrupt wiring. The existing DDR bridge is 64-bit, so this first SoC is RV64;
  the independent adapter is tested at both RV32 and RV64. The reused fabric permits line sizes
  through 128 bytes; unsupported combinations are rejected, not silently truncated.
- The two-slot DDR option reuses `TileLinkAxi4OutstandingBridge`, with one write credit and
  unordered **whole-message** responses. IF/D retain independent sources and same-address
  read/write hazards still serialize. The single-slot option reuses `TileLinkAxi4BurstBridge`.
  Both source files, the arbiter, UART and timer are unchanged. No OoO CPU test is rerun.
- D-cache remains blocking, write-through/no-write-allocate with synchronous RAM payloads.
  Cache capacity remains 2+2 KiB in the speed profile, and the CPU is still **IF/ID/EX/MEM/WB**.
  These bridge slots connect existing IF/D owners; they do not add a CPU MSHR or store queue.
- AXI R/B errors become precise load/store access faults. A late B error can follow an external
  side effect; the affected cached hit is conservatively invalidated instead of exposing old RAM
  data. This is not rollback of external device effects, atomic write recovery or transparent retry.
  Partial/error read fills remain invalid, including an error on the final AXI beat.

### Memory, clocks and boot boundaries

| Window | Address | Access contract |
| --- | --- | --- |
| DDR | `0x80200000 .. 0x1001fffff` (2 GiB) | 64-bit physical TL address; subtract base before narrowing to the 32-bit MIG AXI offset |
| MSIP | `0x02000000` | 32-bit right-justified register; present with interrupts enabled |
| MTIMECMP | `0x02004000` | 64-bit base access or 32-bit low/high halves at +0/+4 |
| MTIME | `0x0200bff8` | Same half/full geometry; increments once per CPU clock |
| UART | `0x10000000 .. 0x10000007` | Existing 16550 byte registers; virtual baud reference is `16 * uartBaud` |

Reset/trap defaults are `0x80200000` / `0x80200100`; the test programs set their own mtvec.
This initial top runs a **preloaded DDR image**, without a BootROM/UART/TFTP downloader or on-chip
ROM/RAM boot path. It does not yet replace the existing board wrapper, clock wizard or reset controller.
The caller must hold reset until DDR is initialized and the image exists. Resetting the CPU/fabric
without draining or resetting outstanding downstream AXI owners is not a supported warm-reset operation.

CPU/fabric/AXI and UART/timer are one clock domain here. The AXI output is the CPU-side interface
for the board's existing CDC/converter/MIG; that board connection and its multi-clock reset/STA are
still qualification work. An external IRQ input must be a CPU-domain synchronized level. Reused UART
RX has its own serial synchronizer. `clockHz=100000000` describes the time/baud configuration,
**not a new proof of 100 MHz timing**.

The core's existing precise M-mode IRQ inputs receive MSIP, timer MTIP, and UART/external MEIP.
There is no APLIC/IMSIC claim interface yet: existing Linux/AIA drivers cannot be used on this top.
The reused AIA controller needs committed CSR support in the new CPU before it can be integrated.
DMA/GMAC are not instantiated; these caches must not be treated as DMA-coherent. Future integration
requires an explicit uncached-buffer or cache-maintenance/coherence contract.

### Short verification

Six pure Scala configuration cases pass. Adapter tests independently derive A metadata, subword
lane masks, response lengths/errors and owner lifetimes: **1,200 requests each** at RV64 and RV32
(2,600 / 4,200 returned beats). Wrong-source response negative controls are rejected.

The cache short gate covers RV64/RV32 and disabled-cache profiles, with 1,000 random accesses
per profile plus failed refills, partial writes, invalidation, held outputs and reset checks. Its new
late-write-error case deliberately changes backing RAM before returning an error: the CPU gets
the fault, the old hit is invalidated, and a subsequent read observes actual RAM, not stale data.

The actual SoC CPU executes a self-checking linked RV64 bare-metal program through the reused
TL/AXI bridge and real peripheral RTL; the host never supplies fake UART/timer register replies.
Bounded random AXI AR/AW/W backpressure and delayed R/B replies check stable offers, IDs,
address translation, byte strobes, burst geometry and WLAST. The guest verifies dependent DDR
stores/loads, the 2-GiB last word above 4 GiB, byte writes, timer high halves, UART FIFO loopback,
MSIP/MTIP/MEIP handlers, MRET and exact MMIO/AXI load/store access-fault counts and mtval.
Deliberate DDR data corruption takes the guest failure path and is rejected by the driver.

| Executing profile | Cycles to complete smoke | AXI reads / writes | Line reads | Max observed concurrent AXI reads |
| --- | ---: | ---: | ---: | ---: |
| 2+2 KiB / BTB64 / both memory optimizations / original DSP / DDR slots2 | 6,517 | 33 / 142 | 33 | **2** |
| Caches/predictor off / M removed / DDR slot1 | 25,605 | 1,797 / 142 | 0 | 1 |

The same image polls asynchronously changing IRQ/FIFO state, so its retirement counts differ;
these completion times are **not a controlled CoreMark speedup comparison**. The first result
does establish that both independent DDR read owners are actually exercised. A third elaboration
removes UART, timer, interrupts and M together; absence of those IP modules is checked in FIRRTL.
That third profile is an elaboration/removal check, not an executing UART/IRQ test.

SoC smoke uses guest checks plus an independent AXI scoreboard. Separate CoreMark tests below
retain the stronger every-retirement independent ISA oracle and full final RAM/official CRC check.
Do not describe the short SoC smoke as an exhaustive SoC or ISA certification.

### O2 versus O3 without changing benchmark types

CoreMark permits compiler optimization such as `-O3`; use the same flags for all benchmark
sources and record compiler/ISA/linkage/flags. Standard `ee_u32` remains unsigned; no source
algorithm or type change was imported from the NaxRiscv port. Both builds use the clean pinned
CoreMark commit, GCC 13.2.0, `rv64im_zicsr_zifencei/lp64`, standard 2,000-byte dataset, one iteration,
and the identical standalone speed-first core/cache/predictor model and 64-bit RR memory service.
The compiled compiler-flag string is selectable too, rather than falsely hardcoding O2 for O3.

| Optimization | Image bytes | Service1 ROI cycles | ROI IPC | Service12 ROI cycles | ROI IPC |
| --- | ---: | ---: | ---: | ---: | ---: |
| O2 baseline | 12,040 | 511,198 | 0.705050 | 681,664 | 0.528736 |
| O3 | 16,280 | 500,691 | 0.690086 | 677,421 | 0.510052 |

At the same configured clock/service law, O3 throughput improves **2.10% / 0.63%**. It retires
345,520 ROI instructions instead of 360,420, so lower IPC does not mean lower benchmark performance.
The binary is 35.2% larger and whole-run I-cache misses grow 422 -> 909; bus beats grow roughly
22.9%. That explains why fewer instructions do not yield a proportionate speedup with 2-KiB caches.
Keep both compiler profiles instead of assuming O3 always wins.

Each optimization cohort has the same architecture stream and final CRC at both service settings;
different compiled O2/O3 images intentionally have different instruction traces. The O2 result
reproduces the previous throughput-r4 baseline exactly, so adapter metadata and fetch alignment
did not cause a core throughput regression. Standard CRCs and final RAM match, and register-oracle
negative controls fail correctly in both optimization cohorts.

These are **short CRC/architecture comparisons, not formal CoreMark scores**. A formal board
measurement must run for at least ten seconds and report actual clock, complete flags and memory
placement. The O2/O3 table tests the independent cached core backend; whole-SoC CoreMark with
the real TL/AXI bridge is a subsequent throughput measurement, not implied by this table.

No Vivado/synthesis/place/route/bit was run in this batch. Cache-equipped SoC LUT/FF/BRAM/DSP
counts and maximum frequency remain unmeasured; historical bare-core 200-MHz evidence does not
qualify this assembled configuration. Original OoO sources and `/home/openion/Valence` are preserved.

Reproduce the bounded batch:

```sh
cd /home/openion/Valence-inorder
GSIM_CXX=clang++-19 python3 -B simulator/gsim/inorder/soc_acceptance.py --tag UNIQUE_TAG
```

Preserved development failures: `r1` exposed a missing isolated build dependency; `r2` used a
TL size encoding unsupported by the existing fabric; `r3` counted asynchronous IRQs as instruction
retirements; `r4` found the uncached RV64 PC+4 word-alignment bug. Logs/receipts are retained.
These gates were corrected before the passing r5/r6 snapshots; no failing gate was waived.

## BootROM / startup reset / PLIC / FPGA shared-JTAG batch

Evidence: `build/gsim/five-stage-boot-20261013-r2/receipt.json`,
status `PASS_I1_BOOTROM_RESET_PLIC_LOGICAL_JTAG_SHORT_ONLY`.
Only this independent worktree is edited. Original `/home/openion/Valence` and its uncommitted
board changes are preserved. No commit/push is made in this batch.

### Storage and startup contract

- Default reset vector is `0x00010000`: **4 KiB synchronous dual-read-port 64-bit BootROM**.
  Payload is SyncReadMem with block-ROM hierarchy intent and file initialization, not a reset
  FF vector or a combinational instruction mux. Actual RAMB mapping remains unmeasured.
  Each uncached port has one owner, one-cycle memory read, at most one request per two cycles
  without stalls and a held response under backpressure. Writes are denied without modifying ROM.
  Boot instructions/constants are outside the DDR-cacheable range.
- `fpga/inorder/bootrom/start.S` is stackless RV64I/Zicsr/Zifencei firmware. It prints
  `Valence Orbital-I1 BootROM V0.1` when UART is present, waits for DDR readiness, then jumps
  to preloaded DDR or waits for a configured JTAG download. Current code/constants are **390 bytes**.
  `src/main/resources/inorder/bootrom.hex` is a reproducible text initialization asset.
  `fpga/inorder/bootrom/build.py --output <fresh-build-folder>` emits ELF/bin/hex/manifest;
  acceptance compares all 512 words against the source asset. Build outputs are not source inputs to commit.
- Entry ABI: M mode, mie/MIE disabled, a0=mhartid, a1=0; guest initializes sp/gp/mtvec.
  Boot exceptions and a returned guest park in ROM. This is not an OpenSBI/Linux boot contract.
- FiveStageStartup samples lock/readiness through two local registers and holds CPU/cache reset
  for four consecutive qualified edges. With ROM, lock alone releases the CPU, and firmware waits
  for DDR-ready. With `--soc-no-bootrom`, DDR-ready is required before CPU release.
  Later lock/calibration loss latches resetFault instead of abruptly discarding accepted transactions.
  A fault flag cannot guarantee progress when a broken/stopped DDR no longer returns responses.
- FiveStageFpgaShell provides CPU clock, common active-low POR, lock/calibration-ready, UART,
  synchronized external IRQ and CPU-side AXI. It reuses asynchronous-assert/synchronized-release
  CdcResetRelease. Clock wizard, AXI CDC/converter and physical MIG remain external.
  **Common POR must reset the downstream AXI/CDC endpoint too**. This is startup/common reset,
  not a claimed safe unilateral hot-reset or architectural debug halt implementation.

### MMIO and PLIC

| Resource | Address/source | Access |
| --- | --- | --- |
| BootROM | `0x00010000 .. 0x00010fff` | Read-only, uncached instruction/data |
| Boot status | `0x10002000` | 64-bit: ready bit0, JTAG mode bit1, reset fault bit2, UART-present bit3 |
| Preloaded entry | `0x10002008` | 64-bit configured DDR base |
| PLIC priority | `0x0c000000 + 4*source` | Aligned 32-bit LW/SW |
| PLIC pending | `0x0c001000 + 4*word` | Read-only packed bits |
| PLIC M-context enables | `0x0c002000 + 4*word` | Packed bits, source zero absent |
| PLIC M-context threshold | `0x0c200000` | Three priority bits by default |
| PLIC M-context claim/complete | `0x0c200004` | LW claims, SW completes |
| Optional PLIC S enables | 0x0c002080 + 4*word | Present when S-mode and interrupts are enabled |
| Optional PLIC S threshold | 0x0c201000 | Same configurable priority width |
| Optional PLIC S claim/complete | 0x0c201004 | Context 1 routes to SEIP |
| External level / UART | PLIC source **1 / 3** | No direct UART-to-MEIP bypass |
| JTAG CPU control | `0x10003000 .. 0x1000303f` | Existing 64-bit loader control/status/generation map |

DDR remains **2 GiB**, `0x80200000 .. 0x1001fffff`; subtract base before narrowing AXI offsets.
UART/MSIP/MTIME/MTIMECMP addresses are unchanged. MTIP/MSIP stay hart-local, not PLIC sources.

New reusable Plic supports 1..1023 level sources, 1..16 contexts and 1..7 priority bits;
the I1 M-only SoC connects one M context, eight sources and three priority bits by default.
Selection is a balanced priority tournament, with lowest-ID ties. Gateways retain pending levels
after deassertion and block repeats until completion. Claim ignores threshold; completion checks
current enable, not a fabricated last-claim authorization. Disabled/out-of-range completions
are ignored. MMIO claim side effects occur once at acceptance, not while a response is stalled.
Reference: [ratified RISC-V PLIC 1.0](https://github.com/riscv/riscv-plic-spec/blob/master/riscv-plic.adoc).
Large source/context scaling and FPGA timing are not qualified by the eight-source/two-context test.

### Optional FPGA shared JTAG download

`withJtagLoader=false` remains default; enabling it requires ROM. `--soc-jtag` connects the
unchanged JtagRamLoader, one acknowledged RegisterPort-to-TL adapter and the DDR fabric.
`FiveStageFpgaShellMain --soc-jtag --soc-user-chain=2` selects existing real BscanRamTransport
behind FPGA **USER2/BSCANE2**. No additional package JTAG pins or soft TAP are created.
USER2/3/4 must be explicitly allocated; USER1 is rejected because the current debug hub uses it.
This custom USER/DMI endpoint is **not a RISC-V Debug Module/GDB target/halt/resume/step**.

ROM arms only after DDR-ready and link-up. Host writes a contiguous raw binary at the advertised
base; one 32-bit memory operation owns the bus until the real response, including AXI B/errors.
Generation-bound COMMIT stops further writes. ROM independently verifies CRC32 over the logical
byte length, claims launch, executes fence rw,rw and fence.i, then enters the image.
Bad CRC closes/re-arms. Registered D-cache invalidation on open/close prevents stale CRC reads
when the next download changes RAM contents. After claim, host RAM writes remain disabled until
coordinated common reset. This is boot-only downloading, not live CPU/DMA coherence.

Existing SBA is **32-bit-addressed**. Default download window is the first **64 MiB**,
`0x80200000 .. 0x841fffff`; parameterization must remain inside DDR and below 4 GiB.
CPU DDR remains the full 2 GiB. Link reset must not discard already offered/accepted bus owners.
See [BSCAN scan framing](debug/bscan-user-transport.md) and
[existing OpenOCD loader](../simulator/jtag/RAM-LOADER.md). I1 ROM automatically arms in configured
JTAG mode; it does not need the older OoO monitor's UART `j` command.

Only shell elaboration/resource/removal checks are performed here. Actual TAP order, USB adapter,
new-image USER-chain freedom, vendor primitive/CDC simulation, physical timing, board operation
and JTAG bandwidth are **not tested**. Existing post-synthesis chain-collision and BSCAN timing/
CDC audits remain required; this is not yet a board-qualified JTAG loader or complete I1 board bit.

### Short acceptance and limits

Seven pure configuration cases pass. PLIC independent software oracle checks **2,516 transactions**,
two contexts, priorities/ties, threshold-independent claims, level completion, invalid geometry
and response stalls; deliberately wrong claim expectations are rejected. Startup oracle checks
**5,760 cycles each** with/without ROM and lock/readiness loss. ROM independent oracle checks
**2,400 two-port transactions**, rejected writes and held responses; corrupted byte expectations fail.

| Executing CPU path | Cycles | ROM / DDR retired | AXI reads / writes |
| --- | ---: | ---: | ---: |
| ROM -> preloaded DDR, 2+2 KiB caches / predictor64 | 74,298 | 22,405 / 3,125 | 34 / 142 |
| Explicit preloaded DDR, no caches/predictor/M / one DDR slot | 45,555 | 0 / 1,285 | 1,815 / 142 |
| ROM -> logical JTAG -> CRC/claim -> DDR | 230,702 | 66,064 / 2,973 | 48 / 355 |
| Wrong RAM first image -> CRC reject -> corrected download -> DDR | 387,015 | 109,702 / 2,969 | 62 / 568 |

These are **bring-up checks, not performance/CoreMark comparisons**: ROM UART polling, readiness
at cycle 20,000, interrupts and randomized memory service change cycle/retirement counts.
Previous standalone O2/O3 benchmarks are not rerun or reinterpreted.
CPU checks PLIC UART claim/complete, MSIP/MTIP/MRET, 2-GiB last word above 4 GiB, byte lanes
and precise MMIO/AXI fault counts. No DDR access occurs before test calibration.
Bad-CRC-only test re-arms after 66,059 ROM retirements with **zero DDR-code retirement**.
Retry changes actual RAM bytes before fixing them, exercising cached verification invalidation.
Post-claim JTAG writes are rejected; the program image remains byte-exact.
Host drives logical DMI, not fake UART/timer replies or a pretend BSCAN clock. ASan/UBSan are enabled.
Shell and disabled-IP checks are elaboration-only.

Reproduce:

```sh
cd /home/openion/Valence-inorder
GSIM_CXX=clang++-19 python3 -B simulator/gsim/inorder/boot_acceptance.py --tag UNIQUE_TAG
```

Pinned GSIM ignores file ROM initialization and cannot emit top-level Vec accessors. Test-only
wrappers pack/unroll interfaces and initialize all 512 exact ROM words under common reset.
FPGA shell has **no ROM programming/test input** and uses the source hex annotation.
Initial r1 accessor failure is retained; r2 does not change or weaken the independent oracles.
A subsequent configuration-only DDR/MMIO-overlap guard and format cleanup change no accepted-profile
RTL: seven configuration checks pass again, and final CHIRRTL is identical to r2 after removing
source-location annotations. Follow-up evidence: `build/gsim/i1-boot-final-equivalence-20261013-r2/`.
Header hashing and explicit preloaded entry points were maintained without rerunning the O2/O3 suite.

**No Vivado synthesis/place/route/bit, new physical frequency/area signoff, full GSIM/Linux run,
or OoO rebenchmark.** Next: actual clock/MIG/common-reset hookup, RAM-leaf audit and one combined
physical qualification before any cached-SoC/board frequency claim.

## 2026-10-14: optional M/S/U, PMP, Sv39 and PLIC S context

Final evidence: **build/gsim/five-stage-privilege-20261014-r6/receipt.json**.
Status: PASS_I1_MSU_PMP_SV39_PLIC_S_SHORT_ONLY.
Original OoO source/branch/dirty files are preserved. No commit/push, Vivado, bit or OS boot.

### Architectural and software contract

- FiveStageConfig parameterizes withUser, withSupervisor, withSv39, pmpEntries,
  physicalAddressBits and tlbEntries. S requires U; Sv39 requires RV64 S/U.
  Default S/U/Sv39/PMP remain **off**. --sv39 enables S/U, --pmp=4 selects protection,
  --tlb=4 is the tested size of **each** I/D TLB. --supervisor without Sv39 permits Bare S/U.
- M/S CSR banks and access checks, MRET/SRET, U/S/M ECALL causes, direct/vectored mtvec/stvec,
  medeleg/mideleg, MIE/MPIE/MPP and SIE/SPIE/SPP are implemented. M traps never delegate downwards;
  machine IRQ delegation bits are WARL zero. MPRV affects explicit data only and clears on return below M.
  TVM/TSR/TW and mcounteren/scounteren are checked. WFI is a permitted no-op, not clock gating.
- State changes happen at WB after older instructions drain. Context barriers kill old prefetched
  instructions without discarding accepted read owners; stores require real physical acknowledgements.
  mip.SEIP reads external OR software state, but CSRRS/CSRRC modify only the software latch.
- Sv39 supports canonical addresses, three levels, 4KiB/2MiB/1GiB leaves, reserved-PTE rejection,
  superpage alignment, U/S permissions, SUM and MXR. ASIDLEN=0; SFENCE.VMA globally invalidates
  local entries, including against in-flight refill resurrection. Unsupported satp modes ignore the write.
- **Svade** is explicit in the enabled ISA string: A=0 or store D=0 causes a page fault, not a
  non-atomic PTE RMW. Future I1 DT/firmware must report this software A/D policy.
  Physically inaccessible PTE reads/final PMP denials produce access faults, with the original VA in tval.
- PMP supports OFF/TOR/NA4/NAPOT, 4-byte grain, R/W/X, lowest-entry priority, complete-access
  checking and locks, including a locked TOR predecessor address. 4/8/16 writable regions are exposed
  in a 16-entry architectural CSR bank; unused entries are OFF/zero. Zero entries remove the bank/checkers.
  Automatic PA width: RV32=32, RV64=36, configurable up to min(XLEN,56).
- PLIC context 0 is M/MEIP; optional context 1 is S/SEIP. UART remains source 3 and external level
  source 1. MSIP/MTIP are hart-local. mip supports SBI-style SSIP/STIP injection; Sstc/AIA are not claimed.
  Machine timer still counts CPU clocks; DVFS needs a later fixed timebase/CDC design.

Reference:
[ratified machine/PMP specification](https://docs.riscv.org/reference/isa/v20260120/priv/machine.html),
[ratified Sv39/Svade specification](https://docs.riscv.org/reference/isa/v20260120/priv/supervisor.html).

### FPGA timing/resource boundaries

The architecture remains **IF / ID / EX / MEM / WB**, single issue, ordered and without ROB/rename.
Cache/walk latency stalls these stages rather than becoming a sixth architectural stage.

- Data path is registered lookup -> registered PA -> PMP authorization; EX carry is not chained into
  TLB + PMP + external admission. TOR/NAPOT range decoding is captured atomically on serial CSR commit,
  outside the access critical path. Four writable entries add 296 logical range-register bits.
- IF's PC is already registered. Its optional page-qualified hit skips repeated PMP work, with
  authorization covering the exact 4KiB slice. Only IF uses this fast path; early-MEM stays staged.
  Offers remain sticky; a real synchronous I-cache hit can overlap the next fetch.
  --no-fast-instruction-translation selects staged IF, not a newly routed-qualified profile.
- Four-entry small TLBs use unreset payload registers/reset valid bits. PPN is 24 bits for 36-bit PA,
  saving 160 logical bits across I/D versus full 44-bit PPNs. 4KiB indices have a small VPN XOR fold.
  Existing entry zero holds a real 2MiB/1GiB mapping and a short prefix match reuses its subpages.
  Fast IF permission remains specific to one 4KiB slice, **never** the whole superpage.
- Two small walk FSMs share **one existing physical D-cache port/owner** with demands under fair
  arbitration. No additional cache, AXI master, MSHR or posted-store queue. This is not a single shared walker.
- The accepted CHIRRTL retains SyncReadMem: 2+2KiB caches = 32,768 payload bits; two 32x64 RF banks =
  4,096 payload bits. GSIM does not measure RAMB inference, LUT/FF totals or routed timing.
- A legal scalar whose surrounding line fails PMP takes an uncached path. Bypass writes invalidate
  the matching cache index at admission, so a prior M-mode line cannot expose stale bytes after an ack/error.

**No new WNS, frequency ceiling, FPGA area, routed/CDC or board qualification.**
The old uncached/unpredicted foundation's 200MHz result does not qualify this privileged cached SoC.

### Short acceptance and measured CPU model

- Eight pure configuration tests; 12,000 independent PMP interval/priority/partial-overlap cases,
  CSR delegation/xRET/MPRV/counter/TVM/TSR/TW/locks and external/software SEIP separation.
- 285 data + 285 instruction translation cases: permissions/A-D/all leaf levels, superpage reuse,
  reserved PTEs, physical/PMP limits, response errors, SFENCE races, held owners and PMP slice boundaries.
- PLIC oracle: 2,516 two-context transactions. Cache byte-memory oracle: 1,000 randomized operations
  plus boundary bypass writes, true ack/error, partial writes, failed refills/invalidation and warm reset.
- Actual CPU creates page tables in DDR, transitions M->S->U, fetches/stores through Sv39, checks
  precise exceptions, changes a warmed mapping, tests MPRV, and receives actual UART loopback through
  PLIC-S plus SBI-style STIP. 19 trap events; denied stores leave the complete U program byte-exact.
- M-only baseline passes: 26,672 cycles / 2,977 retired / 34 AXI reads / 142 writes, including the full
  2GiB end address, MSIP/MTIP, PLIC-UART and precise MMIO/AXI errors.
- Deliberately wrong delegation/page/claim/result expectations are rejected. ASan/UBSan are enabled.
  RV32 S/U/PMP and stripped RV64 are elaboration-only secondary profiles.

Same short streaming binary, CPU, 2+2KiB caches, four-entry TLBs and random AXI service law;
host selects only Bare vs Sv39, both execute in S-mode. Buffers are 8KiB each, all bytes/checksums verified.

| S-mode path | READ cycles | WRITE cycles | COPY payload cycles |
| --- | ---: | ---: | ---: |
| Bare, same protected/MMU-capable hardware | 13,876 | 21,300 | 30,879 |
| Sv39 with actual-superpage reuse | 13,934 | 21,300 | 30,831 |

READ overhead is 0.42%, WRITE is equal, COPY is effectively equal (0.16% fewer cycles from service
scheduling, not a universal virtual-mode advantage). Before true superpage reuse, Sv39 COPY cost
40,883 cycles: the fixed-capacity change yields **24.59% fewer cycles / 32.60% higher payload per cycle**.
Whole-test AXI reads fall 327->265, vs Bare 264; writes remain 3,077.
At nominal 100MHz, final COPY is about 25.34MiB/s payload in this short write-through CPU model,
not a measured FPGA clock/DDR peak/CoreMark/Linux memcpy/OoO comparison.
Four-entry 4KiB-only workloads can still have capacity/conflict misses; Linux performance is unqualified.

Reproduce with a fresh tag:

~~~sh
cd /home/openion/Valence-inorder
GSIM_CXX=clang++-19 python3 -B simulator/gsim/inorder/privilege_acceptance.py --tag UNIQUE_TAG
~~~

Privileged SoC parameters: --sv39 --pmp=4 --tlb=4 --icache=2048 --dcache=2048 --predictor=64
--early-memory-issue --overlap-write-lookup. The default keeps BootROM; acceptance explicitly
uses --soc-no-bootrom for new CPU tests. It does not falsely requalify physical BootROM/JTAG/CDC.
Original defaults remain M-only, all protection/translation options off.

Retained intermediate evidence: r1 functional PASS; r2 IF Scala forward-reference failure;
r3 fast-hit pulse under held-offer missing; r4 PASS but superpage thrashing; r5 fixed-capacity
throughput PASS; r6 adds cache-bypass coherence. No failed gate was waived.

At the end of this earlier privilege-only batch, C/A and actual OpenSBI were still pending.
The following batch supersedes those pending items; Linux and optional F/D remain unqualified.

## 2026-10-14 — optional C/A, actual OpenSBI and complete SoC synthesis

Canonical evidence in this independent worktree:

- `build/gsim/five-stage-ca-units-20261014-r2/receipt.json` — C/A module PASS.
- `build/gsim/five-stage-ca-soc-20261014-r6/receipt.json` — actual CPU C/A/ROM/OpenSBI/S-mode PASS.
- `build/gsim/five-stage-ca-default-off-20261014-r2/receipt.json` — default-OFF M-only ROM SoC PASS.
- `build/fpga/five-stage-ca-physical-20261014-r2/receipt.json` — synthesis setup100 estimate only,
  including negative hold; no placement/routing/bit/board qualification.

### Architecture and parameter contract

`withC` and `withA` are independently selectable, **both default false**; CLI `--c` / `--a`.
The current verified hardware remains IF/ID/EX/MEM/WB, single issue, no ROB/rename/sixth RF stage.
Integer RV32/RV64 C covers legal instructions, HINTs and reserved encodings. F/D compressed
instructions remain illegal because I1 has no F/D. Expansion is combinational in ID, while
retire/tval retain raw 16-bit encodings. EPC alignment, branch checks and sequential +2/+4 are updated.
IF authorizes two-byte parcels: a compressed instruction at page end does not overfetch;
32-bit halfword-aligned instructions crossing a word/page get a separate second-parcel permission
check unless a whole-word authorization proof exists. Partial-fetch faults keep the original EPC
and report PC+2 as tval. Existing BTB RAM stores a length hint; cold/conflict misses repair in EX
and have a real penalty. This batch does not claim a new compressed CoreMark score.

A supports LR/SC.W and RV64 .D plus AMO ADD/SWAP/XOR/OR/AND/MIN/MAX/MINU/MAXU in W/D.
The atomic unit is **after VA/PMP, before the sole D-cache owner**. It retains ownership across
read, registered modify and true write acknowledgement. SC success and AMO results wait for
the real write response; errors remain precise. Failed SC issues no write. AMO needs read and
write permission. Natural alignment and RAM-only atomic PMA are checked; MMIO atomics fault.
All A instructions drain older instructions and stop younger issue, giving strong aq/rl ordering;
FENCE drains acknowledged memory owners. Registered modify avoids a cache-return -> arithmetic
-> write chain in one cycle, without adding an architectural stage.

Reservations are physical address+size, survive cache eviction and permit virtual aliases.
SC attempts, overlapping stores/AMOs, reset, trap/xRET and permission/translation context changes
invalidate them; an EX prediction repair alone does not. Invalidation racing LR cannot resurrect it.
The contract is **single hart, exclusive runtime writer**: IF/PTW are read-only; boot JTAG is
closed before guest execution; this profile has no live DMA/GMAC. A reserved invalidation input
does not establish atomicity against concurrent external writers. Future DMA/multicore requires
a fabric atomic/coherence ownership contract, not just this local read-modify-write FSM.

### Short GSIM and throughput

Nine configuration checks pass. Exhaustive C: 65,536 encodings at each XLEN, with 28,823 RV32
and 38,551 RV64 legal cases. Parcel tests: 1,505 cases at each XLEN. Atomics: 1,347 RV32 and
1,420 RV64 cases, including sign/unsigned W/D, upper word lane, reservation lifecycle, real
ack/error and randomized backpressure. Deliberately wrong expansion/parcel/AMO/completion/handoff
oracles are rejected. GSIM stays pinned; ASan/UBSan are enabled.

Actual C/A CPU profiles finish in 101,835 / 102,054 cycles for 32-bit partial-page-fault /
16-bit page-end-retire scenarios, each with eight precise traps. Includes aliased LR/SC, W sign
extension, all D AMOs, aq/rl/FENCE and denied MMIO. Existing M/S/U/PMP/Sv39/Svade/PLIC-S tests
pass with 19 traps. C/A-OFF full BootROM baseline: 74,298 cycles, 3,081 DDR + 22,402 ROM instructions,
34 AXI reads / 142 writes. Disabled C aligner/decompressor, atomic and MMU modules disappear.
RV32 is module-tested; integrated SoC tests in this batch use RV64.

Same protected RV64 hardware, 2+2KiB caches, four-entry I/D TLBs, same uncompressed streaming
binary and bounded random AXI law; host selects S-mode Bare vs Sv39. All bytes/checksums pass:

| Path | READ cycles | WRITE cycles | COPY payload cycles |
| --- | ---: | ---: | ---: |
| Bare | 13,838 | 21,279 | 30,912 |
| Sv39 | 13,894 | 21,329 | 30,763 |

Earlier COPY was 30,879/30,831: +0.11%/-0.22%, not material improvement/regression.
Between batches BTB also changes 64->128, so only within-batch Bare/Sv39 is strictly paired.
At nominal100MHz, COPY is about25.27/25.40MiB/s, not DDR peak, FPGA or formal CoreMark.
D-cache stays precise write-through/no-write-allocate, not writeback.

### Untouched OpenSBI v1.9 -> actual S-mode

Stock source: `/home/openion/Valence/simulator/build/opensbi-v1.9`, clean revision
`cbf9f6734dd85a982c63e3cb5db7ffe09da839ca`; full generic default, independent `O=`, no patches.
Build uses RV64IMAC/Zicsr/Zifencei, LP64 and Linux-gnu linker for required PIE.
Manifest: `build/gsim/i1-opensbi-firmware-20261014-r5/manifest.json`.

| Address | Image |
| --- | --- |
| 0x00010000 | Same 4KiB synchronous BootROM |
| 0x80200000 | M-mode shim supplying hart0/DTB |
| 0x80280000 | Stock fw_jump, aligned to its 0x40000 RX/RW split |
| 0x80400000 | Small S-mode diagnostic, not Linux |
| 0x80500000 | I1 DTB: PLIC M/S, CLINT, UART, Sv39/Svade, 2GiB RAM |

Full profile uses **8 writable PMP entries**; four are insufficient for stock domain isolation.
This is a selected parameter, not a global default change. PLIC's two-context ~2MiB extent is
rounded to one4MiB NAPOT region in DT; no PLIC storage expansion or64MiB reservation.
UART TX is actually decoded at100MHz/460800; no host fake SBI or printf console.
S-mode receives a0=0/a1=0x80500000, confirms SBI v3 BASE, probes TIME, runs LR/SC/AMO under
OpenSBI PMP, receives one actual SBI_TIME supervisor timer IRQ and prints via SBI_DBCN.
Result: **22,628,000 cycles / 6,005,722 retired / 35 S ECALLs / 1 S timer IRQ / 72 MRET /
3,919 S-mode instructions / 2,749 UART bytes** (~0.226s guest CPU time at nominal100MHz).
Wrong handoff expectation fails on the same image. No Linux/all-SBI-extension/multi-hart claim.
Sv39 is covered separately; OpenSBI's handoff starts satp Bare.

### Complete synthesis and the correct frequency targets

Vivado2025.1, `xczu15eg-ffvb1156-2-i`, top `FiveStageSoc`.
Valid physical package:
`E:\\VM\\Share\\Valence-rtl\\orbital-i1-rv64imac-msu-20261014-r3`.
Source/RTL/GSIM hashes and small reports are archived at
`build/fpga/five-stage-ca-physical-20261014-r2/`; DCP stays in the Windows package.

| Metric | Complete SoC synthesis |
| --- | ---: |
| CLB LUTs | 22,119 /341,280 (6.48%) |
| FFs | 8,524 /682,560 (1.25%) |
| LUTRAM, included above | 756 |
| BRAM36 / BRAM18 / URAM | 6 /0 /0 |
| DSP48E2 | 16 |
| Reference100MHz setup WNS /TNS | +2.760ns /0 |
| Hold WHS /THS | -0.075ns /-0.302ns |
| Hold failing endpoints | 11 |

Two BRAM36 hold RF banks, two I/D payloads and two the initialized dual-read BootROM.
BTB and cache tags use distributed RAM. Physical ROM INIT is nonzero; hex and raw/stamped
leaf attributes are hash-bound. No payload reset loop is added. CSR hierarchy reports9,883LUT;
hierarchical/shared counts are not additive feature costs and need a separate area review.

One invalid attempt was stopped because CIRCT readmemh was excluded by SYNTHESIS; a following
preflight failed before synth_design because read_verilog -define requires compile-unit mode.
These packages are marked invalid. The one completed valid synthesis uses
`synth_design -verilog_define ENABLE_INITIAL_MEM_`; RANDOMIZE_MEM_INIT/REG_INIT are absent.
Readmemh success, real BRAM mapping and nonzero INIT are checked; an empty ROM is not accepted.

**The original200MHz acceptance target was not lowered.**100MHz was incorrectly selected
as this run's reference constraint; positive setup there does not satisfy200MHz.
Same-DCP reanalysis produces200MHz(5ns) and300MHz(3.333ns) reports without another synthesis.
These are timing estimates on nominal100MHz peripheral/timebase hardware, not newly configured
200/300MHz firmware or board clocking. UART/timer/DT settings must match actual clocks later.
Hold is negative even at100MHz. No clock/unconstrained-endpoint/loop checks are missing in this
OOC scope, but zero I/O placeholder budgets do not qualify a board or CDC/MIG/clock IP.

Same-checkpoint target reports are now complete:

| STA target | Period | Setup WNS | Setup failing endpoints | Hold WHS |
| --- | ---: | ---: | ---: | ---: |
| 200MHz | 5.000ns | -2.240ns | 2,608 | -0.075ns |
| 300MHz | 3.333ns | -3.907ns | 6,595 | -0.075ns |

Both are unqualified; both have11 hold violations. This is not another synthesis or physical
optimization. Windows reports:
`E:\\VM\\Share\\Valence-rtl\\orbital-i1-target-200-300-20261014-r1\\reports\\cpu200` / `cpu300`.
Canonical WSL receipt/reports:
`build/fpga/five-stage-ca-target-200-300-20261014-r1/receipt.json`.
The OOC clock has no real HD.CLK_SRC/placed clock buffer; actual board clock-tree timing remains unqualified.

Worst setup: `core/dcache/savedCacheable_reg -> core/icache/state_reg[0]/CE`,
7.136ns, logic2.063ns +estimated net5.073ns, 34levels /17CARRY8.
The cross-cache memory-route/admission chain, CSR/PMP arithmetic and RF/cache boundaries are
next optimization priorities. This batch does not re-run opt/place/route or generate bit.

### Implemented selectable pipeline batch (2026-10-14)

Latest instruction permits more stages: low resources, high frequency and **frequency x IPC**
take precedence over a fixed five-stage count. Preserve this verified five-stage C/A baseline.
Actual profiles are now implemented and selectable, not dummy delay registers:

| Option | Actual architectural stages | Primary boundary |
| --- | --- | --- |
| `--pipeline=compact5` (default) | IF ID EX MEM WB | Preserve five-stage latency and existing software contracts |
| `--pipeline=balanced7` | IF ID EX ADDR MEM CMP WB | Registered address before alignment/store lanes; registered raw return before load/fault completion |
| `--pipeline=fpga8` | IF ID RF EX ADDR MEM CMP WB | Also capture synchronous RAM operands in a real RF stage; held operands snoop WB |

All are single-issue, strictly in-order, with no ROB/rename/issue queue. Profile choice is
independent of XLEN, M/C/A, S/U/MMU/PMP, cache/predictor capacity and multiplier/RF style.
Unknown depths are rejected. Payload registers are not reset; ownership valid bits are reset.
Nearest-producer bypass includes ADDR/MEM/CMP/WB, with loads/atomics forwarded only from
registered WB to avoid raw load-extension -> EX carry paths. RR/ADDR/MEM/CMP are included
in CSR drains, interrupt boundaries and precise recovery. An older CMP fault prevents
younger external memory effects before WB; branch repair does not discard its own ADDR owner.

The same batch removes the 65-bit end-address addition from DDR/ROM/atomic range admission.
Naturally aligned transfers and aligned windows prove the end bound without that addition;
malformed alignment is denied without MMIO side effects. DDR still spans 2GiB through
0x100200000. An independent 128-bit end-arithmetic oracle tests 1,416 requests in each route
mode, including addresses above4GiB, exact ends, denied beat counts and backpressure.
PMP address writes now share one trailing-one prefix/range datapath; per-entry registered
NAPOT/NA4 bounds are selected by config mode. TOR predecessor locks and atomic config-byte
updates remain covered by 12,000 independent PMP cases. No LUT/FF reduction is claimed yet.

Canonical receipt: `build/gsim/inorder-pipeline-20261014-r3/receipt.json`,
`PASS_PARAMETERIZED_5_7_8_STAGE_SHORT_ONLY`, 54 recorded positive/negative checks.
Six unchanged unit qualifications and exact model objects were reused only after fresh
CHIRRTL/tool/artifact/dependency identity checks; changed CPU drivers were rerun.
The earlier failed receipts remain: r1 exposed a C++ reserved-word model name, fixed in
the RTL source; r2 exposed a hardcoded five-stage total-cycle gate, replaced with stricter
steady-state checks, not relaxed data or exception expectations.

RV32/RV64 native CPU tests pass all three profiles, including register/byte/next-PC oracles,
same-rd load-over-ALU precedence, held-RF WB snooping, late faults before younger stores,
interrupt drains and real store acknowledgements. Each bypass-enabled profile retires
800 independent ALUs and 800 dependent ALUs consecutively: first-to-last span799cycles,
steady state1instruction/cycle. Five/seven/eight total cycles including serial EBREAK:
810/814/816. The eight-stage no-M/no-bypass profile also executes correctly; its dependent
ALU span3196cycles is an intentional option cost, not 1IPC. C/A are default OFF and native
tests use them OFF; protected ROM SoC tests explicitly enable them.

Integrated RV64IMAC/Sv39/PMP8 ROM SoC passes both compressed-page cases (9traps, including
unsupported long-prefix mtval=0), previous privilege regression (19traps), and S-mode streams:

| Profile | Bare READ / WRITE / COPY cycles | Sv39 READ / WRITE / COPY cycles |
| --- | ---: | ---: |
| compact5 | 13,838 /21,279 /30,912 | 13,894 /21,329 /30,763 |
| balanced7 | 15,991 /21,346 /32,906 | 15,936 /21,337 /33,024 |
| fpga8 | 15,923 /21,346 /32,905 | 15,950 /21,331 /32,954 |

All data/checksums pass. compact5 matches the saved C/A baseline exactly in these ROIs.
Full untouched stock OpenSBI v1.9 boots on fpga8 and hands off to the same S diagnostic:
22,984,000cycles /5,692,024retired /35S ECALLs /1S timer IRQ /72MRET /3,358S instructions /
2,749UARTbytes. Its wrong-handoff negative control fails correctly. Different boot-poll
instruction counts are expected between profiles; they are not compared as equal workloads.
Linux is NOT boot-qualified.

### Matched short O3: deeper is not automatically faster

Same pinned standard CoreMark source, one unchanged RV64IM/Zicsr/Zifencei LP64 `-O3` binary,
standard2000bytes, one iteration, 2+2KiB direct-mapped caches /64B lines /BTB128.
All six runs retire367,146instructions, ROI345,520instructions, same trace
`4509c0a4825b10bb` and CRCfinal59156; official other CRCs, every register and final RAM match
the independent ISA oracle. This is NOT a >=10second formal score or measured board frequency.
Shared I/D service has one capture/arbitration cycle plus1/12 response-service cycles,
one subsequent beat/cycle; at most one owner/cache, real store ACKs.

| Profile | Low-latency ROI cycles / IPC | 12-cycle-service ROI cycles / IPC | Break-even frequency increase |
| --- | ---: | ---: | ---: |
| compact5 | 505,784 /0.6831 | 682,415 /0.5063 | Reference |
| balanced7 | 567,390 /0.6090 | 743,746 /0.4646 | >12.18% / >8.99% |
| fpga8 | 572,542 /0.6035 | 748,688 /0.4615 | >13.20% / >9.71% |

At equal frequency the deeper profiles are slower. A higher-frequency profile is a net
performance improvement only when its actual qualified frequency ratio exceeds its ROI-cycle
ratio; compare frequency x IPC, not pipeline length. Store/request totals stay unchanged;
fpga8 adds nine speculative instruction refills (19823totalrequests vs19814), not more useful work.
Load-use costs remain the next measured throughput priority. Do not bypass precision or move
raw response extraction into the EX carry chain merely to recover cycles.

### Physical gate and next batch

The proven prior compact5 source is preserved at `build/checkpoints/i1-ca-five-stage-20261014-r1/`.
No new synthesis/place/route/bit is run in this pipeline batch. Earlier22,119LUT/8,524FF/6BRAM/
16DSP numbers and200/300MHz failures belong to the previous five-stage source, NOT these profiles.
Current LUT/FF/BRAM/DSP, routed hold/setup and300MHz remain unqualified.

Only fpga8 was freshly exported for the next combined physical check:
`build/fpga/orbital-i1-fpga8-300-target-20261014-r1/manifest.json`.
Source/GSIM hashes match; RF/cache RAM and initialized BootROM array attributes are bound,
simulation ROM write ports are absent. The STA target is explicitly300MHz(3.333333333ns).
Export is not synthesis and not a300MHz clock IP: UART/timer/DT still use the100MHz reference
timebase until board integration changes them together. The exporter now requires explicit
pipeline and target for batch receipts, rejects RUNNING/FAIL, and the collector reads the
actual profile/target rather than hardcoding five stages/100MHz.

Reproduce with fresh evidence names:

~~~sh
cd /home/openion/Valence-inorder
GSIM_CXX=clang++-19 python3 -B simulator/gsim/inorder/pipeline_acceptance.py --tag FRESH_PIPELINE \
  --firmware build/gsim/i1-opensbi-firmware-20261014-r5/manifest.json
python3 -B fpga/inorder/export_soc.py \
  --receipt build/gsim/inorder-pipeline-FRESH_PIPELINE/receipt.json \
  --pipeline fpga8 --target-mhz 300 --output build/fpga/FRESH_FPGA8_RTL
~~~

The following original direction remains the governing qualification contract:
Share ISA/MMIO/TileLink/software contracts, but explicitly adjust forwarding, stall propagation,
precise traps, atomics, store-side effects, CSR ordering and branch recovery per actual register boundary.
Use synchronous RAM and optional output registers without disguising extra stages or sacrificing
hot-cache throughput. Report per-profile CoreMark/IPC, LUT/FF/BRAM/DSP and routed timing.
CPU300MHz is a design goal, not a guarantee; DDR/peripheral clocks need not run at CPU frequency.
No arbitrary numerical pipeline-depth selector should silently generate unverified hardware.

Reproduce with fresh evidence names:

~~~sh
cd /home/openion/Valence-inorder
GSIM_CXX=clang++-19 python3 -B simulator/gsim/inorder/ca_units.py --tag FRESH_UNITS
python3 -B simulator/gsim/inorder/build_opensbi_i1.py --output build/gsim/FRESH_FIRMWARE
GSIM_CXX=clang++-19 python3 -B simulator/gsim/inorder/ca_acceptance.py --tag FRESH_CA \
  --units build/gsim/five-stage-ca-units-FRESH_UNITS/receipt.json \
  --firmware build/gsim/FRESH_FIRMWARE/manifest.json
python3 -B fpga/inorder/export_soc.py \
  --receipt build/gsim/five-stage-ca-soc-FRESH_CA/receipt.json --output build/fpga/FRESH_RTL
~~~

Explicit profile: `--c --a --sv39 --pmp=8 --tlb=4 --icache=2048 --dcache=2048 --predictor=128
--dsp-tiled --early-memory-issue --overlap-write-lookup`; ROM/UART/timer/PLIC enabled,
runtime DMA/GMAC/JTAG loader disabled in this matched proof. At this historical pipeline
checkpoint F/D was still pending; the following batch supersedes that item. Linux boot,
DMA coherence and board qualification remain next gates. No automatic commit/push.

## Parameterized RV64 F/D and USER2 integration (2026-10-14)

Canonical short receipt: `build/gsim/i1-fd-jtag-20261014-r2/receipt.json`,
`PASS_I1_PARAMETERIZED_FD_JTAG_SHORT_ONLY`. The first failed receipt is preserved; it
exposed a C++ host-adapter method mismatch, not a relaxed hardware/oracle requirement.
All checks in r2 ran again; exact unchanged numerical models were reused only after
fresh FIRRTL, tool and artifact identity checks.

### Compile-time ISA selection remains mandatory

| Parameter / CLI | Default | Contract |
| --- | --- | --- |
| XLEN | 64 | RV32 or RV64 integer profiles |
| `withM` / `--no-m` | ON | Can remove integer multiplication/division independently |
| `withC` / `--c` | OFF | Compressed integer instructions; compressed D memory operations require D |
| `withA` / `--a` | OFF | Single-hart LR/SC and AMO with real acknowledged memory ownership |
| `withF` / `--f` | OFF | Single precision, FCSR, FS/SD, floating RF and memory operations |
| `withD` / `--d` | OFF | Double precision; requires F, does not silently enable it |
| `--soc-jtag` / explicit USER2 | OFF | Independent boot-only download, not an ISA extension or Debug Module |

M, A, C, F/D and the optional S/U/MMU/PMP features are not an inseparable RV64GC profile.
`misa` and the ISA configuration string advertise only selected features. F/D OFF removes
the execution units, floating payload/state and RF banks at elaboration, not just software
access. Real RV32/RV64 default-off CPU tests still pass the independent integer/register/
memory oracles and steady 800-ALU span799cycles. D without F is rejected. This first F/D
integration supports RV64 only; requesting RV32 F/D is explicitly rejected, not advertised
as implemented. The CPU's pipeline selector is independent of ISA selection.

### Numerical implementation and precise state

Berkeley HardFloat remains pinned at `c1105e6ac6a0dd90fc80893efc4830ab609005d3`;
its 18 source hashes and licenses are unchanged. I1 copies the already-adapted numerical
wrappers with provenance into its own namespace; no OoO decoder/ROB/rename/state control
is imported. Shared per-format rounders and shared multiply/FMA are selected; division
and square root are iterative. Independent Berkeley SoftFloat is pinned at
`a0c6494cdc11865811dec815d5c0049fba9d82a8`, with fixed known-answer anchors.

Implemented numerical families: add/subtract, multiply, divide, square root, fused
multiply-add variants, min/max, sign injection, comparisons, classification, raw moves,
32/64-bit signed/unsigned integer conversion and S/D format conversion when D is selected.
All five architectural rounding modes, flags, subnormal/NaN/boxing behavior and illegal
rounding encodings are checked. F-only and F+D each pass 27,840 reference vectors plus
39 illegal cases, real held-response/backpressure/flush and independent negative controls.
8,192 compressed floating-memory encodings match the independent enabled/disabled oracle.

Three synchronous 1R1W floating RAM replicas provide three source reads and one common
WB write; f0 is a real register, not x0. Payloads have no reset loop; a 32-bit validity
bitmap, explicit read/write collision forwarding and response holding make reset behavior
defined. FLW/FLD/FSW/FSD use the existing LSU, alignment, PMP, Sv39, cache and acknowledged
TileLink path. Only successful WB writes the floating RF or accrues flags; faults leave
architectural state untouched. FS=Off rejects FP/FP-CSR access, successful FP retirement
conservatively marks Dirty, and SD reflects FS. Static/dynamic reserved rounding is illegal
before numerical issue. The initial FP path drains older instructions and serializes its
owner through retirement: this is a precise functional baseline, not a one-FP-instruction/
cycle claim. Integer throughput is not deliberately serialized by enabling F/D.

Actual CPU tests execute 2,320 independent numerical-result/flag cases on each of compact5,
balanced7 and fpga8; F-only executes 1,120 applicable cases and rejects D. Each context
program independently saves, overwrites and restores all 32 FPRs including f0. Precise
FS/CSR/rounding traps, misalignment, real AXI read/write failures and non-identity Sv39
floating access/page faults pass (9 traps including final EBREAK for F+D; 10 for F-only).
The existing actual-CPU 19-trap scalar privilege test passes unchanged. On fpga8, Bare
READ/WRITE/COPY remain 15,923/21,346/32,905 cycles and Sv39 remains
15,950/21,331/32,954 cycles, exactly matching the preceding integer-enabled profile.
This does not requalify full Linux or Linux floating-point context switching.

### Logical JTAG and physical export boundary

F+D fpga8 boots via the existing CPU-domain DMI downloader, verifies the exact image bytes,
executes the FP context test and rejects post-claim writes. A wrong-CRC image is rejected;
a correct retry executes the same precise-state program. USER2 shell elaboration passes.
These logical GSIM tests do not exercise the physical TAP or asynchronous BSCAN edges.
Architectural Debug Mode/DM, halt/resume, single-step and OpenOCD target support remain
reserved, not implemented.

The original combined synthesis export is `build/fpga/orbital-i1-fd-jtag-20261014-r5/manifest.json`.
The completed report package is `E:\VM\Share\Valence-rtl\orbital-i1-fd-jtag-20261014-r11`,
with the corresponding WSL export `build/fpga/orbital-i1-fd-jtag-20261014-r11/manifest.json`.
The shell's CHIRRTL is byte-identical to its qualified fixture. Pinned firtool 1.135.0
keeps packed SV arrays needed by the shared arbiter's assertion. CIRCT deduplicates the
GPR/FPR 32x64 module definition, but the two GPR plus three FPR physical instances remain.
Array attributes are the only RAM binding edits. Source-controlled BSCAN resource bytes
and initialized BootROM contents are retained. Export attempts r1-r4 are failed formatting/
resource-identity evidence; none ran synthesis.

One combined synthesis checked the full shell at the explicitly requested 300MHz target,
GPR/FPR/cache BRAM mapping, BootROM INIT and exact USER2 ownership/related-event/held-bus
constraints. No blanket asynchronous clock groups or multicycle exemptions are added.
The scope excludes MIG, board clock IP and place/route. UART/timer nominal timebase is
still 100MHz until actual board clock integration changes it consistently.

### Completed synthesis and precise timing limitations

Canonical physical receipt: `build/fpga/orbital-i1-fd-jtag-synth-20261014-r1/receipt.json`,
`SYNTHESIS_SETUP_FAILS_300MHZ_ESTIMATE`. Exactly one `synth_design` ran (r5,
3min42s elapsed). Subsequent r6-r11 packages contain the exact same SV/XDC/ROM/source
and resume that checkpoint for report/constraint auditing only; they are not new hardware
optimizations or additional synthesis runs. Complete initial log and manifest provenance,
checkpoint hash and per-file identity are rechecked by export and collection.

The original generic BSCAN mock did not model Vivado 2025.1 object-handle conversion,
empty cell inversion parameters, C-pin timing startpoints or a fabric clock exposed as
an OOC port. The independent `fpga/inorder/bscan_timing.tcl` now re-resolves exact
objects, checks the real C-pin IS_INVERTED, requires the precise release C startpoint
AND Q in its full reset cone, and accepts ONLY `io_clockIn` for the fabric-clock
port boundary. Data/reset/constant drivers still require one actual primitive output.
All 28 selector/topology/negative cases pass; only12 checked synchronizer CLR false-path
pins, four8ns datapath limits and two8ns held-bus skew constraints are emitted. The real
netlist passes all these structural gates. No old OoO constraint/source was edited.
This is still not a physical TAP or routed CDC/protocol signoff.

Full I1 F+D fpga8 SoC plus shared USER2 resources: **37,128 LUT /14,349 FF /9 BRAM36 /
27 DSP**, 0 BRAM18, 0 URAM. The two GPR and three FPR replicas each use BRAM36;
I/D cache data use one each; initialized dual-read BootROM uses two with nonzero INIT.
The numerical FPU hierarchy reports8,764LUT /2,580FF /11DSP. Cross-boundary synthesis
can move surrounding combinational logic into RAM-parent hierarchies, so an FPR hierarchy's
LUT count is not the storage cost alone. This is not a matched FPU-only resource delta
against the earlier compact5 no-FPU snapshot.

| Synthesized path / endpoint partition | Setup slack at 300MHz | Data-path estimate |
| --- | ---: | ---: |
| FPR BRAM output -> single-precision FMA input alignment | -4.731ns | 7.998ns /26levels |
| Non-FP endpoint: I-cache saved address -> I-cache admission/state CE | -4.227ns | 7.456ns /33levels /13CARRY8 |
| I-cache saved address -> D-cache admission/state CE | -3.962ns | 7.191ns /32levels /13CARRY8 |
| PLIC priority -> instruction translation recovery/reset | -3.170ns | 6.386ns /19levels |
| PLIC priority -> CSR trap-state enable | -1.259ns | 4.488ns /14levels |
| PLIC priority -> data translation state | -1.112ns | 4.427ns /14levels |

The non-FP endpoint query is not an emulation of a F/D-OFF synthesis; the rest of the
F/D-enabled hardware remains present. These partition reports identify additional long
chains, not just FPU input delay. They justify a coherent next batch: register the FP
operand/boxing/recode boundary and divide FMA preparation; stage range/request admission
between caches and the fabric; and cut interrupt/drain/translation recovery fanout while
preserving precise traps and acknowledged ownership. No next-batch source edit is claimed.

Overall hold/removal WHS is **-3.976ns**,338failing endpoints; the worst is BSCANE2 RESET
to `hard_reset_reg/CLR`, not a FPU path. CPU-only hold WHS is **-0.076ns** with10failing
endpoints. BSCAN held-bus skew's worst estimated slack is+7.710ns, but functional recovery/
removal and several related-clock hold paths still fail. Thus neither CPU300MHz nor
JTAG-inclusive full timing is qualified. Do not waive functional reset pins to declare PASS.

Reports: `timing_synth.rpt`, `setup_cpu_synth.rpt`, `setup_non_fp_endpoint_synth.rpt`,
four per-partition setup reports, `hold_synth.rpt`, `bscan_bus_skew_synth.rpt`,
`clock_interaction.rpt`, `check_timing.rpt`, `ram_dsp_mapping.txt`. All are archived
under the canonical receipt's `reports/` directory in WSL, and remain in the r11 shared package.
Unconstrained internal endpoints and combinational loops are zero. Vivado rounds the requested
3.333333333ns to3.333ns; actual reported300.030MHz is a1ps precision effect, not a changed target.
The external CPU buffer HD.CLK_SRC remains unset in this deliberately unplaced OOC shell:
route delays are estimates, not routed wires, and clock skew/board frequency are not signed off.
No opt/place/route, bit generation, Linux boot or board test was run.

Reproduce the batch with fresh names:

~~~sh
cd /home/openion/Valence-inorder
GSIM_CXX=clang++-19 python3 -B simulator/gsim/inorder/fd_jtag_acceptance.py --tag FRESH_FD
python3 -B fpga/inorder/export_soc.py \
  --receipt build/gsim/i1-fd-jtag-FRESH_FD/receipt.json \
  --pipeline fpga8 --target-mhz 300 --output build/fpga/FRESH_FD_RTL
~~~

### 2026-10-14: optional fpga8 timing/performance cuts, batch 1

All changes remain in the independent `feat/orbital-i1-five-stage` worktree.
The original OoO core, original transport resources and vendor HardFloat/SoftFloat
sources are untouched. `--timing-cuts` defaults OFF and requires fpga8; it
does not force M/A/C/F/D ON. F and D remain independent compile-time options
(D requires F). No enlarged cache, transaction slot or write credit was introduced.

Batch: capture floating operands at the existing RF->EX boundary; recode/raw,
17-bit DSP tile products, carry-save rows, exponent sum, alignment distance and
FMA alignment/product cuts; one-owner exact floating arithmetic; registered TL
route admission reusing the existing saved packet; natural-alignment prefix
hazards instead of 65-bit interval-end addition; registered interrupt eligibility
and matching cause, invalidated on architectural CSR/trap/xRET changes; registered
CMP load extraction/forwarding; opposite-edge functional USER2/CDC reset release.
Compact5/balanced7 and the default timing-cut-OFF implementation remain available.

GSIM receipt: `build/gsim/i1-fd-jtag-timing-20261014-r1/receipt.json`,
`PASS_I1_PARAMETERIZED_FD_JTAG_TIMING_CUTS_SHORT_ONLY`. Both F and F+D
pass 27,840 independent SoftFloat vectors plus 39 illegal cases. Exact numerical
latency/II now mul=7/8 and FMA=8/9 in the cut profile; add=3/4, misc=2/3 and
operand-dependent div/sqrt cycles are unchanged. Flush tests cover all added stages
and held responses. Thus the extra arithmetic stages are NOT a floating IPC gain.
Actual fpga8 CPU: 2,320 F/D corpus cases; all 32 FPR save/restore, flags/FS/FCSR,
nonidentity Sv39 FP load/store and precise errors; F-only 1,120 cases with D illegal.
RV32/RV64 no-F CPU integer, precise older-fault/store suppression and 800 ALU
steady streams also pass. USER2 logical download plus bad-CRC/retry pass.

Registered route: 1,416 cases per register-enabled/disabled mode, 4,089 response
beats each, above-4GiB boundaries, alignment/lane/denial, downstream backpressure,
live-host changes after admission and independent wrong-route negatives pass.
Two-slot/one-write-credit AXI mixed tests pass RAW/WAR/WAW, inverse read arrival,
AW/W independence, errors, oversized requests and reset recovery; independent
data-corruption negative is rejected. The CPU still waits for real write completion.

Same immutable RV64IM O3 binary and independent instruction/register/memory oracle:

| fpga8 CoreMark short ROI | Previous cycles | Cut cycles | Time reduction |
| --- | ---: | ---: | ---: |
| Memory first-response latency 1 | 572542 | 536287 | 6.33% |
| Memory first-response latency 12 | 748688 | 712433 | 4.84% |

All have the same 345,520 ROI instructions, 367,146 retired instructions,
trace hash 4509c0a4825b10bb and CRCfinal 59156. These are short cycle comparisons,
NOT new formal >=10-second CoreMark scores and NOT a board frequency measurement.
At the SoC fabric boundary registration has a mixed cost: Bare READ 15923->15023,
WRITE 21346->22155, COPY 32905->33148 cycles; Sv39 READ 15950->15052,
WRITE 21331->22187, COPY 32954->33115. READ improves about 6%, WRITE is about
4% slower, COPY is within 0.8%. Do not describe every workload as accelerated.

Installed Vivado 2025.1 xsim receipt in
`E:\VM\Share\Valence-rtl\orbital-i1-cdc-20261014-r2\receipt.json`:
`PASS_I1_HALF_CYCLE_CDC_XSIM_ONLY`. Mailbox (101 requests), USER pin-event
and qualification suites retain unchanged stimulus, payload/reset/backpressure
oracles and watchdogs; only DUT module names are adapted. Production SV bytes are
unchanged by the runner. This is not a board TAP or routed CDC timing signoff.
The new strict constraint profile checks five 3-FF release banks (15 synchronizer
CLR exceptions only) and opposite-edge functional reset cones; functional reset
paths remain timed. No blanket asynchronous clock-group or multicycle waiver.

Fresh combined 300MHz OOC synthesis candidate:
`E:\VM\Share\Valence-rtl\orbital-i1-fd-timing-20261014-r1`.
The constraint is not a Clock Wizard configuration: UART/timer remain nominal
100MHz in this test candidate. A board bit additionally requires matched real
clock/timebase configuration, existing MIG/AXI CDC integration and complete
place/route setup, hold, bus-skew and DRC signoff. No bit is qualified by these
functional checks alone.

### 2026-10-14: report-driven batch 2 and bandwidth qualification

Batch 2 jointly changes six chains: parallel one-hot EX operand forwarding with
the identical youngest-eligible priority; parallel target/sequential prediction
comparisons before boolean selection (no extra branch stage); EX-predecoded
context-barrier/translation-invalidation bits carried through existing completion
owners to WB; miscellaneous FP input capture plus signed-integer magnitude before
normalization; registered cache RAM-write scheduling; positive-TCK USER2 event
payload/toggle before negative-TCK functional consumers. No new MSHR/AXI slot/write
credit or cache capacity. The cache write cut is ONE beat of scheduling, not an
additional accepted transaction. It still drains one refill beat/cycle and inhibits
last-beat hit replacement until the scheduled RAM write has committed, avoiding
undefined same-address read/write without assuming a vendor BRAM write-first mode.

`build/gsim/i1-fd-jtag-timing-20261014-r2/receipt.json` passes the same
independent F/F+D vectors, actual-CPU FP/context/fault/Sv39, privilege and integer
oracles, route/AXI negatives and JTAG CRC/retry tests. Added cache tests cover
RV32/RV64, IF hit replacement and no-cache removal, plus partial stores, real late
errors, failed/stale refills, MMIO, backpressure and common reset. Cut-profile misc
latency/II is now 3/4; integer-to-FP is 4/5. Mul/FMA/add/div/sqrt from batch 1 unchanged.
`build/gsim/i1-timing-opensbi-20261014-r2/receipt.json`: stock OpenSBI->S
PASS, 23,223,000 cycles, 35 SBI S ECALLs, one S timer IRQ, 72 MRETs, UART banners
and an independent wrong-handoff negative. This is NOT a Linux/context-switch test.
New USER2 payload-stage pin-event/CDC xsim receipt:
`E:\VM\Share\Valence-rtl\orbital-i1-cdc-20261014-r5\receipt.json`, three
unchanged protocol/reset oracles PASS. An additional installed UNISIM suite is
NOT qualified: both the old unmodified transport control and the earlier I1
candidate stop at the SAME selection-phase assertion at 26342ns. Those failures
are retained, not changed into a PASS or used to waive physical clock arcs.

CoreMark same-binary ROI is 536927/713064 cycles at modeled latency 1/12,
0.12%/0.09% slower than batch 1 but 6.22%/4.76% faster than the original fpga8
572542/748688 baseline. Same independent retired/trace/official-CRC gates.

Combined F+D/USER2 300MHz synthesis is source-bound in
`build/fpga/i1-fd-timing-synth-20261014-r2/receipt.json` and shared package
`E:\VM\Share\Valence-rtl\orbital-i1-fd-timing-20261014-r2`. Full native log
is retained in batch 2. Batch 1's original launch disabled the native log despite
also naming it, so its collector explicitly labels the preserved real completion/
constraint-gate stdout as PARTIAL, not a complete warning log.

| Combined synthesized result | Before cuts | Batch 1 | Batch 2 |
| --- | ---: | ---: | ---: |
| 300MHz setup WNS | -4.731ns | -3.109ns | -2.810ns |
| Setup failing endpoints | 12558 | 9802 | 7555 |
| Hold/removal WHS | -3.976ns | -0.388ns | -0.348ns |
| Hold failing endpoints | 338 | 267 | 134 |
| LUT | 37128 | 37402 | 36907 |
| FF | 14349 | 15688 | 16285 |
| BRAM36 / DSP | 9 /27 | 9 /28 | 9 /28 |

Batch 2 CSR partition improves to +0.316ns; D translation -0.559ns, D-cache
-0.448ns. The new limiting combinational feedback is I-cache tag/hit -> compressed
parcel decision -> fast IF translation/request admission -> I-cache state,
6.125ns/23levels, of which 4.568ns is UNPLACED route estimate. IF translator endpoint
-2.368ns. The worst remaining hold is BSCANE2 INTERNAL_TCK -> primitive TDO,
NOT the now-cut UPDATE payload -> negative-TCK functional register path.
An internal OOC opt/place/route DIAGNOSTIC reuses the same constrained DCP without
another synthesis. Its explicit hypothetical BUFGCE site is not a configured board
Clock Wizard, MIG integration or an actual board-clock signoff. No bit can be
declared qualified on this basis alone.

Bandwidth receipt: `build/gsim/i1-bandwidth-20261014-r1/receipt.json`,
`PASS_I1_MODELED_BANDWIDTH_NOT_BOARD`. The Windows project's actual
`ddr4_0.xci` is snapshotted and hashed: TimePeriod=1000ps, DDR DQ32,
PHY ratio4:1, AXI64. This means CK1GHz / DDR2000MT/s / UI250MHz, NOT 1000Hz.

| Interface ceiling (before overhead) | Decimal bandwidth |
| --- | ---: |
| DDR wire, 32bits x 2 x 1GHz | 8GB/s |
| MIG AXI, 64bits x 250MHz | 2GB/s |
| CPU AXI at nominal100MHz | 800MB/s |
| CPU AXI if 200MHz achieved | 1.6GB/s |
| CPU AXI if 300MHz achieved | 2.4GB/s; capped by MIG at2GB/s |

Same two-slot bridge, one write credit, 64B lines: 16 saturated READ cases cover
first-R modeled delay0/12/32/64, READY backpressure and above4GiB physical addresses.
Every case checks all 256 transactions/2048 actual R beats/2048 D beats, exact
data/source/length, stable stalls, translated AXI addresses and complete drain;
independent data corruption is rejected. Without imposed backpressure:

| First-R delay (CPU cycles) | Useful bytes/cycle | R channel useful occupancy |
| --- | ---: | ---: |
| 0 | 6.71475 | 83.93% |
| 12 | 4.25780 | 53.22% |
| 32 | 2.55680 | 31.96% |
| 64 | 1.55979 | 19.50% |

These are modeled bridge ceilings, not MIG hardware throughput. At the GSIM
nominal100MHz, actual CPU short8KiB READ/WRITE/COPY payload is Bare
51.50/35.27/23.66MiB/s and Sv39 51.90/35.21/23.59MiB/s. COPY's logical R+W
is twice payload; it is not measured AXI traffic. They do not imply current
FPGA timing supports100/200/300MHz. The much lower CPU result identifies a
remaining blocking LSU/cache/translation/instruction-overhead limit: bridge
slots are shared I/D owners, NOT two independent CPU data MSHRs. Do not explain
the difference as DDR capacity or theoretical wire bandwidth alone.

Final internal OOC route diagnostic:
`build/fpga/i1-fd-routed-diagnostic-20261014-r2/receipt.json`.
All 44995 routable nets are reported fully routed, zero routing errors; one
explicit OOC gap remains. This is NOT the real board clock/MIG/pin assembly.
At the unchanged 3.333ns target, routed internal setup is **-4.453ns**,
13,984 failing endpoints in the overall report. Worst: AXI AR queue dequeue
control -> slot1 burst-payload LUTRAM data input, 7.599ns with only0.601ns logic
and6.998ns physical routing (92.1%). The earlier unplaced WNS improvement must
NOT be advertised as routed300MHz success. Existing DCP is retained; no bit.

Routed register-to-register hold worst is **+0.010ns**. BSCAN TCK/DRCK/UPDATE
intra-clock groups report setup+19.753/+47.225/+47.407ns and
hold+0.022/+0.115/+0.402ns; UPDATE->TCK hold+19.047ns. Held request/response
datapath groups also have positive setup. Global hold -2.087ns is the placeholder
OOC external IRQ port -> first synchronizer D (input delay0 versus a routed
clock arrival), not an internal register path. Raw POR-port removal also needs
real board reset constraints. These distinctions do not waive any paths or
qualify an actual board. Bus-skew and check-timing reports remain part of the archive.

Next report-driven batch should localize AXI R ownership/data/write-enable at
each existing slot and remove the I-cache/C-parcel/fast-translation admission
feedback while retaining hit throughput. Do not add transaction capacity as
a substitute or blindly add another cache-hit cycle. Validate one-beat/cycle
burst flow, precise errors and identical CPU architectural traces before
repeating combined implementation. Matching physical CPU clock, UART/timebase
and real board/MIG integration remain necessary before any eventual bit delivery.

### 2026-10-14: report-driven AXI/IF batch 3 and bandwidth check

Short receipt: `build/gsim/i1-fd-jtag-timing-20261014-r3/receipt.json`.
This optional `--timing-cuts` batch moves the shared payload data mux
selection from R.fire to the registered lane phase, keeps cache hit qualification
on VALID but not on the wide data mux, and adds a registered C-parcel response
boundary with reuse of one previously authorized word. It does not add CPU
data MSHRs or AXI transaction slots. Reuse requires a successful fetchSpan
grant; privilege changes, traps/xRET, PMP/SATP/SFENCE and FENCE.I invalidate it.
An in-flight invalidation poisons publication without withdrawing the old owner.

RV32/64 parcel tests include held replies, cross-page second-half faults,
partial-word grants, same-word reuse, reauthorization errors and invalidation
during fill; independent byte mutation remains rejected. Actual CPU C/A
cross-page/page-end, complete F/D numerical/precise context tests, scalar
privilege, logical JTAG download/CRC retry and default-off checks PASS.
Stock OpenSBI/S handoff also PASS at nominal 100MHz:
`build/gsim/i1-timing-opensbi-20261014-r3/receipt.json`.
No Linux or physical-board qualification is implied.

| Combined 300MHz synthesis estimate | Batch 2 | Batch 3 |
| --- | ---: | ---: |
| Setup WNS | -2.810ns | -2.642ns |
| Setup failing endpoints | 7555 | 6488 |
| IF translation endpoint | -2.368ns | -1.178ns |
| Non-FP endpoint | -2.810ns | -2.084ns |
| LUT / FF | 36907 / 16285 | 37249 / 16502 |
| BRAM36 / DSP | 9 / 28 | 9 / 28 |

Evidence: `build/fpga/i1-fd-timing-synth-20261014-r3/receipt.json`;
shared `E:\VM\Share\Valence-rtl\orbital-i1-fd-timing-20261014-r3`.
The newly exposed worst path is double FADD/FSUB exponent difference ->
alignment -> signed sum -> absolute magnitude -> CLZ -> normalization,
5.957ns/27 levels. Batch 3 is NOT routed300MHz success and generates NO bit.

Same RV64IM O3 binary without C enabled retains ROI 536927/713064 cycles.
A separate C-front-end diagnostic (same IM binary, NO compressed opcodes)
uses 664853/831353 cycles, 23.83%/16.59% more than the no-C configuration:
`build/gsim/i1-fetch-coremark-20261014-r1/receipt.json`.
All retired instructions/registers/final RAM/official CRC/trace match.
This is a CONFIGURATION comparison, not an old-vs-new C comparison or a
formal CoreMark score. Do not claim the registered IF boundary is a performance
win based only on the no-C benchmark; its admission/latency still needs work.

Bandwidth: `build/gsim/i1-bandwidth-20261014-r2/receipt.json`,
source/model/MIG-XCI bound. The 16 bridge read cases and independent corruption
negative pass; bridge bytes/cycle remain exactly the earlier table. CPU
short8KiB results at the model's nominal100MHz:

| Mode | READ | WRITE | COPY payload |
| --- | ---: | ---: | ---: |
| Bare | 51.725MiB/s | 35.285MiB/s | 23.608MiB/s |
| Sv39 | 51.663MiB/s | 35.245MiB/s | 23.647MiB/s |

The actual XCI still derives DDR wire8GB/s and MIG AXI2GB/s ceilings.
300MHz CPU AXI64 would offer2.4GB/s, capped at2GB/s by MIG before all overhead.
These are theoretical/projection values, NOT qualified300MHz throughput.

Next batched source candidate localizes R capture to registered AR-issued
credits (zero-delay RVALID remains legal but its first beat is held one edge)
and splits pinned HardFloat add equations at exponent-distance, alignment,
signed-sum, absolute-magnitude and leading-zero boundaries. Compact FADD
remains unchanged. Timing-cut add becomes latency8/II9 with one owner and no
intermediate rounding; independent SoftFloat/handshake/flush validation must
pass before any physical result or numerical qualification is claimed.

Batch 4 complete short proof:
`build/gsim/i1-fd-jtag-timing-20261014-r7/receipt.json`, PASS.
The 6-edge raw add adapter retains the pinned AddRawFN equations/license;
format rounding remains shared and unchanged. F and F+D each pass 27840
SoftFloat vectors plus39 illegal cases, exact8-edge add latency/II9,
held response, full tokens/flags and all11 flush offsets. Actual CPU corpus,
FP context/nonidentity Sv39 memory faults, C/A boundaries, privilege,
default-off, logical JTAG download/CRC retry and same-binary integer CoreMark
also pass. Integer ROI and the Bare/Sv39 stream cycles match batch3 exactly.

The new AR-issued R capture qualification has an independent same-edge
AR/R offer test for 1/8-beat bursts. RREADY deliberately holds that first
offer for one edge; subsequent beats still take one per cycle. Invalid A
payload/mask noise cannot affect the shared read buffer. Byte mutation and
unowned AXI ID are rejected; mixed RAW/WAR/WAW/error/reset cases remain
covered with only2 slots/1 write credit. Bandwidth receipt
`build/gsim/i1-bandwidth-20261014-r3/receipt.json` reproduces all16
bridge results and CPU cycles exactly, not a measured bandwidth gain.

Failed intermediate receipts are preserved, not relabeled PASS:
r4 had a Chisel Bool-width elaboration constraint, corrected with explicit
UInt constants; r5 hit pinned GSIM readFile's page-aligned EOF mmap bug;
r6 exposed an incomplete-model reuse guard, now requiring the header,
generated model source and compiled objects before reuse.
The SoC FIR was3547136 bytes (=866*4096); GDB stopped with SIGBUS in
unchanged GSIM `src/main.cpp:326`/readFile before parsing. Source hash:
`667fcf7236522dd3828c52923a813af1d1dcfb6b423fad7461665690ef26ae88`.
The runner preserves original CHIRRTL and records a separate parser input
with ONE blank newline plus both hashes in `gsim_input_padding`.
No expression, simulator, vendor arithmetic, stimulus or numerical oracle
is changed by this input-format workaround.

Fresh combined batch4 physical candidate is
`E:\VM\Share\Valence-rtl\orbital-i1-fd-timing-20261014-r4`.
Completed physical receipt:
`build/fpga/i1-fd-timing-synth-20261014-r4/receipt.json`.
Combined300MHz synthesis WNS=-2.473ns, WHS=-0.348ns; 7566 setup failing
endpoints (MORE than batch3's6488 despite a better single worst slack).
LUT37405, FF17035, BRAM36=9, DSP=28. This is still synthesis only, not routed.
The old add exponent/normalization path is no longer worst; common raw
exponent -> shared round/pack -> response now takes5.788ns/19levels,
of which4.592ns is UNPLACED routing estimate. Non-FP endpoint worst is
ADDR-address -> architecturalNextPc, -2.350ns/21levels; IF translator
-1.344ns, DT -0.559ns, D-cache -0.481ns, CSR +0.314ns.
Do not claim this small WNS improvement establishes300MHz or that every
path improved. Next batch must address the shared rounding boundary and
permission/recovery fanout as well as C-front-end performance before another
implementation attempt. No bit has been generated.
Stock OpenSBI/S handoff is also PASS:
`build/gsim/i1-timing-opensbi-20261014-r4/receipt.json`.
The new `fpga/inorder/soc_top_i1_ddr.sv` is an UNQUALIFIED independent
real-board wrapper preparation, adapted from verified DDR pin/CDC wiring.
Clock/MIG projects and real CPU/UART/DTB300MHz timebase still need matching
configuration and full-board timing before a bit; the OOC package remains
nominal100MHz RTL with a300MHz STA target only.

One additional performance diagnosis: current C-enabled BTB indexes PC at
halfword granularity, so a wholly32-bit instruction stream only uses half
the entries. A future fully tagged folded index can recover these slots
without more RAM. This has NOT been implemented or benchmarked; it also
means the C/no-C diagnostic cannot attribute all slowdown to IF staging.

### 2026-10-14: report-driven rounding/bypass/prediction batch 5

Short receipt: `build/gsim/i1-fd-jtag-timing-20261014-r8/receipt.json`, PASS.
This batch remains optional behind `--timing-cuts`; compact5 and the default
ISA switches are unchanged. The original OoO worktree is not modified.

Three related changes were validated together before one combined synthesis:

- Equal-format F/D rounding uses the pinned HardFloat equations/license, with
  exponent/subnormal-mask, rounded-significand and recoded-result boundaries.
  The final IEEE denormal packing no longer shares an edge with the whole
  exponent/rounding chain. One owner, exact exception flags and final-only
  rounding are retained. No new FP transaction capacity is introduced.
- ADDR bypass eligibility no longer waits on a newly computed alignment
  fault for an already registered non-memory result. Youngest-rd ownership
  remains visible even for faulting packets; eligibility is separate, so
  an older value cannot incorrectly bypass a younger faulting producer.
  This targets the actual address-low-bits -> bypass -> branch -> redirect
  path, not a conjectured direct PMP comparator path.
- C-mode BTB uses a full-tagged folded halfword index at the same 128-entry
  capacity. Both aligned 32-bit and dense 16-bit instruction streams can
  use all entries. The new independent full-PC ledger passes 16770 checks,
  including 512-byte aliases, instruction length, counter saturation,
  invalidation and deliberate wrong-target rejection.

Timing-cut FP add/sub latency is now11 / II12, multiply10 / II11 and
FMA11 / II12; division/square-root add3 cycles to their prior exact variable
latency. Compact/vendor arithmetic is unchanged. Both F and F+D pass
27840 SoftFloat vectors plus39 illegal cases, 27880 exact-latency checks,
held responses, full tokens/flags and all14 flush offsets.
Actual CPU F+D corpus2320 takes464500 cycles versus462004 in batch4
(0.54% more cycles); F-only1120 takes262965 versus262070 (0.34% more).
These are diagnostic corpus costs, not application or formal CoreMark scores.
Precise context/nonidentity Sv39/error, C/A page boundaries, privilege,
logical JTAG CRC retry and RV32/64 default-off checks also pass.
Independent ALU streams retain800 instructions over799 steady-state cycles.

Matched C-front-end diagnostic:
`build/gsim/i1-fetch-coremark-20261014-r2/receipt.json`.
It uses the same immutable RV64IM O3 binary and independent complete
PC/register/RAM/CRC trace as the earlier C-enabled r1 receipt.
ROI reduces664853 ->654019 cycles (1.63%) at first-response latency1,
and831353 ->823235 (0.98%) at latency12. Mispredictions reduce
9718 ->7763 and9722 ->7767. No-C ROI remains536927/713064.
The C-enabled configuration is still21.81%/15.45% slower than no-C on
this wholly32-bit binary; folding the BTB is a measured small gain,
not a resolution of the remaining registered IF/admission overhead.

Bandwidth receipt: `build/gsim/i1-bandwidth-20261014-r4/receipt.json`.
All16 bridge cases, Bare/Sv39 stream cycles and independent corruption
negative reproduce batch4 exactly. No bandwidth gain is claimed.
With the SAME modeled cycle counts, scaling nominal100MHz to300MHz
projects Sv39 READ154.989 / WRITE105.736 / COPY70.941 MiB/s.
COPY is payload; logical R+W is twice payload, not actual AXI bytes.
Real DDR/CDC latency in CPU cycles changes with frequency, so this is
an ideal projection, not a board measurement.
CPU-side AXI64 at300MHz has a2.4GB/s beat ceiling, but the actual
64-bit250MHz MIG AXI interface caps the path at2.0GB/s before overhead.
The32-bit DDR2000MT/s wire ceiling is8.0GB/s and is not CPU throughput.

Fresh physical candidate:
`E:\VM\Share\Valence-rtl\orbital-i1-fd-timing-20261014-r5`.
Completed source/RTL/GSIM-bound physical receipt:
`build/fpga/i1-fd-timing-synth-20261014-r5/receipt.json`.
Combined300MHz synthesis WNS=-2.651ns, WHS=-0.348ns, 8843 setup-failing
endpoints versus7566 in batch4. LUT37057 (-348), FF17323 (+288),
BRAM36=9 and DSP=28 unchanged. No placement/route or bit was run.
This is NOT an overall timing improvement: the worst WNS and failing
endpoint count both regress despite the targeted FP and bypass gains.

`report_selected_units.tcl` rereads each unchanged constrained DCP;
its current reports and `reports/baseline-r4-units` are archived together.
No synthesis, exception or clock adjustment is used for this comparison:

| 300MHz synthesis endpoint partition | Batch4 | Batch5 |
| --- | ---: | ---: |
| Shared single FP arithmetic | -1.347ns | -0.694ns |
| Shared double FP arithmetic | -2.473ns | -0.969ns |
| Architectural next-PC recovery | -2.350ns | -2.053ns |
| I-cache | -2.084ns | -2.651ns |
| C fetch aligner | -1.216ns | -2.181ns |

The FP worst endpoint has moved from raw exponent -> rounding/packing
to EX instruction decode -> raw-unit issue enable. The old ADDR alignment
source no longer owns the recovery worst; EX rs2 selection still traverses
bypass/branch/recovery. The overall worst is now aligner registered state
-> offered-address choice -> fast-page translation/PA choice -> cacheable
range/admission -> I-cache state, 5.966ns/22levels. It contains1.589ns logic
and4.377ns UNPLACED routing estimate, not measured routed interconnect.
The fast IF path already uses cached full-page PMP permission; do not
incorrectly diagnose this report as recomputing all PMP entries per fetch.
The rerun remaps unchanged frontend logic as well as the edited modules;
no isolated causal attribution to the BTB fold has been established.

Stock unchanged OpenSBI/S handoff and wrong-handoff negative also pass:
`build/gsim/i1-timing-opensbi-20261014-r5/receipt.json`,
24874000cycles,35 S-ecalls and1 S-mode timer interrupt at nominal100MHz.
No Linux or real-clock300MHz qualification follows from this diagnostic.

Next batch should address front-end offered-PC/translation/cache-admission
feedback together with EX branch recovery and FP issue-enable fanout.
Blindly adding another I-cache hit cycle would compound the measured C
front-end penalty; preserve synchronous RAM hit overlap and exact permission
invalidation. Separately, throughput is bounded by the current one-owner,
write-through/no-write-allocate data cache and real store acknowledgements.
Changing that memory pipeline requires precise late-error, fence and LR/SC
ordering proof; clock scaling or more cache capacity alone is not a solution.

### 2026-10-14: fixed-window / registered recovery / FP dispatch batch 6

Short source-bound receipt:
`build/gsim/i1-fd-jtag-timing-20261014-r9/receipt.json`, PASS.
The new changes remain behind the existing default-off `--timing-cuts`.
ISA switches, pipeline profiles, cache sizes and transaction capacity are unchanged.
The original OoO worktree and its shared IP bytes are not modified.

The fixed cache/DDR window check now separates a constant upper-prefix match
and only the changing non-alignment middle bits, instead of using an XLEN
range carry comparison. It does not grant PMP permission or imply the
complete access fits. The existing natural-alignment/burst rules remain.
Independent RV32/64 tests each check36120 addresses against12 fixed windows:
empty, one-byte, unaligned, non-power-of-two, full address space, exclusive
limit and above4GiB boundaries. Deliberate wrong-result negatives reject.
Cache miss/error/partial-store/reset and DDR/MMIO route tests remain passing.

Branch comparison/forwarding still happen in EX, but recovery consumes
the EXISTING registered ADDR packet in this profile. There is no ninth
pipeline stage or new transaction owner. Wrong-path EX/RF/ID/IF is killed,
while the branch continues through MEM/WB. MDU/FP producers are explicitly
flushed with this older ADDR redirect, and EX transfer is inhibited at
the same edge. The architectural interrupt resume register now uses only
the WB/IRQ recovery PC, not a mux connected to speculative branch targets.
Independent RV32/64 wrong-path-divider tests force real older-load delay16/96,
check intermediate/held cancellation, forbid wrong-path stores, execute a
new divider owner and preserve priority of an older load fault.
Actual overlap counts are recorded in the short receipt, not inferred
from elaboration. ALU steady state remains800 retires over799 cycles.

The FPU dispatcher captures its one complete owner before format/opcode
issue. Capacity remains1; request-to-result/II each gain one edge.
Timing-cut add/sub and FMA latency12/II13, multiply11/II12, miscellaneous4
and integer-to-FP5. Illegal numerical dispatch now responds in2 edges.
Both F and F+D independently pass27840 SoftFloat vectors plus39 illegal
cases, exact latencies/tokens/flags/backpressure and all15 early flush offsets.
CPU FD corpus rises464500 ->475065 cycles (+2.27%); F-only
262965 ->267859 (+1.86%). Context, nonidentity Sv39 floating memory faults,
C/A boundaries, privilege and boot-owned JTAG download/CRC retry also pass.

Same immutable O3 IM-binary architectural/CRC traces remain identical.
No-C ROI rises536927 ->548351 (+2.13%) at modeled latency1 and
713064 ->725280 (+1.71%) at latency12.
C-front-end matched receipt:
`build/gsim/i1-fetch-coremark-20261014-r3/receipt.json`,
654019 ->663111 (+1.39%) and823235 ->839844 (+2.02%).
These are measured SAME-FREQUENCY costs, not IPC improvements or formal
CoreMark scores. Higher qualified frequency must outweigh the cycle cost
before calling this a system-performance win.

Bandwidth: `build/gsim/i1-bandwidth-20261014-r5/receipt.json`.
Bridge16 cases are unchanged. Bare READ/WRITE/COPY are15100/22142/33091
cycles; Sv3915122/22167/33040. Changes are within0.03%, not a bandwidth gain.
Sv39 nominal100MHz READ51.663 / WRITE35.244 / COPY23.646 MiB/s.
The unchanged MIG64/250MHz ceiling is2.0GB/s. Clock projections still do
not qualify an actual300MHz board.

One combined300MHz synthesis completed in
`E:\VM\Share\Valence-rtl\orbital-i1-fd-timing-20261014-r6`.
Receipt: `build/fpga/i1-fd-timing-synth-20261014-r6/receipt.json`.
Setup WNS improves -2.651 -> -2.124ns; setup-failing endpoints8843 ->7454.
LUT37057 ->36677 (-380), FF17323 ->17571 (+248), BRAM36=9/DSP=28
unchanged. WHS=-0.348ns/134 endpoints, CPU hold=-0.076ns/10 endpoints.
No placement/route or bit is run: this still fails300MHz and is not
qualified real-board frequency x IPC improvement.

| 300MHz synthesis endpoint partition | Batch5 | Batch6 |
| --- | ---: | ---: |
| Shared single FP arithmetic | -0.694ns | -0.449ns |
| Shared double FP arithmetic | -0.969ns | -0.809ns |
| Architectural next-PC recovery | -2.053ns | -0.062ns |
| I-cache | -2.651ns | -2.111ns |
| C fetch aligner | -2.181ns | -1.504ns |
| IF translation | -2.051ns | -1.809ns |
| Data translation | -0.559ns | -1.230ns |
| D-cache | -0.481ns | -0.460ns |

These endpoints are the same report partitions, not isolated placement
experiments. DT translation regresses; do not claim every path improved.
The overall worst is now D -> S conversion exponent -> pinned general
rounding/IEEE packing -> MiscS response:5.439ns/18levels,1.224ns logic
and4.215ns UNPLACED routing estimate. Shared-format arithmetic cuts do not
cover this different-exponent/significand converter. Next arithmetic
batch needs its own exact general-round/pack boundary; reusing the
equal-format rounder without exponent/sticky adaptation would be incorrect.
The I-cache offered-address/fast-page/cache-admission chain remains nearly
tied at-2.111ns, so the next batch must also keep addressing front-end
handoff and permission invalidation without silently adding hit latency.

Stock unchanged OpenSBI/S-mode and wrong-handoff negative pass:
`build/gsim/i1-timing-opensbi-20261014-r6/receipt.json`,
26118000cycles,35 S-ecalls,1 S-timer IRQ and72 MRET. This is a nominal100MHz
short boot test, not Linux qualification or a300MHz firmware timebase.
No original OoO source/default or external DDR/board project was changed.

### 2026-10-14: exact D-to-S round cuts / fast data authorization batch 7

First direct-data prototype short receipt, superseded after timing review:
`build/gsim/i1-fd-jtag-timing-20261014-r11/receipt.json`,
57 necessary checks pass. The original OoO worktree is unchanged.
M/A/C/F/D and pipeline choices remain independently parameterized.

HardFloat provenance is explicit: all18 vendored Scala files remain hash-bound
to the documented local import in `floating-point-dependencies.json`, from pinned revision
`c1105e6ac6a0dd90fc80893efc4830ab609005d3`.
There is an ALREADY RECORDED bit-equivalent unsigned alignment-distance
patch for the pinned GSIM in the imported vendor baseline; do not claim
this tree has never differed from upstream. This timing batch makes no
new vendor-source changes. The local licensed adapter
`I1FloatingPointNarrowRoundCuts` specializes the pinned
`RoundAnyRawFNToRecFN(11,53,8,24,sigMSBitAlwaysZero)` equations.
Exact signed exponent/sticky preparation, denormal mask, increment and
recoded packing are separated by4 validity registers. No intermediate IEEE
rounding is added. After-rounding tininess, NaN boxing/canonicalization,
overflow/underflow/inexact and flush/token ownership preserve the oracle.
Under timing cuts, FCVT.S.D latency/II changes4/5 ->8/9; other batch6
latency contracts remain unchanged. Both F and FD pass27840 independent
SoftFloat vectors plus39 illegal cases, latency/II/flags and all15
flush offsets; F-only structurally removes the new D-to-S module.

New `fastDataTranslation` / `--fast-data-translation` defaults OFF.
It requires `fpga8 + --timing-cuts` and actual PMP or Sv39 protection.
The selected candidate explicitly enables it; no generic default changes.
The EXISTING4-entry D-TLB stores separate read/write full-4KiB PMP proof
tags for the current slice of a real superpage. Bare has separate read/write
proof tags as well, avoiding source/destination COPY permission ping-pong.
There are NO added TLB entries, cache capacity, data transaction slots or
posted-store acknowledgements. Dynamic S/U privilege, SUM/MXR, PTE R/W/A/D
and canonicality still gate each request. PMP changes/SFENCE invalidate
proofs; stale in-flight walks cannot publish them. RMW additionally
requires read permission; SC does not borrow read permission. A write-only
PMP page must not cause a speculative cache-line read. A denied/partial
page falls back to the registered scalar authorization path.
The first direct prototype held the SAME unaccepted offered owner during
downstream READY stalls. This protocol is superseded by the registered D
owner below; the independent IF fast protocol is unchanged. CPU D accesses
remain naturally aligned and still await actual physical success/error.
Responses stay registered, including stores.

Paired MMU fixtures each pass435 independent cases and deliberate
wrong-page negatives. Coverage includes4K/2M/1G,256 PTE flag combinations,
SUM/MXR changes without SFENCE, MPRV effective privilege, locked R-only /
W-only PMP, SC/AMO, partial-line noAllocate, stale walks and READY stalls.
The alternating32 read/write-pair diagnostic changes1047 ->855 cycles
in Bare and1023 ->831 in Sv39, with the SAME64 physical requests and
zero additional PTW traffic. This is a local latency result, not a CPU
throughput claim. Hardware fast-data qualification here is RV64; RV32
configuration legality is tested, not a separate RV32 protected CPU run.

Actual S-mode CPU same-source ON/OFF bandwidth comparison:
`build/gsim/i1-bandwidth-20261014-r7/receipt.json`.
Each operation processes8192 bytes; all bytes and READ checksum are checked
by an independent memory oracle under unchanged bounded-random AXI service.

| Mode / operation | Fast data OFF cycles | ON cycles | Throughput gain | ON MiB/s at nominal100MHz |
| --- | ---: | ---: | ---: | ---: |
| Bare READ |15100|11977|26.07%|65.229|
| Bare WRITE |22142|19055|16.20%|41.000|
| Bare COPY payload |33091|26873|23.14%|29.072|
| Sv39 READ |15122|11974|26.29%|65.246|
| Sv39 WRITE |22167|19039|16.43%|41.034|
| Sv39 COPY payload |33040|26898|22.83%|29.045|

Bare retains264 AXI reads/3077 writes; Sv39 retains265/3077 in BOTH
models. No payload/traffic/workload shrink or larger queue explains this
gain. Total retired counts include more iterations of fixed-time BootROM
UART polling when loads become faster, so they are NOT a same-retirement
stream CoreMark metric. FD2320-case CPU corpus now takes438784 cycles;
F-only1120 cases250660. Precise context/memory faults, C/A/LR-SC/AMO
boundaries,19 privileged traps and logical USER2 download/CRC retry pass.
These totals are diagnostics, not an isolated FPU numerical IPC claim.

The proposed new offered-PC preparation register was functionally correct
but REJECTED before synthesis: same immutable O3 IM binary with C frontend
took775414/937449 ROI cycles vs663111/839844 at latency1/12
(16.94%/11.62% slower). Evidence:
`build/gsim/i1-fetch-coremark-20261014-r4/receipt.json`;
unused export `orbital-i1-fd-timing-20261014-r7/REJECTED.json`.
Only that candidate was restored byte-exactly to batch6. Final C diagnostic
`build/gsim/i1-fetch-coremark-20261014-r5/receipt.json` reproduces
663111/839844 EXACTLY; no-C remains548351/725280. Same instruction/register
trace,367146 retires andCRC are preserved. These are short diagnostics,
not formal >=10-second scores. CoreMark here has no PMP/Sv39/FPU, so do
not extrapolate the S-mode streaming gains to its score.

The bridge's16 bandwidth/error cases remain unchanged, including latency
0/12/32/64, backpressure and above4GiB. It still has2 transaction slots /
1 write credit. The D-cache is still a single-owner, write-through,
no-write-allocate cache. Thus this batch removes authorization bubbles,
NOT the remaining blocking store-ack/read-owner bottleneck or the gap to
MIG peak. MIG CK1000MHz/DDR2000MT/s/DQ32 wire ceiling8GB/s; AXI64/UI250MHz
ceiling2GB/s. Projected300MHz CPU numbers are not qualified board results.

The first combined300MHz OOC synthesis completed from this direct
prototype in `E:\VM\Share\Valence-rtl\orbital-i1-fd-timing-20261014-r8`.
Receipt: `build/fpga/i1-fd-timing-synth-20261014-r8/receipt.json`.
WNS regressed -2.124 -> -4.565ns,9446 failing endpoints; resource
38315 LUT /18062 FF /9 BRAM36 /28 DSP. WHS=-0.348ns/134,
CPU hold=-0.076ns/10. The FP MiscS partition improved -2.124 ->-0.757ns
(the D-to-S numerical chain no longer owns its worst endpoint), but the
new direct D path connects CPU admission/CSR permission, translation,
atomic selection and D-cache admission:7.880ns/27levels,1.807ns logic
and6.073ns UNPLACED route estimate. It also couples CPU admission into IF
and FP issue enables. The direct prototype is therefore superseded, NOT
advertised as an overall frequency x throughput improvement.
The rejected r7 offered-PC export was never synthesized. No layout/route,
board/MIG/clock-IP qualification or bit comes from either prototype.

#### Registered owner correction: final functional candidate

Current source-bound receipt:
`build/gsim/i1-fd-jtag-timing-20261014-r12/receipt.json`, all57 gates PASS.
The D fast path now captures the existing saved/context/PA/noAllocate
owner with READY depending ONLY on registered idle state. A proven page
skips lookup/authorize, but its physical request is issued from the EXISTING
registered send state. D no longer drives upstream READY from the atomic/
cache READY network. A delayed/error physical reply still controls final
success; there is no posted acknowledgement or additional transaction slot.

At normal authorization, each EXISTING read/write proof also stores its
complete physical4KiB page. Thus a fast superpage slice needs neither
level-dependent PA reconstruction nor a duplicate generic TLB tag check.
Exact proof VPN tags and current PTE permissions are still checked.
Proof valid bits are cleared on replacement and global invalidation; stale
walks cannot publish them. These8 x24-bit PA proof fields add192 metadata
bits in this RV64/physical36 configuration, not more TLB entries/data slots.
Paired MMU fixtures now pass439 cases, including cached reads AND writes to
a nonidentity physical mapping above4GiB. Their alternating pairs use
1041 ->849 cycles(Bare) and1026 ->834(Sv39), with the same64 requests;
the changed phase/seed history is not comparable to an older microbenchmark
in isolation.

Final bandwidth receipt: `build/gsim/i1-bandwidth-20261014-r8/receipt.json`.

| Mode / operation | OFF cycles | Registered ON cycles | Throughput gain | ON MiB/s at nominal100MHz |
| --- | ---: | ---: | ---: | ---: |
| Bare READ |15100|13053|15.68%|59.852|
| Bare WRITE |22142|20031|10.54%|39.002|
| Bare COPY payload |33091|28808|14.87%|27.119|
| Sv39 READ |15122|13045|15.92%|59.889|
| Sv39 WRITE |22167|20013|10.76%|39.037|
| Sv39 COPY payload |33040|28894|14.35%|27.038|

Traffic stays264/3077 AXI reads/writes in Bare and265/3077 in Sv39.
The registration gives back some cycles relative to the superseded direct
prototype, but retains real same-frequency gains over the published batch6
configuration. FD corpus451069 cycles, F-only256070, context/error/C/A/
privilege19-trap and USER2 download/retry regressions pass.
Final C-front-end diagnostic:
`build/gsim/i1-fetch-coremark-20261014-r6/receipt.json`;
663111/839844 ROI cycles and complete architectural traces/CRC remain
EXACTLY the batch6 values. The M-only benchmark does not activate data
translation, so streaming gains still must not be labelled CoreMark gains.

Corrected combined OOC synthesis/reporting is COMPLETE in
`E:\VM\Share\Valence-rtl\orbital-i1-fd-timing-20261014-r9`.
Canonical receipt:
`build/fpga/i1-fd-timing-synth-20261014-r9/receipt.json`,
SHA256 `d3fd4ac2c3354c46723a76c6bfa7d317fab756b601de723951c97e7301401259`.
No constraints were relaxed; actual tool period3.333ns is the1ps rounding
of the requested300MHz. Both supplemental report scripts read the SAME
constrained DCP; they do not perform further synthesis.

| Synthesis metric / partition | Published batch6 | Direct prototype | Corrected registered owner |
| --- | ---: | ---: | ---: |
| Overall setup WNS | -2.124ns | -4.565ns | -2.361ns |
| Setup-failing endpoints |7454|9446|8034|
| Data translation | -1.230ns | -3.670ns | -1.733ns |
| D-cache | -0.460ns | -4.565ns | -0.477ns |
| FP miscellaneous S | -2.124ns | -0.757ns | -0.698ns |
| Shared arithmetic S | -0.449ns | -0.469ns | -0.410ns |
| Shared arithmetic D | -0.809ns | -0.619ns | -0.619ns |
| Architectural next PC | -0.062ns | -0.040ns | -0.050ns |
| IF translation | -1.809ns | -3.441ns | -1.884ns |
| I-cache | -2.111ns | -2.388ns | -2.361ns |
| C aligner | -1.504ns | -1.515ns | -1.911ns |
| LUT |36677|38315|38271|
| FF |17571|18062|18261|
| BRAM36 / DSP |9 /28|9 /28|9 /28|

Corrected hold WHS=-0.348ns/134, CPU hold=-0.076ns/10; these are still
unplaced estimates. The new direct CPU->cache chain is gone. The worst is
again C aligner registered state -> offered address/IF authorization ->
I-cache admission,5.676ns/21levels,1.497ns logic plus4.179ns UNPLACED route
estimate. MiscS worst is now WB-valid -> issue/flush control, not the old
continuous D-to-S rounding/packing chain.

Overall setup is0.237ns WORSE than published batch6, despite the FPU
improvement and same-frequency bandwidth gains. Do not claim every
partition improved or that frequency x IPC has been physically proved.
The optional candidate adds1594 LUT(+4.35%) and690 FF(+3.93%) over batch6,
with all GPR/FPR/cache/ROM BRAM gates and USER2 clock-shape gates passing.
It does NOT meet300MHz; no placement/route or bit was attempted. Neither
the previous foundation's200MHz route nor a clock-scaled projection
qualifies this current protected cached F/D SoC.

Stock unchanged OpenSBI/S-mode handoff and wrong-handoff negative pass:
`build/gsim/i1-timing-opensbi-20261014-r9/receipt.json`,
24377000 cycles,35 S-ecalls,1 S-mode timer IRQ and72 MRET at nominal100MHz.
Linux floating context/boot and board clock/MIG/CDC remain unqualified.
Next work must redesign frontend offered-PC/IF/cache admission TOGETHER
with its predictor/parcel lookahead and measure the whole CPU; the
rejected ad-hoc offered-PC register must not be reinstated as a timing-only
fix. Data authorization still has a remaining WB/control->noAllocate
chain. Longer-term bandwidth also needs exact-error-preserving fill
handoff and blocking store-ack/owner optimization, not more cache capacity
or a misleading clock-only bandwidth estimate.

### 2026-10-14 batch8: existing IF page proofs and private cache PMA

Final source-bound short receipt:
`build/gsim/i1-fd-jtag-timing-20261014-r15/receipt.json`, all80 gates PASS.
Configuration remains RV64IMAFDC, M/S/U, Sv39, PMP8, TLB4, I/D2KiB,
BTB128, fpga8, timing cuts, registered fast-data authorization and USER2.
The generic ISA/parameter defaults are unchanged; this is the independent
I1 tree, not an update of the Orbital-A1/OoO worktree.

The longest published chain was C parcel state -> offered address ->
instruction authorization/PA assembly -> I-cache admission. This batch
does NOT add the previously rejected offered-PC register or a fetch wait
state. It changes three connected combinational boundaries together:

- At existing full-page authorization, IF proof rows also save the exact
  physical4KiB page and cacheable-window classification. A warm fast
  superpage slice no longer reconstructs its PA on every request.
- For TLB2/4/8, compare the EXISTING27-bit exact VPN proof tags in parallel.
  A real row0 superpage still dominates overlapping leaf rows. The data/PMA
  selection is independent of the dynamic X/A/U/canonicality grant; that
  grant still controls physical request acceptance. TLB16+ retains the
  indexed lookup rather than growing an unbounded associative structure.
- A private read-only IF cache input consumes the already checked PMA
  classification. It is NOT a software/TL cacheability override. The
  cache asserts that it equals the full physical-window/noAllocate policy
  and rejects writes/atomics on this port. The normal D-cache and default
  non-cut cache path keep their original checks and timing protocol.

Aligned4KiB windows can use the proof's stored PMA bit; a non-page-aligned
window still evaluates the exact physical byte range. Explicit noAllocate
is preserved. Normal authorization includes line-PMP permission; a full
page proof alone never bypasses live PTE/privilege checks, invalidation or
a stale walk. Unsupported raw SATP fixture modes cannot publish a virtual
page proof. A backpressured fast request captures the existing owner,
physical address and PMA, without increasing transaction capacity.

Bare read/write proof tags now use the configured physical address width
under timing cuts, with an explicit reject of nonzero higher XLEN bits.
An address above physical36 cannot alias a warm valid page. For the selected
configuration this removes84 tag bits across IF read, D read and D write;
the IF physical-page/PMA metadata adds102 bits, for a net18 functional
metadata bits before synthesis optimization. No TLB/cache entries, data
owners or architectural pipeline stages are added.

New independent coverage: seven IF profiles each pass305 cases, spanning
TLB2/4/8/16, fast IF on/off, aligned/shifted/board2GiB windows,4K/2M/1G,
nonidentity PA above4GiB, superpage priority and physical-width alias
rejection. Paired data authorization fixtures each pass447 cases,
including both high-bit read and write aliases. Deliberately wrong PMA
and wrong-page expectations are rejected. Three RV32/RV64/read-cache-off
fixtures each pass269 checks, plus wrong-hint DUT assertions and independent
wrong-data negatives. Warm cache hit throughput stays16 hits in17 cycles.
The original general read/write cache tests are also retained.

The first r13 attempt failed elaboration on an unknown-width fast-PA wire
in the shifted-window configuration. The explicit XLEN wire fix and
passing r14 intermediate evidence are preserved; neither failure nor
negative controls were relabelled as positive results.

Real CPU Bare/Sv39 READ/WRITE/COPY cycles and AXI traffic exactly reproduce
the corrected batch7 values. FD corpus451069 cycles, F-only256070, context/
fault tests,19 privileged traps and USER2 CRC retry likewise remain exact.
Final bandwidth evidence: `build/gsim/i1-bandwidth-20261014-r9/receipt.json`.
It retains the same16 bridge cases and2-slot/1-write-credit limit.
The same immutable O3 IM binary's C-frontend diagnostic reproduces
663111/839844 ROI cycles at latency1/12, with the same register trace,
367146 retirements andCRC59156:
`build/gsim/i1-fetch-coremark-20261014-r7/receipt.json`.
No-C stays548351/725280. These M-only diagnostics do not exercise Sv39
and are not formal >=10-second scores. This batch targets timing without
claiming a new same-frequency throughput gain.

Stock unchanged OpenSBI and the wrong-handoff negative pass again:
`build/gsim/i1-timing-opensbi-20261014-r10/receipt.json`.
24377000 cycles,5778207 retirements,35 S-ecalls,1 S timer IRQ,72 MRET,
3801 S retirements and2751 UART bytes exactly match batch7.
This remains short firmware/S-mode validation, not Linux qualification.
All332 source hashes in the final short receipt match the current source;
the imported HardFloat files and original OoO worktree are unchanged.

Exactly ONE combined300MHz OOC synthesis completed in
`E:\VM\Share\Valence-rtl\orbital-i1-fd-timing-20261014-r10`.
Both supplemental report jobs open its SAME constrained checkpoint;
neither reruns synthesis nor changes any clock/timing exception.
Canonical receipt:
`build/fpga/i1-fd-timing-synth-20261014-r10/receipt.json`,
SHA256 `531907f6587eaf5f177c759f8819b7e26a542c4363536d9b811351d39ae74f27`.
Final short receipt SHA256:
`19ef5b21e0f9d257e5ae111b0a22434e9cd0f39340fa0f20bec8b74edcdb219d`.

| Same target/endpoint partition | Batch7 registered owner | Batch8 IF proof/PMA |
| --- | ---: | ---: |
| Overall setup WNS | -2.361ns | -2.373ns |
| Setup-failing endpoints |8034|8038|
| I-cache | -2.361ns | -1.614ns |
| IF translation | -1.884ns | -1.624ns |
| C aligner | -1.911ns | -1.825ns |
| Data translation | -1.733ns | -1.820ns |
| D-cache | -0.477ns | -0.477ns |
| Shared FP S | -0.410ns | -0.535ns |
| Shared FP D | -0.619ns | -0.619ns |
| FP miscellaneous S | -0.698ns | -0.823ns |
| FP miscellaneous D | -0.679ns | -1.096ns |
| Architectural next PC | -0.050ns | -0.017ns |
| LUT |38271|38350|
| FF |18261|18276|
| BRAM36 / DSP |9 /28|9 /28|

The targeted I-cache endpoint set improves0.747ns, but overall setup is
0.012ns WORSE, not a demonstrated clock-rate gain. Most new worst paths
are still control/enable chains. No change to the FP arithmetic sources
explains a new arithmetic capability: its changed S/misc worst paths start
at WB MRET control. Data authorization's worst path is likewise WB MRET ->
noAllocate. These observations must not be hidden behind the frontend gain.
The candidate costs79 LUT and15 mapped FF over batch7; ROM, GPR/FPR and
cache BRAM mapping plus DSP count/USER2 constraint-shape gates all pass.

Overall hold remains WHS=-0.348ns/134, CPU-only hold=-0.076ns/10.
Current worst setup is EX rs2 index -> youngest-forwarding selection ->
ALU/word/result selection -> ADDR result,5.688ns/19levels, with0.903ns
logic and4.785ns UNPLACED route estimate. The hierarchy includes the
mulDiv consumer of the shared rs2 bus; the reported path does not traverse
a multiplier DSP, and must not be misdiagnosed as multiplier arithmetic.
The previous longest IF/cache chain is no longer the global worst.

Using actual3.333ns STA period minus WNS gives a SYNTHESIS-ONLY rough
setup frequency estimate175.25MHz, essentially unchanged from175.62MHz.
This is NOT a routed/board-qualified maximum.300MHz is still unmet; hold
also fails. No place/route or bit was attempted, and no broad exceptions,
cache expansion, owner expansion or benchmark shrink was used to claim
closure. Nominal100MHz CPU model throughput remains the batch7 table;
frequency-scaled bandwidth projections do not replace physical qualification.

Next batch must address EX operand-selection, ALU shift/word normalization
and final completion-result selection together, preserving the closest
producer priority, held operands, no older-fault bypass and one-ALU-per-cycle
steady state. The WB retirement/return -> permission/noAllocate and
issue/flush-enable control fanout is the other joint target. IF still has
a decode/global cancellation -> admission enable chain and cannot be called
closed at300MHz. Each next coherent batch needs the same exact-byte/trace,
real Sv39/Bare CPU and negative/error checks before another combined STA;
simply adding a fetch preparation register remains a rejected alternative.

### 2026-10-14 batch9: joint EX payload and WB recovery boundaries

The selected architectural pipeline is still exactly8 stages:
`IF -> ID -> RF -> EX -> ADDR -> MEM -> CMP -> WB`.
It is a single-issue, strictly in-order core, not the original Orbital-A1.
The parameterized alternatives remain compact5(default) and balanced7.
The selected candidate enables RV64IMAFDC/Zicsr/Zifencei, M/S/U, Sv39/Svade,
PMP8,4-entry I/D TLBs,2KiB direct-mapped I/D caches with64B lines,128-entry
prediction, the DSP-tiled integer multiplier and optional FPGA timing cuts/
registered fast-data proofs. Its independent SoC has4KiB BootROM/reset,
UART460800, a CPU-rate machine timer, M/S PLIC contexts, a64-bit AXI DDR
boundary with2 shared slots/1 write credit and the2GiB address map, plus
boot-owned USER2 JTAG download. It does not contain the production OoO
SoC's MAC/DMA/CMU, live coherent DMA, full architectural Debug or qualified
Linux boot. GSIM timebase remains100MHz;300MHz is the STA target, not an
implemented board clock. Multicycle FPU/MDU latency is not another
architectural pipeline profile.

Source-bound short receipt:
`build/gsim/i1-fd-jtag-timing-20261014-r17/receipt.json`, all89 gates PASS,
SHA256 `a5cc1326e609d373810ee020a29a8b27c339656c0557e96223a0b758049221d9`.
This coherent batch modifies the optional timing-cut implementation only:

1. Share the same youngest-eligible one-hot operand masks across raw rs1/
   rs2 and ALU inputs. PC/immediate/register-use qualification now precedes
   the wide payload reduction, instead of adding another XLEN mux after it.
2. Share the SRL/SRA barrel shifter with an explicit extension bit, preserving
   SRLW/SRAW32-bit normalization and every shift amount. Word high/sign
   contributions are packed per operation before the result reduction.
3. Decode the5-way FP/jump/CSR/MDU/ALU result mask at the existing ID->RF
   boundary and carry it into EX. This preserves the original priority even
   for overlapping illegal-control fixtures; no new pipeline edge is added.
4. Classify fault/xRET/SFENCE/FENCE.I/context-barrier recovery from the
   registered CMP owner into a WB recovery bit. It changes exactly on the
   existing WB packet/valid edge. Architectural CSR/privilege updates,
   invalidation and exception/interrupt commit remain WB-only and same-cycle.
5. Separate early memory payload choice from actual request admission.
   Address/size/write/data/mask selection uses the registered ADDR owner
   and existing MEM slot availability, NOT WB flush, external READY or
   addressFire. A live normal MEM memory owner always excludes that choice.
   Request VALID is unchanged and retains all old fault/recovery checks.
   The fire-time assertion proves the selected payload equals the admitted
   owner; stores still await real completion/error.
6. FPU/MDU result READY now describes execution capacity independently of
   that result's own VALID. Their actual fire/EX transfer is unchanged,
   all other completion/fault/kill qualifications remain, and there is no
   posted reply, extra numerical owner or new issue opportunity.

The result mask adds5 bits at each existing RF/EX register boundary, and WB
recovery adds1 bit:11 functional state bits before synthesis trimming.
The pure helpers add no state. ISA/resource/pipeline switches and generic
defaults stay unchanged. A new no-M/no-F/no-D real RV64 core fixture proves
MDU/FPU/FPR hardware disappears and disabled M encodings trap. Existing
RV32/RV64 default-off, F-only and F+D checks remain in the same batch.
No vendored HardFloat, GSIM, shared OoO IP or ISA oracle is modified.

Four raw-input EX fixtures each pass37984 independent semantic checks,
covering RV32/RV64 and cut/non-cut ALUs, all operand offers and x0, PC/
immediate qualification, integer opcodes, signed/unsigned shifts, all
word/shift boundaries and result priority. Each deliberate wrong-result
negative fails its independent oracle. The first r16 fixture attempt exposed
the pinned GSIM's invalid C++ setter for top-level Vec input ports; r17
exposes the SAME six operands/four result sources as scalar ports instead.
The original failure is preserved and no simulator or expected value was
changed to obtain a pass.

Real CPU FD/F-only corpora retain451069/256070 cycles; FCSR/FS/FPR restoration,
memory errors, C/A cross-page and19-trap privilege checks, JTAG CRC retry
and late-recovery/older-fault cancellation pass without a new bubble.
Independent and dependent steady ALU streams both retain800 instructions
spanning799 cycle intervals. The new matched-performance gate rejects an
O3 ROI or Bare/Sv39 slowdown before marking acceptance PASS.

| Same-source selected CPU operation | Batch8 cycles | Batch9 cycles |
| --- | ---: | ---: |
| Bare READ / WRITE / COPY |13053 /20031 /28808|13053 /20031 /28808|
| Sv39 READ / WRITE / COPY |13045 /20013 /28894|13045 /20013 /28894|
| No-C immutable IM O3 ROI, latency1 /12 |548351 /725280|548351 /725280|
| C frontend, same IM O3 ROI, latency1 /12 |663111 /839844|663111 /839844|

Streaming byte geometry and AXI traffic are exact:264/3077 reads/writes
in Bare and265/3077 in Sv39. The auth-OFF paired models also retain their
old cycle counts. Nominal100MHz Sv39 READ/WRITE/COPY stays59.889/39.037/
27.038MiB/s. Bandwidth evidence:
`build/gsim/i1-bandwidth-20261014-r10/receipt.json`.
All16 bridge latency/backpressure/above4GiB cases remain unchanged.
The C diagnostic explicitly rejects a same-binary cycle regression:
`build/gsim/i1-fetch-coremark-20261014-r8/receipt.json`.
Both C/no-C reproduce345520 ROI instructions,367146 retires, register
trace4509c0a4825b10bb andCRC59156. The immutable IM binary does not exercise
Sv39/FPU and these short diagnostics are not formal >=10-second scores.
This batch seeks a timing/area benefit with NO measured same-frequency
IPC/throughput regression; actual frequency x IPC awaits physical timing.

Stock unchanged OpenSBI/S-mode handoff and its deliberate wrong-handoff
negative pass:
`build/gsim/i1-timing-opensbi-20261014-r11/receipt.json`.
24377000 cycles/5778207 retires,35 S-ecalls,1 S timer IRQ and72 MRET are
exactly unchanged. All334 source hashes in the final short receipt match.

ONE combined300MHz synthesis is COMPLETE in
`E:\VM\Share\Valence-rtl\orbital-i1-fd-timing-20261014-r11`.
Canonical receipt:
`build/fpga/i1-fd-timing-synth-20261014-r11/receipt.json`,
SHA256 `acb304e321007e24f0f70f93fac5022f6bc4c4ada5c43f0b3db0ffcd4bc5e9d9`.
RAM/ROM/FPR/DSP/USER2 gates pass. No clock period or timing exception
changes: actual period remains3.333ns, the tool-rounded300MHz target.

Two standard supplemental jobs query the same current DCP. A third
report-only job opens the ALREADY EXISTING batch8 and batch9 constrained
DCPs and uses the same EX result D-pin and WB control source-selection
rules. It writes only into the new package, never edits the old package,
and performs NO further synthesis/placement/route. Its input checkpoint
hashes, native log, script and four detailed path reports are bound into
the canonical receipt's `ex_wb_comparison` and archived in WSL.
Paths: `reports/ex-wb-comparison/{baseline,current}/`.

| Same300MHz target/path scope | Batch8 | Batch9 |
| --- | ---: | ---: |
| Overall setup WNS | -2.373ns | -2.225ns |
| Setup-failing endpoints |8038|6433|
| EX -> ADDR result DATA pins | -2.373ns | -1.053ns |
| WB control sources -> CPU endpoints | -1.820ns | -2.191ns |
| IF translation | -1.624ns | -2.204ns |
| I-cache | -1.614ns | -2.174ns |
| C aligner | -1.825ns | -1.899ns |
| Data translation | -1.820ns | -1.809ns |
| D-cache | -0.477ns | -0.460ns |
| CSR | -0.193ns | +0.294ns |
| Shared FP S | -0.535ns | -0.866ns |
| Shared FP D | -0.619ns | -0.619ns |
| FP miscellaneous S | -0.823ns | -0.135ns |
| FP miscellaneous D | -1.096ns | -0.241ns |
| Architectural next PC | -0.017ns | -0.034ns |
| LUT |38350|38887|
| FF |18276|18279|
| BRAM36 / DSP |9 /28|9 /28|

EX's targeted data path improves1.320ns and19 ->14 logic levels:
5.688 ->4.368ns unplaced data delay. This does NOT mean the whole core
improves1.320ns. The EX tree costs additional LUT: whole SoC adds537
LUT(+1.40%) and3 mapped FF, while steady-state and workload cycle costs
remain exact. The implementation is therefore retained as a tested
frequency-oriented candidate, not an area reduction or a proven physical
frequency x IPC win.

The full WB-source endpoint set REGRESSES0.371ns. Its new worst is
`wbValid -> irqCommit -> FPU completion/execute capacity -> rrFire ->
idFire -> ifFire -> offered-PC enable`, not the previous MRET-driven
early-payload -> MMU noAllocate path. The global worst takes the same
chain from exValid:5.454ns/15levels,0.789ns logic and4.665ns UNPLACED
route estimate, ending at offerPc CE. IF/cache endpoint regression is
also this shared admission/control network, not renewed superpage PA
assembly or a new FP numerical chain. Do not describe both user-requested
chains or all partitions as closed/improved.

Rough synthesis-only setup estimate changes175.25 ->179.92MHz(+2.66%),
using actual period minus WNS. Overall setup only improves0.148ns.
WHS remains-0.348ns/134; CPU-only-0.076ns/10.300MHz remains unmet,
and these estimates are not a routed maximum, real IPC speedup or board
qualification. There is no place/route and no bit from this batch.

Next coherent timing batch: separate IRQ drain qualification from LIVE
backend-owner admission, FPU/MDU cancellation/result qualification, RF/
ID/IF capacity and offered-PC enable TOGETHER. A live EX/MEM/ADDR/CMP
owner already proves `irqCommit` cannot be true; ID/IF qualification
also checks registered irqPending. This suggests removing redundant
global IRQ feedback from local paths, but is an UNIMPLEMENTED candidate:
precise WB faults, the immediate frontend IRQ kill, held offered requests,
older memory-error cancellation and no stale numerical owner must still
be proved. No broad false-path exception or added pipeline bubble should
substitute for that proof. Repeat one affected short/performance batch
then one combined STA, not a synthesis after each local tweak.

## 2026-10-15 batch10 — live-owner recovery and measured retirement experiment

Selected profile is still eight-stage RV64IMAFDC/M/S/U, Sv39/Svade,
PMP8, four I/D TLB entries, I/D2KiB and BTB128. No queue/cache/owner
expansion, new architectural stage, posted store or vendor arithmetic
change. Original OoO worktree remains untouched.

The implemented timing change replaces global IRQ+WB recovery in LIVE
CMP/MEM/ADDR/EX/RF admission with WB recovery alone. IRQ commit already
requires all those owners to be empty. ID/IF also explicitly reject
irqPending, so need not feed backend emptiness through their capacity.
FPU/MDU cancellation and backend valid clears use this same local
recovery; EX redirects still cancel younger numerical owners. Actual
IRQ trap PC/cause, immediate frontend redirect/kill, held request drain
and reservation clear retain the full IRQ event. Runtime assertions
reject an empty-backend IRQ with a live numerical owner.

Selected short receipt:
`build/gsim/i1-fd-jtag-timing-20261015-r2/receipt.json`,
SHA256 `153d6344c83d414748fed3ca1e177e733a23832bf4d9b3e0974fe2e1c7bbfa94`.
All89 gates pass;334 frozen sources. Configuration now has14 unit tests.
Busy-state interrupts, older faults versus younger stores, late recovery,
M/F/D removal, F/D numerical/reference/context, PLIC S timer, C/A,
Sv39/PMP boundaries and JTAG CRC retry are included. Same-frequency
Bare R/W/COPY remain13053/20031/28808; Sv39 remain13045/20013/28894,
with unchanged264/265 AXI reads and3077 writes. The slower authorization
OFF reference also exactly matches batch9. This is timing-oriented,
NOT a measured same-frequency throughput improvement.

O3 no-C ROI remains548351/725280; C frontend remains663111/839844
at modeled memory delays1/12. Same345520 ROI instructions,
367146 retires, trace4509c0a4825b10bb andCRC59156. C evidence:
`build/gsim/i1-fetch-coremark-20261015-r1/receipt.json`.
Bandwidth evidence: `build/gsim/i1-bandwidth-20261015-r1/receipt.json`.
Nominal100MHz Sv39 R/W/COPY remain59.889/39.037/27.038MiB/s,
not a board result or formal >=10-second CoreMark score.

Stock OpenSBI and the independent wrong-handoff negative also pass:
`build/gsim/i1-timing-opensbi-20261015-r1/receipt.json`.
24377000 cycles/5778207 retires,35 S-ecalls,1 S timer,72 MRET,
3801 S retires and2751 UART bytes match batch9 exactly. This is a
bounded S-mode handoff test, not Linux or FPGA qualification.

### Retirement overlap: implemented, default OFF, NOT selected for synthesis

New `overlapDataRetirement`/`--overlap-data-retirement` defaults
OFF and requires explicit timing cuts, early issue and an actual
translation/protection boundary. The D translator can replace its one
saved owner only when the old REGISTERED reply is consumed. The CPU
can early-offer the next non-atomic access only after a real successful,
non-serial old memory reply. Old bus errors/CMP faults/WB recovery still
prevent younger irreversible accesses; the payload mux never depends on
raw response VALID/error or admission READY. There is no extra buffer,
MSHR, credit, predicted store acknowledgement or raw response bypass.

Experimental receipt `build/gsim/i1-fd-jtag-timing-20261015-r1/receipt.json`
is deliberately FAIL, not relabelled. All95 recorded functional/paired
checks completed, including fast/slow authorization with639 cases each,
192 dense replace/hold/error transactions per fixture and independent
data mutation negatives. Fast mode observed188 same-edge replacements.
But the prior-baseline performance gate rejected authorization-OFF
Sv39 WRITE:22167 ->22168 cycles. Selected fast-authorized scalar READ
and COPY did not improve; Bare WRITE saved just4 cycles. The option is
therefore excluded from the accepted r2 configuration/export.

To distinguish sparse instruction supply from replacement capability,
a separate eight-way-unrolled program reuses the SAME already compiled
OFF/ON CPU models and independent whole-buffer/checksum/retired-byte
oracle. No new elaboration or synthesis was needed. Final diagnostic:
`build/gsim/i1-retirement-dense-20261015-r2/receipt.json`.
Four deliberate guest-data mutations are rejected. Exact paired traffic
is266/267 AXI reads and3077 writes; byte/retirement counts are unchanged.

| Dense8 CPU cycles, same binary | OFF | ON |
| --- | ---: | ---: |
| Bare READ |9772|8842|
| Bare WRITE |17349|17460|
| Bare COPY |25257|23225|
| Sv39 READ |9767|8783|
| Sv39 WRITE |17180|17383|
| Sv39 COPY |25365|23353|

This improves READ/COPY throughput roughly9-11%, but WRITE worsens
roughly0.6-1.2%. It is a NEW instruction schedule, not comparable to the
old scalar-loop cycle counts or proof of a general SoC speedup. The
experiment demonstrates request-retirement overlap potential AND a
write-scheduling tradeoff; it does not justify enabling it by default.
Next bandwidth work should isolate read-to-read replacement, write
arrival phase/arbitration and frontend supply with per-operation ledgers,
not expand capacity or relax a failed throughput gate.

### Completed STA: local recovery gain, overall regression — NOT promoted

ONE combined300MHz synthesis of r2 is complete at
`E:\VM\Share\Valence-rtl\orbital-i1-fd-timing-20261015-r1`.
Canonical receipt:
`build/fpga/i1-fd-timing-synth-20261015-r1/receipt.json`,
SHA256 `0d09bf9467d9939b75fe5e862f905df86fc7820b432605af6c3a0cc6de537701`.
It explicitly reports `SYNTHESIS_SETUP_FAILS_300MHZ_ESTIMATE`.
No additional synthesis, placement, route or bit was run. The three
supplemental jobs only query completed constrained checkpoints.

| Same300MHz target/scope | Batch9 | Batch10 |
| --- | ---: | ---: |
| Overall setup WNS | -2.225ns | -2.401ns |
| Setup-failing endpoints |6433|8407|
| EX result D-pin set | -1.053ns | -2.222ns |
| WB control-source set | -2.191ns | -2.010ns |
| CSR | +0.294ns | +0.560ns |
| Architectural next PC | -0.034ns | +0.251ns |
| IF translation | -2.204ns | -2.401ns |
| I-cache | -2.174ns | -2.157ns |
| C aligner | -1.899ns | -2.114ns |
| D translation | -1.809ns | -1.673ns |
| D-cache | -0.460ns | -0.477ns |
| FP arithmetic S / D | -0.866 / -0.619ns | -0.859 / -0.859ns |
| FP miscellaneous S / D | -0.135 / -0.241ns | -1.147 / -1.132ns |
| LUT |38887|38979|
| Mapped FF |18279|18354|
| BRAM36 / DSP |9 /28|9 /28|

Overall WNS regresses0.176ns even though the identical WB-source
endpoint comparison improves0.181ns. The paired reports are bound to
both original DCP hashes under `ex_wb_comparison` in the receipt;
files are `reports/ex-wb-comparison/{baseline,current}/`. EX data
endpoints regress1.169ns: the mapped rs1-match -> operand-mask ->
ALU/word-shift/result network is now18 levels,5.537ns unplaced delay.
There is no arithmetic source change to that tree in this batch;
changed global optimization/mapping does not preserve its previous STA.
Do not advertise this batch as a net timing/resource win.

The overall worst now starts at exPacket.rs2[3] and follows CSR
read-legal/fault classification -> numerical completion/exFire ->
RF/ID/IF capacity -> instruction request -> IF translator state CE.
The reported path is18 levels,5.630ns, with0.888ns logic and4.742ns
UNPLACED route estimate. Some synthesized instance names include mulDiv
or FP modules because of optimization sharing; that is not evidence
that the numerical multiplier itself is the critical algorithm.
WB-source worst is now wbRecovery -> the same frontend admission chain,
not the removed empty-backend IRQ feedback.

Hold remains-0.348ns/134; CPU-only-0.076ns/10. The rough synthesis-only
setup estimate worsens179.92 ->174.40MHz using actual3.333ns minus WNS.
It is NOT a routed maximum,300MHz success or board signoff. OOC input
clock HD.CLK_SRC remains unset as in the prior run; placement, skew,
clock-tree, MIG and full board closure are outside this evidence.

Current source is a functionally qualified timing CANDIDATE, not a new
preferred release. Preserve batch9/r11 as the better prior synthesis
reference; do not replace a board bit with this package. The retirement
experiment remains OFF in r2 and was not synthesized.

Next coherent batch, before the next single synthesis:

1. Separate actual MDU/FP owner faults from unrelated CSR legality in
   numerical request/completion readiness. Prove decode mutual exclusion,
   do not suppress architectural faults or accept a stale numerical result.
2. Revisit operand-mask fanout and word/shift/result selection together
   with RF/ID/IF capacity. Preserve eight stages, held offers, precise
   faults and the same-frequency O3 no-regression gate.
3. For bandwidth, isolate read-only retirement replacement from writes,
   then trace write service/arbitration phases using matched sparse AND
   dense Bare/Sv39 traffic. The mixed read/write replacement tested here
   is not ready for default enablement.

## 2026-10-15 batch11 — broad EX/numerical/frontend structural batch

User refinement: change the related long-chain family together, not two
small edits followed by another synthesis. This batch contains21
structural change points in four connected groups; these are NOT21
independent critical paths:

1. ID captures numerical legality, resolved FP rounding and integer
   source-present bits at existing ID/RF/EX boundaries. MDU request,
   FP request, MDU completion and FP completion use owner-local legality.
   Unrelated CSR/system read-legal logic and cross-unit completion
   conditions no longer belong in their ready/valid capacity. Precise
   architectural fault/cause/tval computation remains in EX -> WB.
2. Priority prefix OR is a reduction; nearest-writer ownership precedes
   value availability. Hazards and value masks share that owner, so a
   blocked youngest producer cannot fall back to an old same-rd value.
   Source qualification is predecoded, and payloads reduce in three-pair
   near/far groups instead of another priority chain.
3. Direction-shared left/right barrel, independent narrow32-bit W barrel,
   shared signed/unsigned comparator, parallel low/high/word-sign packing,
   and ALU result qualification before packing. The ALU is already zero
   for a non-ALU completion, avoiding another wide ALU selection gate.
4. Exact lookahead absorbs duplicate RF/ID/IF valid/permission factors,
   reply-space factors and pending-owner factors. No READY prediction,
   extra queue, extra stage or forced bubble. Runtime assertions compare
   every rewritten capacity/transfer with the original equation.
   New default-OFF read-only retirement mode permits only read-to-read
   CPU replacement; neither old nor new owner may be a store/atomic.

Stage count remains8, single issue; I/D2KiB, TLB4 per side, BTB128,
one CPU/cache D owner, two DDR bridge slots and one write credit.
The newly captured metadata costs at most12 functional bits for RV64FD
(6 each in existing RF/EX packets),6 without F, and zero without timing
cuts. Mapped FF/resource impact is measured by synthesis, not assumed
equal to those metadata bits. No pinned HardFloat arithmetic is changed.
Optional ISA features remain parameterized. Timing/retirement switches
default OFF; M retains its prior default ON.
Original OoO tree/defaults remain untouched.

### One batch of short acceptance, no per-edit synthesis

Initial `build/gsim/i1-fd-jtag-timing-20261015-r3/receipt.json`
records an RV32 elaboration failure: Chisel Bool padding is not a legal
wide UInt construction. Explicit zero concatenation fixes the same
comparison value; no oracle or architectural behavior was relaxed.
No synthesis was run for that failure.

Final95-gate receipt:
`build/gsim/i1-fd-jtag-timing-20261015-r4/receipt.json`,
SHA256 `25552b5ac310a68ff2c1a08a3d3e8089b091ec7965110d75921f9516a72ceead`.
The selected experiment explicitly enables both
`--overlap-data-retirement --read-only-data-retirement`, plus
registered fast data authorization; ordinary defaults remain unchanged.
Four32/64 x timing-off/on EX fixtures each pass44128 independent
software checks and a deliberate result-mutation negative. Every
nearest-owner availability mask is covered; it is not a DUT-derived
reference. All14 configuration tests pass.

True CPU FD2320 and F1120 corpora, FP context/FS/FCSR faults, disabled
ISA hardware, C/A, busy interrupts, late recovery, wrong older producers,
Sv39/PMP and JTAG retry pass. Registered numerical metadata equivalence
and exact frontend transfer assertions remain enabled throughout GSIM.
Bare R/W/COPY13053/20031/28808 and Sv3913045/20013/28894 are EXACTLY
unchanged, including authorization-OFF references. O3 no-C ROI
548351/725280 and C ROI663111/839844 are exactly unchanged at modeled
delays1/12, with the same architectural trace/CRC/instruction count.
Bandwidth: `build/gsim/i1-bandwidth-20261015-r2/receipt.json`.
C diagnostic: `build/gsim/i1-fetch-coremark-20261015-r2/receipt.json`.

### Dense bandwidth and separate WRITE intervention

`build/gsim/i1-retirement-dense-20261015-r4/receipt.json`
reuses the same compiled OFF/ON CPU models and unchanged normal dense
binary. Four independent guest-data negatives pass. It additionally
archives measurement source/assembly/linker, so later script edits do
not erase reproduction inputs.

| Dense8 CPU cycles, same binary | OFF | read-only ON |
| --- | ---: | ---: |
| Bare READ |9772|8842|
| Bare WRITE after READ |17349|17455|
| Bare COPY |25257|24414|
| Sv39 READ |9767|8783|
| Sv39 WRITE after READ |17180|17383|
| Sv39 COPY |25365|24360|

READ throughput improves10.52% Bare /11.20% Sv39; COPY payload improves
3.45%/4.13%. Whole-program cycles140566 ->138889 and140526 ->138736
improve while retirement and266/267 read +3077 write transaction counts
are identical. The sequential program's WRITE portion still varies
after accelerated READ; do not hide those values or call every phase
faster. A fresh-reset variant SKIPS the preceding timed READ, verifies
WRITE contents before COPY can overwrite them, and then runs COPY.
Isolated WRITE is EXACTLY17429 cycles in both Bare modes and17476 in
both Sv39 modes. This intervention plus the read-only boundary assert
supports a preceding-READ/service-phase explanation in this model,
not an intrinsic store-service regression; it does not establish a
universal arbitration law or a hardware bandwidth score.

### Combined STA

One complete300MHz synthesis has finished at
`E:\VM\Share\Valence-rtl\orbital-i1-fd-timing-20261015-r2`.
The target, RAM sizes and ownership credits are unchanged. The same-DCP
queries now compare ID/RF, EX, operand-hold, ADDR and CMP families as
well as prior EX-data/WB and FP/cache/MMU scopes. Their detailed paths,
native log and JSON are cross-checked; this is report reuse, not
additional synthesis.

Canonical synthesis receipt:
`build/fpga/i1-fd-timing-synth-20261015-r2/receipt.json`,
SHA256 `1fead5dcb7d65b20cb865ec3fc092ba25093970b5f0f95a85bcd286d785e24e6`.
Status remains `SYNTHESIS_SETUP_FAILS_300MHZ_ESTIMATE`.

| Same300MHz target/scope | Batch10 | Batch11 |
| --- | ---: | ---: |
| Overall setup WNS | -2.401ns | -1.659ns |
| Setup-failing endpoints |8407|6374|
| Setup TNS | -6766.498ns | -3268.334ns |
| EX result D-pin set | -2.222ns | -1.026ns |
| WB control-source set | -2.010ns | -1.197ns |
| ID/RF packet | -1.084ns | -0.407ns |
| EX packet | -0.377ns | +0.194ns |
| Held operands | -0.351ns | +0.189ns |
| ADDR packet | -2.282ns | -1.659ns |
| CMP packet | +1.642ns | +1.642ns |
| IF translation | -2.401ns | -0.692ns |
| I-cache | -2.157ns | -0.899ns |
| C aligner | -2.114ns | -0.602ns |
| D translation | -1.673ns | -1.495ns |
| D-cache | -0.477ns | -0.477ns |
| FP arithmetic S / D | -0.859 / -0.859ns | -0.145 / -0.619ns |
| FP miscellaneous S / D | -1.147 / -1.132ns | -0.269 / -0.259ns |
| CSR | +0.560ns | -0.082ns |
| Architectural next PC | +0.251ns | -0.019ns |
| LUT / mapped FF |38979 /18354|38898 /18366|
| BRAM36 / DSP |9 /28|9 /28|

Overall and the connected EX/WB/frontend families improve together;
CSR and architectural-next-PC scopes regress and are NOT hidden.
Global hold stays-0.348ns/134 endpoints; CPU hold stays-0.076ns/10.
Worst setup is EX rs1-index -> nearest-owner/operand -> branch compare
-> exception target selection/addition -> ADDR tval[63]:26 logic levels,
4.975ns total,1.457ns logic and3.518ns UNPLACED route estimate.
The rough synthesis-only estimate is200.32MHz rather than174.40MHz;
neither number is a physical clock qualification.

Stock OpenSBI short handoff and its independent wrong-handoff negative:
`build/gsim/i1-timing-opensbi-20261015-r2/receipt.json`.
23987000 cycles/5848115 retires,35 S-ecalls,1 S timer,72 MRET,
869 S retires and2750 UART bytes. The stock firmware image is unchanged.
Timer/poll phases alter the dynamic instruction stream and bounded
exit/UART tail; do not compare its cycle count as matched CoreMark or
claim identical instruction counts to the prior boot probe.

### User-requested physical follow-up

Reuses exactly `reports/synthesized_constrained.dcp`, SHA256
`819664b7249a9c4499e414bd0ee3edde6bbbebf8dad8f9f245eac8bea03ed862`.
No new synthesis or RTL edit. Flow: opt Explore, place Explore,
physical optimization AggressiveExplore, route Explore; max8 threads.
300MHz CPU and scoped USER2 event clocks/held-bundle constraints remain.
Routing uses an explicit hypothetical external BUFGCE_X0Y0 source for
the OOC clock input, not the board Clock Wizard's qualified location.
Output: package `physical-diagnostic/`, native
`vivado_route_diagnostic.log`. Implementation finished11:35:11,
read-only routed audit finished11:36:26. There was exactly one
opt/place/physical-opt/route flow, not another synthesis.

Canonical routed receipt:
`build/fpga/i1-fd-route-20261015-r1/receipt.json`,
SHA256 `e2b283cf16d2a687b5a261cc04bc4a470320015d1a1549ae8c5400e5a79d5a2e`.
Status `ROUTED_INTERNAL_OOC_FAILS_300MHZ_NO_BIT`.
Routed DCP SHA256:
`2f40ad2361f2e0a5c518cf942772ada61ca8778f0b302cf02f82da9fdf1bc1c7`.
Final reports are `physical-audit/` in the same Windows package.
`setup_cpu`/`hold_cpu` mean the CPU CLOCK DOMAIN, including
fabric and timed boundary I/O, not core-only paths. Register-to-register
results are separately named `setup_internal`/`hold_internal`.

| Same300MHz OOC flow | Setup WNS | Setup TNS |
| --- | ---: | ---: |
| Placed, before explicit physical optimization | -1.127ns | -3719.352ns |
| After AggressiveExplore, estimated | -0.806ns | -2840.054ns |
| Final routed, actual | -2.940ns | -5721.719ns |

11459 setup-failing endpoints remain. Global hold is-2.128ns/17,
while worst REGISTER-TO-REGISTER hold is+0.010ns. Worst pulse width
slack is+1.124ns, zero violations. Both JTAG held-bundle skew checks
pass:41-bit request+6.715ns and34-bit response+6.638ns. Scoped USER2,
positive qualifier banks and functional reset fences remain verified.
No_clock/unconstrained_internal_endpoints/generated_clock/loop and
all other native check_timing counts are zero.

All47543 routable nets are routed, zero routing errors. One explicit
OOC clock-net gap remains; a reopened DCP reports Partially Routed.
This is NOT a fully routed real board. Default OOC DRC has41 warning
checks (DSP pipeline suggestions and no-routable-load warnings), no
error checks; connectivity-based board DRC is not qualified.
Post-physical resources:39517 LUT,18657 FF,9 BRAM36 tiles,28 DSP.
Place4m01s, explicit physical-opt17m51s, route2m45s; eight-thread limit.

The final overall worst is a real INTERNAL fabric path:
bridge slot1 state[2] -> reply ownership/route/arbiter READY ->
slot1 index[0] CE. It is11 logic levels and6.067ns, including0.875ns
logic and5.192ns route. Two final routed nets alone take1.498ns and
1.738ns. It is NOT valid to dismiss that negative setup as an I/O-only
report, or claim the FPU alone is the bottleneck.

However, the raw AXI boundary uses a zero-delay synchronous placeholder:
worst global hold starts at `io_ddrAxi_r_bits_id[0]`, reaches
bridge `arIssued_1` in0.052ns, but has2.120ns destination clock
insertion and zero launch insertion. The router explicitly identifies
222 pins as both setup-critical and hold-critical, fixing hold at the
expense of setup. Shared index-control pins occur in that warning.
This is evidence of a setup/hold optimization conflict in the current
OOC context, not a controlled proof of how much of the6.067ns disappears
with real CDC registers. Do NOT invent input delays, waive internal
paths, or infer board Fmax from these placeholders.

| Additional routed destination scope | Setup WNS |
| --- | ---: |
| EX -> ADDR exception tval[63] | -1.525ns |
| I translation | -1.345ns |
| FP arithmetic D / S | -1.334 / -0.612ns |
| D translation | -1.235ns |
| FP miscellaneous D / S | -0.945 / -0.849ns |
| C aligner / D-cache / I-cache | -0.876 / -0.875 / -0.836ns |
| ID/RF / EX packet | -0.666 / -0.536ns |
| Architectural next PC / CSR | -0.504 / -0.500ns |
| Held operands / CMP | -0.475 / +0.108ns |

Core-only EX/FPU paths also fail, so boundary modeling alone cannot
justify300MHz. Do not promote the pre-route-0.806ns estimate to a
physical result or run repeated seeds hoping these families vanish.
Next structural batch should address bridge response/READY ownership,
EX exception payload selection independent of branch resolution,
PMP/TLB physical-address preparation and FPU fused-sum/output packing
together, retaining precise faults and same-frequency matched gates.
This follow-up is not implemented by the physical-only experiment.

User added the next delivery requirement: once qualified, integrate the
complete independent board SoC, actual DDR4 MIG/AXI CDC/clock IP and
existing board XDC, then run full-board timing and generate a bit for
board testing. Original OoO project remains untouched. The present
nominal UART/timebase is100MHz despite300MHz STA: real-board clock
selection MUST update UART divisor, BootROM, DT and firmware timebase
together. OOC success would still not qualify MIG, clocks, DDR pins or
a bit; the present experiment does not even meet the internal300MHz
setup prerequisite, so no board implementation or bit was launched.

## 2026-10-15 batch12 — real TL-C, isolated peripheral clocks, 300MHz remains mandatory

Work remains confined to /home/openion/Valence-inorder,
branch feat/orbital-i1-five-stage. The original OoO worktree is unchanged.
CPU target is300MHz (10/3ns); there is NO new timing closure or bit.
The selected core is still the parameterized8-stage fpga8 profile,
not a claim that a compact5 configuration meets300MHz.

Implemented composition, all opt-in:

- --coherent-caches selects real private I/D write-back caches:
  AcquireBlock(nToT), GrantData/GrantAck, Release/ReleaseData,
  ProbeBlock(toN), ProbeAck/ProbeAckData. Resident lines exclusively own T.
  B/C/E are NOT tied off at the CPU caches. The Home terminates coherence;
  its DDR backing port legitimately uses TL-UH.
- --coherent-ways=1 or2 selects associativity at UNCHANGED byte capacity.
  I/D capacities must initially be equal, RV64,64-byte lines, at least two
  sets. Default coherence OFF; coherent ways defaults to1. The measured
  network candidate explicitly selects2KiB+2KiB,2ways, not larger caches.
- Bounded directory size equals combined I+D line capacity:64 entries
  for2KiB+2KiB. Directory ways equal the two clients' combined associativity
  (2 or4). It does NOT allocate a directory entry per2GiB DDR line.
  The Home remains a serialized baseline, not a nonblocking multi-MSHR
  coherent fabric or a maximum-bandwidth design.
- Shared atomic/DMA exclusion sits BEFORE the Home. Uncached instruction
  reads, CPU atomics, JTAG and network DMA all see dirty D-cache data.
  Atomics occur after translation/PMP. Reservation clearing includes
  context changes, ordinary CPU stores, probes and matching-line DMA writes.
  Native lane versus right-justified atomic operands/results is explicit.
- Invalidate/FENCE.I maintenance releases ALL valid lines, including clean
  owners; a clean flush cannot leave a phantom Home directory owner.
- --soc-fabric-cuts inserts independent2-entry registered queues on ALL
  five private TL-C channels, plus the DDR-facing A/D timing boundary.
  B/C/E can progress without depending on A/D queue readiness. Queues add
  channel latency, not extra CPU miss owners or DDR write credits.
  DDR remains2 transaction slots and1 write slot.
- EX fault tval selection is now based on registered instruction class,
  independent of resolved branch-taken/misaligned reduction. A runtime
  assertion compares every actually faulting packet against the previous
  precise tval expression. Compressed PC+2 and ordinary PC+4 are calculated
  in parallel before selection. Non-cut profiles retain the previous logic.

I1NetworkFpgaShell connects the existing managed peripheral bank,
tri-speed MAC and Ethernet packet DMA. --soc-network requires coherent
caches, managed UART/CMU and PLIC. CPU clock is separate from AON/UART50MHz,
MAC TX reference125MHz, recovered RX clock, and external DDR UI250MHz.
The MAC handles10/100/1000 full duplex through its existing speed/drain
policy; RX frequency follows the PHY. CPU300MHz is NOT imposed on PHY IO.
CMU defaults, quiesce-before-gate and persistent receive/wake paths are
reused. No CPU DFS, unilateral hot-reset recovery or new10G MAC is claimed.

| I1 network window / IRQ | Assignment |
| --- | --- |
| UART | 0x10000000, PLIC3 |
| Boot status | 0x10002000, unchanged |
| USER2 boot JTAG | 0x10003000, unchanged |
| Network DMA | 0x10005000, PLIC6 |
| MAC/MDIO | 0x10040000, PLIC5 |
| CMU | 0x10080000, PLIC7 |

Network DMA was deliberately NOT placed at the OoO platform's0x10002000,
because that aliases I1 boot status. Software/DT must use this I1 map and
PLIC contract; the old OoO Linux image must not be assumed compatible.
The existing4KiB I1 BootROM still offers its boot-owned JTAG/CRC path;
adding MAC hardware does not implement TFTP or UART program download.
General-purpose DMA has not been connected by this batch.

### Independent short evidence and actual CPU cost

Initial direct-mapped TL-C candidate passed byte/protocol checks but
COPY regressed badly. This result is PRESERVED, not promoted:
build/gsim/i1-coherent-network-20261015-r1/receipt.json,
SHA256 c23e71c7ce2231fc6e837a515fedf75c542e2d9d163d2bd4e1117d6012a6cc14.
The two COPY buffers conflict in direct-mapped write-allocate sets.
Same-capacity2-way caches reduce Sv39 COPY157382 ->34645 cycles.

Matched CPU results (same payload, random AXI service/backpressure,
2KiB+2KiB,8-stage RV64IMAFDC/Sv39/PMP8/BTB128):

| 8192-byte loop | Legacy Bare | TL-C2way Bare | Legacy Sv39 | TL-C2way Sv39 |
| --- | ---: | ---: | ---: | ---: |
| READ cycles | 15063 | 18935 | 15080 | 18896 |
| WRITE cycles | 22046 | 19354 | 22087 | 19346 |
| COPY cycles | 32928 | 34453 | 32896 | 34645 |

These are GSIM cycle counts, NOT measured300MHz bandwidth.
Sv39 READ is25.3% more cycles, WRITE12.4% fewer, COPY5.3% more.
Coherence/timing isolation is useful functionality, but this is NOT an
across-the-board performance improvement or a final throughput candidate.
ROI excludes host readback. Write-back tails are not explicitly drained
inside these existing software timed regions; do not call these flush-
inclusive streaming figures. Correctness reads back through a REAL
coherent DMA port after ROI, then retains the original full backing-byte
oracle. No private-cache peeks or relaxed software expected values.

Throughput/parameter/CHIRRTL receipt:
build/gsim/i1-coherent-network-20261015-r2/receipt.json,
SHA256648b37c2890a6b681cceee79b1edc232e4d50f4ce57119779ee5c309da3688a4.
15 parameter checks pass; explicit bad-data/checksum negative controls
are rejected. Cut and uncut dual-cache tests cover sustained hits,
response stalls, hit-under-miss ordering, dirty migration, DMA read/write
invalidation, clean/dirty flush and repeated bounded-directory aliases.
Register cuts add4 cycles to dirty-owner migration (41 ->45).

Further pair-only atomic/DMA integration:
build/gsim/i1-coherent-network-20261015-r4/receipt.json,
SHA2569e03d5fac23a9d8f87e9c9c7cd8516501b53e78f41d4dc0d373c2fbe08a8585c.
All three pair profiles pass through the same shared atomic/DMA boundary
as production: DMA between LR/SC forces failure without changing its data,
uncontended SC succeeds, AMOADD waits for the real write reply, and LR.W/
SC.W at byte offset4 preserve the other32 bits.249 production Scala/build
hashes match the CPU-throughput qualification exactly. r3 is a preserved
failed test-fixture attempt: its RAM incorrectly required only size3;
the naturally aligned W access assertion was added before r4.

Precise exceptions and C/A supplemental acceptance:
build/gsim/i1-coherent-completion-20261015-r1/receipt.json,
SHA25612f0f935b53bef9a765ddef7b1329ab3c3f5d2f07eb7d11b8a9ab85a2a94b005.
Fresh exact FIR matches both saved CPU models before reuse.
M/S/U, delegation, PMP, Sv39/Svade, MPRV/SUM/MXR/SFENCE, PLIC S,
compressed page-end faults, W/D LR/SC and AMO/aq/rl/fence pass.
Both independent completion-ledger mutations are rejected.
F/D hardware is enabled in these models but these payloads are integer:
the prior FP numerical/context receipt is not new coherent-FP acceptance.

Short native xsim, CDC ONLY:
E:\VM\Share\Valence-rtl\orbital-i1-network-cdc-20261015-r1\receipt.json.
PASS_MANAGED_CLOCK_GATE_CDC_SHORT, actual BUFGCE,3 clock cases,
pulse-width/retention checks and independently wrong stopped-clock
negative control. This validates shared gate/handshake machinery, NOT
the complete network datapath, actual DDR AXI CDC, RGMII board IO,
full CMU firmware or any300MHz physical timing.
The receipt/logs are also archived in WSL at
build/fpga/i1-managed-clock-cdc-20261015-r1/xsim/.
Receipt SHA256:
5a8e9aa567846a1c61352e1781358e14e8d8b7bb9cc1875bc54ac94398cb8e15.

### Remaining delivery gates

1. Keep300MHz /10/3ns hard target. The last ACTUAL routed result is still
   batch11 setup-2.940ns; it predates this fabric and cannot qualify it.
   MMU/PMP, FPU post-multiply normalization/packing and other reported
   core families remain open. Do not hide them with I/O exceptions,
   false paths, slower clocks or an untested numerical rewrite.
2. Reduce remaining coherent read/refill/control overhead without growing
   capacity. Maintain the measured timing-cut latency/IPC ledger.
3. Complete coherent F/D state-memory, fault/backpressure and active
   MAC/DMA/PLIC system validation. Backing dirty-writeback errors retain
   a fail-fast assertion assumption, NOT a demonstrated hardware recovery
   policy; implement/report a production fatal-error policy before claiming
   robust memory-error handling.
4. Export the NEW tested network profile with all blackboxes and real
   SRAM attributes, check actual BRAM inference and USER2 CDC constraints.
   Current synchronous bank declarations alone do not prove BRAM binding.
5. Real board MMCM/BUFG, DDR AXI CDC/MIG, RGMII IOB and manufacturer XDC
   remain outside this new shell. Coordinate reset with accepted AXI/DMA
   owners. Set300MHz CPU firmware/DT timebase and50MHz UART domain divisor
   consistently, then qualify routed setup/hold/CDC/RGMII/DRC before bit.
   No new Vivado run, board signoff or bit was launched in this batch.

## 2026-10-15 batch13 —32KiB I/D and a combined RAM/PMP/FMA timing batch

Selected integration profile: fpga/inorder/network32-profile.json.
I-cache32KiB + D-cache32KiB,2ways,64-byte lines;1024-entry/4-way
combined-capacity directory. CPU fpga8 /300MHz, RV64IMAFDC, Sv39,
PMP8, TLB4, BTB128, tiled DSP integer multiply, native tri-speed MAC,
managed UART/CMU and USER2. Generic ISA/cache defaults remain removable.
DDR transaction slots stay2, write slots1; no extra CPU MSHR.

Combined hardware changes:

- Private-cache tags use two single-query256x19 asynchronous RAM banks
  instead of512-entry register/mux payloads. Probe has lookup priority;
  CPU, probe and flush share the query set. Data remains synchronous,
  eight512x64 byte-enabled banks per cache, unchanged hit II1.
- Home tag/owner payload uses four single-query256x20 RAM banks. Its
  physical set bits are implicit in the RAM address, not duplicated in
  every stored tag. Only the selected acquisition, ordinary request,
  probe completion, release or GrantAck consumes this read. Assertions
  verify that every consuming edge owns the shared query address.
  Directory capacity still equals I+D lines, not DDR capacity.
- Cacheability for the real, unaligned2GiB DDR aperture uses a constant
  window decoder plus a three-bit end-lane check. It no longer cascades
  a65-bit address-length addition into range compares on SRAM admission.
  An assertion preserves COMPLETE access length, including malformed
  unaligned input near the aperture end.
- Timing-cut PMP queries split page-low arithmetic from high-bound
  comparisons. A parallel exact power-of-two carry predicate preserves
  unaligned overlaps, lowest-region priority and the exclusive PA limit.
  Runtime equivalence assertions and an independent software full-
  interval oracle cover both RV32 and RV64.
- The LOCAL pinned-HardFloat FMA postMul equations are cut at sum,
  absolute significand, and normalization distance. Guard/round/sticky,
  cancellation and exceptional classes are retained without intermediate
  rounding. Fixed third-party sources are unchanged. FMA request latency
  is now exactly15 versus12 cycles; ordinary multiply remains11.
  Flush kills all added valids. This does not change the CPU's named
  eight-stage architectural pipeline into a15-stage scalar pipeline.

Canonical short receipt:
build/gsim/i1-coherent-network-cache32-20261015-r4/receipt.json,
SHA2566ee61062ae6af556d5b8ba0ebd2102ff9723cc874805b17855d846ecb486b278.
Each PMP width passes65536 independent queries and a wrong-permission
negative control. F-only and F+D each pass27840 independent SoftFloat
vectors, all flags, full tokens, held replies, exact latency/II and
stage-flush checks; value mutations are rejected. Instruction/data MMU
short suites pass289/447 cases. Full32KiB private capacities are filled
concurrently and all1024 dirty lines are read through coherent DMA.
Small1/2-way/cut/uncut cases also pass, including DMA versus LR/SC.

The first full run r3 passed before a physical-attribute compatibility
fix: firtool rejects AttributeAnnotation directly targeting a Mem.
Those two source annotation sites were removed; the real emitted
Memory arrays are now styled by the hash-bound exporter. Fresh r4 FIR
must match r3 EXACTLY, including source locators and all functional
statements, ignoring ONLY those specifically named RAM hints. Only
after this proof are hashed GSIM model objects reused; ALL short tests
and negative controls are rerun, not marked passed by inheritance.
Earlier compile/PMP carry-expression failures r1/r2 remain archived.

### Same-service CPU measurements, not physical bandwidth

Both capacities use the SAME new hardware, code, clock target and
randomized AXI service law (3..15-cycle initial response/backpressure).
The2KiB rows retain the previous throughput cycles exactly, so RAM
conversion and PMP cuts did not add scalar cycles. Each entry below
is READ / WRITE / COPY cycles:

| Working set per buffer | Mode | 2KiB+2KiB | 32KiB+32KiB |
| --- | --- | ---: | ---: |
| 8KiB | Bare | 18935 /19354 /34453 | 11325 /15084 /16593 |
| 8KiB | Sv39 | 18896 /19346 /34645 | 11337 /15074 /16593 |
| 64KiB | Bare | 142192 /162867 /272635 | 160720 /144287 /281862 |
| 64KiB | Sv39 | 142122 /162688 /272872 | 160580 /144181 /281943 |

8KiB Sv39 COPY improves2.088x. This small working set fits the enlarged
caches; it is NOT a DDR streaming claim.64KiB exceeds32KiB D-cache;
READ regresses12.99%, WRITE uses11.38% fewer cycles, COPY regresses3.32%.
Total guest completion improves741071 ->729063 cycles (~1.62%).
The existing timed regions do NOT explicitly drain write-back tails;
different eviction/drain scheduling also affects these per-phase costs.
Real coherent host readback and the original full-buffer byte oracle
are outside ROI. Do not convert these counts into measured300MHz board
bandwidth or claim a universal16x-capacity performance gain.

Physical export:
E:\VM\Share\Valence-rtl\orbital-i1-network32-20261015-r2.
Top I1NetworkFpgaShell, exact CHIRRTL matches the short receipt.
Actual data_512x64 arrays bind block RAM; tagBanks_256x19 and
directoryBanks_256x20 bind distributed RAM; RF/FPR and BootROM bind BRAM.
The combined synthesis below confirms these physical mappings. The
unchanged USER2 pin-event/CDC short receipt is hash-checked on export.

### Combined synthesis: RAM mapping passes,300MHz does NOT

One actual synth_design completed in about10m07s. Report generation was
resumed from that checkpoint after supplying a missing JTAG-check helper
and replacing unsupported XDC loop syntax with declarative constraints.
The hardware was NOT synthesized again. Hash-bound diagnostic evidence:
build/fpga/i1-network32-synth-20261015-r1/receipt.json,
SHA25651485e4b091bbbdcb3e6ea8ad5ab977b8d386a95a4f0aa89ec5cd4898364fd76.

The unplaced I1NetworkFpgaShell uses80,895LUT (23.70%),48,633FF (7.13%),
26RAMB36 +1RAMB18 (26.5tiles,3.56%),28DSP,0URAM. Each32KiB private
cache occupies8RAMB36,16combined; RF2, FPR3 and BootROM1 map toBRAM.
Tag/directory RAM payload has0FF; valid/dirty/replacement metadata is
still registered and is NOT claimed as all-BRAM metadata.

CPU-only setup WNS=-9.373ns at3.333ns,12.688ns estimated data delay,
43logic levels. Critical source:
soc/fabric/ordinary/order/deq_ptr_value_reg[1]/C;
endpoint: soc/core/dt/state_reg[2]/D. The path passes through ordinary
return ownership, uncached I-side response/admission, private-cache
lookup, atomic/Home directory admission and D-MMU control. This is a
cross-module combinational handshake chain, not evidence that32KiB
data BRAM itself requires12.688ns. No place/route or bit was attempted.
Read the archived setup_cpu_synth.rpt, not an old pre-TL-C checkpoint.

CDC constraint APPLICATION matches2register bridges,9mailboxes,3gray
FIFOs,62level synchronizers and3held FIFO payloads; this is NOT CDC
signoff. report_cdc still lists CDC-1:2, CDC-10:7, CDC-11:37critical
patterns, mainly reset release, duplicated level synchronization and
held-mailbox structures, requiring explicit per-instance review.
No generic waiver/blanket asynchronous clock group was added.
check_timing reports0unclocked/internal-unconstrained endpoints and
0combinational loops, but partial input delays remain for externalIrq
and mdioIn. Board MMCM, MIG/AXI CDC, RGMII IOB timing and DRC remain
outside this OOC shell and are not qualified by its resource report.

## 2026-10-15 batch14 — native ownership cuts and bounded line buffers

Follow-up to the actual batch13 critical chain, without growing caches,
MSHRs, DDR slots or write credits:

- With fabricTimingCuts only, independent two-register request/reply
  boundaries separate EACH private uncached port from CPU arbitration,
  atomic exclusion from Home, and Home ordinary backing from TL reply
  ordering. Ready is local occupancy-only, no empty bypass; II1.
  A real downstream response is still required for EVERY write ack.
  Each boundary adds at least1request +1reply cycle on that path.
  Cache-hit and coherent line-refill paths do not traverse these native
  boundaries. Uncached/MMIO/AMO paths pay explicit latency instead.
- Private Acquire buffering4->2; serialized Home transfer/probe engines
  each4->2. These parent state machines have one line/probe owner,
  not four independent outstanding line transactions. Two is the shared
  engine minimum. This removes unused512-bit FF storage without
  changing the generic shared engines or the original OoO core.
- The pair fixture includes the SAME three native-boundary locations.
  Independent short tests now include real CPU C/A/LRSC/AMO, precise
  M/S/U/Sv39 faults, and F/D numerical/context-memory completion using
  coherent DMA to retrieve dirty ledgers, not direct backing reads.
  FP programs park after their final completion trap so that readback
  cannot race a later fail-handler write. No DUT force/flush is used.
- GSIM object reuse requires exact fresh FIR identity. Genuinely changed
  pair/CPU models are newly generated and compiled; unchanged numerical
  and PMP/MMU models are hash-verified and all checks/negatives rerun.

Canonical batch14 receipt:
build/gsim/i1-coherent-network-cache32-return-cuts-20261015-r4/receipt.json,
SHA256644d5840f49284d52abaff3d0a3ca6086099ee6d9e6627de96dd033ee858bf84.
All46named short checks (including independent negative controls) and
15Scala configuration tests pass. Six unchanged models have exact FIR
identity; all6changed pair/CPU models were regenerated/compiled.
Both capacities retain EXACT batch13 READ/WRITE/COPY cycle counts for
all8KiB/64KiB Bare/Sv39 rows above, including guest AXI traffic counts.
This proves no regression for these workloads, NOT zero AMO/MMIO cost.

The real32KiB CPU additionally passes2,320SoftFloat-backed numerical
cases (497,774cycles,39,466retired,8,560FPR writes) and32FPR context
save/restore with FS/SD/FCSR, compressed FP accesses, MPRV/Sv39, precise
illegal/page/access faults and injected memory errors (5,616cycles,
9traps). Completion data is verified by actual coherent DMA readback.
This is NOT Linux floating-point context-switch validation.

Earlier r1/r2 are retained compiler-selection startup failures (the
project variable is GSIM_CXX, not CXX). The first supplemental32KiB C/A
run r3 exposed an undefined empty-FIFO lane value in the GSIM C++ shift
path. I1DmaRegisterDataAdapter now selects lane0 unless an owner is valid.
No generated simulator patch, sanitizer suppression or ignored failure
was used; r4 reruns all checks with ASan/UBSan enabled and C/A passes.

The exact passing network shell has been exported to
E:\VM\Share\Valence-rtl\orbital-i1-network32-returncuts-20261015-r1.
One combined follow-up synthesis completed successfully in10m35s,
with4actual native-boundary instances checked in the synthesized
netlist. All checkpoint/resource/JTAG/CDC-constraint-application report
gates complete; this does NOT mean timing or CDC signoff passes.
Final diagnostic receipt:
build/fpga/i1-network32-returncuts-synth-20261015-r1/receipt.json,
SHA2567cfdb81cc51f3eec8c19df14c9dbf3e0de556771624f73ea46ab7f140b4c1fe8.

| Same32KiB+32KiB full network shell | Before native cuts | Batch14 |
| --- | ---: | ---: |
| CPU300MHz synthesis setup WNS | -9.373ns | -3.932ns |
| Longest data path estimate | 12.688ns | 7.161ns |
| Longest logic levels | 43 | 22 |
| LUT | 80,895 | 77,272 |
| FF | 48,633 | 44,293 |
| BRAM36-equivalent tiles | 26.5 | 26.5 |
| DSP | 28 | 28 |

That is5.441ns better WNS,3,623fewer LUT (~4.48%) and4,340fewer FF
(~8.92%), with unchanged measured streaming cycle counts. Each private
cache still occupies8BRAM36; tag/directory payload remains0FF.
These are UNPLACED estimates, not achieved operating frequency.
300MHz remains FAILED. No placement, routing or bit was launched.

The new worst chain starts at
soc/core/icache/coherent/cache/state_reg[1]/C and ends at
soc/core/core/offerPc_reg[0]/CE:
cache response qualification -> aligner/I-MMU next request selection ->
asynchronous cache tag lookup/miss admission -> upstream ready ->
front-end PC enable. Returning to a different bottleneck is expected
after eliminating the ordinary/atomic/Home chain, not signoff success.

Remaining setup endpoint families, same synthesis/constraints:

| Family | WNS | Required next structural review |
| --- | ---: | --- |
| Fetch/offer-PC | -3.932ns | Separate reply completion from next-lookup admission; measure branch/IPC cost |
| Private-cache state/dirty | -3.632ns | Shared tag/way lookup, state fanout and metadata write qualification |
| Network DMA control | -2.734ns | TX-length to RX-state/credit handoff, not a larger data buffer |
| Home directory | -1.329ns | Lookup/qualification and per-operation ownership control |
| GMAC CSR | -0.828ns | MMIO decode plus64-bit statistics-counter carry chain |
| FPU input | -0.352ns | Operand recoding before the first tiled-DSP input |

Do NOT claim only the fetch module remains. Next work should batch the
remaining admission/feedback/control families and rerun the same byte
oracles/latency/throughput checks before another combined synthesis.

CPU hold WHS is-0.075ns; global hold WHS is-2.473ns, on raw UART ingress
to the gated UART clock. The report estimates2.635ns raw-versus-BUFGCE
clock skew. This is NOT merely an unconstrained I/O/zero-delay artifact.
Balanced real clock-buffer placement and routed hold closure remain
mandatory; do not hide this clock-tree boundary with a false path.
CDC-1:2, CDC-10:7, CDC-11:37patterns and the2partial input delays remain
as above, not waived. Actual board MIG/AXI CDC/RGMII/clock IP and DRC
are still outside this shell. Physical/board qualification remains false.

## 2026-10-15 batch15: occupancy-only fetch, split cache/Home lookup and device timing cuts

The explicit I1 integration option --coherent-control-cuts remains OFF by
default and requires coherent caches plus --timing-cuts. Generic ISA/cache
parameters and compact5/balanced7/fpga8 remain independently selectable.
This candidate retains fpga8, RV64GC/Sv39/PMP8/BTB128/TLB4, I/D32KiB each,
two ways,64-byte lines, DDR2slots/1write slot and four credits per originating
network/loader adapter. The original /home/openion/Valence worktree, OoO
core and fixed HardFloat sources are not modified.

The combined structural batch comprises:

- Read-only instruction-cache admission uses occupied response slots, not
  the new physical address/tag, to decide READY. It permits the final older
  hit reply and a next request on the same edge, so no additional word-fetch
  stage is needed. A stalled uncached offer is captured into bypassSend;
  no store/AMO or older-reply overtaking is permitted.
- CPU/flush and B-probe tag RAM queries have separate read ports. Per-way
  hit/dirty selection and compact eviction qualification avoid a dynamic
  selected-slot/tag reread feedback. This is additional read-port logic,
  not additional cache capacity; physical LUTRAM cost is measured separately.
- The Home foreground request and maintenance directory lookups use separate
  RAM read ports. Owner decode is a parallel per-way one-hot selection;
  grant/probe/release/writeback operations retain their proper maintenance
  lookup and actual acknowledgment conditions.
- The production network/loader front end now has optional request/reply
  cuts before arbitration and before the shared atomic exclusion point.
  There are7native timing boundaries in the selected shell, formerly4.
  This does not increase CPU MSHRs, DDR slots or per-device credits.
- UART and retained MAC-TX control/ingress use an actual continuously
  running BUFGCE parallel to their managed BUFGCEs. Raw and gated leaves
  share the same pre-global-buffer root, never a cascaded BUFG. The physical
  gate checks5actual buffers and matching roots and assigns CLOCK_DELAY_GROUP;
  this is not a hold exception or a routed hold guarantee. Board clock-IP
  integration must preserve this root contract.

Canonical short evidence:
build/gsim/i1-coherent-network-control15-20261015-r2/receipt.json,
SHA2565be2974f4460408555d24e8ad80375f31c269279ccd7118647ad8e6f8616fb9c.
All56named affected checks/negative controls and15Scala configuration
tests pass with ASan/UBSan. Independent device tests exercise1,200mixed
subword transactions, four live credits per origin, held requests/replies,
36injected error replies and the full final byte ledger. Direct/cut versions
take2,861/3,303cycles under the same adversarial service: a15.45%cycle cost
for those device transactions. This is not hidden as zero DMA latency cost.

All eight2KiB/32KiB x Bare/Sv39 x8KiB/64KiB CPU streaming rows retain the
batch14 READ/WRITE/COPY cycle counts and AXI traffic exactly. Actual32KiB
CPU F/D2,320cases and32FPR context/fault cases also retain497,774/5,616cycles.
The new self-modifying/FENCE.I/branch/JALR wrong-path fixture verifies
retirement and the final full byte image via real coherent DMA, not force
or a direct dirty-cache peek.

The same new standard2000-byte, one-iteration O3 CoreMark binary is run
on the current32KiB model and the hash-verified frozen batch14 hardware:

| Actual coherent SoC, same image/service | Frozen batch14 | Batch15 |
| --- | ---: | ---: |
| ROI simulator cycles | 856,199 | 856,199 |
| ROI retired instructions | 345,517 | 345,517 |
| ROI IPC | 0.40354754 | 0.40354754 |
| Whole-program retired instructions | 367,211 | 367,211 |
| CRC final | 0xe714 | 0xe714 |
| Retired PC/instruction trace FNV64 | 7b173819116883a2 | 7b173819116883a2 |

Every retired register value, PC, instruction, next PC and final8KiB RAM
image is checked by the independent ISA/byte oracle. This is NOT a formal
CoreMark score: the official <10second warning is preserved, its validated
banner must be absent, and the official known CRCs are checked independently.
No fake elapsed time is supplied to obtain a validation banner.

The retained r1failure is diagnostic evidence: its request-only IF queue
added one word-fetch cycle and regressed streaming WRITE about10%. That
queue is removed in r2, not accepted as an IPC cost. Its added CoreMark
checker also incorrectly expected the official >=10second validation
banner in a short run. The corrected r2 records the duration warning and
does not weaken the CRC/retirement oracle.

The balanced-clock xsim proof is at
E:\VM\Share\Valence-rtl\orbital-i1-control15-20261015-r1\clock-xsim\receipt.json,
SHA25616492864fa87d09e5dc5b9cae381cab99e8616d22890e7d51c04344beb2e6804.
It exercises actual vendor BUFGCEs at three asynchronous raw rates, busy
drain, canceled stop, stopped-clock wake, missing source clock, cold reset,
and ordered64-bit mailbox transfer/backpressure/reset epochs. Independent
wrong-clock and mailbox-data mutations are rejected. It does not qualify
every GMAC CDC instance, warm reset tree or RGMII pin.

CDC Critical inventory is now explicit and checked against the report
header/detail counts. Held/captured mailboxes, common-reset fanout,
combinational warm-reset trees, BSCAN reset OR trees and duplicated
persistent-level synchronizers remain REVIEW_REQUIRED, never waived.
Unknown patterns or missing report rows are rejected; five audit tests
cover unknown paths, wrong bit pairing, missing details and the rule
that a classified registered warm-reset path remains unresolved.

One exact tested export is at
E:\VM\Share\Valence-rtl\orbital-i1-control15-20261015-r1\rtl.
One combined300MHz synthesis completed in9m45s, with0errors and0critical
synthesis warnings (ordinary warnings remain). Structural/RAM/JTAG/CDC
constraint-application gates pass, not timing or CDC signoff. The exact
source/export/short-test hashes and reports are archived in WSL:
build/fpga/i1-network32-control15-synth-20261015-r1/receipt.json,
SHA256c275380a63ba0634c578813b4481bdcc2175493dcb72f6a6608e7b744df88ae0.
The4.3MiB archive includes the small physical reports and actual clock
and USER2 xsim proof artifacts; the27.8MiB constrained checkpoint stays
in the shared RTL package. Original short/synthesis failure evidence
is preserved, not overwritten.

| Same32KiB+32KiB network shell, unplaced | Batch14 | Batch15 |
| --- | ---: | ---: |
| CPU300MHz setup WNS | -3.932ns | -2.594ns |
| Worst CPU data-path delay | 7.161ns | 5.909ns |
| Worst CPU logic levels | 22 | 20 |
| Private-cache endpoint WNS | -3.632ns | -2.106ns |
| DMA endpoint WNS | -2.734ns | -0.822ns |
| Home/directory endpoint WNS | -1.329ns | -1.374ns |
| LUT | 77,272 | 76,612 |
| FF | 44,293 | 43,991 |
| BRAM36-equivalent tiles / DSP | 26.5 /28 | 26.5 /28 |

CPU WNS improves1.338ns while the measured CPU cycle counts/IPC remain
unchanged; LUT/FF fall660/302. Each cache still occupies8BRAM36, with
zero tag/directory payload FF. Do not claim the Home family improved:
its new worst chain is lineTransfer reader/sendQueue -> writer activeData
enable, slightly worse than the old directory lookup endpoint. FPU
arithmetic endpoint WNS is-0.021ns in this mapping, not a new FPU logic
change or a routed result.

The current worst chain is:
soc/core/dt/state -> demand/PTW arbitration -> D-cache asynchronous tag
lookup and request READY -> D-MMU state. Its20logic levels and5.909ns
estimated delay are still far from3.333ns. Cache replacement metadata
also remains at-2.106ns. CPU scalar EX rs2/forwarded operand -> nextPC
remains-1.301ns; DMA status-counter/credit logic is-0.822ns.
The old TX-length -> RX-state arbitration chain is no longer worst,
but DMA is not fully closed.

Hold is deliberately reported in distinct scopes. A READ-ONLY query
of the two existing constrained checkpoints adds no constraints,
exceptions, synthesis, optimization, placement or route:

| Hold scope, same checkpoint contracts | Batch14 | Batch15 |
| --- | ---: | ---: |
| UART retained raw ingress -> gated UART | -2.473ns | -0.037ns |
| All internal sequential endpoints | -2.473ns | -0.348ns |
| CPU-only register-to-register | +0.006ns | +0.006ns |
| Global including OOC input budgets | -2.473ns | -2.701ns |

The remaining internal worst is USER2 INTERNAL_TCK -> TDO, not CPU.
UART clock-tree skew in its worst reported hold path falls from2.635ns
to0.152ns (different worst corners); its-0.037ns is STILL NOT PASS.
The new global-2.701ns is io_uartRx -> sampledRx_meta with a declared
zero-delay OOC input and a buffered destination clock. This is distinct
from the old internal raw/gated path, not permission to ignore it.
Actual asynchronous-input treatment, board budgets and routed hold
remain required. CPU clock-group min query is-0.075ns because it includes
io_clockLocked input; do not mislabel it register-to-register hold.

The CDC report still has CDC-1:2, CDC-10:7 and CDC-11:37, all46entries
retained as REVIEW_REQUIRED with no waivers. Four warm-reset OR paths
now explicitly name the CPU-domain media/ingressResetSource register;
the MAC reset-release recovery endpoint is-1.025ns. First audit correctly
stopped on these changed source patterns; source inspection identified
them and the revised classification still does NOT sign them off.
Common-reset fanout, duplicate quiesce/media synchronizers, the held
mailbox instances and BSCAN reset OR trees need their own instance-level
protocol/reset proof and scoped constraints. Existing short mailbox/
BUFG tests are not a blanket waiver for these paths.

check_timing reports0clockless registers,0unconstrained internal maximum
endpoints and0loops, with2partial input delays still present. Those
checks do not establish complete board constraints. Full MIG/AXI CDC,
RGMII IOB, actual clock IP, routed setup/hold and board DRC remain outside
this shell. No placement, route or bit is launched:300MHz remains FAILED.
Next combined batch should address D-MMU/D-cache admission, cache
replacement/metadata fanout, lineTransfer read-to-write ownership,
DMA status carry and the reset/reconvergence/TDO boundaries together;
retain the same capacity, real completion conditions and CPU performance
oracles rather than adding queues indiscriminately.

## 2026-10-15 batch16: bounded Home write cohorts and measured coherent bandwidth

New --coherent-bandwidth / coherentBandwidth defaults OFF and requires
the explicit coherent-control timing profile. This batch keeps fpga8,
RV64GC/Sv39/PMP8/BTB128, four I/D TLB entries, I/D32KiB each, two ways,
64-byte lines, two DDR slots and ONE AXI write slot. Each network/loader
origin retains four credits. No cache/MSHR/TLB or transaction expansion,
posted write success, OoO-core change or HardFloat-source edit is used.

The combined structural changes are:

- The physical D-cache owner now uses occupancy-only ordered admission.
  The next address/tag does not control its READY. A miss/bypass cannot
  overtake an older hit response; a stalled bypass is captured rather than
  acknowledged as complete. Read-only IF admission from batch15 is retained.
  The general cache still offers its original hit-under-miss mode when the
  new option is OFF; the SoC's demand/PTW interface already has one owner.
- Demand/PTW arbitration may replace ONLY a physical owner whose actual
  response is consumed on that same edge. The old owner still chooses the
  old response recipient; the new owner is registered for later replies.
- Home ordinary unowned DDR writes no longer each enter a private
  accessSend/accessWait round trip. Same-direction cohorts use the existing
  outstanding counter and bridge slots. Reads, MMIO, a required probe,
  releases, acquires and drain requests preserve their ordering boundaries.
  The DDR's single real write owner guarantees accepted-write execution
  order. Every native reply still waits for the true downstream completion.
- The existing line-transfer direct dispatch option is selected in Home,
  skipping an empty scheduler without bypassing the writer's active payload
  registers. Dirty migration still waits for real writeback acknowledgment.
- The two registered device-origin cuts are retained, while one redundant
  arbiter-output cut is removed. The selected shell has6native boundaries,
  formerly7; neither device origin exceeds its configured four credits.

The selected performance profile ALSO explicitly enables the existing
--fast-data-translation option, which was not selected in batch15's TL-C
profile. Its registered full-page PMP/permission proofs skip repeated
lookup/authorize states, not PTE permissions, SUM/MXR/MPRV, invalidation,
real memory acknowledgment or precise faults. This is profile selection
of previously implemented logic, not a newly invented MMU algorithm.

Canonical necessary short receipt:
build/gsim/i1-coherent-network-bandwidth16-20261015-r1/receipt.json,
SHA256594f6313164fda24c93e42e284c64fe199a10717e902fdbc4e81c88d3caf6be5.
All107named checks/negative controls and15Scala configuration tests pass,
with ASan/UBSan. Changed models are freshly generated/compiled; unchanged
independent numerical/PMP/MMU models require exact FIR/artifact identity.
The original batch15 CPU model is retained as an explicitly frozen OLD
performance reference, not misrepresented as current RTL qualification.

Coverage includes compact/default DMA cuts, four live credits per origin,
36error replies in1,200subword transactions, one/two-way cache coherence,
the full32KiB+32KiB directory, both general and ordered physical-cache
admission, LR/SC/AMO, C page boundaries, M/S/U/Sv39/PMP and actual CPU F/D
memory/precise-state completion. A four-credit native stream crosses
from128writes to128reads while older replies remain live and repeatedly
holds response READY low; independent byte/order mutations are rejected.

| Same bounded device traffic/service | Batch15 cuts | Batch16 compact |
| --- | ---: | ---: |
| 1,200mixed native device transactions | 3,303cycles | 3,065cycles |
| Four-credit Home stream,1KiB write +1KiB read | 1,269cycles | 733cycles |
| Observed Home in-flight ordinary writes | 1 | 4 |

The native device test improves7.77%; the Home fixture improves73.12%.
The uncut device reference remains2,861cycles, so compact cuts STILL
cost7.13% versus no cuts. The Home fixture has an ordered short-latency
RAM, not the actual DDR/MIG. Its four Home write owners are NOT four
AXI write owners: the actual DDR limit remains one.

The real CPU uses the SAME8KiB and64KiB-per-buffer binaries, seeded AXI
backpressure/service laws and final full-buffer/checksum/coherent-DMA
oracles for baseline and candidate. All eight compared scenarios retain
identical retired instructions, AXI read/write transaction counts and
payload sizes.64KiB exceeds one32KiB L1;8KiB fits and is not a DDR peak
test. Initialization policy/dirty tails remain identical. Timed CPU
loops do not explicitly drain the final writeback tail, as before.

|32KiB+32KiB CPU profile, cycles|Batch15|Batch16 selected|
|---|---:|---:|
|8KiB Bare READ /WRITE /COPY|11325 /15084 /16593|9278 /13689 /12499|
|8KiB Sv39 READ /WRITE /COPY|11337 /15074 /16593|9284 /13697 /12499|
|64KiB Bare READ /WRITE /COPY|160720 /144287 /281862|142806 /133644 /246204|
|64KiB Sv39 READ /WRITE /COPY|160580 /144181 /281943|142843 /133360 /245783|

64KiB Sv39 READ/WRITE/COPY throughput improves12.42%/8.11%/14.71%;
the8KiB resident COPY improves32.75%. These are measured CPU-model
cycle improvements, not board MiB/s or evidence that300MHz is achieved.

Higher response-latency tests reuse the SAME compiled models and images.
R first-beat delay is floor+[0,12]cycles; B delay is floor-1+[0,10] after
all W beats. R/B/AR/AW/W backpressure and cross-ID completion are unchanged.
This is a representative latency law, NOT measured board DDR latency.

|64KiB Sv39, memory latency floor|READ old ->new|WRITE old ->new|COPY old ->new|
|---|---:|---:|---:|
|40cycles|217561 ->199555|201097 ->190458|404927 ->368963|
|80cycles|278857 ->260836|262766 ->252046|538238 ->502123|

COPY throughput still improves9.75% at40cycles and7.19% at80cycles.
Bare shows the same direction,9.89%/7.22%. These gains diminish as actual
memory response wait dominates; do not call the bus saturated.

The structural-only ablation deliberately keeps fast data authorization
OFF. Its64KiB Sv39 READ/WRITE/COPY is159013/142825/278949cycles, versus
160580/144181/281943previously: roughly1% CPU-stream improvement, not
the whole selected-profile gain. Its actual O3 CoreMark ROI is856079cycles,
only0.014% faster than856199. The large CPU IPC improvement comes
mainly from explicitly enabling the existing registered authorization,
while the new Home/device structure removes their serial handoffs.

|Same standard2000-byte one-iteration O3 CoreMark|Batch15 frozen|Structure only|Selected +fast authorization|
|---|---:|---:|---:|
|ROI cycles|856199|856079|740574|
|ROI instructions|345517|345517|345517|
|ROI IPC|0.40354754|0.40360411|0.46655297|
|Whole-program retired|367211|367211|367211|
|CRC final|0xe714|0xe714|0xe714|

The retired PC/instruction trace remains7b173819116883a2, and every
retired register/next-PC/exception and final8KiB RAM byte is independently
checked. Selected IPC/throughput rises15.61%, but the official <10second
warning remains present: this is NOT a formal CoreMark score. Actual
2,320F/D CPU cases take469,915cycles (previous497,774), and32FPR context/
precise-fault cases take5,413(previous5,616), with unchanged results/flags.

One exact tested RTL package is at
E:\VM\Share\Valence-rtl\orbital-i1-bandwidth16-20261015-r1.
The clock/USER2 proof sources have not changed and are hash-checked
against their WSL archives. The single combined300MHz synthesis has
completed; it DOES NOT meet the target and has not been placed/routed.
Its reports, exact RTL manifest, all short-proof artifacts and checkpoint
hashes are archived in
build/fpga/i1-network32-bandwidth16-synth-20261015-r1/receipt.json,
SHA25640714e84879f5bd272948820c39e0bfd31598ce788134dd2d8013f3e346ac866.

|Synthesized estimate, same300MHz constraint|Batch15|Batch16|
|---|---:|---:|
|CPU setup WNS ns|−2.594|−3.341|
|Cache endpoint WNS ns|−2.106|−2.148|
|Home endpoint WNS ns|−1.374|−3.341|
|Core endpoint WNS ns|−1.301|−1.301|
|DMA endpoint WNS ns|−0.822|−0.837|
|FPU arithmetic endpoint WNS ns|−0.021|−0.021|
|LUT|76612|79530|
|FF|43991|44093|
|BRAM tiles /DSP|26.5 /28|26.5 /28|

The new worst actual path is fabric/cut/a/headValid -> directory LUTRAM
lookup/qualification -> line reader sendQueue -> shared line arbiter ->
memory READY -> line writer activeAddress.CE. It has22logic levels and
6.570ns data delay, of which5.234ns is unplaced routing estimation.
The path crosses the newly selected empty-dispatch bypass; therefore this
batch is a cycle-throughput improvement but NOT a frequency improvement.
No single-change physical ablation was run, so do not attribute every
added LUT or all timing loss solely to that option. Next revision should
break this ownership/READY feedback with a registered independent offer,
preserving dispatch throughput and actual completion ordering rather than
blindly adding another serial wait.

Data arrays still map to16BRAM36 primitives, eight per cache. Tag and
directory payload FF count remains zero. All five parallel raw/gated
BUFG roots and six native request/reply boundaries were found in the
actual netlist. Resource growth is2,918LUT and102FF, not a cache/slot
capacity increase.

Read-only re-query of BOTH existing constrained checkpoints, without any
new synthesis, constraint changes or optimization, confirms identical
register-to-register hold: CPU +0.006ns, UART raw-to-gated −0.037ns,
and all internal clocks −0.348ns (USER2 TCK/TDO). Clock-group CPU hold
−0.075ns also includes the declared clockLocked input budget and is not
the internal-register number. Global hold remains −2.701ns, including the
zero-delay OOC UART RX input budget. These values are NOT routed signoff.

CDC critical inventory is unchanged: CDC-1=2, CDC-10=7, CDC-11=37, total46.
The auditor classifies every row but marks them REVIEW_REQUIRED, not
waived or signed off. Common/reset-OR release, reconvergent synchronized
levels, held mailbox instance handshakes and USER2 boundaries still need
their exact full-instance proof/physical handling. check_timing reports
zero clockless registers, unconstrained internal maximum endpoints and
loops; two partial input delays remain. The existing short BUFG/mailbox
proof does not establish complete network/board CDC correctness.

Remaining bandwidth limits are explicit: Home serializes coherence
transactions, the CPU demand/PTW port has one physical owner, the DDR
bridge still has one AXI write owner, and read/write cohort changes must
drain. Concurrent real-CPU plus DMA throughput/QoS was not measured in
this batch. Do not equate four accepted Home writes with four concurrent
AXI writes or call this maximum DDR bandwidth. Future whole-line return
or burst aggregation must retain independent error/order/coherence tests
and include the new Home critical path, not just a small-module gain.

Actual board clock IP, MIG/AXI CDC, RGMII IOB/constraints, Linux boot and
routed setup/hold are still separate gates. No placement, route or bit
was launched;300MHz remains FAILED. Original Orbital-A1 worktree and
vendored HardFloat sources remain untouched.

## 2026-10-15 batch17: break Home READY and metadata feedback without extra CPU stages

This timing-focused revision keeps the batch16 selected profile, including
I/D32KiB, fpga8, full selected RV64GC/Sv39, four-entry TLBs, two DDR
slots, one AXI write owner, four native device credits and fast data
authorization. No core-stage, ISA, cache-capacity or transaction expansion
is made. Existing coherent-control cuts select the local changes; reusable
IP additions default OFF. Original Orbital-A1 worktree is not modified.

- Home gives each Acquire client an independent asynchronous directory read
  address. Arbitration selects completed match/owner results, not the RAM
  input address, and ordinary/maintenance lookup keep their own addresses.
  No ownership entries are added; the physical mapper may replicate read
  ports, so resource cost must be measured.
- The serialized Home selects optional isolatedWriteLaunch. Writer launch
  uses registered !active, not remote last-beat A.fire. Its active payload
  remains registered and beats remain II=1. Generic independent queued
  multi-line users retain original final-edge replacement by default.
  Home cannot prepare a second coherence write while the first is active,
  so this removes a control dependency without an intended Home bubble.
- Cache flush reads have an independent metadata address. A CPU eviction
  clears valid/dirty from the captured pendingIndex during existing
  evictCapture, before Release is offered. CPU/probe admission is already
  blocked in this state; no hit stage or response delay is added.
- The network shell selects optional boundedDescriptorChecks. Frame
  rounding is in aligned word units; address-end/overlap arithmetic uses
  the full configured significant bits. Full64 length legality, high
  address rejection and 65-bit end/overflow semantics remain enforced.
  MMIO ABI, posted ownership, true completion and stop/drain are unchanged.

The first short attempt timing17-20261015-r1 failed a newly added illegal
length case: the OLD C++ startTx/armRx helper accepted unsigned length and
truncated a 64-bit test input to a valid low32 length. The DUT was therefore
being sent a different value from the oracle's invalid case. The helper
now accepts uint64_t; no expected result was relaxed and the failed
receipt is retained. The corrected 8KiB and2GiB DMA variants each pass
158 packet/error cases plus posted RX/retained ownership/stop/drain,
overlap, invalid high-address/length and >4GiB cancellation checks.
An independent TX-byte mutation is required to fail.

Combined necessary short qualification PASSES at
build/gsim/i1-coherent-network-timing17-20261015-r2/receipt.json.
SHA256b5678eba13eb9f8fd8601811a273215ed1a1c99e53cecbcaf3342e373f588948.
All111checks/negative controls and15Scala configuration tests pass with
ASan/UBSan. Changed models are freshly generated and compiled; unchanged
numerical/PMP/MMU models require exact FIR/artifact identity.

All eight old/new32KiB CPU throughput scenarios match exactly, including
8KiB/64KiB Bare/Sv39 and64KiB first-response latency floors40/80. READ,
WRITE,COPY cycles, retired instructions, AXI counts and full-buffer bytes
are unchanged. The2KiB removal profile also passes. Home's four-credit
stream remains733cycles; native DMA frontend remains3065cycles.
The original batch16 model is rerun as a frozen independent performance
baseline, not claimed to qualify the modified current RTL.

Actual32KiB CPU O3 CoreMark remains740574ROI cycles /345517instructions,
IPC0.4665529711, trace7b173819116883a2, CRC final0xe714, whole-program
retired367211. Architectural register/next-PC/exception and final RAM
byte checks pass; the official<10second warning remains, not a formal
score. F/D corpus remains469915cycles for2320cases and context/fault
5413cycles for32FPR cases. Self-modify/FENCE.I/JALR smoke remains1766cycles.

The exactly hash-bound whole network RTL is exported to
E:\VM\Share\Valence-rtl\orbital-i1-timing17-20261015-r1.
One combined synthesis completed;300MHz is NOT met. Reports and the
exact tested manifest are archived at
build/fpga/i1-network32-timing17-synth-20261015-r1/receipt.json,
SHA25688e4dcd0d2f099f4c8c1a364a51cc0b023b285675fbfd52ca43de43f9b93626f.

|Same300MHz synthesized estimate|Batch16|Batch17|
|---|---:|---:|
|CPU/Home WNS ns|−3.341|−1.899|
|Worst CPU logic levels|22|18|
|Writer active-register family WNS ns|−3.341|−1.683|
|Cache valid metadata WNS ns|−2.148|+0.809|
|Cache replacement WNS ns|−2.142|−1.855|
|DMA WNS ns|−0.837|−0.363|
|Core endpoint WNS ns|−1.301|−1.085|
|FPU arithmetic endpoint WNS ns|−0.021|−0.009|
|LUT /FF|79530 /44093|80870 /44149|
|BRAM tiles /DSP|26.5 /28|26.5 /28|

CPU WNS improves1.442ns. No core or HardFloat logic was changed in this
batch; their small timing variations are mapping results, not claimed
new core arithmetic optimizations. Extra read ports increase LUT memory
2478 ->3630; the total cost is1340LUT/56FF. Cache data still use16BRAM36
and tag/directory payload FF count stays0. Six native boundaries and
five parallel BUFG roots are found in the real netlist.

The remaining CPU/Home worst path is the registered Acquire address
through directory/read dispatch/line arbitration and remote READY into
writer phase.CE,5.128ns/18levels. Removing the large active-line
activation CE cone did not eliminate ordinary beat-advance/state READY
dependencies. Cache's remaining worst is IF response/reissue -> tag
lookup -> replacement update,5.170ns/17levels. Valid metadata now
has+0.809ns margin; do not confuse that with whole-cache closure.
DMA's old postCapacity rounding chain is no longer worst; the new worst
is routed saved MMIO address -> decode/legal -> txLength.CE.

Read-only comparison of the existing batch16/17 checkpoints confirms
the same hold: internal CPU +0.006ns, UART ingress-to-gated −0.037ns,
all internal clocks −0.348ns(USER2 TCK/TDO), global including OOC input
budgets −2.701ns. CPU clock-group −0.075ns includes declared input
budgets and is not register-to-register only. All46CDC critical rows
remain known REVIEW_REQUIRED, none waived; no clockless/unconstrained
internal maximum endpoints/loops, two partial input delays remain.
This is neither CDC nor routed hold signoff.

Next batch should jointly remove Home's residual read/write arbitration
dependency, defer LRU/dirty updates using existing ordered hit ownership
with the required forwarding, and share non-overlapping probe/flush tag
ports to recover LUT cost. Whole-line DDR return may reduce repeated
eight-beat internal transport without adding DDR slots, but needs actual
CPU/error/order/backpressure comparisons before selection. No placement,
routing, bit or original OoO worktree modification was performed.

## 2026-10-15 batch18: retained whole-line return, compact Home storage and forwarded metadata

This batch follows the user's combined timing/bandwidth/blocking/resource
request. I/D remain32KiB each, two ways, fpga8, RV64GC/Sv39, four-entry
TLBs, two real DDR slots and ONE AXI write owner. Original OoO and pinned
HardFloat sources remain untouched.

- New --coherent-whole-line /coherentWholeLine defaults OFF and requires
  coherentBandwidth. The existing I1 bridge's whole-line interface reuses
  the SAME two real DDR slots, their error aggregation, tag ownership and
  RAW/WAR/WAW ordering. Home does not release/consume that owner until
  its full response handshake. Internal read serialization and its duplicate
  two-line reader payload are removed, not the external eight R beats.
- A two-entry request-only boundary replaces the old line reader's dispatch
  storage. It cuts Home directory/offer from DDR admission. There is NO
  new512-bit response FIFO; the DDR slot retains payload under backpressure.
- Home's existing single coherent write owner selects an optional compact
  serialized writer: one active line rather than two unused queued copies
  plus an active copy. Generic multi-owner writer and transfer defaults
  retain their original behavior. No write is acknowledged before its
  final accepted A beat and real D acknowledgment; A remains II=1.
- Ordered two-way caches commit hit LRU/dirty using EXISTING pendingIndex,
  readPending and storePending, not new owner/state capacity. Victim choice,
  pending dirty eviction and probe dirty capture forward the older pending
  hit. No cache-hit stage is added. Generic hit-under-miss mode remains direct.
- B-probe and flush already exclude one another. They now share a metadata
  maintenance read port with B priority; CPU tag address stays independent.
  This aims to recover the third read-port LUT cost measured in batch17.

Added actual two-slot/one-write bridge checks exercise8/16-beat backing
geometry, same physical>4GiB address window, held responses/tag reuse,
independent return progress, blocked-write bypass, complete late-error
zeroing, byte strobes, gapped A, stalled AW/W and192 mixed transactions.
Independent data/tag mutations, wrong R ID and early RLAST must be rejected.
The16-beat profile is a parameter-removal check; selected I1 remains8.
Adjacent cached write -> bypass or replacement must accept on consecutive
edges, preserve MRU and return all pending dirty bytes independently.

Two preliminary failures are retained. bandwidth18-r1 failed the newly
added parameter's missing CLI allow-list entry, fixed before simulation.
bandwidth18-r2 reached the old four-slot test's12000-cycle TOTAL timeout:
both directions had accepted91/96 and returned90/96, with AXI progress
35cycles earlier. It was not a deadlock or unbounded memory model.
The total finite budget now scales with declared work; the original
12000-cycle NO-PROGRESS failure bound and250000-cycle overall hard limit
remain. Service delays, ordering and byte/error/owner oracles are unchanged.
The diagnostic executable is in
build/gsim/i1-line-read-timeout-diag-20261015-r1; failed receipts are retained.

Current necessary short qualification PASSES at
build/gsim/i1-coherent-network-bandwidth18-20261015-r3/receipt.json.
SHA2564f6bb4f5c220d9326212e806d4cd44f7b2419061a7d6a7cf63f68e48a1efc912.
All140checks/negative controls and15Scala configuration tests pass with
ASan/UBSan. Every changed model is regenerated/recompiled; unchanged
independent numerical/PMP/MMU models require exact fresh FIR/artifact
identity. The original batch17 actual CPU model is rerun as a frozen
performance reference, not claimed to qualify the changed current RTL.

|32KiB+32KiB actual CPU,64KiB-per-buffer cycles|Batch17|Batch18|
|---|---:|---:|
|Bare READ /WRITE /COPY|142806 /133644 /246204|133451 /124493 /226983|
|Sv39 READ /WRITE /COPY|142843 /133360 /245783|133488 /124239 /227540|
|Sv39 R latency floor40|199555 /190458 /368963|190466 /181324 /350309|
|Sv39 R latency floor80|260836 /252046 /502123|251895 /243011 /483982|

Sv3964KiB throughput improves7.008%/7.342%/8.018%; COPY still improves
5.325%/3.748% at40/80-cycle R service floors. B floor is R floor-1 and
the original independently seeded channel stalls/response jitter remain.
This is a representative AXI service law, not measured board DDR latency.
Every compared scenario retains identical payload, retired instructions,
AXI read/write counts and final independent full-buffer/checksum/coherent
DMA oracles.64KiB exceeds one32KiB L1; timed writeback tails are not
explicitly drained, exactly as in the old reference.

The whole-line-OFF same-capacity ablation keeps new compact Home, tag
port sharing, hit metadata forwarding and the existing fast authorization
ON. All eight stream scenarios, including high latency, reproduce the
batch17 cycle/traffic fields EXACTLY; O3 CoreMark is740574cycles again.
Thus the new CPU-cycle gain is attributable to whole-line return, while
the other changes aim at timing/storage, not an invented IPC improvement.
The fast-data-OFF/whole-line-ON removal profile also passes.

The8KiB resident CPU results are not universal zero cost: Bare READ
9278 ->9279cycles (+1cycle), Sv39 READ9284 ->9281; Sv39 WRITE13697
->12553 and COPY12499 ->12473. No claim of board/DDR peak follows.
Home native stream remains733cycles and compact native DMA frontend
3065cycles; no additional device credits are introduced.

Same standard2000-byte, one-iteration O3 actual-CPU CoreMark:
ROI740574 ->739550cycles,345517instructions, IPC0.4665529711
->0.4671989723. Whole-program retired367211, trace7b173819116883a2,
CRC final0xe714 and AXI257reads/0writes are unchanged. Independent
register/next-PC/exception and final RAM bytes pass. The official duration
warning remains; this is NOT a formal CoreMark score.
F/D actual CPU corpus improves469915 ->429755cycles for2320cases;
32FPR context/precise-fault cases5413 ->4993, unchanged numerical results,
flags and traps. Privilege, C/A, page-end and late-error checks pass.

Exactly qualified network RTL is exported to
E:\VM\Share\Valence-rtl\orbital-i1-bandwidth18-20261015-r1.
ONE combined300MHz synthesis completed with the exact tested FIR/source
and resource hashes. Its canonical WSL archive is
build/fpga/i1-network32-bandwidth18-synth-20261015-r1/receipt.json,
SHA25693267525a4d87392b8b687cef88fcb0cb054f2b7b1a2211ca50e804af12056c3.
It includes every small timing/CDC/mapping report, exact export manifest,
full synthesis log, clock/USER2 proofs and a read-only old/new checkpoint
comparison. Original large DCPs remain in the E: export package; they are
hashed but not redundantly copied to WSL.

|Actual synthesis /same existing constrained checkpoints|Batch17|Batch18|
|---|---:|---:|
|CPU300MHz setup WNS ns|−1.899|−2.013|
|Home writer endpoint WNS ns|−1.899|+1.004|
|Cache replacement endpoint WNS ns|−1.855|+1.202|
|Cache valid metadata endpoint WNS ns|+0.809|+0.568|
|Core endpoint WNS ns|−1.085|−1.301|
|DMA endpoint WNS ns|−0.363|−0.552|
|FPU endpoint WNS ns|−0.009|−0.021|
|CLB LUT /FF|80870 /44149|79578 /43055|
|LUT as memory|3630|3154|
|BRAM tiles /DSP|26.5 /28|26.5 /28|

Total saves1292LUT/1094FF versus batch17. Actual Home lineTransfer
hierarchy shrinks2369LUT/2967FF ->243LUT/639FF; the old reader is absent
and the selected compact writer is found in the netlist. Some of that
saving is consumed by the bridge's whole-line selection/control logic;
do NOT report the local hierarchy savings as the top-level reduction.
Cache data remain16BRAM36, tag/directory payload FF count0, native
boundaries6, request-only line boundary1, parallel BUFG roots5. Private
cache miss capacity and actual CPU/PTW ownership are NOT increased.

The targeted LRU and Home READY/writer chains are now positive, but the
whole design is NOT timing-closed. New worst:
I-cache.state -> hit response visibility -> IF/IT reissue address ->
asynchronous tag RAM/comparison -> uncached request valid ->
fabric native request capture.CE. This is5.242ns/16logic levels, CPU
WNS−2.013ns,0.114ns worse than batch17. The cache's own state feedback
on this cone is−1.979ns/18levels. This is a real remaining admission
feedback path, not justification to grow the cache or DDR slots.
Core's separate residual is EX operand bypass/ALU/branch nextPc
(−1.301ns); DMA remains saved-address/decode/legal ->txLength.CE
(−0.552ns). Core/FPU hardware did not change this batch; differences
there are mapping variation, not new arithmetic optimizations.

Existing constrained checkpoints were reopened only for reporting:
no constraints changed, no optimization/placement/routing/synthesis
rerun. Actual CPU register-to-register hold remains+0.006ns;
UART raw-ingress ->gated remains−0.037ns; all-internal remains−0.348ns
(USER2 TCK/TDO). Global hold including declared OOC input delays
remains−2.701ns. Clock-group hold−0.075ns includes input budgets and
must not be mislabeled CPU-register hold.
CDC retains46Critical rows (CDC-1=2,CDC-10=7,CDC-11=37), all known
REVIEW_REQUIRED, unknown0; none is waived or signed off. check_timing
has no clockless, unconstrained internal max endpoints or loops;
two partial input delays remain. Five CDC-auditor tests and
git diff --check pass.

Next concentrated timing batch should cut the actual IF-response/
translation-reissue/tag-qualification/uncached-admission feedback while
preserving same-edge useful hit throughput. Also jointly address EX
bypass->nextPc and bounded DMA address/decode CE qualification, then
recheck actual CPU cycles rather than assuming another stage is free.
Private CPU demand/PTW still has one physical owner and Home still
serializes coherent ownership; those remain bandwidth limits after
removing repeated line transport. No claim of saturated bus bandwidth,
routed300MHz, CDC signoff, full-board compatibility or bit generation.
Original OoO worktree, pinned HardFloat and pinned GSIM engine remain
untouched; the local independent test harnesses were extended as above.

## 2026-10-15 batch19: early IF payload, existing ADDR branch candidates and parallel MMIO admission

User-directed combined timing batch: IF response/reissue/tag admission,
EX forwarded-operand/branch/next-PC and DMA register qualification. Keep
fpga8, RV64GC/Sv39, I/D32KiB two-way, two real DDR slots/one AXI write
owner, existing native boundaries and peripheral clock resources.
No original OoO worktree or pinned HardFloat/GSIM-engine change.

- Instruction translation computes the offered fast physical payload
  before the older physical response arrives. Only VALID/acceptance,
  not the physical address mux, depends on owner turnover. Registered
  send/fastHold payload and all invalidate/PMP/PTE/privilege checks remain.
- Existing ADDR branchTaken/branchTarget/nextPc fields now retain taken
  and fallback candidates separately. Resolve next-PC after this existing
  edge; compare both predictions in parallel before choosing the boolean.
  EX no longer appends the fault-qualified XLEN next-PC mux to operand
  forwarding/comparison. No stage, owner, redirect edge or branch bubble
  is added. Non-FPGA profiles retain their original selection.
- FPGA peripheral routing uses exact constant windows with parallel
  hit qualification, one-hot ready/owner encoding and a nonalias assert.
  Its generic profile retains the old priority/range path. Disabled IP
  windows return errors without forwarding. MMIO ABI/map are unchanged.
- Bounded DMA register decode uses full56-bit prefix equality plus8-bit
  offset, not XLEN subtraction. Simple descriptor-field writes have
  their exact local legality/idle checks, independently of unrelated
  posted overlap/end-address validation. Complex POST/START/STOP and
  all real memory acknowledgments retain their checks. Descriptor
  fields/readback remain full64, including invalid values until START.

New actual peripheral-router test endpoints retain responses and exert
independent request/reply backpressure. Direct/cuts/all-disabled profiles
each check163cases, including full64 high aliases, exact window edges,
forwarded address/data/size/mask and local boot/MSIP behavior; owner
mutation must fail. The DMA driver additionally rejects high/adjacent
MMIO aliases, size/mask errors and verifies unchanged descriptor fields
and zero memory side effects. The real CPU fetch-control image now
exercises signed/unsigned comparisons, repeated closest-rd producers
and odd-address JALR low-bit clearing against the independent ISA oracle;
the SAME new binary is rerun on the frozen previous hardware.

Final necessary combined GSIM qualification PASSES:
build/gsim/i1-coherent-network-timing19-20261015-r2/receipt.json,
SHA256b816299d3afba53aafd0196c4c45f75f1dbdceca49957dc7340b9d2f17887164.
All150checks/negative controls and15Scala configuration tests pass under
ASan/UBSan. The first r1 passed hardware/CPU comparisons, but audit found
its new peripheral fixture observed a copy of the upstream payload. It
is NOT the final forwarded-payload proof. r2 observes actual child-port
requests and additionally rejects payload mutations. No CPU RTL changed
between r1/r2; only exact fresh-FIR-identical objects are reused, and the
frozen OLD performance hardware remains bandwidth18-r3, independently
of compile reuse. This distinction is recorded in the receipt.

All12distinct matched stream scenarios (2KiB parameter profile and selected
32KiB; Bare/Sv39,8/64KiB and selected40/80-cycle service floors) retain
EXACT read/write/COPY cycle counts, retired instructions and AXI traffic.
In selected32KiB Sv3964KiB, READ/WRITE/COPY remain133488/124239/227540;
at40/80-cycle R floors COPY remains350309/483982. No bandwidth gain is
invented for this timing-only batch, and batch18's whole-line gains remain.
Both fast-data-OFF and whole-line-OFF profiles preserve their respective
old stream/CoreMark results. Native Home stream remains733cycles and
compact DMA frontend3065cycles.

O3 CoreMark standard2000-byte one-iteration ROI remains739550cycles,
345517instructions, IPC0.4671989723, retired367211,
trace7b173819116883a2, CRC final0xe714, AXI257reads/0writes. The official
duration warning remains: NOT a formal score. New real-CPU branch/
FENCE.I/JALR smoke is1819cycles/304retired for BOTH old and new models.
F/D2320cases remain429755cycles and32FPR context/faults4993cycles,
with identical numerical/flag/trap oracles. Precise M/S/U, PMP, Sv39,
C/A, page-end, full-memory and error-injection cases pass.

The exact candidate is exported to
E:\VM\Share\Valence-rtl\orbital-i1-timing19-20261015-r1.
ONE combined300MHz synthesis completed after that final short gate.
Its canonical WSL archive is
build/fpga/i1-network32-timing19-synth-20261015-r1/receipt.json,
SHA2561de1f4761d6036ec7244e9f484ba14d3b762d998bafe34cdb2e7ead9286ce5b2.
Exact manifests, all small reports/logs, clock/USER2 proof and a read-only
comparison of the SAME existing constrained old/new DCPs are archived.
No repeated synthesis, relaxed constraint, optimization, placement,
routing or bit generation was used for that comparison.

|Actual synthesis /same register-endpoint families|Batch18|Batch19|
|---|---:|---:|
|CPU300MHz WNS ns|−2.013|−2.098|
|EX ADDR packet WNS ns|−1.301|−1.099|
|Native request/reply boundary WNS ns|−2.013|−2.020|
|DMA WNS ns|−0.552|−0.346|
|Cache valid /replacement WNS ns|+0.568 /+1.202|+0.553 /+1.202|
|Home writer WNS ns|+1.004|+1.004|
|All core endpoints WNS ns|−1.301|−1.604|
|CLB LUT /FF|79578 /43055|79021 /43119|
|BRAM tiles /DSP|26.5 /28|26.5 /28|

This is a partial structural improvement, NOT overall timing progress or
300MHz closure:557LUT fewer but64FF more, CPU WNS0.085ns worse.
The target EX next-PC cone is no longer the EX packet worst; forwarded
branch comparison ->cause.D remains−1.099ns. Old saved-MMIO-address ->
decode ->txLength.CE is no longer DMA worst; postCapacity rounding/
POST legality ->rxCapacity.CE remains−0.346ns. A later periphery batch
should separate true RX_STOP qualification from unrelated complex POST
legality before using STOP to decide automatic RX launch.

Early IT payload removes one response-dependent PA mux, but does NOT
close all IF admission: aligner.state -> fast permission/physical tag ->
nativeCut.requests.head_address.CE is still−2.020ns/17levels.
The native boundary family includes I/D bypass paths; it is not a
claim that every instruction request traverses that path.

The new global worst is memPacket.fault -> MEM/CMP advancement/recovery
qualification -> numeric result visibility -> EX admission/exFire ->
RF/ID/frontend capacity -> IT physical-request VALID -> I-cache state.D,
5.413ns/17levels. Unplaced route estimate4.509ns is83.3% of that path,
not a measured routed interconnect delay. Source confirms the coupling:
numeric result VALID is masked by flush; execute admission and RF/ID
capacity depend on the same completion/recovery/progress conditions.
Changing pipeline names or adding arithmetic stages alone cannot break
that cross-module control dependency. A next architectural batch should
localize recovery/kill and registered completion ownership, then partition
frontend capacity/admission, preserving precise faults and same-edge
useful progress. No enlarged cache, issue width or DDR quota is implied.
Keep the exact batch18 export/checkpoints as a measured reference;
do not promote this candidate as a timing-qualified replacement.

Existing-checkpoint hold remains: actual CPU register-to-register
+0.006ns; UART raw-ingress-to-gated−0.037ns; all internal−0.348ns;
global including OOC input budgets−2.701ns. CPU clock-group hold−0.075ns
includes OOC input budgets, not only CPU registers.
All46CDC Critical rows remain (2CDC-1,7CDC-10,37CDC-11), known
REVIEW_REQUIRED, unknown0, none waived or signed off. check_timing
has no clockless or unconstrained internal maximum endpoints or loops;
two partial input delays remain. Five CDC-auditor tests pass.
No source/simulator/clock constraints were modified after qualification.
No routed300MHz/full-board/Linux/bit result is claimed.

## 2026-10-15 batch20: local numerical completion, speculative EX and independent DMA STOP

This batch keeps fpga8, single issue, I/D32KiB two-way, two real DDR
slots and one AXI write owner. There is no new architectural stage,
CPU request owner, cache line, FPU response buffer or instruction queue.
The original OoO worktree is not modified. Generic timing cuts and bounded
DMA checks remain explicitly removable.

The batch19 MEM-fault/numerical-kill/frontend-capacity chain is addressed
as control ownership, not by changing pinned HardFloat arithmetic:

- At the existing ADDR/MEM edge, capture one bit indicating whether the
  MEM owner needs a real data response. Requests and MEM completion use
  that registered classification; an assertion checks equivalence to
  the live memory opcode/fault. No reply is invented or posted.
- In the cut profile CMP already contains memoryResult, including real
  access errors. Use that captured fault rather than decoding the raw
  saved response again in capacity. The legacy fault expression is
  independently asserted equivalent.
- FPU/MDU expose local registered completed-owner status separately from
  transferable result VALID. Flush/kill still blocks request/result
  transfers and clears the owner. Cut-profile FPU payload selection uses
  registered producer ownership, not flush-qualified VALID. Core EX still
  requires real result consumption for every non-killed numerical advance.
  No HardFloat source, arithmetic latency or numerical rules change.
- EX capacity no longer waits on the ADDR branch's redirect cancellation.
  A younger EX packet may advance speculatively at that edge; the branch
  transfers to MEM and the younger replacement ADDR valid is cleared.
  Its data request/architectural side effects cannot escape. Older CMP
  fault and WB recovery protection remain in place. This uses existing
  packet registers, not extra buffering or another stage.
- In bounded DMA mode accepted RX_STOP validates only its exact window,
  size/mask/opcode/data. Unrelated POST overlap/length/end-address
  arithmetic no longer controls automatic RX launch. An assertion checks
  equality with the complete ABI predicate; accepted/held memory requests
  still drain and STOP wins over a same-edge launch.

The short test additionally observes completed status during a cancelled
held result, verifies that no transfer or stale owner survives, and rejects
a completion-status mutation. MDU32/64 adds eight late-completion kills
per profile. DMA checks invalid POST independence, invalid STOP size/mask/
data/high aliases and zero unowned memory effects. The CPU smoke adds
taken-branch wrong-path store/register/trap checks against the independent
ISA/full-byte oracle; the same image also runs on frozen batch19 hardware.

Canonical short receipt:
build/gsim/i1-coherent-network-timing20-20261015-r2/receipt.json,
SHA25668dd7d737e2937bcbbeb4b366e2adedec8893400246afede86bf4c0d18800e44.
All158checks/negative controls and15Scala configuration tests PASS under
ASan/UBSan; pinned GSIM and HardFloat are unchanged.

r1 is retained as FAIL: the new test stored at _stack_top, the exclusive
upper bound of the independent oracle's RAM. r2 reserves16stack bytes;
hardware is unchanged. Explicit --reuse-failed-builds reuses only compiled
objects whose fresh FIR and artifact hashes match, not any PASS result.
ALL positive/negative checks rerun. The distinct performance reference is
still the passing timing19-r2 receipt; failed evidence is never a performance
baseline. r2 reuses28exact-FIR models and builds two previously absent
ablation models.

|Same-binary selected32KiB CPU check|Batch19|Batch20|
|---|---:|---:|
|O3 CoreMark one-iteration ROI cycles|739550|738505|
|ROI instructions /IPC|345517 /0.4671989723|345517 /0.4678600687|
|Whole run cycles /retired|786749 /367211|785672 /367211|
|F/D corpus2320cases cycles|429755|428892|
|32FPR context/fault cycles|4993|4993|
|Precise privilege cycles /traps|26502 /19|26489 /19|
|New branch/FENCE.I/JALR smoke cycles /retired|2009 /314|2009 /314|

CoreMark ROI throughput improves0.1415%, with identical retired trace
7b173819116883a2, CRCfinal0xe714 and257AXI reads/zero writes.
Standard2000-byte data and unchanged O3 options are used, but the official
duration warning remains: NOT a formal CoreMark score.
All eight selected32KiB stream cohorts (Bare/Sv39,8/64KiB and40/80-cycle
service floors) have EXACT old read/write/COPY cycles, AXI traffic and
retired instructions. Sv3964KiB remains133488/124239/227540cycles;
COPY at40/80-cycle floors remains350309/483982. There is no new bandwidth
gain in this control-timing batch.

The2KiB parameter profile also passes. Its Sv39 cycles are unchanged;
Bare phase timing changes slightly:8KiB READ/WRITE/COPY deltas
+49/−26/−55cycles,64KiB deltas+118/+137/−337cycles, unchanged traffic
and instruction cohort. Thus a0.32% small-profile READ regression exists;
do not claim every configurable profile is cycle-identical.
Whole-line-OFF and fast-data-OFF ablations pass their own data/ISA oracles.

Exact export: E:\VM\Share\Valence-rtl\orbital-i1-timing20-20261015-r1.
ONE combined300MHz synthesis completed after the final short gate.
Canonical WSL physical archive:
build/fpga/i1-network32-timing20-synth-20261015-r1/receipt.json,
SHA256d4d3d92cad96f988c06a1544f71078cc5527ebd7b69147a213950f1a9c319d2f.
All source/artifact hashes, native/line boundaries, single Home writer,
RAM mapping and five parallel BUFG roots pass the exact existing gates.
Reports/logs, manifests and unchanged USER2/managed-clock short proof are
archived. Two EXISTING constrained DCPs are read-only compared with no
additional synthesis, constraint edit, optimization, placement or routing.

|Actual synthesis /same endpoint families|Batch19|Batch20|
|---|---:|---:|
|CPU300MHz WNS ns|−2.098|−2.255|
|All core endpoints WNS ns|−1.604|−1.286|
|EX ADDR packet WNS ns|−1.099|−1.062|
|Native request/reply boundary WNS ns|−2.020|−2.255|
|DMA WNS ns|−0.346|−0.125|
|Cache valid /replacement WNS ns|+0.553 /+1.202|+0.041 /+1.202|
|Home directory /writer WNS ns|−1.320 /+1.004|−1.320 /+1.004|
|FPU endpoints WNS ns|−0.201|−0.193|
|CLB LUT /FF|79021 /43119|78057 /43120|
|LUT memory /BRAM tiles /DSP|3154 /26.5 /28|3154 /26.5 /28|

This is an area/IPC improvement and a partial control-chain improvement,
NOT an overall timing improvement:964LUT fewer, exactly one FF more,
but CPU WNS0.157ns worse. The selected candidate remains NOT300MHz
qualified; older measured exports are retained, not overwritten.

The new global worst is aligner.cuts.state[1] -> selected fetch address ->
fast physical-address qualification -> asynchronous I-cache tag lookup/
eviction-bypass classification -> CPU native request offer ->
nativeCut.requests.head_address.CE. It is5.484ns/17logic levels.
Estimated unplaced interconnect is3.957ns(72.155%): this is NOT measured
routed delay. The corresponding batch19 boundary path was5.249ns, with
1.570ns logic/3.679ns estimated route; batch20 is1.527/3.957ns.
Thus the reported path got worse mainly in unplaced interconnect estimate,
not because an extra CPU stage or arithmetic operator was added. That
does not make the violation acceptable or establish routed Fmax.
The old MEM-fault/numerical-cancel path is no longer the global worst;
neither frontend admission nor every FPU control path is now closed.

DMA's POST-capacity ->automatic RX-launch enable is no longer its worst.
Its remaining worst is full64 saved MMIO address ->queuedAddressWords.CE,
−0.125ns/10levels. EX's remaining worst is registered MEM rd ownership/
bypass ->integer result ->ADDR result.D,−1.062ns/18levels.
Home C-head/directory write remains−1.320ns; the positive serialized
writer+1.004ns must not be misreported as closing the whole Home.

An additional edge risk is now explicit: incoming B-probe address ->
probeDirty/metadata classification ->D-cache valid.D is+0.041ns/11levels,
versus old worst+0.553ns. Its source was not changed in this batch; global
mapping/fanout estimates changed. A positive sign alone is not useful
margin. Next structural work must prioritize splitting IF translation/tag/
admission and B-probe metadata qualification, alongside remaining EX/Home/
DMA controls, without pretending that more queues or relaxed clocks fix it.

Existing-checkpoint hold comparison is unchanged: CPU internal registers
+0.006ns; UART raw-ingress-to-gated−0.037ns; all internal−0.348ns;
global including input budgets−2.701ns. CPU clock-group−0.075ns includes
OOC input delays and is NOT the CPU register-to-register minimum.
All46CDC Critical rows remain known REVIEW_REQUIRED (2CDC-1,7CDC-10,
37CDC-11), unknown0, no waiver/signoff. check_timing has no clockless
registers, unconstrained internal maximum endpoints or loops; two partial
input delays remain. Five CDC-auditor unit tests pass.
No routed300MHz, full-board/Linux or bit qualification is claimed.

## 2026-10-15 batch21: split IF authorization, retained bypass and registered cache metadata

This is a combined cross-module ownership/admission refactor, not another
ALU stage or larger cache. fpga8, single issue, I/D32KiB two-way, two DDR
slots, one AXI write owner and the existing hit/miss/response capacities
are unchanged. No OoO source/worktree or pinned HardFloat/GSIM is changed.

The IF path is restructured at three interfaces:

- Translation continuously prepares the offered physical payload while
  idle/receiving. Dynamic permission, invalidation and old-response slot
  qualification gate VALID/actual transfer, not a mux back to old PA before
  the I-cache tag RAM. Registered send/fastHold owners remain sticky.
- The existing private read-only MMU PMA proof is now actually connected
  through FiveStageWordCache and I1CoherentWordCache into the coherent L1.
  Cached admission uses that proof, rather than recomputing full64 range
  qualification before every tag hit. Compact tags never authorize a hit
  alone: ordinary/PMA must be true; probes keep independent full-address
  qualification. Assertions compare the hint to complete physical access/
  noAllocate semantics and reject writes, AMOs and virtualized IF owners.
- Cut-profile read-only bypass only leaves from the EXISTING pending
  authorized owner/bypassSend state. Live IF translation/tag/victim
  classification no longer drives native request acceptance. Required
  resident eviction still precedes a noAllocate RAM access; real response/
  error is required. Cache hits retain the same SRAM acceptance/response
  edges. An uncached IF request without required eviction gains one request
  handoff cycle; no latency-neutral claim is made for uncached code/BootROM.
  The actual-CPU performance comparisons below execute from cached DDR.

The maintenance side is also restructured, with no new probe owner:

- At B acceptance retain its resolved physical row with the existing
  hit/dirty/address/source context. Invalidate valid/dirty in the already
  existing probeCapture phase, before ProbeAck is offered. CPU and further B
  admission stay blocked; the SRAM capture/C phases and their latency do
  not gain an edge. Older CPU responses remain drainable.
- Replace cut-profile priority chains of dynamic valid/dirty Vec writes
  with parallel row-local refill/store/evict/flush/probe events. Refill
  installation and clears use registered owner indices; maintenance events
  are asserted mutually exclusive. Deferred store-dirty/LRU forwarding is
  retained. The32KiB configuration adds a9-bit resolved-row field to each
  existing probe context, not another line/transaction slot.
- Retained native offers stay VALID and payload-stable through B/C stalls.
  probeResume handles a scalar request accepted on the B edge or during
  probeSend, including simultaneous C completion, without duplicating or
  losing its one owner. No clock, CDC exception or response prediction changes.

New independent actual-cache/PMA fixtures cover256B and32768B, both two
ways. Their C++ manager supplies all TL-C grants, releases/probes and
scalar data/errors; no DUT tags/RAM provide expected bytes. The32KiB case
checks1038reads in16676cycles,519acquires/3scalar requests/4probe ACKs.
It covers full capacity, high aliases of CPU and B addresses, warm noAllocate
release, real corrupt refill, held hit response versus probe/new bytes,
native offer stability across B/C backpressure, flush and warm reset.
Both fixtures sustain32warm accepted hits/results in33cycles. Data and
incorrect-PMA-hint negative controls must fail independently.

Canonical necessary short receipt:
build/gsim/i1-coherent-network-timing21-20261015-r1/receipt.json,
SHA256c59b40ddaba63745e87f875a37d78716a9c95864ba4dfc6e547baf24bb68614a.
All166checks/negative controls and15Scala configuration tests PASS under
ASan/UBSan. Sixteen exact fresh-FIR models reuse compile artifacts,
14changed models rebuild, and two new IF fixtures are generated.
All tests rerun; the performance reference is frozen passing batch20-r2.

All12matched CPU stream scenarios (2KiB parameter profile and selected
32KiB; Bare/Sv39,8/64KiB plus selected40/80-cycle service floors) retain
EXACT read/write/COPY cycles, total cycles, retired instructions and AXI
traffic. Selected Sv3964KiB remains133488/124239/227540cycles; COPY at
40/80-cycle floors remains350309/483982. Home streaming remains733cycles.
No bandwidth gain or larger resource quota is claimed for this batch.

O3 standard2000-byte one-iteration CoreMark remains738505ROI cycles,
345517ROI instructions/IPC0.4678600687,785672whole cycles,367211retired,
trace7b173819116883a2,CRCfinal0xe714,257AXI reads/zero writes for BOTH
new and frozen old hardware. Its duration warning remains: NOT a formal
score. Whole-line-OFF and fast-data-OFF ablations retain their old results.
F/D2320cases428892cycles,32FPR context/fault4993cycles, privilege26489
cycles/19traps, C/A24805/24830cycles and fetch-control2009cycles remain.
Full32KiB I/D dirty-probe, adjacent store/LRU, error and byte oracles pass.

Exact RTL package: E:\VM\Share\Valence-rtl\orbital-i1-timing21-20261015-r1.
ONE combined300MHz synthesis completed after that final short gate.
Canonical synthesis receipt:
build/fpga/i1-network32-timing21-synth-20261015-r1/receipt.json,
SHA256dcce75e69e7f6297be98770866e99cf90a57a1b71770523dee340f1e7e676dc2.
Report-only comparison queries the same constrained old/new DCPs, without
resynthesis or constraint changes: nine setup families and three hold scopes.

| Same selected setup endpoint family | batch20 WNS/ns | batch21 WNS/ns |
| --- | ---: | ---: |
| CPU clock group, overall | -2.255 | -1.791 |
| Native fetch request boundary | -2.255 | -0.084 |
| Instruction translation | -0.880 | -0.663 |
| Instruction cache | -2.221 | -1.487 |
| Cache valid bits | +0.041 | +0.917 |
| Cache probe context | +0.622 | -0.431 |
| Cache replacement | +1.202 | +1.475 |
| EX/ADDR packet | -1.062 | -1.791 |
| DMA | -0.125 | -0.382 |
| Serialized Home writer | +1.004 | +0.972 |

The original IF tag/native admission path is structurally shortened, not
merely renamed: request-boundary worst depth17→11levels and its WNS improves
2.171ns. Valid-bit depth11→7levels improves0.876ns, with the live B-address
removed from that worst path. I-cache still has a15-level aligner-state/
authorization→victimAddress.CE chain; it is not closed. probeResume now exposes
an11-level D-translation/tag/native-accept qualification chain at−0.431ns;
moving invalidation must NOT be reported as making all probe logic positive.

The overall CPU WNS improves0.464ns, but remains negative. The new18-level
worst is PLIC pending→external interrupt classification→CSR read mux→EX result/
ADDR result.D,5.106ns data delay (0.848ns logic/4.258ns unplaced route estimate).
EX's family regresses and must be reported; its data path is CSR/control,
not simply the old bypass→ALU carry path. Home directory write remains−1.320ns.
DMA regresses to−0.382ns full64 MMIO/status write qualification. Network
reset recovery remains−1.025ns and FPU control−0.178ns, not an arithmetic
FMA failure. These are synthesis estimates, NOT routed maximum frequency.

Mapped total78,150LUT/43,094FF versus78,057/43,120: +93LUT,−26FF.
LUT-memory3154,26.5BRAM tiles and28DSP are unchanged; real cache data/RFs
remain BRAM and tag/directory payload FF count is zero. No LUT reduction
is claimed for this batch.

Read-only hold comparison is unchanged: CPU internal register-to-register
+0.006ns, UART raw-to-gated−0.037ns, all internal−0.348ns, global including
OOC input budgets−2.701ns. CPU clock-group−0.075ns includes external input
budgets and must not replace the internal FF-only number. All46CDC Critical
rows remain known REVIEW_REQUIRED, unknown0, not waived or signed off.
No physical/timing/CDC/board PASS is inferred from short GSIM or synthesis.

### User-requested implementation trial, 2026-10-15

After the above completed evidence, the user requested physical optimization.
fpga/inorder/route_network_diagnostic.tcl starts from the SAME constrained DCP,
SHA25640b11fa35c173fc4762d362747760767aaae782ef71a5e5e3bba3f776ad9866b.
The entry-point SHA256 is
3d92c4b1cd746f1a581ca315a68549fefa9a5644e1605fdc3da88818432a63a6.
Output: E:\VM\Share\Valence-rtl\orbital-i1-timing21-20261015-r1\physical-route-r1;
live log: same package/vivado_route.log.
One Explore placement/route with AggressiveExplore pre-route optimization,
plus at most one post-route optimization/repair; no new synthesis, RTL edits,
clock relaxation, broad exception or bit generation. It preserves first-route
and final-route checkpoints and reports each milestone separately.

This is still NETWORK INTERNAL OOC, not full board implementation: existing
UART/TX parallel real BUFG roots are retained; CPU/AON/RX get explicitly
hypothetical external BUFGCE_X0Y0/Y1/Y2 context. Actual Clock Wizard, MIG,
RGMII IOB and board pins are outside. Original I/O budgets and scoped CDC/
USER2 recipes stay in force; endpoint-specific recipes reapply after opt.
The bounded trial COMPLETED without closing300MHz. Exact physical receipt:
build/fpga/i1-network32-timing21-route-20261015-r1/receipt.json,
SHA2560f2e8b5c5a2b944f0721d7c432244cc4ceb2b7ce219c114671e36ff7cf562136.

CPU setup milestones: placed−1.944ns, pre-route physical optimization−1.782ns,
first route−4.522ns, final after one post-route optimization/repair−4.648ns.
The extra physical pass does NOT improve the final CPU worst. CPU-domain
register-to-register setup is also−4.648ns, not just an OOC I/O failure:
registered address interval→line-read allocation/selection→payload-bank.CE,
12levels/7.814ns (1.342ns logic/6.472ns real route). The first-route worst
also reaches the64-bit payload data mux. Synthetic line Get selection must
not gate unrelated ordinary write bytes.

The separate CPU+L1/MMU register partition is−2.621ns: aligner state→
translation/tag-selected I-cache BRAM read address,13levels/5.477ns.
This is not closed by only preparing victim registers. Home directory
metadata−2.833ns/16levels, EX result−2.051ns/16levels, valid bits−1.253ns
and DMA status capture−1.774ns remain physical risks. No claim that a
positive synthesis valid-bit number establishes routed timing is made.

All internal register hold+0.010ns; UART raw-to-gated hold+0.238ns.
CPU clock-group hold−2.982ns is the declared OOC DDR input budget, not the
internal FF result. Global hold−3.008ns is external reset→release synchronizer.
96,858/96,858 routable nets fully routed, zero routing errors, but three
explicit external-clock gaps are retained and NOT waived. All internal
endpoints are constrained and clocked; two partial input-delay checks remain.
Mapped78,479LUT/43,127FF/26.5BRAM/28DSP. CDC inventory after optimization
is22Critical (4CDC-10/6CDC-11/3CDC-1/9CDC-7), including10UNKNOWN rows.
The change in count is NOT a CDC improvement/signoff. All original rows,
skew, DRC and native reports are retained, not hidden or reclassified as PASS.
No board,300MHz,CDC or bit qualification.

Before the next batch edited any source, all350source/exporter/resource
files were copied and rehashed against the exact old manifest into
build/fpga/i1-network32-timing21-source-snapshot-20261015-r1,
receipt SHA256dd38adbc3925e0eee7a59c16a95d9ae671e634cbfff525daabb377c41dbad38e.
Physical collection validates THAT complete historical source snapshot and
records subsequent workspace drift explicitly. It does not certify newer
workspace edits. This permits further batch development while an existing
long-running implementation finishes without mixing versions or loosening
the source gate.

## 2026-10-15 batch22: parallel instruction SRAM, retained Home rows and prepared DDR payload

Continues only the independent Orbital-I1 worktree on feat/orbital-i1-five-stage.
The original OoO worktree remains untouched. Selected fpga8 single-issue
RV64GC/Sv39, I/D32KiB each, two cache ways, two DDR slots and one actual AXI
write owner are unchanged. Private CPU/cache/PTW remains one actual owner;
this is NOT a claim of two CPU MSHRs. No pipeline stage or transaction slot
is added. Generic ISA, cache and timing options remain removable.

### Combined structural changes

- Read both physical instruction-cache SRAM ways from the raw set before tag
  qualification; select returned bytes with the existing retained CPU/probe/
  flush row. Normal D-cache and non-cut/single-way paths keep their existing
  layout. Full byte, PMA/noAllocate, aliases, error, probe, flush, reset and
  stall oracles still apply. Warm32 hits remain33cycles.
- Prepare victim address/dirty during idle independently of true request/
  eviction qualification. Only an actually accepted owner can consume the
  prepared context; existing flush captures retain precedence.
- Home retains Acquire/probe/release directory row indices at real acceptance.
  Per-client raw C addresses read tags before arbitration; successful E uses
  the retained row instead of a fresh tag/priority search. Voluntary release
  clears in the EXISTING releaseAck phase; dirty release still waits for real
  backing B. No early coherence ACK or directory-capacity increase.
- PLIC IRQ notification is a parallel pending/enabled/above-threshold OR,
  not the claim-winner tournament. Priority/lowest-ID claim selection and
  combinational IRQ semantics are unchanged. An independent MMIO sweep
  covers256 enable masks ×8thresholds ×2contexts; both data and IRQ negative
  controls must reject mutations.
- Synthetic line Get selection no longer gates its unused64-bit write-data
  payload. Idle DDR lanes may prepare an UNOWNED ordinary first word; actual
  A acceptance alone grants a slot/credit/AXI side effect. Continuations use
  the already authorized collecting owner and assert raw presence equals
  real A.fire. R capture still requires real AXI R. No speculative response,
  premature W credit or overwrite of held W/D payload.
- DDR fixtures now test burst8/16 with writeCollectionFlow both false and
  true, including continuation/new-line overlap, masks, errors, IDs, RLAST,
  source reuse, backpressure and byte/tag negative controls. The selected
  network fabric STILL leaves writeCollectionFlow=false; testing that option
  must not be described as enabling early AW/W in the delivered profile.

### Exact short evidence and performance

Intermediate batch22-r1 passed170checks with the first four structural cuts,
but was never synthesized. The FINAL hardware is batch22-r2:
build/gsim/i1-coherent-network-timing22-20261015-r2/receipt.json,
SHA256 a3c6488e100659135a9511788f93fbfbc6403eadc632df8e1186cdca48ea9264.
186checks/negative controls and15Scala configuration tests PASS.
All342source and521artifact hashes match. ASan/UBSan GSIM remains pinned;
no Verilator, full Linux simulation or full regression was run.

All12 matched CPU streaming scenarios exactly retain cycles, read/write/
copy ticks, retired instructions, bytes, AXI traffic and service floors:
2KiB control fixtures and selected32KiB Bare/Sv39, including40/80-cycle
response floors. Frozen batch21 hardware is also rerun with the same new
binary/oracle/service law, not merely compared against stale numbers.
O3 CoreMark ROI738505cycles,345517instructions, IPC0.4678600686522095;
whole785672cycles/367211retired, trace7b173819116883a2, CRCfinal0xe714,
257AXI reads/0writes. EXACTLY unchanged from batch21.
This short one-iteration CRC-valid run has a duration warning and is NOT a
formal CoreMark score. No assertion of a measured bandwidth/IPC increase.

### Physical export and resource tradeoff

Final package: E:\VM\Share\Valence-rtl\orbital-i1-timing22-20261015-r2.
Its CHIRRTL exactly matches the qualified network-shell artifact.
firtool deduplicates sixteen256x64 instruction-way instances and two
synchronous DMA payload banks into mem_256x64.sv. Export now verifies all
16actual way coordinates and the real256x64 leaf geometry before binding
ram_style=block. Shared DMA uses receive the same attribute; raw/stamped
leaf hashes are retained, and removing the attribute reproduces exact raw
bytes. Five new exporter tests reject missing/duplicate ways, unrelated
names and wrong geometry while preserving old data/RF/tag policies.
The failed r1 name-only export has NO synthesis or qualification.

ONE synthesis, unchanged3.333ns/part/directive/clock and CDC recipes:
77,288LUT/43,222FF/3666LUT-memory/34.5BRAM tiles/28DSP.
Versus batch21: −862LUT,+128FF,+512LUT-memory,+8BRAM tiles,DSP unchanged.
The logical I/D capacities are unchanged; parallel-way SRAM wastes more
physical packing to remove the tag-selected BRAM input mux. All24cache
BRAM primitives map,884736allocated bits; RF2/FPR3BRAMs and ROM present.
Tag/directory payload FF count remains zero.

Canonical synthesis/archive receipt:
build/fpga/i1-network32-timing22-synth-20261015-r2/receipt.json,
SHA256 81bbfbb3eb2c7056e35132e917368ac3b844bf589712911008023d0984410bbe.
Constrained DCP SHA256:
eabac3ada9c71e1737ea39c4690a8a508abef011ed24555d308283507633a4a2.
All196small reports/proofs/logs/helpers are archived in WSL; large DCPs stay
in the above E: package. The collector verifies native log/JSON/path values,
same-DCP hashes, all12performance scenarios and source/RTL/proof identities.

### Same-checkpoint timing, not routed results

Nine setup and three hold families are queried from the exact old/new DCPs.
Four additional storage/PLIC families query real mapped endpoints; both
BRAM A/B address/enable groups are included because Vivado remaps read
ports. No new synthesis, pin-segmented model, constraint change or route.

| Setup family (ns) | Batch21 | Batch22 |
| --- | ---: | ---: |
| Overall CPU | −1.791 | −1.574 |
| EX/ADDR result | −1.791 | −0.811 |
| Native fetch admission | −0.084 | +0.052 |
| IF translation | −0.663 | −0.672 |
| Entire instruction cache | −1.487 | −1.574 |
| Instruction BRAM address/enable | −1.416 | −0.434 |
| Instruction victim registers | −1.487 | −0.817 |
| DDR payload capture | −0.561 | +1.309 |
| PLIC pending to live CSR result | −1.791 | +0.459 |
| Entire Home directory/control | −1.320 | +0.498 |
| Home line writer | +0.972 | +1.002 |
| Cache valid metadata | +0.917 | +0.759 |
| Cache probe context | −0.431 | −0.429 |
| Replacement metadata | +1.475 | +1.231 |
| DMA status capture | −0.382 | −0.130 |

The old interval-hazard→DDR bank capture falls15→5levels; its source is
now registered lane phase, not allocation range/selection. IF BRAM input
falls14→10levels but is NOT yet positive. PLIC→CSR falls18→10levels.
Home's15-level tag-search→directory WE chain is no longer the worst;
its new worst has8levels and positive synthesis slack.

Overall improvement is only0.217ns;300MHz is NOT closed.
The new17-level worst is aligner state/address selection→superpage/physical
address/permission→cache admission/classification→I-cache state.D,
4.889ns (0.997logic/3.892unplaced route estimate). Entire I-cache WNS
regresses0.087ns even though its BRAM/victim subpaths improve.
EX now exposes its17-level operand/bypass→ALU result path at−0.811ns.
IF translation−0.672ns, probeResume−0.429ns, DMA−0.130ns and FPU
control−0.185ns also remain risks. Next structural batch should separate
fetch authorization/admission from cache next-state classification, with
the real CPU IPC/traffic oracle retained; do not declare success from local
positive subpaths or from merely moving the overall worst endpoint.

Hold is unchanged: CPU internal FF-only+0.006ns, UART raw-to-gated−0.037ns,
all internal−0.348ns, global including OOC I/O budgets−2.701ns.
CPU clock-group−0.075ns includes input delays, not FF-only hold.
All46CDC Critical rows remain known REVIEW_REQUIRED (7CDC-10/37CDC-11/
2CDC-1), unknown0, no waiver/signoff. Narrow managed-clock/USER2 proofs
do not sign off all reset/mailbox/reconvergence instances.
The historical batch21 routed result does NOT qualify this new netlist.
No new placement/route, full-board MIG/RGMII/clock-IP qualification, bit,
commit or push was performed.

## 2026-10-15 batch23: parallel parcel translation and disjoint instruction-cache control

Continues only /home/openion/Valence-inorder on feat/orbital-i1-five-stage.
Original OoO sources/worktree are not modified. Selected fpga8, single issue,
RV64GC/Sv39, I/D32KiB each/two ways, existing response queues, two DDR slots,
one AXI write owner and one private CPU/cache/PTW owner are unchanged.
No new architectural stage, TLB row, MSHR, prefetch queue or memory owner.

### Combined front-end restructuring

- FetchWordCuts exposes the already-existing current-PC and retained cross-word
  PC as raw alternatives plus the actual parcel selector. It creates no new
  instruction/translation owner or extra request.
- An optional translator interface defaults OFF. The selected CPU enables it
  only for C + FPGA cuts + fast IF + TLB<=8. Other profiles retain their normal
  indexed/no-sideband paths. Both raw addresses decode Bare/Sv39 exact page
  proofs, canonicality, privilege/PTE permissions and PMA in parallel BEFORE
  late parcel selection. Physical offer/acceptance and fastHold remain real
  sticky handshakes, with selected-address consistency assertions.
- Exact row0 payload precedence removes superpage-dominance qualification from
  unaccepted PA payload selection. Dominance remains mandatory for permission.
  An eligible physical page must equal the original fully qualified selection;
  stale/dominated leaves cannot authorize a request. Full-page PMP proof
  invalidation, SUM/MXR/U rules, A/D, noAllocate and precise faults remain.
- Instruction-cache phase transitions become mutually exclusive parallel
  events instead of a nested eviction/bypass/read/write/hit priority chain.
  Explicit B priority preserves simultaneous native response/probe and
  bypass/probe handoffs. The old next-state expression remains assertion-only:
  GSIM checks exact next-phase equality each cycle plus event exclusivity.
  Default/non-read-only cache state updates still use the original expression.
- Existing pending payload/index/bypass registers prepare while idle, even
  without a transfer; only accepted requests commit phase/response ownership.
  Old synchronous hit completion uses the old retained row on the same edge.
  Read-only hit completion is independent of miss/bypass priority. No hit or
  miss phase is added; no response can precede actual accepted ownership.

### Short verification and matched performance

Receipt: build/gsim/i1-coherent-network-timing23-20261015-r1/receipt.json.
SHA256 3575c750dd9999ce51dcede2221339f5eda66b0e0963cdb1017a9c5e30f6223f.
198checks/negative controls and15Scala configuration tests PASS;342source/
558artifact hashes match. Necessary short ASan/UBSan GSIM only; no full Linux
simulation, full regression or retired simulator.

New independent instruction-candidate fixtures use4/8TLB rows and aligned,
non-page-aligned and board2GiB PMA windows. Each executes305cases, including
4KiB/2MiB/1GiB, PMP, privilege/PTE faults, SFENCE, physical/PTE errors and
stalls; selector mask3 exercises BOTH address alternatives while changing
the unselected candidate10103times. Existing exact physical-address and
single-owner oracles remain independent. Page-fault and PMA negative controls
reject their mutations. No fake passed marker replaces these byte/fault checks.

Both256B/32KiB cache fixtures preserve warm32hits/33cycles and full-capacity
alias/PMA/noAllocate/error/probe/flush/reset/stall coverage, with exact old
phase assertions active. Real CPU C/A partial-page faults, privilege/PLIC/
timer and2320F/D numerical cases plus32context/fault cases also pass.

ALL12 selected2KiB/32KiB Bare/Sv39 streaming scenarios exactly retain cycles,
read/write/COPY ticks, retired instructions, bytes, AXI traffic and latency
floors, including40/80cycles. Actual old hardware is rerun under the same
new driver/service law. Whole-line-off and fast-data-off parameter controls
also pass. O3 CoreMark remains ROI738505cycles/345517instructions,
IPC0.4678600686522095, whole785672cycles/367211retired,
trace7b173819116883a2, CRC0xe714,257AXI reads/0writes.
Short duration warning remains: this is NOT a formal CoreMark score.

### One synthesis and same-DCP diagnostics

Package: E:\VM\Share\Valence-rtl\orbital-i1-timing23-20261015-r1.
Its exact-qualified CHIRRTL/ISA/options, RAM binding and original3.333ns
constraints pass the exporter gates before ONE synthesis. No weakened
exception, change to part/directive/clock target or resynthesis for queries.
Existing setup/hold and storage diagnostics run in parallel ONLY after
synthesis finishes and available host memory is checked.

Canonical archive:
build/fpga/i1-network32-timing23-synth-20261015-r1/receipt.json.
SHA256 1ade144acb39bd0134179dfb69bfff3149e4b26912cbd103daa87cab9d1ca548.
Constrained DCP SHA256:
fcc0089c273df5a3f7afe40624efbe54a0211db5f6e356ca742385f96f81eca9.
196small reports/logs/helpers/proofs live in WSL; full DCPs remain in E:.
Collector verifies old/new native logs, reports, JSON, same checkpoint hashes,
all12performance scenarios and exact current source/export/GSIM/proof hashes.

Mapped77,240LUT/43,216FF/3666LUT-memory/34.5BRAM tiles/28DSP.
Versus batch22: −48LUT,−6FF; BRAM/DSP/LUT-memory unchanged.
All24cache BRAMs remain mapped with884736allocated bits; RF2/FPR3 and ROM
are real BRAM, tag/directory payload FF count stays zero. Duplicating small
combinational candidate proof logic does not add translation capacity.

| Setup family (ns, synthesis only) | Batch22 | Batch23 |
| --- | ---: | ---: |
| Overall CPU | −1.574 | −1.288 |
| Entire instruction cache | −1.574 | −1.282 |
| Native fetch admission | +0.052 | +0.515 |
| Instruction BRAM address/enable | −0.434 | +0.029 |
| Instruction victim registers | −0.817 | −0.279 |
| IF translation/control | −0.672 | −1.113 |
| EX/ADDR result | −0.811 | −1.062 |
| Probe context | −0.429 | −0.735 |
| Cache valid metadata | +0.759 | +0.759 |
| Replacement metadata | +1.231 | +1.482 |
| Entire Home directory/control | +0.498 | +0.498 |
| Home line writer | +1.002 | +1.002 |
| DDR payload capture | +1.309 | +1.309 |
| PLIC pending→CSR result | +0.459 | +0.459 |
| DMA status capture | −0.130 | −0.130 |

The requested address/BRAM path improves and its BRAM-input slack is positive,
but+0.029ns is thin SYNTHESIS slack, NOT routed closure. I-cache overall only
improves0.292ns and CPU0.286ns;300MHz remains UNMET.
EX, IT control and probe regressions are retained explicitly, not hidden by
the aggregate improvement.

New CPU worst is15levels/4.504ns: MEM packet fault→core admission/permission/
progress control→D-translator PA synchronous reset,−1.288ns.
New I-cache worst is14levels/4.511ns: EX source-register selection→operand/
numerical completion control→CSR/IF eligibility→Cache state.CE,−1.282ns,
not the previous aligner-state→superpage-selected PA→tag→state.D path.
EX's18-level MEM-destination/bypass→ALU result remains−1.062ns.
The next batch must address backend completion/fault/forward-progress fanout
and translator owner qualification TOGETHER, not add another PC mux tweak
or call this a fully solved IF chain. Preserve precise kill/drain, context
ordering, byte/traffic oracles and the measured IPC.

Hold unchanged: internal CPU FF-only+0.006ns, UART raw→gated−0.037ns,
all internal−0.348ns, global/OOC-input-budget−2.701ns.
CPU clock-group−0.075ns includes declared input delays, not FF-only hold.
All46CDC Critical remain known REVIEW_REQUIRED (7CDC-10/37CDC-11/2CDC-1),
unknown0, no waiver or signoff. A category-name/reset-net representation
change is NOT a CDC improvement. Narrow clock/USER2 proofs do not qualify
all MAC/reset reconvergence or actual board clock/MIG/RGMII I/O timing.
Historical batch21 routing does not qualify this netlist. No new placement/
route, bit, commit or push. Original OoO remains untouched.

## 2026-10-15 batch24: parallel backend capacity and unowned translation payload preparation

User-requested combined follow-up to batch23: backend fault/progress to
translation/cache admission, EX bypass, IT and probe regressions. The selected
fpga8 single-issue RV64GC/Sv39 configuration keeps I/D32KiB, two ways,
predictor128/PMP8, all existing pipeline edges and transaction slots.
Private CPU/cache/PTW capacity remains ONE real owner; the DDR engine retains
two real slots and one AXI write owner. No OoO source or vendored FPU change.

### Combined structure, not additional stages

- MEM completion, ADDR vacancies and EX local completion are separate from
  the common recovery mask. ID capacity is a parallel sum of vacancies,
  rather than the MEM-fire to ADDR-fire to EX-fire to frontend-ready ripple.
  Runtime assertions compare exact old handshakes. No predicted reply,
  skipped dependency, reservation change or posted store acknowledgement.
- EX payload selection uses the nearest producer owner before availability.
  The dependency/admission path still blocks an unavailable owner; it must
  never select an older same-rd writer instead. Availability no longer gates
  the wide operand mux before the ALU. Consumed values are checked against
  the admitted-mask result. Stalled, unconsumed payloads are not architectural.
- Existing saved/context/PA registers prepare while the translation payload
  is unowned: idle, fast IF receive, or replaceable registered data reply.
  Phase/authorization, real request acceptance, sticky fastHold, physical
  response/error and context invalidation semantics remain authoritative.
  A successful fast page proof selects its real PA; a slow access keeps
  the original VA for lookup/authorization. No TLB row or payload slot added.
  Idle payload switching may increase; power has not been measured.
- Existing probe resume prepares from local phase, bypass-acceptance and
  reply-consumption events, without a B-fire-qualified encoded priority mux.
  A shadow of the original resume update is assertion-only and compared
  whenever a probe owns the cache. B/C, reply consumption, backpressure and
  simultaneous bypass/probe handoffs retain their original edges.

All new production behavior is under the existing FPGA/control-cut options;
ISA features, cache capacities and parameter-off paths remain removable.

### Short evidence and unchanged performance

Receipt: build/gsim/i1-coherent-network-timing24-20261015-r1/receipt.json.
SHA256 706703b529a309bcfe601369dfecaee888e7a05266a6d0013afa4a9b553d5558.
202checks/negative controls and15Scala tests PASS. All344source and572artifact
hashes were read back. ALL198pre-existing check results are exactly identical
to batch23, not merely passing status markers.

The new independent actual-helper fixture exhausts128backend occupancy/
completion combinations and512producer/availability combinations, including
112blocked-nearest cases and100cases with a shadowed older producer. Both
capacity and payload-oracle mutations are rejected. Existing exact probe
resume, IF phase and true handshake assertions run in the affected models.
Both256B/32KiB IF fixtures keep32warm hits/33cycles; resident aliases, PMA,
noAllocate, errors, probe, flush, reset and stalls pass.

ALL12selected Bare/Sv39 streaming scenarios retain exact read/write/COPY ticks,
cycles, bytes, retired instructions, AXI traffic and service floors, including
40/80cycle delays. Actual frozen old hardware is rerun with the same driver.
Whole-line-off and fast-data-off controls also keep their previous results.
O3 CoreMark retains ROI738505cycles/345517instructions, IPC0.4678600686522095,
whole785672cycles/367211retired, trace7b173819116883a2, CRC0xe714,
257AXI reads/0writes. This short run is NOT a formal CoreMark score.
CPU2320F/D numerical and32context/fault cases, C/A partial-page faults,
privilege/delegation/PLIC/SBI timer and fetch-control checks pass.
Fifteen Python exporter/RAM, report-collector and CDC-parser unit tests pass.

### One synthesis: local gains, overall regression, NOT promoted

Package: E:\VM\Share\Valence-rtl\orbital-i1-timing24-20261015-r1.
Original3.333ns/part/Default directives and all constraint gates are retained.
ONE synthesis, then parallel read-only setup/hold/storage queries on the
exact batch23/current constrained DCPs. No optimization or constraint change
is performed by those queries.

Canonical archive:
build/fpga/i1-network32-timing24-synth-20261015-r1/receipt.json.
SHA256 de51df0383afcb2b441fb53d95d8f77f4e9cb958230f0dff802ee57f2bd3a9f9.
Current constrained DCP SHA256:
71b6e1ec3f5bf8f3f5ce5108394cbd5e36cdb99ee2f518ef235daaad3c3173d4.
196small reports/logs/helpers/proofs are archived in WSL. Full DCPs stay in E:.
Collector verifies current source/export/GSIM/proof hashes, both checkpoint
identities and native/JSON/report ledger agreement;12matched stream cohorts
are all cycle-identical. Physical/board/CDC/routed/bit flags remain FALSE.

77,186LUT/43,215FF/3666LUT-memory/34.5BRAM/28DSP: versus batch23,
54fewer LUT and1fewer FF. Cache24BRAM primitives/884736allocated bits,
RF2/FPR3/ROM1 and zero tag/directory payload FF remain. No storage expansion.

| Setup family (ns, synthesis only) | Batch23 | Batch24 |
| --- | ---: | ---: |
| Overall CPU | −1.288 | −1.431 |
| Entire instruction cache | −1.282 | −1.431 |
| IF translation/control | −1.113 | −1.102 |
| EX/ADDR packet | −1.062 | −1.003 |
| Probe context | −0.735 | +0.231 |
| Native fetch admission | +0.515 | +0.535 |
| Instruction BRAM address/enable | +0.029 | +0.049 |
| Instruction victim registers | −0.279 | −0.345 |
| Cache valid metadata | +0.759 | +0.165 |
| Replacement metadata | +1.482 | +1.473 |
| Entire Home directory/control | +0.498 | +0.498 |
| Home line writer | +1.002 | +1.002 |
| DDR payload capture | +1.309 | +1.309 |
| PLIC pending to CSR result | +0.459 | +1.004 |
| Entire fabric | −0.889 | −1.297 |
| DMA status capture | −0.130 | −0.130 |
| FPU control | −0.187 | −0.252 |

Probe gains0.966ns and becomes positive in SYNTHESIS; this is not routed
closure. EX and PLIC/CSR improve, but IT barely changes. Overall CPU regresses
0.143ns; cache metadata loses0.594ns of margin, fabric loses0.408ns, and
victim/FPU also regress. This candidate is NOT a new best timing baseline
or a qualified300MHz replacement. Preserve batch23 as the better completed
synthesis reference; it also did NOT meet300MHz.

The new worst is15levels/4.660ns (0.647logic/4.013estimated routing):
ID instruction bit14 to C expansion/serial decode, ID drain/frontend response
capacity, aligner/translation admission, then I-cache state.CE. The actual
netlist includes decoder/rrPacket_control_serial_i_1 and the frontend-ready
chain. It is no longer the previously reported MEM fault to DT PA capture
path; that does NOT prove every D translation path is closed.

Second: DT state to nativeCut_1 request address.CE,14levels/4.526ns,
−1.297ns. EX's worst now ends at ADDR cause rather than the previous result:
WB destination ownership/bypass to fault classification,16levels/4.318ns,
−1.003ns. Those control/authorization cones remain real unresolved work.

Next coherent batch should preclassify serial/control at an existing frontend
packet edge, isolate live C expansion/decode from global fetch capacity,
and address D translation/cache/native admission together. Also inspect
EX fault/cause selection and local metadata clears with reduced margin.
Do not add bubbles, stages, transaction slots or a success-prediction shortcut
to hide these paths; preserve the measured IPC and independent byte oracles.
These are next-step candidates, NOT implemented or verified improvements.

Hold unchanged: CPU internal FF-only+0.006ns, UART raw-to-gated−0.037ns,
all internal−0.348ns, global/OOC-input-budget−2.701ns. CPU clock-group
−0.075ns includes declared input delay, not FF-only hold.
CDC remains46Critical (7CDC-10/37CDC-11/2CDC-1), unknown0, review required,
no waivers/signoff. Narrow clock/USER2 proofs are unchanged and do not cover
all MAC/reset reconvergence or actual board clock/MIG/RGMII I/O timing.
No new placement/route, bit, commit or push. Historical batch21 routing
does not qualify batch24. Original OoO remains untouched.

## 2026-10-15 batch25: registered serial class, prepared native payload and local metadata

Combined follow-up for the measured ID decode/frontend/cache phase,
D translation/cache/native admission and marginal cache valid-bit paths.
Selected fpga8/RV64GC/Sv39, I/D32KiB/two ways, predictor128/PMP8 and all
transaction slots/pipeline edges remain unchanged. No shared OoO or vendored
source changes, no extra queue slot, RAM port, MSHR or response prediction.

### Structure and compatibility guards

- A compact raw-instruction serial CLASS is captured at the existing IF/ID
  edge. Live ID compressed expansion/full decode is no longer in serial
  drain/frontend capacity. This is not legal-instruction or permission
  prediction: native A/F-disabled behavior and reserved compressed classes,
  including illegal JR-x0's expanded SYSTEM class, match the original decoder.
  A live-ID assertion compares the retained bit with full C/ISA decode.
  The bit exists only with the existing FPGA timing-cut option.
- Existing ordered D-cache pending request/index/bypass registers prepare
  while idle, like the IF side; only real acceptance commits ownership.
  Older pending hit metadata consumes the OLD registers at the same edge.
  Existing dirty/MRU forwarding and data/response edges remain unchanged.
- I1-local request FIFO implementation optionally prepares EMPTY/vacated
  head/tail payload independently of input VALID. Moving an owned tail wins;
  held owned head/full tail cannot change. Capacity2, minimum1cycle, II=1,
  occupancy-only READY and no full-queue credit borrowing are unchanged.
  Original shared TwoEntryRegisterQueue is not modified. Preparation defaults
  OFF; only the two private native fabric cuts select it under coherent
  control cuts. Other native boundaries retain default payload behavior.
- Flush scanning clears its addressed row without reading a dynamic512-row
  valid mux to authorize clearing that same row. An already invalid row
  stays invalid; invalid rows must not own dirty data. State progression and
  actual release traffic still use the real resident/dirty state.
  Local valid/dirty next-bit equations replace clear-qualified hold enables.
  Old next-bit semantics and invalid/dirty ownership are assertion-checked.
  Install/probe/victim/flush maintenance ownership remains mutually exclusive.

Independent new fixtures cover98304serial samples (all65536compressed
encodings,7ISA configurations) and default/prepared FIFO behavior against
both an external byte-token/credit ledger and the original shared FIFO.
Each FIFO mode runs20000stimulus iterations and11resets, including held
payloads, full queues and simultaneous consume/replace. Class, payload and
credit mutations must all be rejected. All prior qualification gates remain.

The first short attempt, build/gsim/i1-coherent-network-timing25-20261015-r1/
receipt.json, stopped at the existing180second limit on the Bare64KiB/
80cycle-latency check. It remains FAIL; the synthesis gate correctly stopped.
All preceding completed selected stream results matched old cycles/traffic.
CHIRRTL inspection found that the assertion-only legacy valid(flushIndex)
lookup was independently expanded for every row:512copies of a512-way mux
per cache. Sharing this read-only expression reduced raw CHIRRTL lookups516
to5, but generated C++ only shrank1380bytes: backend CSE already merged much
of the duplication. It was NOT sufficient evidence of a solved runtime cost.
The r2 attempt was explicitly stopped during its owned32KiB compile and
recorded FAIL(-15); its synthesis gate also stopped, before CPU qualification.

The final verification formulation compares complete valid/dirty NEXT-state
bitmaps and the complete invalid/dirty ownership bitmap in THREE assertions,
not3*lines separate event-driven monitors. Each bit/row is still checked:
legacy masks independently retain the old install/store/clear priority and
valid-qualified flush condition. Production next-bit equations, timeouts,
service laws and external byte oracles are unchanged. Fresh r3 must rebuild
all changed FIR models and rerun ALL positive/negative checks. Failed runs
can provide only exact hashed unaffected compilation artifacts, never PASS
qualification. No batch25 synthesis was launched by r1 or r2.

## 2026-10-16: batch25 stopped-test scope and actual ZU15EG board integration

The user explicitly stopped the remaining control comparisons after the selected
CPU configuration passed. The r4 receipt remains FAIL(-15), not a fabricated
full-suite PASS. Its adjacent stop-summary.json records176/212 completed checks
and36 deferred comparisons (whole-line-off9, structural-only13, frozen-baseline13,
network-shell1). The selected Bare/Sv39 streams retain the batch24 cycles and
traffic. The short O3 CoreMark ROI is738505cycles/345517instructions,
IPC0.4678600687; this is NOT a formal>=10second CoreMark score.
Only the approved per-check wall-clock limit changed180->300seconds;350 frozen
hardware/oracle input fingerprints are unchanged.

An explicit diagnostic export preserves that incomplete scope. Default strict
export still rejects the raw FAIL receipt. The independent selected target and
reference gates are not replaced with a success prediction. The diagnostic OOC
synthesis completed with CPU WNS-1.493ns: it is not a300MHz or board PASS.

Following the user's requirement for actual hardware, the isolated board is:

- E:/VM/Share/Valence-rtl/orbital-i1-board-zu15eg-20261016-r2/project/i1_board.xpr
- Top: soc_top_i1_network_ddr; xczu15eg-ffvb1156-2-i.
- Actual DDR4 MIG,32physical data bits,2GiB,1000ps memory clock period
  (1000MHz CK/2000MT/s),250MHz UI,64bit AXI. CPU addresses start0x80200000;
  range-checked subtraction produces the31bit physical DDR offset.
- Actual axi_clock_converter_i1, asynchronous AXI4 CPU300/UI250; not tied-off
  handshakes or a simulation memory.
- Actual clk_wiz_i1: CPU300, raw UART50, raw MAC125, pad250, IDELAY reference500MHz.
  UART/raw/gated and MAC/raw/gated BUFG leaves share parallel unbuffered MMCM
  outputs, not cascaded BUFGs.
- Real UART460800, reset/button/LED, verified DDR and RGMII package pins,
  MDC/MDIO IOBUF and carrier-inverted PHY reset. The tri-speed physical boundary
  uses recovered RXC directly, PHY RXDLY=1 with no second input data delay,
  and FPGA TXC+2ns with PHY TXDLY=0. Physical speed scenarios still require STA.
- Actual BRAM-inferred4KiB I1 BootROM hex, reset/calibration qualification and
  shared USER2 BSCAN loader. No unused licensed AXI Ethernet or legacy128KiB BMG
  is instantiated. I1 uses PLIC M/S contexts, not the OoO AIA firmware's DT/ABI.
  Old OoO Linux images are NOT declared compatible or board-tested.

Original GUI and OoO projects are not modified. A failed r1 IP-import output
location was corrected with import_ip into the isolated r2 project; r1 evidence
was retained. The r2 MIG, clock and AXI CDC synthesis runs all completed.
Actual clock-IP/physical-boundary short xsim passed300/50/125/250/500MHz periods,
12symbol cases covering all four TXC data pairs, common word reset and fixed2ns
TX skew. This is not analog calibration, full-board boot or routed signoff.

Whole-board synthesis completed:92036LUT,58333FF,58RAMB36+2RAMB18,31DSP,
including MIG/AXI CDC. These are pre-optimization counts, not routed utilization.
Strict endpoint checks verified real clocks, package/electrical constraints and
USER2. The unused external IRQ first-stage D is proven directly GND; it receives
no timing exception and is excluded from qualified CDC counts. Other actual
CDC bounds remain strict (2register bridges,9mailboxes,3Gray FIFOs,61level links,
3FIFO payload paths). Tcl-only revisions preserve the initial board manifest
and all prior failed implementation logs, reusing the SAME CPU/IP synthesis.

The real-board implementation has completed with300MHz unchanged. Final routed
WNS is-1.207ns, TNS-10225.333ns (26445failing setup endpoints), WHS-0.714ns,
THS-3.421ns (five failing hold endpoints). The worst CPU path is
csr/pmpNapotUpper_4_reg[15] -> it/state_reg[2]; its4.251ns data delay is
1.305ns logic plus2.946ns routing. No300MHz signoff or bit release is allowed.

Final routed utilization, including MIG/AXI CDC and physical MAC, is91316CLB LUTs
(26.76%),59074CLB register resources (8.65%;59073actual FFs),58RAMB36+2RAMB18
(59BRAM36 equivalents,7.93%),31DSPs (0.88%) and no URAM. The prior synthesis
figures above remain historical, not final utilization.

Read-only reports from the same real_board_routed.dcp are in
reports/media-rates-r2. CPU/DDR UI/AON/UART/fixed MAC/PAD/IDELAY setup slacks are
-1.207/+0.071/+2.426/+2.426/+1.171/+0.109/+0.027ns respectively; their hold
slacks are+0.005/+0.011/+0.021/+0.021/+0.012/+0.185/+0.049ns. AON and UART
rows share an actual generated clock but retain their separate hardware buffers,
gates and hierarchy. The recovered RX internal-clock row is+1.566/+0.021ns;
it does NOT include or qualify the physical RX input hold check.

All three temporary STA media-rate scenarios (1000/100/10Mb/s) retain TX
setup/hold+0.064/+0.136ns. Physical RX setup is+1.148/+17.148/+197.148ns,
but physical RX hold is-0.714ns at ALL three rates. No hardware clock, RTL,
PHY/PCB budget or routed checkpoint was changed for this analysis.
Bus-skew constraint24 is also negative (-3.991ns), with mixed RAM/local-FF
launches to physicalIngress/crossing/fifo/output_0_reg*. CDC has50critical
classifications, not50proven functional bugs, and is NOT signed off.

The requested read-only GitHub comparison used dev commit
1a40353eadf8b2962fd3416f03f2dba4ed2cdc21 (2026-10-16,+0800), not main.
Its fpga/next/soc_top_fpga_next_ddr.sv explicitly selects RX_DATA_DELAY_PS=1100;
the current I1 board wrapper selects0. PHY RXDLY concerns clock timing whereas
IDELAY here delays data; the earlier no-second-delay rationale is not physical
proof. Revisit the full input timing window before selecting a new value.
Dev also provides default-off MacRawHandoff, LOCAL_PAD_RESET_RELEASE and
REGISTER_SELECTED_HALF candidates, plus exact RAM-leaf CDC payload audits.
These are not a measured fix for this board and cannot resolve the CPU PMP
path. The exact-leaf audit may clarify the mixed-launch skew scope without
relaxing actual crossing bounds. No dev changes have been merged or applied.

Consolidated results and comparison details are in the board package's
reports/board-review.md; the unchanged routed DCP SHA256 is
56e7a07878a7b8c15d9d555d6c106b9ada9e71abec6c17df5c2a60e575495f11.
All350frozen inputs and staged input fingerprints remain unchanged.
Full short-suite qualification, CDC/hold signoff and Linux/board boot remain
unclaimed; no bit was generated.

## 2026-10-16: batch26 CPU cuts and temporary no-MAC board candidate

The user requested a coherent batch targeting the actual routed CPU paths,
retaining300MHz, I/D32KiB, independent CPU/DDR/AON/UART clocks and the unchanged
OoO core. MAC/PHY/network DMA are deliberately omitted from this NEW board
candidate while waiting for dev MAC work; the normal network sources and prior
routed board are preserved. This is not a claim that MAC timing has been fixed.

The batch changes only I1 hardware and its independent test adapters:

- Effective PMP lower/upper ranges are CSR sidecars committed on the same WB
  edge, including TOR neighbour dependencies, locks and NAPOT/NA4 modes.
  Assertions compare them with the original architectural range expressions.
- Optional registered PMP range-match/grant vectors separate parallel
  comparisons from first-match permission/state reduction. Cold demand and PTW
  authorization each gain one edge; cached full-page hit paths do not.
- Offered PA capture is independent of fast permission and upstream admission.
  Only real Sv39 chooses a cached physical page. A reserved SATP MODE fixture
  caught and corrected an early candidate's wrong PA choice; its failed receipt
  is retained, not relabelled PASS.
- RF->EX captures nearest-producer identity; a stalled EX follows only real
  ADDR/MEM/CMP/WB handoffs. No request slot or pipeline stage is added.
  A live independent nearest-writer expression asserts exact ownership.
- IF decodes fixed halfword windows before parcel selection, removing the
  wide byte-barrel/length/selection cascade without changing reuse or latency.
- Victim tag words are retained before live hit/way selection, and the existing
  evictCapture edge reconstructs the address before the first C beat.
- FCVT-to-integer alignment and rounding/saturation are split in an I1-local
  adapter derived from pinned RecFNToIN, preserving its license and arithmetic.
  Vendor HardFloat and OoO sources are unchanged. This instruction gains one
  edge; independent SoftFloat values/flags, exact per-op latency, token,
  backpressure, completion and stage-kill checks remain mandatory.

The focused runner is simulator/gsim/inorder/cpu_timing26_acceptance.py.
It uses exact hashed batch25 payloads and runs only affected units plus one
actual32KiB CPU model: Bare/Sv39 normal and80cycle memory latency, privileged
faults, C/A page boundaries, F/D corpus/context and same-binary O3 CoreMark ROI.
It does not run the full212-check suite, long Linux or physical qualification.
All execution checks rerun even when exact-FIR/hash-verified compilation objects
are reused; an earlier failed receipt never supplies PASS status.

Active short evidence is build/gsim/i1-cpu-timing26-20261016-r4/receipt.json.
Earlier r1/r2/r3 failures retain the original diagnostics and test status.
The r4 affected short receipt completed PASS with51checks, including actual CPU
privilege/C/A/F/D, all six selected Bare/Sv39 streams and exact-binary O3 ROI.
The O3 ROI changed738505->747569cycles (+1.2273%); retired ROI instructions,
trace hash, CRC and AXI traffic remain identical. IPC changed0.467860->0.462187.
This is a measured performance cost, not a zero-IPC-cost claim. A cold
authorization means a permission-memo miss and can recur during execution,
not only once at boot. Its contribution to this ROI has not been counter-traced.
64KiB COPY cycles: Bare226983->226949, Sv39227540->227540;
80cycle memory latency: Bare483485->483267, Sv39483982->483985.
No new routed frequency, board, bit or formal CoreMark result is claimed yet.

The new export_board_cpu.py strictly requires the complete affected-short PASS
and unchanged source/artifact/HardFloat fingerprints before export. Its explicit
I1PeripheralFpgaShell composition retains CMU and managed UART50, M/S PLIC,
F/D, Sv39, BootROM and USER2 while reporting Ethernet clock resources absent.
Real MIG2GiB/UI250 and asynchronous AXI64 CPU300->UI250 are retained exactly.
The old board's fixed IP outputs may be copied into a fresh isolated project;
the OLD CPU synthesis/placement/routing is not copied or reused. The new CPU
must undergo one fresh full-board synthesis and route with setup/hold/CDC/skew
and utilization reports. The pipeline waited for short PASS before launching.
The new project is E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261016-r1.
Fresh CPU synthesis completed with82480LUT/50876FF/54RAMB36+1RAMB18/31DSP;
these are pre-optimization counts, not final routed resources. MAC removal is
part of the area reduction, so it must not be credited entirely to CPU changes.
Whole-board implementation completed with the tested RTL frozen. Final routed
STA is WNS-0.956ns / TNS-2405.386ns (8894failing endpoints), WHS+0.002ns,
THS0 and pulse-width slack+0.081ns. Thus300MHz is NOT qualified and no bit
was generated. The new worst path is secondPc[15] -> instruction translation
selection -> I-cache tag compare -> cache state CE,4.257ns /12levels /68.1%route.
The next near-worst families include memValid -> DTstate (-0.954ns) and ITtag
-> PA enable (-0.952ns); removing the prior PMP path from the very worst
position does not imply the remaining CPU paths have passed.

Final no-MAC whole-board resources are82268LUT (24.11%),51744register
resources (7.58%),54RAMB36+1RAMB18 (54.5tiles,7.33%),31DSP (0.88%),0URAM.
All119530routable nets are routed with0routing errors. DDRUI250 setup/hold
are+0.400/+0.011ns; AON/UART50 share an actual generated clock and retain
the independent physical UART buffers/gate, with group slacks+1.490/+0.025ns.
UART-internal sequential paths alone have+14.360/+0.025ns.
All20reported bus-skew constraints are positive; the smallest slack is+2.315ns.
CDC reports9critical classifications (6reset fan-outs and3reset logic
crossings), not9proven functional bugs and not signed-off CDC. No new
blanket false paths, clock-group cuts, or relaxed timing constraints are added.
check_timing retains missing-delay classifications for button_n/sys_rst_n,
MIG c0_ddr4_reset_n and partial UART RX; it has0unconstrained internal endpoints.

The original build flow exited only during the final UART report query because
the unused ManagedUart.managedClock output had been optimized away. The routed
DCP and all main reports had already been saved. A read-only checkpoint review
resolves actual UART storage clock pins instead; it performs no implementation,
constraint modification or bit generation. The source build script is corrected
for the next export, but the staged original script and failure log are retained.
An initial review also retained its failed extra PMP-family hierarchy query.
The real routed DCP SHA256 is
924454ca0de9e50563db888cfd2b800ce35f9a26a06ff020ea352690b250a2a6.
All353frozen test/source inputs,364staged inputs and32reused fixed-IP files
remain hash-identical; the original OoO worktree is not modified.
The complete read-only recovery is reports/review-r4 (exit0), resolving the
actual UART storage clocks and all8CPU path families. PMP upper/lower launch
slacks are-0.214/-0.168ns; ALU-result endpoints are-0.659ns; FPU endpoints are
-0.739ns on branch-target/recovery control to misc-S response reset. These are
remaining violations, not passing families. reports/board-review.md consolidates
the real-board results, exact source/receipt boundaries and bandwidth conversion.

Bandwidth conversion for the user's 300MHz question uses the r4 measured
64KiB-per-buffer stream cycles, not old OoO or Linux results. At300MHz,
MiB/s = bytes *300000000 / cycles /1048576:

| Model / translation | READ MiB/s | WRITE MiB/s | COPY payload MiB/s |
| --- | ---: | ---: | ---: |
| Low latency, Bare | 140.48 | 150.80 | 82.62 |
| Low latency, Sv39 | 140.20 | 150.88 | 82.40 |
| Read floor80 / write floor79 cycles, Bare | 74.44 | 77.19 | 38.80 |
| Read floor80 / write floor79 cycles, Sv39 | 74.49 | 77.16 | 38.74 |

The low-latency model uses read floor3 / write floor2 cycles. These are
CPU-visible cached loops, not an uncached test or MIG peak. Each buffer is
larger than the32KiB D-cache, but cache allocation, hits, evictions and initial
state still affect results. The timed assembly does not explicitly drain the
final dirty writeback tail. COPY logical read-plus-write bandwidth is twice
payload (164.81MiB/s for low-latency Sv39,77.48MiB/s for latency80), not a count
of actual AXI bytes. The real board has fixed UI250 and asynchronous crossings;
memory latency in CPU cycles can change with CPU frequency. These conversions
are not board measurements, do not establish a maximum bandwidth, and do not
qualify300MHz setup/hold/CDC.

## 2026-10-16: batch27 in progress, same no-MAC multi-clock board target

This batch targets the actual batch26 routed paths, not an OOC-only CPU.
CPU300, DDRUI250, AON/UART50 with the existing physical buffers/gate, I/D32KiB
and the original OoO project remain unchanged in scope. No MAC is reintroduced.
Before editing, the affected batch26 sources were copied to
build/checkpoints/i1-timing26-before-batch27-20261016.

The combined implementation changes are:

- Existing I-cache pending payload, raw way tags and SRAM return cycle now
  classify the accepted owner AFTER the edge. A three-bit marker/way-valid
  sidecar selects the effective phase from registered inputs; hit data and
  miss/eviction/bypass commands retain their intended old cycles. An independent
  captured legacy phase asserts the retiming, and the existing continuous-hit
  test still requires32hits in33cycles. No extra request/response slot is added.
- Both ordered32KiB caches read physical ways before hit qualification.
  D-cache BRAM address/enable no longer depends on live tag selection. This
  trades BRAM packing for timing, NOT larger caches; final area is unmeasured.
  Ordered native bypass now always leaves the retained owner, not live DT/tag
  classification. It may add one edge to an uncached D request.
- The bounded fast D translator prepares the existing MEM/ADDR candidate
  addresses/operation fields in parallel. Late backend occupancy selects only
  prepared results. Superpage dominance, exact proof tags, dynamic SUM/MXR,
  effective privilege, A/D, atomic read/write checks and sticky offers remain.
  Configurations above8TLB entries retain the indexed implementation.
- IT/DT lookup and PTE PA payload capture no longer uses permission/tag success
  as a wide register enable. Only the phase authorizes physical side effects.
- Grouped FPGA equality/ordering and eight-bit carry-select/lookahead shorten
  PMP, EX ALU/address/branch and branch-recovery comparison cones. Compact/default
  arithmetic remains selected outside explicit FPGA timing mode.
- Miscellaneous F/D does not clear invalid response payloads at intake.
  Completion still writes every result/status field and captures the real
  token. Flush invalidates ownership immediately; vendor HardFloat is unchanged.
- An architectural pmpAllOff sidecar commits on the SAME CSR edge as PMP
  configuration. Only effective M-mode, an aligned <=8B interval and a fitting
  physical address can bypass page-proof thrash. S/U/MPRV-lowered accesses,
  active/locked/partial PMP regions and high aliases retain ordinary checking.

Verification uses simulator/gsim/inorder/cpu_timing27_acceptance.py and exact
old payloads. It adds both32/64 EX numerical/ownership tests, noisy unselected
DT candidates, all-OFF cross-page and privilege/limit controls, and independent
full-capacity coherent I-cache PMA/probe/flush/continuous-hit tests. All original
independent oracles and negative mutations remain. A selected one-slot
retirement-overlap mode is measured explicitly; generic defaults remain OFF.
CoreMark must recover the pre-batch26 ROI and the64KiB READ+WRITE+COPY aggregate
must not regress at either modeled latency before this candidate can pass.

The r1 receipt preserves a missing default clang++ preflight failure; the runner
uses the pinned installed clang++-19. The r2 receipt preserves30passed checks
followed by a cache elaboration failure (effective state wire width unknown).
An explicit enum width fixes elaboration without changing permission/data
oracles. The active r3 run enables full single-owner consume-and-replace;
unit compilation may be reused only on exact fresh-FIR/artifact hashes, and
every execution/negative check reruns. No new performance gain, routed300MHz
qualification or bit is claimed while this acceptance is incomplete.

The r3 candidate was interrupted after51completed checks when a required
64KiB aggregate was already deterministically worse (484756vs484755ticks,
READ/COPY equal, WRITE+1; whole-program cycles equal). It is not promoted.
The raw FAIL/KeyboardInterrupt receipt and a hash-bound stop-summary.json
remain preserved; CoreMark had not completed and no synthesis was launched.
The second small source snapshot is
build/checkpoints/i1-batch27-r3-before-direct-20261016.

The r4 extension retains the same batch/targets and adds:

- Default-OFF directFastDataIssue / --direct-fast-data-issue. Only an already
  authorized, naturally aligned <=8B non-atomic owner can hand off physically
  at its real CPU acceptance edge. Otherwise the exact same owner is retained
  in existing send. No posted success, extra credit/slot or atomic reordering.
- FPU producer cancellation is registered locally in FPGA mode. Top-level
  VALID is immediately suppressed on flush; registered cancel-pending masks
  stale completion while local producers clear. The existing capture/dispatch
  edge can accept the next token without adding normal numerical latency.
  Raw completed remains independent of same-cycle flush as required by the
  original independent completion-status oracle.
- Independent stream executions use two processes with separate DUT state and
  logs, a locked receipt writer and unchanged300second per-item wall limits.
  No simulation size, memory-service law or negative-control criterion changes.

R4 unit evidence so far retains the exact F/FD numerical/latency/II/stall/kill
counts from r3, and the same32hits/33cycles coherent IF check. A separate24request
diagnostic linked the SAME already compiled split-D model:16physical handoffs
occur at the CPU acceptance edge and8use retained/cold/backpressured paths;
all responses use the independent software address/data oracle. This diagnostic
does not itself establish CPU bandwidth. Its source/result are included in
build/gsim/i1-cpu-timing27-20261016-r4.

R4 acceptance completed PASS_I1_CPU_TIMING27_AFFECTED_SHORT_ONLY with61checks.
All6performance gates pass. The same O3 binary has345517ROI instructions,
367211total retires, trace7b173819116883a2 andCRC59156, unchanged. ROI is
747569->648282cycles (-13.2813%cycles /+15.3154%throughput), IPC0.462187->0.532973.
Against pre-batch26 ROI738505, throughput improves13.9172%; the earlier loss is
recovered. CoreMark AXI reads change257->256, writes remain0; do not claim
identical CoreMark bus traffic. This is one-iteration short ROI, NOT a formal
>=10second CoreMark score or a board frequency/performance result.

| 64KiB CPU stream model | READ old -> new | WRITE old -> new | COPY old -> new |
| --- | ---: | ---: | ---: |
| Bare, read3/write2 floor | 133467 ->125915 | 124339 ->123474 | 226949 ->211345 |
| Sv39, read3/write2 floor | 133733 ->125688 | 124272 ->123446 | 227540 ->211077 |
| Bare, read80/write79 floor | 251871 ->244050 | 242899 ->241768 | 483267 ->467565 |
| Sv39, read80/write79 floor | 251721 ->243822 | 243006 ->241930 | 483985 ->467541 |

COPY payload throughput improves7.38%/7.80% in low-latency Bare/Sv39 and
3.36%/3.52% in latency80 Bare/Sv39. Every large stream retains the exact
same retired instruction count,5132/5133AXI reads (Bare/Sv39) and2819writes.
At a hypothetical qualified300MHz, Sv39 low-latency R/W/COPY is
149.18/151.89/88.83MiB/s; latency80 is76.90/77.50/40.10MiB/s. All prior
cached-loop/undrained-tail/model-vs-board boundaries still apply.

Actual CPU privilege/C/A/F/D/fetch-control checks pass. FD2320cases now take
418027cycles (old429509), with39466retires/8560FP writes/23flags/1trap;
FP context32cases take4863cycles,578retires/105FP writes/16flags/9traps.
All355frozen source/test files have no drift; compared with batch26,
OoO and shared IP source changes are zero.

One fresh real-board synthesis/implementation completed at
E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261016-r2. It was launched
only after short PASS and all performance gates. Its actual manifest binds
both32KiB caches'32per-way SRAM instances, CPU300/UI250/AON50/UART50,
2GiB DDR,64-bit AXI and the same fixed MIG/clock/AXI-CDC IP; old CPU reuse=false,
MAC=false. RTL remained frozen through implementation.

The candidate is NOT promoted: short cycle/IPC/bandwidth gains are positive,
but routed timing and LUT area are worse. CPU300 WNS is -2.164ns,
TNS -11544.286ns,26980failing endpoints, versus prior WNS -0.956ns /
TNS -2405.386ns. Global WHS +0.011ns, THS0, WPWS +0.081ns.
No new300MHz qualification, board boot or bit is claimed.

| Actual domain | Period ns | Setup ns | Hold ns |
| --- | ---: | ---: | ---: |
| CPU300 | 3.333 | -2.164 | +0.011 |
| DDR UI250 | 4.000 | +0.157 | +0.013 |
| AON50 | 20.000 | +2.310 | +0.017 |
| UART50 storage clock | 20.000 | +2.310 | +0.017 |

The whole50MHz domain reports include CMU/UART CDC control paths; they do not
mean an isolated UART internal path consumes17.69ns. AON/UART retain the
existing parallel physical root buffers, not a cascaded BUFG or a new clock.

| Routed family worst setup | Batch26 ns | Batch27 ns |
| --- | ---: | ---: |
| PMP upper | -0.214 | -1.084 |
| PMP lower | -0.168 | -1.087 |
| IT endpoints | -0.952 | -1.607 |
| DT endpoints | -0.954 | -1.668 |
| I-cache endpoints | -0.956 | -1.357 |
| D-cache endpoints | -0.924 | -2.164 |
| EX ALU result | -0.659 | -1.660 |
| FPU endpoints | -0.739 | -1.251 |

These are worst paths in the same hierarchy families, not identical old/new
paths. Detailed start/endpoints are in reports/review-r4/families.tsv, queried
read-only from the SAME routed DCP. No extra synthesis/route or timing waiver
was used for these reports. The reused review script's legacy RECOVERY label
does not indicate a failure of the new automatic reporting flow.

The worst chain is dt/bareFastPage_reg[10] -> live authorized D-cache write-hit
control -> dataWays_2_1_ext/Memory_reg/ENBWREN:5.270ns,16logic levels,
1.584ns logic and3.686ns routing. This is the BRAM WRITE enable, not a harmless
speculative read enable. Do not remove authorization or write unconditionally
to hide it. The directFastDataIssue throughput option exposes a too-long
same-edge path when combined with physical cache write commit.

Other newly exposed paths include D-cache BRAM output -> IT PTE / DT result
payload capture, EX operandEnable -> upper ALU-result bits, and
addrPacket_address[1] -> FPU captured operand CE. Moving local cancellation
did not solve the FPU capture-enable boundary. Grouped mathematical operators
and wider parallel proofs must be judged by these physical results, not by
source-level depth or the numerical oracle alone.

Routed resources are87219LUT (25.56%),51612register resources (7.56%),
62RAMB36+1RAMB18 (62.5tiles /8.40%) and31DSP (0.88%).
Prior routed counts were82268LUT /51744registers /54RAMB36+1RAMB18 /31DSP.
LUT increases6.02%; parallel D-way reads cost8extraRAMB36 without increasing
logical cache capacity or request/line-owner slots. This is not an area win.

All20bus-skew constraints pass, minimum slack+2.545ns.131330routable nets are
fully routed, routing errors0. DRC has no Error/Critical,40Warnings.
Internal no-clock/unconstrained-endpoint/loop counts are0; the existing
button/reset input-delay, MIG reset-output-delay and UART partial-input-delay
coverage items remain. CDC still reports3CDC-10+6CDC-11Critical reset-related
classifications and377CDC-15Warnings, unchanged from the prior no-MAC board.
They are NOT signed off by adding a blanket waiver; full CDC closure remains
outstanding even though hold and bus-skew are positive.

The final input audit has355source files,362staged RTL/board/script files and
32fixed-IP files, with0missing/0hash drift in each group. The short receipt SHA256
is a82336fbfc6a8ea9d358d5d9f57f3288d5fb543472a4558edb51026c8e731085.
The routed DCP SHA256 is
72d0c4d97f9825c29fb11b24702d73883bf8746a170fdb57313df81a265f8609.
The machine-readable result and raw report hashes are in
reports/batch27-review.json under the isolated Windows board directory.

Next structural work is not implemented in this frozen batch: separate
authorized D-store ownership from BRAM write commit with correct same-address
forwarding/probe/flush order; bound the BRAM-return-to-translation response
path; remove live recovery/address qualification from FPU capture enables;
and reassess grouped EX/PMP arithmetic against actual FPGA paths. Retain
32KiB I/D, existing ownership capacity, generic switches default OFF and the
original OoO core unchanged. Do not infer physical performance from this
candidate's favorable short-cycle counts.

## Batch28: retained store commit and bounded return paths (2026-10-16)

This batch follows the batch27 routed failure, not a new capacity experiment.
Keep CPU300/UI250/AON50/UART50,32KiB I/D, two ways, existing owner/response
capacities and FPGA8; MAC remains absent. Original OoO/shared IP sources and
vendor HardFloat remain unchanged.

- Extend the existing ordered cache classification edge to D as well as I.
  Preserve the original request/hit-response edges while selecting hit,
  eviction and bypass from the retained request/tag/valid snapshots.
- Commit D hit stores to BRAM from that retained owner during its existing
  response cycle. Factor each way/word write enable directly; no live DT
  authorization -> tag/victim -> physical write enable path.
- A bounded last-write collision shadow forwards masked bytes to same-edge
  CPU reads, B probe capture and victim capture. It is not another request,
  line owner or response credit. Both pending store and this shadow forward
  dirty state; use the shadow's registered physical row for dirty-bit commit.
- Capture per-way victim dirty candidates before hit/victim selection and
  choose within the already existing eviction-capture edge.
- Prepare both SRAM ways continuously in explicit ordered FPGA mode.
  Discarded SRAM reads have no architectural authority or external effects;
  ownership still gates replies/writes. This removes permission from BRAM
  read enables, at the cost of more idle read-port activity in this mode.
- Explicit ReadFirst SRAM plus byte forwarding defines collision semantics.
  Bank selection is registered within the existing owner preparation edge;
  choose the word independently in each way before choosing the return way.
- Format native atomic lane replies before the cache response mux, removing
  the atomic shift barrel from ordinary cached and page-table read returns.
- IT/DT result and PTE registers prepare payload while their receive owner
  waits; ONLY real reply handshakes publish the next phase. No earlier grant.
- Record a real direct DT handoff with one bit, view receive immediately
  next cycle, and reconcile encoded state locally. No extra receive edge or
  replay of a request already physically accepted.
- FPGA FPU capture prepares while unowned; real fire still alone commits
  busy/dispatch. Rejection payload prepares on dispatch independently of
  recovery. Numerical producers, latency and initiation intervals unchanged.
- Zero unused/x0 base operands at the existing RF->EX edge. Producer identity
  and readiness remain exact, but operandEnable no longer precedes the
  wide fallback payload/ALU path. Restore native FPGA carry inference for
  addition/subtraction/ordering after the grouped-LUT physical regression.

The small pre-change snapshot is
build/checkpoints/i1-batch27-before-batch28-20261016. A new raw TL-C fixture and
independent software byte ledger test exact store/read, store/B and
store/noAllocate-victim overlaps at both256B and32KiB. Each currently passes
425accepted/returned requests,112immediate write/read collisions,8B-probe
collisions,8victim/bypass collisions,64dirty probe beats and64release beats,
plus expected independent-oracle negative controls.

The r1 short receipt preserves a pinned-GSIM syntax failure at Chisel's
smem dataWays..., old comma. The pinned parser grammar and AST implementation
support explicit old semantics but require a space instead of that comma.
The runner normalizes ONLY that delimiter in a separate GSIM input, retaining
old, original FIR and both hashes. No simulator/source modification or removal
of collision semantics. Synthesized RTL still uses the original explicit
ReadFirst FIR.

R2 completed PASS_I1_CPU_TIMING28_AFFECTED_SHORT_ONLY at
build/gsim/i1-cpu-timing28-20261016-r2/receipt.json:65checks,18performance gates
all pass. The batch27 PASS receipt is the performance baseline: CoreMark
recovery plus all four64KiB stream aggregates AND each READ/WRITE/COPY
measurement must not regress. All six actual CPU stream measurements match
batch27 EXACTLY, including low-latency and latency80 Bare/Sv39, instruction
counts and AXI traffic. CoreMark ROI648282,345517ROI instructions,
IPC0.532973, total691296cycles /367211retires, trace7b173819116883a2,
CRC59156,256AXI reads/0writes also match exactly. Short ROI, not a formal score.

F/FD each retain27840vectors/27880latency checks and prior II/stall/flush counts.
Actual CPU FD2320cases remain418027cycles,39466retires/8560FP writes/1trap;
context32cases remain4863cycles,578retires/105FP writes/9traps.
The358source hashes have0drift; changed OoO/shared-IP paths are empty.
Short receipt SHA256:
e117ec310cad123bd0ae8cd5c85130033b93024817c269e69f4b8215bcca7297.

Only after this PASS, the strict dependent pipeline staged
E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261016-r3 and launched ONE
fresh real-board synthesis/implementation. The staged manifest has32per-way
SRAM instances and362hashed files; all selected flags and32fixed-IP hashes
match the prior board. CPU300/UI250/AON50/UART50, actual2GiB MIG/64-bit AXI CDC,
BootROM, F/D, Sv39/PMP8, PLIC M/S, CMU and USER2 remain; MAC=false and old CPU
checkpoint reuse=false. Hardware stays frozen through implementation.
No new routed frequency, final resources, board boot or bit is claimed yet.

Batch28 real-board implementation completed: WNS -0.614ns (prior -2.164),
TNS -2353.514ns (prior -11544.286),9896failing setup endpoints;
WHS +0.007ns, THS0, WPWS +0.081ns. No300MHz qualification or bit.
DDR UI250 setup/hold +0.436/+0.012ns; AON/UART50 +1.242/+0.028ns.
Routed resources86740LUT /51668register resources /62RAMB36+1RAMB18 /31DSP.
All20bus-skew constraints pass, minimum+2.357ns. CDC classifications remain
3CDC-10+6CDC-11Critical and377CDC-15Warnings, not blanket-waived/signed off.

| Batch28 routed boundary | Setup ns |
| --- | ---: |
| D BRAM enable/write-mask controls | -0.451 |
| D BRAM address | -0.558 |
| D tag capture | -0.614 |
| D return | -0.608 |
| IT PTE return | -0.601 |
| EX ALU-result family | -0.534 |
| FPU capture | -0.469 |
| I-cache family | -0.573 |

These are not all closed. The old LIVE DT -> BRAM write-enable cone was
removed, but retained local write classification/mask control is still
negative. The new global worst is DT fastWriteTag[22] -> physical valid /
heldGrant arbitration -> tag RAM address (fanout496) -> victimTags[7]:
3.974ns,12levels,71.6%routing. The return worst now comes from retained
pending_address[35] through classification/state -> maintenance readRow ->
forwarding/response mux, rather than the earlier atomic-lane barrel.
FPU capture is now a ZERO-logic-level busy-enable net:3.524ns routing,
284loads. It needs locality/replication, not another arithmetic pipeline.
EX's current worst is the forwarded operand through the shared-direction
barrel shifter, not the restored native adder.

The machine-readable result is reports/batch28-review.json under the r3
isolated board; family and boundary reports reuse the SAME routed DCP.
The358source/362staged-file/32fixed-IP final hashes all matched before further
optimization. Preserve r3 as evidence; subsequent structural work is a new
candidate and must revalidate against the same batch27/28 performance floor.

### 2026-10-16 batch29: retained ownership and local physical boundaries

Continuation after batch28's routed -0.614ns, not a 300MHz pass. Preserve
CPU300/UI250/AON50/UART50, I/D32KiB, existing owners/slots, MAC absent and
the original OoO worktree untouched. Snapshot:
build/checkpoints/i1-batch28-before-batch29-20261016.

- Capture complete-access cacheability at the existing owner preparation
  edge. Ordered cached-hit classification uses retained tag/valid state;
  the retained PMA proof still gates cached replies, stores and eviction.
  High aperture aliases must bypass without evicting/modifying a resident.
- Select the CPU last-write forwarding row from retained CPU hit ownership,
  independently of probe/eviction/flush state. Maintenance reads keep their
  own row and the same masked ReadFirst collision shadow.
- Persist a newly classified row only when eviction needs it; clear the
  victim valid bit in the already existing evictSend phase. No extra beat,
  wait cycle or owner capacity. CPU and B remain blocked during the move.
- In the explicit FPGA/coherent-bandwidth mode, private finite CPU PTWs
  take priority, rotating between IT/DT; demand VALID only authorizes the
  transfer and is not an address-mux selector. Sticky offers and response
  owners remain. This is not a general unbounded-master fairness policy.
- Split FPGA ALU left/right barrel paths (including W operations) instead
  of surrounding a shared barrel with direction/reversal muxes.
- Name the pure FPU capture enable. Isolated FPGA export adds MAX_FANOUT32
  to that net and MAX_FANOUT4 to the sixteen registered PMP bounds; these
  are physical locality hints, not numerical latency or clock exceptions.

The new raw cache oracle additionally tests high-address read/write aliases
and resident preservation. Both256B/32KiB models pass428 accepted/returned
requests,112CPU collisions,8probe and8victim collisions in the initial run.
The combined short runner is cpu_timing29_acceptance.py; batch28's exact
CoreMark and all four large-stream READ/WRITE/COPY and aggregate floors
remain mandatory. No implementation until all65checks/18gates pass.
Final short/physical results are pending; no bit or board qualification.

R1 completed PASS_I1_CPU_TIMING29_AFFECTED_SHORT_ONLY:
build/gsim/i1-cpu-timing29-20261016-r1/receipt.json,
SHA256 b8c9b77c98dc19902f398ea7aa417bf6501a4c1c89108202cd3b6f0b61695d7a.
All65checks and18performance gates pass. All six actual CPU streams match
batch28 exactly in READ/WRITE/COPY cycles, retired instructions and AXI
traffic; O3 CoreMark ROI648282/345517instructions/IPC0.532973 and trace
7b173819116883a2 are also identical. Preserve batch27's recovered performance;
this short ROI is not an official CoreMark score.

Actual CPU precise privilege26161cycles, C/A24602 and page-end24640cycles,
FD2320cases418027cycles and context32cases4863cycles are unchanged.
The independent raw-cache ledger covers the three new high-address alias
transactions as well as masked collision/probe/victim ownership.
All359frozen source hashes,362staged file hashes and32fixed-IP hashes match;
OoO/shared-IP changes versus batch28 are empty. Manifest flags and fixed IPs
match r3 exactly, with32per-way BRAM instances and17explicit locality hints.

After this PASS, launched ONE fresh real-board synthesis/implementation:
E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261016-r4.
No CPU DCP/incremental reuse; only the three unchanged fixed IP runs reused.
Hardware stayed frozen through completion. Final results follow.

Batch29 real-board routing completed, followed ONLY by two read-only query
scripts on the SAME routed DCP. CPU300 WNS -0.348ns, TNS -871.024ns,
6315failing setup endpoints; previous batch28 -0.614/-2353.514/9896.
WHS +0.004ns, THS0, WPWS +0.081ns. Hold margin is positive but very narrow.
This is NOT a300MHz pass and no bit was generated.

DDR UI250 setup/hold +0.163/+0.010ns; AON/UART50 +2.031/+0.030ns.
All20bus-skew constraints pass, minimum +2.251ns. CDC classifications remain
3CDC-10+6CDC-11Critical and377CDC-15Warnings; no blanket waiver or CDC signoff.
No-clock, unconstrained internal endpoints, combinational/latch loops are0.
Existing IO-coverage items remain:2no-input-delay,1no-output-delay and
1partial-input-delay. Clocks/exception scope were not loosened.

| Routed family or boundary | Batch28 ns | Batch29 ns |
| --- | ---: | ---: |
| D BRAM write/enable controls | -0.451 | -0.074 |
| D BRAM address | -0.558 | -0.331 |
| D tag capture | -0.614 | -0.244 |
| D return | -0.608 | -0.346 |
| IT PTE return | -0.601 | -0.224 |
| FPU payload capture | -0.469 | +0.510 |
| EX ALU-result family | -0.534 | -0.329 |
| I-cache family | -0.573 | -0.348 |
| D-cache family | -0.614 | -0.343 |
| IT family | -0.601 | -0.309 |
| FPU whole family | -0.469 | -0.296 |
| PMP upper-bound family | -0.406 | -0.282 |
| PMP lower-bound family | -0.288 | -0.296 |

These compare the same hierarchy/boundary, not identical point-to-point
paths. The FPU capture enable is now positive; this does NOT mean all FPU
paths pass (MiscD recA -> response_value remains -0.296ns). PMP lower-bound
family regressed8ps and still needs attention.

The remaining worst is IT tags_0[2] -> translated-address selection ->
I-cache dataWays_7_1 BRAM ADDRARDADDR[13], -0.348ns:3.298ns data delay,
8logic levels,0.855ns logic/2.443ns routing (74.1%routing). BRAM setup,
clock skew and uncertainty also consume budget: data delay being below
3.333ns alone does not establish a pass.
Other remaining controls include DT saved_address[38] -> result_data reset
(-0.346), D tag -> dirty-bit update(-0.343), EX result bypass/ALU(-0.329),
and FPU recovery -> IT state-enable(-0.309). More than one family is negative;
do not call the I-cache the only unfinished module.

Routed resources86484LUT(25.34%),53899CLB registers(7.90%),
62RAMB36+1RAMB18(62.5tiles/8.40%) and31DSP(0.88%).
Compared with batch28:256fewer LUTs,2231more register resources; RAM/DSP
unchanged. Locality/replication costs physical registers, not architectural
owners or buffer capacity. Final359source/362staged/32fixed-IP hashes all
match; selected flags and fixed-IP hashes remain identical to batch28.

Complete machine-readable evidence:
E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261016-r4/reports/batch29-review.json.
It includes the short receipt hash, performance gates, per-domain/family/
boundary results, resource comparison, raw-report/DCP hashes and input audit.
No full212regression, Linux boot, physical board test or formal CoreMark
score is claimed. No further RTL edits or implementation were started.

### 2026-10-16 batch30: separate ownership/control and bounded native relations

Continue from batch29 WNS-0.348ns/WHS+0.004ns. Keep CPU300/UI250/AON50/UART50,
I/D32KiB, existing TLB/proof/cache/request slots, F/D parameterization,
original OoO/shared IP and MAC absence. Snapshot:
build/checkpoints/i1-batch29-before-batch30-20261016.

- Re-index EXISTING instruction full-page proof slots by offered VPN.
  Exact tag, flags and real-TLB-owner binding still gate actual acceptance.
  PA/RAM address selection no longer waits for full tag matching.
  Replacing a TLB row invalidates its proofs; row0 replacement clears all
  to preserve dominant superpage semantics. Board count4, focused fixture8;
  no independent additional translation entries/owners.
- DT local faults commit a one-bit zero marker instead of64payload reset
  pins. Real bus-error payloads and direct IF replies retain their semantics.
- Registered PMP captures <=12-bit native relations at its EXISTING edge;
  end/carry/permission/lowest-overlap reduction is AFTER that edge.
  No new authorization state/cycle. Capture all participating inputs.
- EX arithmetic uses parallel NATIVE carry-select halves, not the rejected
  grouped-LUT prefix. The upper carry-one identity avoids incrementing a
  completed upper carry-zero sum. Wide order comparisons use native halves.
- FP Misc captures IEEE magnitude/classification facts at its existing
  capture edge, selects compare/min/max in prepared, folds legality into
  onehot result masks, and predecodes completion ownership. Boxed inputs,
  signed zeros and signaling/quiet NaNs remain independently checked.
  HardFloat vendor sources/rounding, latency/II and owner count unchanged.
- Cache maintenance and fill/clear row numbers use their registered owner,
  not late hit classification. Phase/response-order/full-bitmap assertions
  guard the separation. No added line, beat, response slot or wait edge.
- FPGA translation/ordered-cache controllers use onehot phase bits/direct
  tests. Compact modes remain binary. Export checks four actual state
  bindings with EXTRACT_ENABLE=no/FSM_ENCODING=none and local fanout hints.

R1 PASS_I1_CPU_TIMING30_AFFECTED_SHORT_ONLY:
build/gsim/i1-cpu-timing30-20261016-r1/receipt.json.
All65checks/18performance gates pass. CoreMark short ROI648282,
345517instructions/IPC0.532973, trace7b173819116883a2; all six Bare/Sv39
streams match batch29 EXACTLY, including READ/WRITE/COPY and AXI counts.
Not a formal CoreMark score or full212regression.
Add independent PMP capture-hold/noise coverage:768samples per registered
32/64checker. IF tests add real superpage-owner replacement and eight
same-index leaf collisions; verify no hidden retained translation rows.

CPU->CPU hold gets an EXTRA0.050ns uncertainty, not a setup/clock/CDC
relaxation. Read-only same-batch29-DCP query confirmed+0.004 -> -0.046ns
hold, setup unchanged. Final batch30 hold slack includes this stronger guard.

Three xsim protocol/reset checks pass: dmi_cdc101requests, bscan_user,
bscan_qualification. EXTRA installed UNISIM phase0 fails at26342ns:
UNISIM_SELECTION_PHASE_ORACLE outside UpdateIR/reset, fixture line86.
Read-only ORIGINAL transport control reproduces the SAME failure/time.
This is a pre-existing verification gap, not a proven CPU-induced fault;
it is NOT a vendor-model/CDC PASS. Preserve both failed receipts; no waiver.
Six pure Python auditor checks pass. The previous9Critical rows enumerate
6CPU-release reset fanouts +3BSCAN reset OR trees, still REVIEW_REQUIRED,
NOT_SIGNED_OFF; similar wrong endpoints remain UNKNOWN.

Strict export bound all four controllers and two FP completion registers.
ONE fresh full-board implementation uses
E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261016-r5.
Final implementation and all read-only queries are COMPLETE. One fresh
board synthesis/implementation, then ONE isolated physical-only attempt
from that new routed DCP. No additional RTL edits, synthesis/route retries
or bit generation after this result.

| Actual routed result | Batch29 | Batch30 first route | Batch30 physical attempt |
| --- | ---: | ---: | ---: |
| Setup WNS ns | -0.348 | -0.153 | -0.145 |
| Setup TNS ns | -871.024 | -80.409 | -42.218 |
| Failing setup endpoints | 6315 | 1280 | 892 |
| Global hold WHS ns | +0.004 | +0.001 | +0.010 |
| CPU300 hold ns | +0.004 | +0.001 | +0.011 |
| Extra CPU->CPU hold budget ns | 0 | 0.050 | 0.050 |

The physical-only candidate improves WNS, TNS, failing endpoint count and
hold over the first route; keep it as the preferred REVIEW candidate,
not a qualified300MHz deliverable. Versus batch29 the WNS deficit is58.3%
smaller, TNS magnitude95.15% smaller and failing endpoint count85.88%
smaller. These are timing-violation reductions, NOT measured IPC/bandwidth
increases. All892remaining setup violations still need correction.

Selected candidate:
E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261016-r5/post-route-r1/reports/real_board_routed.dcp.
All166written timing commands are EXACTLY equal before/after the physical
attempt, including the0.050ns CPU hold guard. All131792routable nets are
fully routed;0routing errors. Original first-route DCP/reports preserved.

| Actual selected domain | Period ns | Setup ns | Hold ns |
| --- | ---: | ---: | ---: |
| CPU300, including CPU-clocked fabric | 3.333 | -0.145 | +0.011 |
| DDR_UI250, actual MIG/AXI converter | 4.000 | +0.217 | +0.010 |
| AON50 | 20.000 | +1.973 | +0.024 |
| UART50, actual sequential clock pins | 20.000 | +1.973 | +0.024 |

| Routed family/boundary | Batch29 ns | Selected batch30 ns |
| --- | ---: | ---: |
| PMP upper-bound family | -0.282 | +0.143 |
| PMP lower-bound family | -0.296 | -0.011 |
| IT whole family | -0.309 | -0.140 |
| DT whole family | -0.346 | -0.113 |
| I-cache family | -0.348 | -0.100 |
| D-cache family | -0.343 | -0.122 |
| EX ALU-result family | -0.329 | -0.130 |
| FPU whole family | -0.296 | -0.027 |
| D BRAM write/enable controls | -0.074 | +0.282 |
| D BRAM address | -0.331 | -0.081 |
| D tag capture | -0.244 | +0.010 |
| D return | -0.346 | -0.113 |
| IT PTE return | -0.224 | -0.097 |
| FPU payload capture | +0.510 | +0.705 |

Same hierarchy/boundary, not identical point-to-point paths. PMP upper,
D BRAM controls and tag capture are positive; other negative families
are NOT signed off. The latest FPU worst is captured operand -> shared
double div/sqrt input, not the old MiscD compare/minmax path.

New global worst: fabric/bridge/starts_0_reg[5] -> overlaps5 ->
request handoff/address selection -> slots_0/inWindow0 ->
slots_0/state_reg[2], -0.145ns. Fifteen logic levels, sixCARRY8;
data delay3.498ns =1.338ns logic +2.160ns routing.
Source ownership:
src/main/scala/core/inorder/I1TileLinkAxi4OutstandingBridge.scala,
intervalOverlap/request admission, followed by the per-slot burst bridge.
The overlap predicate is prefix equality of naturally aligned intervals,
NOT a new full-width end-address addition. STA shows two cascaded
comparison/check regions through request selection. Next structural
candidate is this admission -> per-slot window chain and its ownership
feedback, without new slots/serialization. No speculative fix is claimed.

Other remaining owners: memPacket load control -> IT stateStorage;
D BRAM data -> DT result/IT PTE; aligner state -> I-cache pending index;
EX operandHeld -> ALU result. Preserve the65check/18gate performance
baseline when restructuring these, rather than adding unconditional waits.

Selected resources85828LUT(25.15%),54988CLB registers(8.06%),
62RAMB36+1RAMB18=62.5tiles(8.40%),31DSP(0.88%).
Versus batch29:656fewer LUTs,1089more register resources, unchanged
RAM/DSP and cache capacities. Sixteen actual cache data BRAMs per I/D.
Final360source/360staged/32fixed-IP hashes have0drift; flags and fixed-IP
hashes match batch29, no original OoO/shared-IP source changed this batch.

All20bus-skew corner rows pass, minimum slack+2.532ns.
No-clock, unconstrained internal endpoints and combinational/latch loops0.
Existing IO-coverage findings remain2no-input-delay,1no-output-delay,
1partial-input-delay. CDC remains3CDC-10 +6CDC-11Critical,
377CDC-15Warning. All9Critical endpoints are enumerated reset topologies,
0unknown rows, but manual reset/CDC signoff is STILL REQUIRED. No waivers.
The extra installed-UNISIM failure and original-transport reproduction
above are preserved as failures, not silently reclassified as PASS.

Final evidence:
E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261016-r5/reports/batch30-review.json.
Linked first-route and post-route audit JSONs contain all source/IP,
receipt, report and DCP hashes, domain/family/boundary results and failed
CDC receipts.65affected checks/18performance gates only; no full212,
formal CoreMark, Linux/physical-board boot or bit claim.
Final status: SHORT PASS,300MHz SETUP FAIL, CDC NOT SIGNED OFF, NO BIT.

### 2026-10-16 batch31: parallel preflight and existing-edge control boundaries

Baseline is the selected batch30 physical attempt: CPU300 WNS-0.145ns,
TNS-42.218ns,892setup endpoints; CPU hold+0.011ns with an extra50ps
CPU->CPU hold budget. Keep all four existing domains, I/D32KiB, current
owners/slots, configurable ISA, original OoO/shared IP and MAC absence.
Pre-change source snapshot: build/checkpoints/i1-batch30-before-batch31-20261016.

- Optional I1-only parallelAdmission (generic default OFF, explicit FPGA
  SoC ON) checks raw ordinary/whole-line windows and translated AXI address
  BEFORE hazard/allocation selection. The existing real A fire commits the
  selected boolean/address; per-slot assertions compare it with the accepted
  full physical owner. No extra acceptance edge, credit or early side effect.
- Prefix-overlap equality becomes a shared XOR plus size-qualified low-bit
  conflicts and a bounded high-prefix equality, rather than many overlapping
  wide comparisons and a final size mux. Old mode remains testable.
- Per-slot window checks reuse I1AddressWindow's constant-range factoring.
  High physical aliases still fail before any AXI effect; modular low-bit
  subtraction is verified against full-width subtraction at acceptance.
- EX preloads its EXISTING held operands at RF->EX. Closest-writer and
  availability logic remain separate; remove operandHeld from the payload
  fallback/ALU mux, with the previous nearest-writer assertions retained.
- PMP uses <=8-bit native registered fragments at the SAME authorization
  edge, not an extra protection cycle. This trades local relation bits for
  shorter carry chains, without adding query owners.
- PTW send/receive/check and authorization-phase bits use local next-phase
  equations checked against the original controller every cycle. Local reply
  retirement does not broadcast backend READY as an unrelated PTW clear.
- DT response data may prepare outside its owned reply phase; status/fault
  ownership and visible stalled replies remain held. PTE payload prepares
  outside walkCheck, which remains the only PTE-consumption phase.
- Div/sqrt leading-zero distances prepare at the existing dispatcher capture
  edge. The next existing recode edge uses those distances; boxing/rounding,
  latency/II and owner count are unchanged. The small derived recoder retains
  the pinned HardFloat license and is asserted equal to the unchanged vendor
  recFNFromFN. No third_party source was edited.

Short acceptance entry:
simulator/gsim/inorder/cpu_timing31_acceptance.py.
R1 stopped before any check because the default clang++ name was absent;
R2 explicitly uses installed GSIM_CXX=clang++-19. Preserve that failed R1.
R2 retains all65previous affected checks/negative controls and18performance
gates, adding16checks for old/new bridge admission and8/16beat bursts,
including full byte/error/RID ownership oracles. No full212or Linux run.
R2 completed: PASS_I1_CPU_TIMING31_AFFECTED_SHORT_ONLY, all81checks and
all18performance gates PASS. Receipt:
build/gsim/i1-cpu-timing31-20261016-r2/receipt.json
(SHA256 f2ed2197df21b5b507f3dd09b62e9886b58703ee90b5fc33e7e9787048074d97).
All six Bare/Sv39 stream outputs exactly equal batch30, including latency80;
CoreMark O3 ROI648282cycles/345517instructions, IPC0.5329733048272203,
trace7b173819116883a2 and CRC59156 also exactly match. This is a short
CRC/trace and performance regression, NOT a duration-qualified CoreMark score.
Actual CPU C/A page-end, F/D corpus and F/D context passed.
The strict81checks/18gates wrapper released fresh r6 export and the single
full-board implementation, now completed; final outcome is recorded below:
E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261016-r6.
No clock change or new bit authorized. CDC is NOT signed off by these GSIM
tests; unchanged-input protocol proof and fresh routed static analysis are
separate evidence, including the previously recorded UNISIM phase-oracle issue.

#### CPU/fabric clock partition: feasible future option, not this batch

The proposed ownership boundary is:

    CPU domain: core / MMU / L1
        <-> complete TL-C CDC with retained credits/reset/quiesce
    Fabric domain: coherent Home / DMA / memory bridge
        <-> existing AXI CDC
    MIG domain: UI250

Registering payload/control before/after an arbiter is useful even within a
single domain. It is NOT a substitute for a multi-bit CDC handshake/FIFO.
TL-C also needs B/C/E probe/release/grant ownership, not only A/D crossing.
The added round trips affect misses, probes and MMIO; keep L1 hits inside
the CPU domain and compare IPC/throughput before selecting a split.

Read back actual fixed IP: ddr4_0.xci C0.DDR4_AxiDataWidth=64 and the
generated AXI data width64. The top and AXI clock converter keep64bits
through to MIG, whose actual UI period is4ns. Thus the ingress has a
2.0GB/s ideal SINGLE-direction limit at UI250, before protocol overhead;
CPU300/64bits offers2.4GB/s nominally. A400MHz fabric alone cannot remove
that UI ingress bottleneck. Future higher throughput requires a joint
width/packing/CDC and latency/credit study, not just a faster clock.
Moving a3.5ns path into a400MHz(2.5ns) domain also makes its timing budget
tighter; internal pipeline boundaries must be solved first. Frequency of
the proposed fabric domain remains unqualified/undecided.

#### Batch31 final full-board result: not qualified at300MHz

Completed one fresh full-board synthesis/place/route with actual MIG and
AXI CDC, then read-only DCP queries. No extra physical retry, no bit and
no new commit/push. Original OoO worktree untouched. Retain batch30's
selected physical result as the prior reference; do not promote this
candidate as a timing-qualified configuration.

Final reports: E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261016-r6/reports.
Machine-readable summary: batch31-review.json.
Raw input/report hash inventory: batch31-route-audit.json
(SHA256 8cb64a6080fa90c7cca6b3048674f3bd3fc3eaa9d4614fad7e02f4b408d9fa76).
Routed DCP SHA256:
8585b7e9cc4bf28bfb5f80c7dafebbd5e4e281bbd67b2dd093bdec4c78625ac1.

| Actual domain | Period ns | Setup slack ns | Hold slack ns |
| --- | ---: | ---: | ---: |
| CPU / TL-AXI | 3.333 | -0.145 | +0.008 |
| DDR UI | 4.000 | +0.419 | +0.014 |
| AON | 20.000 | +2.237 | +0.036 |
| UART storage | 20.000 | +2.237 | +0.036 |

CPU hold includes the unchanged additional50ps intra-clock guard.
Global TNS=-45.462ns,964 failing setup endpoints; hold THS=0,
zero failing hold endpoints. Versus batch30 selected: WNS unchanged,
TNS previously-42.218ns/892 endpoints, so NOT an overall timing win.
LUT89768 (+3940/+4.59%), CLB registers57417 (+2429/+4.42%),
62RAMB36+1RAMB18=62.5tiles and31DSP unchanged.
CoreMark O3 and all six stream outputs exactly preserved, not improved.

| Query family | Batch30 selected ns | Batch31 ns |
| --- | ---: | ---: |
| TL-AXI old worst / current slot admission | -0.145 | -0.013 |
| PMP upper relations | +0.143 | -0.056 |
| PMP lower relations | -0.011 | -0.040 |
| IT | -0.140 | -0.115 |
| DT | -0.113 | -0.130 |
| I-cache | -0.100 | -0.124 |
| D-cache | -0.122 | -0.094 |
| EX result | -0.130 | -0.132 |
| FPU | -0.027 | -0.028 |

The bridge remains in CPU300 before the AXI converter, NOT in UI250.
Its interval-source family is now+0.169ns, but slot admission still
fails by13ps from lineCut.head_address[38] to slots_0.state[0]/CE.
The global worst moved from bridge overlap/window control to I-cache
BRAM data -> coherent read response -> IT/alignment -> compressed
aligner.state[2]. Data3.239ns=logic1.478+route1.761,10logic levels,
clock skew-0.212ns. This is not evidence of stable300MHz silicon.

Remaining targets: I-cache read-return/alignment and re-admission,
DT data/PTE return BRAM muxes, EX producer selection, PMP relation
capture and FPU multiply DSP input. Reassess8-bit PMP fragments against
the prior12-bit mapping: shorter arithmetic did NOT improve these
routed relations and costs more local state. Do not assume replacing
one worst chain means all paths or whole-chip timing improved.

All20bus-skew corner rows pass, minimum+1.987ns. No clock,
unconstrained internal endpoint or loop counts are nonzero. Existing
IO coverage remains2no-input-delay/1no-output-delay/1partial-input-delay.
Static CDC remains3CDC-10 and6CDC-11 Critical,377CDC-15 Warning,
zero UNKNOWN critical classifications. These reset/BSCAN cases still
require instance-level review: no blanket waivers or CDC signoff.
The six unchanged BSCAN/DMI source/fixture inputs match batch30.
Three protocol tests passed there; its extra UNISIM selection-phase
oracle FAILED, identically in the original unmodified transport control.
Preserve that failure; do not describe this as all CDC tests passing.

### 2026-10-16 batch32: fused returns and phase-local admission

Baseline: batch31 short PASS81/18gates, full no-MAC board r6
CPU300 WNS-0.145ns/TNS-45.462ns/964setup endpoints, CPU hold+0.008ns.
LUT89768/FF57417/62.5BRAMtiles/31DSP. Preserve the exact pre-change
sources in build/checkpoints/i1-batch31-before-batch32-20261016.

One structural batch, then affected short verification:

- Replace the local cache response FIFO with exactly pipe=false/flow=true
  semantics and the SAME entries/memory ports. Expose stored/live sources
  only to fuse FIFO flow, miss/bypass, store-zero and masked shadow forwarding
  into one payload-source reduction. This targets I-cache->IT->aligner and
  D-cache->DT/PTE returns together; valid/status and real retirement stay owned.
  Assert every owned fused response equals the original selection.
- Fetch alignment uses five phase-local equations instead of a binary phase
  encoder/CE after BRAM data and length selection. Predecode PC lane at the
  existing request edge; standard32 is low2=11 and next3!=111. Same first/second
  parcel, word reuse, span permission, error and FENCE.I ownership/cycle cost.
- Prepare complete six-way ALU source masks at the existing RF->EX/held-owner
  edges, merging fallback and PC/immediate choice before the register. Keep
  nearest-writer availability and dependency admission separate. An actual CPU
  assertion compares both ALU operands against the original selection.
- Restore the measured12-bit registered PMP native fragments: the trial8-bit
  mapping increased state/fanout and worsened routed relations. Same edge.
- Prepare leading-zero distances for all three format operands at the existing
  FPU dispatcher edge, sharing them with add/multiply/FMA and divide/sqrt.
  Complete recFN equality against unchanged HardFloat remains asserted; no
  third_party edits, token/latency/II or numerical precision change.
- Parallel-admission TL-AXI slots use phase-local onehot equations, removing
  the shared binary state encoder/CE after allocation. The original complete
  transition program remains an every-cycle equality assertion. No extra
  slot, write credit, response posting or external AXI reorder permission.

Entry: simulator/gsim/inorder/cpu_timing32_acceptance.py.
Keep all81prior checks and18performance gates, add8independent flow-FIFO
and32/64bit compressed-parcel checks (89total). No full212/Linux/formal score.
Queue tests use an independent software FIFO plus standard Chisel Queue
equivalence, including reset/full/no-borrowing/stall/flow/error/pageFault.
The original parcel byte/fault oracle is unchanged except a test-header alias.

R1 preserved FAIL: first four queue checks passed, then pinned GSIM generated
an invalid uint32_t getter returning the top addressCandidates array. This was
a test-model C++ compile failure, not an RTL behavioral failure. R2 uses a
test-only scalar facade exposing BOTH original address candidates individually;
it also asserts the real selected memory address, without changing the DUT.
R2 completed PASS_I1_CPU_TIMING32_AFFECTED_SHORT_ONLY: all89checks and
all18performance gates PASS. Receipt:
build/gsim/i1-cpu-timing32-20261016-r2/receipt.json
(SHA256 70e4d2800c8d5863bd4309cd479b724b8cc4176f194523157e0226b3141479e9).
All six Bare/Sv39 streams exactly equal batch31, including both80cycle laws.
CoreMark O3 ROI648282cycles/345517instructions, IPC0.5329733048272203,
total691296cycles, trace7b173819116883a2, CRC59156, AXI256reads/0writes:
all exactly unchanged, not a duration-qualified formal score.
Actual CPU C/A page-end, F/D corpus and FP context passed too.

Exact PASS89checks/18performance gates released the fresh export
E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261016-r7 and ONE complete
board synthesis/place/route, now complete. CPU300/UI250/AON50/UART50, extra50psCPUhold guard,
I/D32KiB, current slots, F/D and USER2 stay unchanged; MAC absent, OoO untouched.

Final CPU300 WNS=-0.170ns, TNS=-78.756ns,1362 failing setup endpoints:
worse than batch31 (-0.145ns/-45.462ns/964). Hold+0.010ns/THS0,
zero failing hold endpoints. DDR UI250 setup+0.183ns/hold+0.011ns,
AON50/UART50 setup+1.764ns/hold+0.032ns. Not300MHz-qualified; no bit.
LUT85678 (-4090 versus batch31), CLB registers56149 (-1268),
62.5BRAMtiles/31DSP unchanged. No CoreMark or stream improvement.

| Family | Final routed slack ns |
| --- | ---: |
| I-cache BRAM -> aligner instruction | -0.170 |
| IT | -0.166 |
| DT | -0.147 |
| I-cache admission | -0.109 |
| D-cache admission | -0.159 |
| EX result | -0.144 |
| TL-AXI admission / interval | -0.051 / -0.041 |
| PMP upper / lower | -0.066 / -0.001 |
| FPU recovery | -0.086 |
| ALU source capture | +0.020 |

Worst data3.231ns=logic1.692+route1.539,10logic levels, clock skew-0.245ns.
Versus batch31 data8ps shorter but skew33ps worse: net slack25ps worse.
Changing phase-control expressions did not remove late parcel selection.
Boundary queries: D-BRAM control+0.451, address-0.071, tag capture-0.075,
D-return-0.136, IT-PTE-return-0.128, FPU-capture+0.656ns.
This is not an overall timing win and is not promoted over retained batch30.

All20bus-skew corner rows pass, minimum+1.977ns; no new exceptions.
Static CDC remains3CDC-10+6CDC-11 Critical,377CDC-15 Warning, zero unknown.
No manual CDC/reset signoff. Six unchanged transport/fixture inputs retain
the prior three protocol passes AND extra UNISIM phase-oracle failure,
which also occurs in the original transport control. Do not waive it.
367qualified source hashes,368staged files and32fixed IP files checked;
zero drift, flags/fixed IP hashes unchanged. Snapshot15files, zero drift.
Full audit: reports/batch32-route-audit.json.
Decision record: reports/batch32-review.json.
No further blind physical retry: next work needs structural boundary changes,
not a claim that equivalent combinational rewrites solved300MHz.

### 2026-10-16 batch33: structural boundaries, not same-cone rewrites

User explicitly rejected another small timing-only rewrite after batch32.
Snapshot: build/checkpoints/i1-batch32-before-batch33-20261016.
CPU300/UI250/AON50/UART50, eight-stage profile, equal32KiB two-way caches,
existing two DDR slots/one write credit, PLIC/CMU/USER2 and no MAC retained.
Original OoO tree/shared IP unchanged.

One combined structural candidate:

- Explicit --cache-fetch-predecode (generic default OFF) classifies every
  instruction halfword during refill. Two format bits/halfword live in
  asynchronous RAM beside I-cache data; capture at the existing SRAM edge.
  Standard32/compressed/unsupported-long metadata travels with exactly the
  same response, word-reuse, context invalidation and first/second parcel owner.
  It is NOT a PMP or execute grant. Owned byte/metadata equality is asserted.
  This moves length classification off BRAM return, rather than only changing
  the aligner FSM after those late bytes. No extra instruction response edge.
- Fuse word-bank, physical-way and live/held/miss/native payload sources into
  one response reduction for BOTH caches. Keep the original retained-data
  and masked-collision oracle. Capacity and SRAM write/read ports unchanged.
- Prepare bounded-window/translated-address/initial phase bits before the
  already-existing two-entry TL A and line-request queue edges. Preserve the
  same A/D/line queue depths and AXI transaction slots; no new bus clock.
  The bridge accepts only proofs belonging to its exact real queue head.
- Valid bounded RAM intervals retain AXI-width lane bits instead of XLEN
  hazard tags. Denied/oversized owners conservatively serialize. Normal
  RAW/WAR/WAW retirement and the original complete slot-transition oracle
  remain; invalid high aliases cannot borrow a valid physical window.
- Prepare free walker root/table/level payload without late TLB-hit or leaf
  permission controlling the wide register CE. The actual walk/permission
  state alone owns usage. Local walk-entry/send equations exclude unrelated
  request READY from all-phase clearing; original full transition equality
  remains an every-cycle assertion, with precise faults unchanged.
- EX logical shifts use radix4 selection; arithmetic sign fill runs beside
  the data shift instead of entering the barrel's sign/control input.
- FPU producers consume completion locally. The dispatcher's pre-existing
  rejection payload register doubles as an elastic completion holder, while
  its existing busy bit retains the sole owner. Bypass preserves visible
  latency; no second FP slot/result payload is allocated. CPU branch/DT/EX
  result READY no longer clears each producer's state through a long cone.
  HardFloat sources and numerical rules are unchanged.

Acceptance: simulator/gsim/inorder/cpu_timing33_acceptance.py,105affected
checks including negative controls,18CoreMark/stream nonregression gates.
R1 preserved FAIL: test-driver symbol escaping at C++ link. R2 preserved
FAIL: standalone predecode fixture had only one set in its dummy two-way
config; corrected to256bytes, real board caches remain32768bytes each.
R3 preserved FAIL: old bare-bridge oracle observes A acceptance as allocation,
which is not valid at an added EXISTING queue's upstream enqueue interface.
Do not weaken or edit line_read_channel.cpp: all original bare-bridge
RAW/WAR/backpressure/credit checks run unchanged. The new queue mode uses
line_read_preflight.cpp with independent DDR byte/error/mask/ID tracking,
bounded physical AXI ownership, plus exact cycle equivalence of every real
bridge interface against direct preflight from the same registered heads.
Distinguish existing queue entries from two actual AXI transaction slots.

R4 PASS_I1_CPU_TIMING33_AFFECTED_SHORT_ONLY:105checks/18performance
gates, no full212/Linux/formal score. Receipt SHA256
61525d17c979cab23ddc7f80eadd4536ec05f0502aff9a72ee0288bf2b3b0112.
CoreMark O3 ROI648282cycles/345517instructions (IPC0.5329733048272203),
total691296cycles, trace7b173819116883a2, CRC59156, AXI256reads/0writes:
exactly batch32. All six complete Bare/Sv39 stream results exactly batch32,
including the80cycle external latency law. Actual CPU C/A page boundary,
F/D2320case corpus/32context faults and FENCE.I control passed.

Main source snapshot370files; inherited harness
allowlist omits the new driver, so additionally pin its exact creation input:
supplemental-source-proof.json, SHA256
7063cb913a352b078a3da951d534c1af0c0436ccd2b4dd404453cb2250bbaba1.
Full chunked readback equals the pre-launch creation input. Export verifies
both sets before and after staging; no original receipt is edited.
The next runner-maintenance revision should add this filename directly to
the primary input list; this run instead records the explicit supplemental proof.
371source hashes,372staged files,32fixed-IP files read back without drift.
Fixed-IP hashes unchanged; flags differ ONLY by --cache-fetch-predecode.
Actual emitted fetchClassBanks_256x64 leaf is annotated distributed RAM;
it is NOT FF payload expansion, an extra I-line or an instruction owner.
Reference bridges are test-only and absent from the real board export.
Only105/18PASS released one fresh full-board synthesis/place/route at
E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261016-r8.
Final r8 full-board route completed. CPU300 WNS-0.161ns/TNS-38.361ns,
872setup endpoints fail; WHS+0.010ns/THS0. DDR UI250 setup+0.460ns;
AON/UART50 setup+2.099ns. Final routed87625LUT/55310FF/62.5BRAM/31DSP.
Versus batch32 routed: WNS+0.009ns, TNS improves40.395ns,490fewer failed
endpoints, LUT+1947 (+2.27%), FF-839; not a300MHz pass and not an area win.
All371source/372staged/32IP hashes remain exact; fixed-IP hashes unchanged.
The routed-clock bus-skew report has20corner rows, minimum slack+1.475ns.
Internal no-clock/unconstrained/loop counts are0; known I/O-delay omissions
remain2no-input/1no-output/1partial-input and are not silently waived.
Only one new full-board implementation; no further phys_opt retry or bit.
The C:/Windows launch caused an optional merged-BMM temp-XML warning during
open_run; MIG calibration ELF population was explicitly successful. Later
read-only grouped reports used the writable r8 run root; logs are preserved.

The top PC predictor self-feedback is-0.161ns,19levels including11CARRY8;
JTAG loader falling-release to rising CRC metadata is-0.160ns at1.667ns
half-cycle; DT tag to D-BRAM address-0.158ns and IT control to I-cache valid
capture-0.154ns. TL_AXI family+0.080ns, slot-state+0.162ns; retained interval
to line-preflight tail still-0.009ns. ALU result/FPU each-0.062ns.
These actual remaining paths, not only prior worst-path names, guide the next
combined structural batch. Exact family/boundary/domain reports and source
hashes are saved under r8/reports/batch33-route-audit.json and
batch33-review.json before further RTL changes.

Known CDC-10x3/CDC-11x6 reset criticals have zero unknown classifications,
but remain unsigned; inherited UNISIM phase-oracle failure is not converted
into a pass. No new timing exception, clock-domain change or CDC waiver.

### Latest dev MAC/fabric comparison (read-only)

Fetched origin/dev ca887740f2f375ef68a275e87cf9135262ebfa7f; no merge/pull,
no hardware change, local I1 HEAD/dev remain1e90af9. Compare actual dirty
shared IP too, preserving existing balancedRawClock/boundedDescriptorChecks.
Detailed eight-part review: docs/orbital-i1-dev-20261016-review.txt.
Best bus candidate is independent upper payload-bank enable/row localization;
the existing I1 raw-data/preflight cuts do not fully cover those upper banks.
DMA TX count capture is also independently reusable when MAC is restored.
The dev future-Home/LRU/cache overlap mechanisms are NOT drop-in for I1's
two-client1024-row/four-way directory and single serialized line context.
MAC rawClockHandoff and combined PAD/RX candidates require a fresh I1 exporter
and related-clock/half-cycle audit, not an overlay of the pinned OoO wrapper.
MAC stays absent now. dev's documented100MHz timing closure is not300MHz
qualification, nor do its known Sv39 WRITE/COPY cycle costs qualify as an
I1 performance gain. No imported RTL or dev runtime/physical test is claimed.

### CPU300 structural batch34 (2026-10-17; verification in progress)

Snapshot: build/checkpoints/i1-batch33-before-batch34-20261017.
Baseline: batch33 r4 short receipt / physical r8. Same CPU300, DDR UI250,
AON/UART50, I/D32KiB two-way, bridge slots2/write credit1 and MAC absent.
Original OoO and shared IP source bytes remain unchanged relative to r8.

- PC: independent16-bit fixed+2/+4 increments with carry derived from original
  lower bits, selected only after completion; no RAM-length-controlled XLEN
  carry-in, no new prediction stage or BTB capacity.
- DT: optional indexedDataProofs defaults OFF, CLI --indexed-data-proofs.
  Re-index existing read/write full-page proof slots by full VPN hash; keep
  source TLB owner bindings and invalidate on replacement/dominant row0.
  PA payload selection no longer depends on superpage tag matching.
  Dynamic privilege/SUM/MXR/A/D, full VPN, PMP and atomic read rules still
  authorize the one real physical owner. No added TLB/proof/request slot.
- Cache: retain set/valid/LRU at acceptance, resolve hit/victim way at the
  already-existing classification edge. Persist selected miss/eviction row,
  including invalid way1; preserve pending-hit LRU forwarding. Independent
  accepted-index and legacy-phase assertions remain. No hit-latency edge.
- TL->AXI: port dev upper-bank enable/row localization into the private I1
  bridge, adapted to onehot phases, raw72-bit first-word preparation and
  independent early-W cursor. Banks1..7 use retained continuation/read cursor;
  first-Put bank0 unchanged. Exact capture-edge/row assertions retain original
  masks, denied drains, AXI IDs, credits, ordering and response cycles.
- JTAG: I1-local loader only; shared JtagRamLoader unchanged. Prepare seven
  metadata words into the free bank, commit only selector/zero bits after
  actual accepted authorization. These are payload copies, NOT transaction
  owners. linkUp is NOT delayed. Dropped link still blocks the same-edge DMI/
  OPEN/CLAIM and cannot cancel a presented/accepted memory obligation.

New tests: 32/64 PC increment independent wrap/carry oracle, full-PC BTB
length/alias tests, JTAG original-vs-private every-cycle interface comparison
PLUS independent bytes/32metadata sessions/timeouts/STOP-like drain/link loss,
and8-slot read/write superpage proof reuse/replacement/dominance/leaf collision
tests. Negative controls stay independent. Original105 affected short checks
plus22 targeted checks ->127, with18 CoreMark/Bare/Sv39 performance gates.
Primary source freeze now includes line_read_preflight.cpp directly; batch33's
supplemental-only input workaround is no longer used for this new run.

Runner: simulator/gsim/inorder/cpu_timing34_acceptance.py --tag20261017-r1
--reuse-compiles build/gsim/i1-cpu-timing33-20261016-r4/receipt.json.
Reuse is exact fresh FIR/tool/object hashes ONLY; every oracle re-executes.
Scala16configuration checks PASS; initial PC/JTAG/indexed-D component cases
PASS. This paragraph does NOT yet claim all127/18 or routed closure.
Strict export/queued one-shot full-board implementation requires the entire
short PASS, real private loader, distributed parcel RAM and indexed-D flag.
No bit generation is authorized by that pipeline.

Six unchanged BSCAN/DMI source/fixture hashes still match the retained batch30
CDC receipt; three protocol cases passed there, vendor_phase_0 remained FAIL
also in original control. New loader GSIM tests do not waive that CDC issue.
Routed hold/recovery/removal, bus skew and CDC inventory will be read from the
new full-board implementation, not inherited as a new timing pass.

Batch34 r1 final short PASS:127checks/18true performance gates, Scala16PASS.
Receipt SHA256 e546f58808d1b05cb2ae15c26ff47dabb14198c763712a21f8675d1e87305fc8.
CoreMark ROI648282cycles/345517instructions, IPC0.5329733048272203;
total691296cycles, retired367211, trace7b173819116883a2, CRC59156,
AXI256reads/0writes: EXACT batch33. This remains a short CRC/cycle comparison,
NOT a formal duration-qualified CoreMark score. All large Bare/Sv39 streams,
including80cycle external latency, exactly preserve each R/W/COPY result.
8KiB Sv39 COPY10439->10412cycles (-0.25865%); read8259/write12432 unchanged.
Thirty-six bridge/cache result strings match batch33 exactly. Actual C/A,
FD2320case corpus/32fault-context and FENCE.I/branch/JALR control passed.
377primary source hashes reread with no drift; no supplemental-only input.
One fresh board run started2026-10-17 10:45CST:
E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261017-r9.
No routed timing/resource result is claimed while this implementation runs.

### CPU300 batch34 r9 final route (2026-10-17 11:26 CST)

Same real board, clocks and 50ps extra CPU intra-clock hold guard.
Final routed setup WNS -0.039ns / TNS -2.695ns /190 failing endpoints;
hold +0.007ns /THS0, pulse width +0.081ns. CPU300 is NOT yet closed.
Previous r8: -0.161ns /-38.361ns /872 endpoints. This is a real routed
improvement, not a pre-place estimate. No bit was generated.

- Resources:88428 LUT /55294 FF /62.5 BRAM tiles /31 DSP; versus r8
  +803 LUT /-16 FF, unchanged BRAM/DSP.
- DDR UI250:setup +0.331ns /hold +0.010ns.
  AON/UART50:setup +2.349ns /hold +0.026ns.
- PC self-feedback:-0.161->-0.018ns.
  JTAG destination-release half-cycle:-0.160->-0.023ns;
  local loader register paths +0.087ns.
  D-cache BRAM address:-0.158->-0.005ns.
- Worst remaining path:I-cache victimTags[11] -> instruction aligner
  result_instruction[30], -0.039ns. IT/DT/FPU and cache families retain
  smaller negative endpoints; exact TSVs are preserved, no false-path waiver.
- CDC remains unsigned:3 CDC-10 BSCAN reset-tree rows and6 CDC-11
  CPU-release/AON reset-fanout rows, unknown critical0. Twenty bus-skew
  corner rows have minimum +2.235ns. Prior independent installed-model
  test failed UNISIM_SELECTION_PHASE_ORACLE at26342ns (also original control);
  that failure is not waived or relabelled as a pass.
- Source snapshot377, staged372 and fixed-IP32 hashes are clean.
  Subsequent user-authorized JTAG-only source advancement is recorded
  separately from the frozen r9 source snapshot.

Evidence:E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261017-r9/reports/
batch34-route-audit.json and batch34-review.json.

### I1 parameterized serial-TAP scan-length fix (batch35, 2026-10-17)

The user reported the OoO USER2 transport's exact64-bit defect. The private
I1 controller had the same check, and r9 staged bytes matched it exactly.
Its old tests explicitly rejected65 bits and did not represent a DAP+FPGA
chain. CPU-local loader GSIM success never proved board BSCAN transport.

The I1-only fix exposes SCAN_BITS (64..127), default64. Every FPGA shell
accepts jtagScanBits; CLI --soc-jtag-scan-bits=65 selects this board's
64-bit FPGA USER frame plus the DAP's one BYPASS bit. The counter saturates
at SCAN_BITS+1, not at the valid count, so66 and arbitrarily longer scans
cannot alias back to65. Signature/version/reserved-bit/capture/overrun checks
are unchanged. The final64 input bits retain the FPGA frame for either TAP
order. Shared debug RTL and the original OoO worktree remain untouched.

IMPORTANT:host OpenOCD still issues a64-bit FPGA drscan. Its declared chain
automatically adds the other TAP's BYPASS bit. Do NOT change the host payload
to65 bits, which would create66 physical clocks and must be rejected.

Independent short verification:
- Actual installed JTAG_SIME2/BSCANE2 plus a separate4-bit-IR DAP TAP with
  IDCODE, full TAP state machine and one-bit BYPASS; no replacement FPGA TAP.
- Both physical orders (DAP upstream/downstream), three independent CPU/TCK
  phase/rate combinations, exact64 default compatibility:7 positive cases.
- Actual unmodified r9 RTL reproduces the65-bit protocol error; wrong64-bit
  board configuration, disabled length guard, wrong saturation bound and
  corrupted expected data are independently detected:5 negative controls.
- Strict66/67/127/128/255-clock rejection with a correctly aligned frame,
  short/empty scans, signature/version/reserved bits, pause/resume,
  backpressure, exact-once writes/readback and reset/no-replay covered.
- Original3 DMI/protocol qualification cases pass unchanged;17 Scala config
  cases pass. Eight freshly executed GSIM loader positive/negative checks
  compare every-cycle old/new interfaces and independent RAM/metadata oracles.
  Fresh FIR and reused binary hashes match the prior tested compilation;
  no reused PASS status. Existing unrelated vendor-phase failure is retained.

Receipt:build/gsim/i1-jtag-chain35-20261017-r1/receipt.json,
status PASS_I1_JTAG_CHAIN35_AFFECTED_SHORT_ONLY,24 grouped checks;
SHA256 6ac9929e2a94db7ef33b907b6b089f6802c4ed6cf791a892a822508c00373d8b.
Windows xsim raw evidence remains in the source-bound paths in that receipt.
The legacy negative RTL is retained under
build/checkpoints/i1-batch34-before-jtag65-20261017/src/main/resources/inorder/.

r10 staging correctly stopped at an overly strict byte-identity gate:
I1UartClockBank differed only in generated trailing source-line comments.
No Vivado was run on r10. Refined audit accepts ONLY these exact known source
location comments and the single SCAN_BITS parameter; no logic/attribute/
arbitrary-comment filtering and no CPU difference is allowed.

New candidate:E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261017-r11.
133 other SV files are byte-identical to r9. UART bank logic is exact after
only known source-location comments; shell logic is exact after those comments
and the one explicit SCAN_BITS(65) parameter. CPU performance127/18 acceptance
is inherited under this identity proof, NOT falsely claimed re-executed.
CPU300/UI250/AON-UART50, I/D32KiB, slots/credits, MAC absent and hold guard
remain unchanged. One fresh board implementation started11:29CST.
Routed timing and real-board JTAG download remain UNVERIFIED until new results.
No bit or board programming is implied by the protocol tests.

Batch35 r11 original implementation completed2026-10-17 12:08CST.
Final routed WNS -0.007ns /TNS -0.039ns /15 failing setup endpoints;
hold +0.010ns /THS0, pulse width +0.081ns. This is still NOT a CPU300 pass.
Resources:88246 LUT /55260 FF /62.5 BRAM tiles /31 DSP.
JTAG half-cycle path now +0.026ns; local loader path +0.047ns.
Worst CPU path:offerPc[7]->offerPc[21], data3.215ns, of which80.684% routing.
Other tiny residuals include CSR/PMP and fabric request-control paths.
DDR UI250 setup+0.376ns/hold+0.014ns; AON/UART50 +2.092ns/+0.023ns.
384 source hashes,372 staged files and32 fixed-IP files have no drift.
Bus-skew20corner rows minimum+2.430ns; known CDC review categories unchanged.
Full original evidence: r11/reports/batch35-route-audit.json.

The first read-only report launcher referenced a helper absent from the staged
scripts folder; it exited without changing the design. A separate r2 read-only
launcher reused r9's verified r8 helper, completed the full13-family/6-boundary
and3 PC/JTAG targeted queries, and preserved the failed log too.

One bounded physical-only AggressiveExplore+Explore trial started12:08CST from
the completed r11 DCP; no synthesis, RTL/clock/exception edits or bit generation.
The trial routed to WNS -0.035ns /TNS -0.413ns /hold+0.010ns, worse than r11.
DO NOT select this trial as an improvement; original r11 stays the best current
JTAG65 candidate at -0.007ns. Trial and all read-only queries finished12:19CST.
Final trial audit: r11/post-route-r1/reports/batch35-physical-audit.json;
decision: r11/reports/batch35-review.json. Trial23setup endpoints remain versus
original15. Both have hold+0.010ns, pulse+0.081ns, the same resources and clean
source/staged/fixed-IP hashes. Clock uncertainty/clock-group commands compare
identically before/after. Bus-skew minimum remains+2.430ns; known CDC reset
review rows remain unsigned, unknown critical0. No false-path waivers added.
All own Vivado processes completed; no extra synthesis/physical retry, bit,
board programming, commit or push was performed. CPU300 remains unclosed.

### I1 bandwidth / PC-feedback batch36 (2026-10-17; affected short PASS, physical pending)

User scope: bandwidth first, preserve CPU300 / DDRUI250 / AON-UART50,
I/D32KiB two-way, existing owner/bridge slots2 and write credit1, no MAC,
no OoO edits and no new Vivado run. Snapshot:
build/checkpoints/i1-batch35-before-batch36-20261017.
Matched performance baseline: i1-cpu-timing34-20261017-r1/receipt.json;
batch35's CPU was identical under its source/staged identity proof.

Three new independent switches default OFF and pass through the normal I1
Scala configuration/SoC arguments, not a special test-only CPU path:

- --coherent-line-grants: reuse the existing shared Acquire engine's private
  LineGrant transport between the private I1 Home and caches. The same
  checked lineData and Acquire response banks replace eight internal D beats.
  Standard external TL-C is unchanged; A source/sink, denied/corrupt and real
  E GrantAck remain mandatory. No extra512-bit FIFO, source or response owner.
- --coherent-miss-turnover: two-way ordered D-cache may consume its successful
  miss response and accept the replacement owner at the same edge. Capture
  the next tags/set/LRU/valid/payload then; never accept ahead of an old error,
  held response, pending probe or flush. No extra miss/request slot.
- --coherent-writeback-overlap: while the existing release context waits for
  its actual write response, the existing Acquire context/DDR second slot may
  fetch a different unowned line. Require an empty directory row different
  from the still-live release row; no ordinary/probe/alias overlap. Prepare
  one-bit per-client directory/alias qualification from a sticky A head in the
  existing write wait, keeping wide tag/space checks out of live A READY.
  Cache installation/CPU completion still waits for the actual ReleaseAck.

The unchanged-size128-entry BTB is banked into four32-row distributed RAMs
under existing FPGA timing mode. Bank-local tag/direction/length qualification
feeds a flattened next-PC reduction; prediction contents, indexing, training,
latency and pipeline stages are unchanged. This targets r11's routed
offerPc[7]->offerPc[21] path (-0.007ns,80.684% routing), not a claimed new STA pass.
The private internal512-bit transport itself requires later routed review.

Focused runner: simulator/gsim/inorder/bandwidth36_acceptance.py.
Independent checks retain full byte/order/dirty/probe/flush/atomic oracles;
new real-engine192-transaction whole-grant test includes64denied/64corrupt,
E/response backpressure, wrong data and unknown-source negative controls.
The old hit-behind-miss stimulus incorrectly classified same-edge consumed
response/replacement as an extra live owner. It now explicitly requires the
second acceptance NOT precede the real older reply; enabled turnover must
achieve equality. No byte/error/order oracle was removed.

r1 preserves that initial stimulus-policy failure. r2/r3 preserve failed
coverage gates: the small pair fixture's old I1TestRamAdapter serializes
backing read/write bursts, so it cannot witness AXI data-channel concurrency.
Do not modify its service law to manufacture a bandwidth gain. A new directed
two-dirty-way/third-same-set-line stimulus witnesses real Home Acquire before
the older ReleaseAck. Actual CPU SoC AXI concurrency is separately counted
by host-only AxiMemory observations; RNG/service/delay law is unchanged.
Compile reuse requires an exact freshly elaborated FIR plus hashed objects/
headers; all selected functional checks execute again, never cached PASS.

Final run: build/gsim/i1-bandwidth36-20261017-r4/receipt.json.
Status PASS_I1_BANDWIDTH36_AFFECTED_SHORT_ONLY;38checks,13true performance
gates,17Scala parameter cases. Receipt SHA256:
ae9cde52871d2257c81a5c76c4c7049ce01d0ffcbab6bb08db3e21411a0920eb.
This is the selected candidate, not the earlier r1/r2/r3 failed coverage runs.

Actual CPU64KiB-per-buffer results, SAME frozen program and memory service:

| Case | READ old -> new cycles | WRITE old -> new cycles | COPY old -> new cycles |
| --- | ---: | ---: | ---: |
| Bare, read floor3/write floor2 |125915 ->102637|123474 ->100782|211345 ->160229|
| Sv39, read floor3/write floor2 |125688 ->102684|123446 ->100781|211077 ->160047|
| Bare, read floor80/write floor79 |244050 ->181494|241768 ->179695|467565 ->317779|
| Sv39, read floor80/write floor79 |243822 ->181711|241930 ->179712|467541 ->317517|

Corresponding100MHz MODEL CYCLE conversions, MiB/s (not board measurements):

| Case | READ old -> new | WRITE old -> new | COPY payload old -> new |
| --- | ---: | ---: | ---: |
| Bare, low latency |49.64 ->60.89|50.62 ->62.02|29.57 ->39.01|
| Sv39, low latency |49.73 ->60.87|50.63 ->62.02|29.61 ->39.05|
| Bare, latency80 |25.61 ->34.44|25.85 ->34.78|13.37 ->19.67|
| Sv39, latency80 |25.63 ->34.40|25.83 ->34.78|13.37 ->19.68|

Low-latency COPY throughput improves31.90% Bare/31.88% Sv39;
latency80 COPY improves47.14% Bare/47.25% Sv39. The four OLD models were
re-executed using exact old FIR/object/header hashes and the NEW host-only
counter driver: every old cycle/instruction/traffic field reproduced exactly.
Evidence: baseline-replay/receipt.json in the final run directory.

Real AXI transaction/data-beat counts AND retired instruction counts match
the old hardware in all four cases. New overlap-owner cycles:
30633/30347 (Bare/Sv39 low latency),247183/246998 (Bare/Sv39 latency80);
old hardware has ZERO in all four. This counts simultaneous live read/write
obligations over the whole guest, not simultaneous R/W data on every clock,
not a timed-COPY-only statistic, and not physical MIG utilization.

O3 short CoreMark ROI648282 ->647379cycles,345517instructions unchanged;
IPC0.5329733 ->0.5337167 (about+0.1395%). Total691296 ->689190cycles;
retired367211, trace7b173819116883a2, CRC59156, AXI256reads/0writes unchanged.
The independent register-oracle negative control rejects corruption.
This remains NOT an official duration-qualified CoreMark score.

Actual M/S/U/Sv39/PMP/PLIC/SBI timer checks, C/A with LR/SC/AMO ordering and
compressed cross-page faults,32 F/D precise context cases all pass.
One supplementary same-object real-CPU fetch-control run passes in1890cycles/
314retired, covering self-modification/FENCE.I/branch/JALR/wrong-path bytes.
Frozen-source/artifact reread and its durable result are recorded separately
in batch36-final-audit.json; that audit is created AFTER the primary receipt,
not retroactively added to or substituted for its checks.

Current READ/WRITE loop uses five instructions per64-bit word and COPY uses
six, so the800MB/s64-bit100MHz interface limit is NOT that scalar program's
achievable bound. Remaining demand/MMU lifetime and serialized Home Acquire
still limit independent read-miss overlap; this batch overlaps writeback with
one refill, it does not claim two independent CPU demand misses or DMA peak.
No final dirty writeback tail is explicitly timed/drained by these assembly
loops; the independent full-byte coherent drain/check remains AFTER timing.
At300MHz the fixed-cycle numerical conversion is3x, but fixed UI250/CDC
latency in CPU cycles changes with actual frequency. Do not infer a physical
board throughput or Linux boot time from that scaling.

No new Vivado/bit/board test, commit or push. Clock/CDC/reset RTL and shared
IP/OoO source hashes are unchanged; new private CPU/cache/Home paths are NOT
routed-qualified. Original r11's WNS-0.007ns/hold+0.010ns remains the best
measured OLD physical reference, not a timing signoff for this new candidate.
The old unsigned CDC/reset review and independent vendor-phase failure are
not waived. Next concentrated implementation must freshly export the three
tested flags, preserve JTAG65 and qualify setup/hold/CDC and512-bit routing.
The strict board exporter still needs explicit batch36 receipt-schema support;
do not bypass its gates or reuse r11 as if it contained these changes.

### 2026-10-17 — batch37: bounded read-owner handoff, NOT a streaming bandwidth win

User scope: restructure CPU/MMU demand lifetime and serialized Home reads;
keep the existing slots, multi-clock boundaries, I/D32KiB and300MHz target;
batch edits, affected short GSIM only, no synthesis and no OoO changes.

Frozen receipt: build/gsim/i1-bandwidth37-20261017-r8/receipt.json,
PASS_I1_BANDWIDTH37_AFFECTED_SHORT_ONLY, SHA256
f024fd9d267e0c6848feaac052fe25e9e173983aa0d9c126c3a146b3acd5f60c.
It records29 affected checks,13 no-regression gates and17 Scala configuration
tests, not a full regression or physical signoff. Final reread:
build/gsim/i1-bandwidth37-20261017-r8/batch37-final-audit.json, SHA256
288297edfcbed5018d91c8a4aa155965b8be1ca96fdb1dbb8fb16b1cf39db822.
The final audit checks383 source hashes,119 artifact hashes,134 unchanged OoO
files and61 unchanged shared-IP files. The original OoO worktree was not edited.
The final audit is additional evidence created AFTER the primary receipt;
it does not replace or retroactively add checks to that receipt.

Two independently removable switches are added, both defaultOFF:

- --data-reply-handoff / dataReplyHandoff: keep the old reply in the existing
  MMU result bank while the already-existing ADDR packet may hand off its
  successor read. Only a real successful old physical response, live full-page
  permission, aligned non-atomic scalar read, cacheable RAM window and no
  invalidation qualify acceptance. No speculative MMIO/store acknowledgement.
  ADDR retains an accepted bit and transfers it to MEM, preventing duplicate
  issue. Physical request and registered reply validity are separated; the
  old result remains immutable under backpressure. This is NOT two unresolved
  demand misses, and does not accept the successor before the old response.
- --coherent-read-overlap / coherentReadOverlap: an independent other-client
  Acquire borrows the existing Home RELEASE address/source/client/directory-row
  context. Exactly two read/release contexts and the same two backing slots;
  no new512-bit payload buffer. The existing reader retains the secondary
  response until the real private Grant. Separate sink0/1 and real E ownership
  are maintained; tag-bank installation is arbitrated. Dirty release/probes,
  ordinary accesses, same-line/same-row hazards and drain remain interlocked.
  A stalled secondary memory request is retained; VALID does not wait for READY.

FIR declaration audit: no RAM array/capacity change and no new payload queue.
Exactly7 additional RTL control bits: ADDR accepted1, D-MMU reply-valid1,
Home paired-read/GrantAck/send3 and two sticky per-client qualifications2.
This is a register-declaration result, NOT a Vivado FF/LUT/resource measurement.
Physical-clock/CDC/reset RTL and the prior BTB organization are unchanged.

Verification includes actual Home RTL with24 read pairs,12 reverse-return
pairs,12 memory errors,240 Grant-stall cycles and600 E-stall cycles, plus an
independent eight-word/source/error mutation negative control. Two physical
read requests are accepted before either response. Real dual-cache/Home
models at256B and32KiB cover dirty migration, voluntary writeback/refill
overlap, probes, flush, ordinary four-credit cohorts and full-byte checks;
the256B model also tests the new Home mode disabled. Its serial backing RAM
service law was NOT changed to manufacture concurrent DDR throughput.

The D-MMU test checks one actual handoff and five rejected cases (old memory
error, younger write, noAllocate, misalignment, missing page proof), holding
the old reply for12 cycles. The supplementary SAME-object retirement run
passes667 cases total, including192 mixed read/write/error/backpressure owners,
188 registered consume/replacements and624 held cycles; its wrong-retirement
negative still rejects. CPU M/S/U/Sv39/PMP/PLIC/SBI, C/A/LR/SC/AMO and compressed
cross-page faults, and32 F/D precise context cases pass.

Same frozen binary, same byte oracle, seed and AXI service law as batch36:

|64KiB standard loop|READ cycles|WRITE cycles|COPY cycles|READ/WRITE/COPY MiB/s at100MHz|
|---|---:|---:|---:|---|
|Bare low latency|102637|100782|160229|60.894 /62.015 /39.007|
|Sv39 low latency|102684|100781|160047|60.866 /62.016 /39.051|
|Bare read-floor80/write-floor79|181494|179695|317779|34.436 /34.781 /19.668|
|Sv39 read-floor80/write-floor79|181711|179712|317517|34.395 /34.778 /19.684|

All SIX standard8KiB/64KiB cases have EXACTLY the old timed cycles, guest total
cycles, retired instructions and AXI request/beat counts. The old bandwidth
gains are preserved, but this batch adds ZERO standard streaming bandwidth.
COPY is payload, not actual AXI traffic; final dirty-tail drain remains outside
the timed region and is independently checked afterwards, as before.

Short O3 CoreMark DOES improve slightly: ROI647379 ->646056cycles,
345517instructions unchanged, IPC0.5337167 ->0.5348097 (+0.2048%).
Total689190 ->687500cycles; retired367211, trace7b173819116883a2 and CRC59156
unchanged. AXI reads256 ->255, writes0 unchanged; do not claim equal CoreMark
traffic or attribute this mixed whole-CPU effect to a particular switch
without an ablation. The independent register negative rejects corruption.
This remains NOT a duration-qualified official CoreMark score.

Additional independent-read diagnosis is in the receipt's paired-read/
artifacts: generated paired_read.S differs from the frozen scalar program
ONLY by pairing two independent loads before their accumulations. It does
not replace the standard benchmark. Old/new CPU objects run the SAME binary,
same byte checks and memory law, at8KiB Bare/Sv39,64KiB Bare floor3 and64KiB
Sv39 floor80. Every corresponding timed and total cycle count is identical.
Host-only observation of unmodified GSIM state sees512 accepted handoffs at
8KiB and4096 at64KiB, with one real Home pair. The switches are exercised;
the lack of bandwidth gain is not a disabled-configuration artefact.

The remaining bottleneck is now more tightly bounded: physical demand/PTW
arbitration and the L1 pending-miss lifecycle still serialize unresolved
data demand. Home now overlaps I/D reads, not two misses from the SAME D-cache.
For64KiB READ there are1024 cache lines; changing the memory floor3 ->80
adds78857 Bare cycles, almost exactly1024*(80-3)=78848. Thus virtually the
entire extra per-line latency remains on the critical schedule.

Do NOT replace the published streaming-performance baseline on the strength
of the small-module handoff or higher overlap counters. Next substantive batch
must restructure existing L1 miss metadata/reservations, ordered/error return
and demand/PTW ownership so a proven independent read can enter BEFORE the
first line returns, retaining same-address/set/victim/probe/flush exclusions
and precise exception drain. Dependent scalar loops may also require bounded,
authorized lookahead; two DDR slots alone cannot create independent CPU work.
Do not grow MSHR/queue/cache capacity or silently turn this into an OoO backend.

Attempts r1-r7 are retained as failed development evidence. Most importantly,
the reverse-return oracle caught secondary Grant wrongly advancing the primary
FSM, and structural generation caught dynamic E READY feedback. Both were
fixed in production RTL, not waived; request-stickiness and error/source checks
remain. No failed run is used as PASS evidence.

No new Vivado, bit, board test, commit or push.300MHz setup/hold/CDC and physical
resource cost remain unqualified for batch36/37. The strict board exporter
still needs explicit current receipt-schema/new-flag support before any future
physical run; do not bypass it or reuse the old r11 timing as current signoff.

## 2026-10-17 batch38: one physical directory writer and reply-independent DT payload

Short receipt: `build/gsim/i1-bandwidth38-20261017-r1/receipt.json`,
`PASS_I1_BANDWIDTH38_AFFECTED_SHORT_ONLY`: 29 checks, 13 performance gates,
17 Scala configuration cases. The 28 FPGA-tool unit tests also pass.
This is a resource-mapping/control-path repair, NOT another bandwidth gain.

The same-stage whole-board synthesis comparison exposed a genuine regression:
batch35/r11 89,330 LUT versus batch37/dev2 156,094 LUT. Home alone changed
9,217 ->74,067 LUT. Four directory banks acquired a second independent RTL
write port, despite logically exclusive GrantAck arbitration; they ceased to
infer LUTRAM and each became 16,348 LUT /5,120 FF. This was not cache growth,
FPU growth, or merely comparing synthesis against routing. An RTL-only +7-bit
state inventory did not account for that physical memory-inference failure.

Home now selects the install row/tag/client BEFORE one Mem.write per bank.
Existing primary-E priority retains a competing secondary E; an errored
primary can still acknowledge alongside the successful secondary. There is
no new queue, delayed directory owner, extra cycle, state bit or payload RAM.
The existing two read contexts still issue both backing reads before either
return. Four E conflicts, eight explicitly secondary-first schedules, reverse
returns, twelve memory errors and grant/E backpressure are independently
checked. The raw secondary_first counter is10 because it also counts two
same-edge acknowledgements with an errored primary. The old serial option
and 256B/32KiB pair configurations pass too.

DT now prepares the offered address/data/mask/noAllocate from the current
registered phase, independently of physical-response valid/ready/error and
requestSlot. Only VALID/ownership remains gated by actual completion and
full permission proof. send/fastHold keep their saved sticky owner. The
reported D-cache reply -> DT slot -> next PA -> cache classification cone is
therefore cut at its payload mux, without removing same-edge read handoff.
The MMU checks 475 cases, one safe handoff/five unsafe rejections and twelve
held-reply cycles. A new prepared-payload witness passes two waiting cycles;
the exact old GSIM object rejects this witness with
`next physical payload depends on old reply admission`.

All SIX frozen 8KiB/64KiB Bare/Sv39 cases have exactly the batch37 timed/total
cycles, retired counts, AXI requests/beats and overlap counters, including
read-floor80/write-floor79. The preceding batch37 table remains current.
O3 CoreMark remains ROI646056 /345517 instructions (IPC0.5348097), total687500,
retired367211, CRC59156, trace7b173819116883a2, AXI reads255/writes0. C/A/AMO
and32 F/D precise-context cases pass. No official duration-qualified score.

The generated CPU FIR retains 6,999 register declarations and four directory
banks; directory write ports fall eight ->four. No original OoO, shared IP,
clock/CDC source, cache capacity or transaction-slot parameter changed.
Experimental switches keep their existing default-off behavior.

Isolated RAM proof: `fpga/inorder/check_directory_writer.py` accepts only a
source/hash-bound complete batch38 PASS, emits the exact tested CPU FIR and
requires a 256x20 six-read/one-write leaf. One Vivado2025.1 leaf-only synthesis
at XCZU15EG-2 maps it to700 LUT (576 distributed-memory LUT +124 logic), zero
FF and no BRAM. Evidence:
`E:/VM/Share/Valence-rtl/orbital-i1-directory38-20261017-r1/`.
The primitive-counts raw number includes hierarchical RAM cell objects; use
the utilization report's576 memory LUT as the physical resource count.
Do not multiply this isolated all-six-outputs result into an asserted final
whole-board count: integration may trim unused ports or optimize logic.

No new CPU/full-board synthesis, route, bit, commit or push. 300MHz setup,
hold and CDC remain pending concentrated implementation. The old −3.089ns
report belongs to pre-fix batch37, not a measured batch38 result. The strict
board exporter still requires explicit batch38 schema/audit registration
before a future full-board export; never substitute the old batch37 receipt.

### Physical follow-up started 2026-10-17 15:39 Asia/Shanghai

The subsequent user continuation registered a DISTINCT batch38 strict export
schema. 32 tool tests pass. It binds the exact baseline, named performance
gates, allowed source changes, zero added state/capacity, actual leaf inference
proof and actual USER2/65 scan proofs. The generated real-board directory leaf
is byte-identical to the separately checked leaf; all older physical hints,
per-way BRAM, JTAG resources and clock/CDC checks remain enabled.

Candidate: `E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261017-dev2-r2`.
One fresh full-board synthesis/place/route, no bit and no further RTL edits.
Same-stage linked real-IP synthesis versus pre-fix dev2-r1:

|Resource|Before|After|
|---|---:|---:|
|Whole-board LUT|156094|93883|
|Whole-board FF|74921|54457|
|Home LUT|74067|11379|
|Each directory bank LUT /FF|16348 /5120|582 /0|
|BRAM36 equivalent /DSP|62.5 /31|62.5 /31|

MIG12272 LUT and AXI CDC422 LUT are included and unchanged. This is actual
whole-board synthesis, not a fourfold extrapolation of the isolated700-LUT
leaf; integration trims unused ports. Route timing and final placed resource
counts are still pending and must not be substituted by these synthesis data.

### Batch38 routed follow-up completed 2026-10-17 16:44 Asia/Shanghai

The RTL remained frozen throughout. The original implementation process
disappeared after writing its placed DCP, with no logged failure reason.
Recovery reused that exact placement (SHA256
`52276bb18ed11314d26240a2c08fae4cabf808216ee826eef3e13b0b75bfab0b`),
completed Explore physical optimization and saved
`reports/real_board_post_place_physopt.dcp` (SHA256
`ea1ab51128c7a1b1095c3410d2765c52c0657cf4af50e2fa5c020a092ff8ea26`).
Explore routing reached zero unrouted/partial nets, then the process exited
at `Phase11.1.1 Leaf ClockOpt Init`, creating zero-byte hs_err log/dump files.
There is no usable stack trace; the root cause is not established. Its
intermediate WNS-0.185/WHS+0.010 is NOT final STA or a completed Explore result.

One bounded recovery used the saved post-physopt DCP with the installed,
documented `route_design -no_psir -timing_summary` command. This is default
timing-driven routing with router-integrated physical synthesis disabled,
NOT Quick/non-timing-driven routing. Completed placement/physical optimization
were reused; synthesis, placement, GSIM and RTL edits were not repeated.
No frequency, setup/hold/CDC exception or50ps CPU hold guard was relaxed.
This strategy difference is part of the result, not hidden as an Explore PASS.

Final actual routed STA (`dev2-r2/reports/timing_summary.rpt`):

|Domain|Frequency|Setup WNS ns|Hold WHS ns|
|---|---:|---:|---:|
|CPU|300MHz|-0.316|+0.010|
|DDR UI|250MHz|+0.244|+0.011|
|AON|50MHz|+1.798|+0.027|
|UART storage (same AON clock)|50MHz|+1.798|+0.027|

Overall TNS-172.500ns /2140 failing setup endpoints; THS0 /zero failing hold
endpoints; WPWS+0.081ns /zero failing pulse-width endpoints. All137530
routable nets are fully routed, routing errors0. Final resources:92982 LUT
(27.25%),55150 CLB registers (55149 FF +one AND/OR register),62.5 BRAM36
equivalents,31 DSP,zero URAM. Home is11514 LUT /3783 registers; each directory
bank remains582 LUT, including480 LUTRAM, withzero FF. Use the SAME-STAGE
synthesis comparison above for the39.9% LUT reduction; do not compare pre-fix
synthesis directly against this routed total as a controlled percentage.

The worst path is `core/addrPacket_address_reg[13]` through DT physical address
qualification, `readHandoff_middle`/VALID admission and the D-cache metadata
queue enqueue to `metadata/ram_ext/.../RAMA/WE`:10 LUT levels,3.307ns data
delay (0.927ns logic +2.380ns routing). Reply-dependent payload selection was
removed, but authorized request-VALID/enqueue control is still a long cone.
Other top60 reported families: D-cache probe/victim capture-0.280/-0.278ns,
PC prediction feedback-0.261ns, IT/PMP state admission-0.260ns, Home/line
request admission-0.234ns. These are observations, not additional RTL fixes.

`check_timing` reportszero no_clock/unconstrained internal endpoints,zero
combinational loops. Remaining port notices: button_n/sys_rst_n without
input_delay, MIG c0_ddr4_reset_n without output_delay, partial uart_rxd
input_delay (pad synchronizer max-delay boundary). These still require
boundary review, not broad false paths. Bus-skew report has no violations
(minimum reported slack+2.336ns). DRC has41 warnings,zero errors/critical:
DSP pipeline recommendations,three LUT equation-term warnings andone
no-routable-load warning. CDC has3 CDC-10 +6 CDC-11 Critical, all reset
boundaries, with EXACTLY the same source/destination pairs as pre-fix dev2-r1;
377 CDC-15 CE-controlled data warnings remain. No new waiver or CDC signoff.

At completion384 source,373 exported-file,8 proof-tool and32 reused-IP hashes
were rechecked withzero mismatches. The branch remains dev2 at e0415d2 with
uncommitted batch38 changes; original OoO/shared IP and architectural slot
counts are unchanged. Six Bare/Sv39 and short O3 CoreMark results remain
bit-for-bit equal to the frozen short baseline, not a new throughput gain.

Result: RESOURCE REGRESSION FIXED, AFFECTED SHORT PASS, ROUTED300MHz SETUP FAIL,
HOLD PASS, CDC/BOUNDARIES NOT SIGNED OFF. No bit, board test, commit or push.
Reports and recovery provenance are retained in dev2-r2/reports/ and archived
outside the source tree at
`/home/openion/Valence-inorder-evidence/batch38-board-routed-20261017-r1`.

## 2026-10-17 batch39: parallel authorization and local capture/PC feedback

Receipt: `build/gsim/i1-bandwidth39-20261017-r1/receipt.json`, SHA256
`796807ab81e73989278355c71046d41ffcca337a6790d5690d890efff0d47cd2`.
PASS_I1_BANDWIDTH39_AFFECTED_SHORT_ONLY:37 affected checks,13 performance gates,
17 Scala parameter tests;35 FPGA-tool unit tests. No full regression or Linux
simulation. `audit_batch39_short.py` rechecks385 source/141 artifact hashes,
the immutable batch38 baseline, all six stream dictionaries and short O3
CoreMark. Exact register declarations remain6999 and memory declarations89;
directory writers remain4. No new pipeline edge, owner, MSHR or payload RAM.

One combined hardware batch, with no OoO/shared IP/clock/reset RTL edits:

- DT predecodes real TLB source read/write permissions before proof-owner
  selection. Existing owner bindings, full VPN tags, A/D, SUM/MXR and privilege
  checks remain live. For a page-aligned cache window, each existing physical
  proof page computes its window Boolean before VPN selection; read handoff
  no longer waits for selected full PA assembly and a subsequent window
  comparison. Non-page-aligned windows retain exact PA qualification. Bare
  candidates also qualify their windows in parallel. Runtime equality checks
  compare the resulting cacheability with the exact original PA window.
- Probe data capture uses its retained B slot directly, not a shared row mux
  containing the CPU's late pending tag/victim decision. Victim collision
  forwarding is resolved independently in each physical way before final way
  selection. Existing SRAM read/capture edges and payload banks remain;
  independent byte oracles plus old-expression assertions check both paths.
- Each existing BTB bank resolves target/direction/compressed fallback locally;
  the early PC-derived bank select chooses the result. Global OR-of-bank hit
  no longer explicitly feeds every next-PC bit. Entry count/RAM geometry,
  index/tag policy, training and combinational prediction semantics are kept;
  the exact old next-PC expression remains a simulation assertion.

New focused checks:18258 predictor cycles with full128 aligned/compressed
slots, carry/wrap, aliases, training and FENCE.I;428 masked transactions at
256B and32KiB each,112 read collisions,8 probe and8 victim/bypass collisions;
two475-case MMU runs, including a non-page-aligned window. Wrong-target,
wrong-forward and wrong-page independent negatives must reject. Existing
paired Home reverse returns, errors, backpressure, two-client coherence,
C/A boundaries and32 F/D precise-context cases remain enabled.

All six measured streams are exactly equal to batch38, including80-cycle
read/79-cycle write service floors. CoreMark ROI646056 cycles/345517
instructions, total687500 cycles/367211 retired, CRC59156 and trace
7b173819116883a2 are also exactly equal. This is timing restructuring with
NO measured IPC/bandwidth loss, not a new throughput gain or formal score.

Reset review queries the actual batch38 routed DCP without another
implementation: `dev2-r2/reset-audit-batch39-r1/`. All nine Critical targets
are the first asynchronous control of a three-stage ASYNC_REG chain;
internal D->Q links are direct and clocks consistent. Seven functional
release branches have positive recovery/removal slack. UART gate/raw-RX
release branches feed only downstream synchronizer reset pins under existing
exceptions; their infinite/empty slack is NOT counted as a timing PASS.
Cold common-reset, stopped-clock and mailbox behavior reuse the source- and
artifact-rechecked balanced BUFGCE proof at
`build/fpga/i1-network32-timing24-synth-20261015-r1/managed-clock-proof/`;
USER2 reuses the unchanged real serial-TAP/protocol proofs. No new waiver,
unilateral hot-reset support or broad CDC signoff is claimed. The new routed
board will repeat per-instance structure and functional release timing audit.

Strict exporter now accepts a distinct batch39 schema and the exact four
changed source files plus its new runner. Current board directory leaf must
still match the proven batch38 single-writer LUTRAM bytes; only that unchanged
leaf's mapping is reused, never the old CPU implementation.

Fresh no-MAC full-board candidate:
`E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261017-dev2-r3`.
Implementation started17:20:21 Asia/Shanghai. CPU300/DDR UI250/AON-UART50,
32+32KiB, two read slots/one write slot, F/D and USER2/65 remain unchanged.
One fresh synthesis/place/Explore phys_opt is followed by a saved checkpoint
and timing-driven `route_design -no_psir -timing_summary`, matching the
completed batch38 strategy and avoiding its crashed router clock-opt stage.
No timing exceptions/frequency are relaxed. Implementation results follow;
the staged manifest and short audit remain immutable pre-physical records.

### batch39 completed real-board implementation and one post-route pass

Fresh synth/place/Explore phys_opt/default timing-driven route completed
18:00:39 Asia/Shanghai. One bounded post-route ExploreWithHoldFix followed by
`route_design -preserve -no_psir -timing_summary` completed18:08:56. It reuses
ONLY this batch's completed routed DCP, with no RTL, clock, exception, place
or synthesis restart. Initial and post-route evidence are both retained.

| Actual routed stage | CPU300 WNS ns | TNS ns | Failing setup endpoints | CPU hold ns |
| --- | ---: | ---: | ---: | ---: |
| batch38 dev2-r2 | -0.316 | -172.500 | 2140 | +0.010 |
| batch39 initial route, reports/ | -0.072 | -1.152 | 92 | +0.010 |
| batch39 one post-route pass, postroute-r1/ | -0.017 | -0.418 | 70 | +0.003 |

300MHz remains NOT MET. The final worst path is I-cache victimTags_0[6] ->
offerPc[50]/CE,13 LUT levels,3.154ns data delay (0.943ns logic/2.211ns route).
Initial DT fastWriteTag -> atomic state deficit improved during physical
optimization; the new worst path does not imply all other families pass.
Read-only same-constraint DCP queries in `dev2-r3/path-review-r2/paths.tsv`
check the full target endpoint collections, not merely the top60 report:

| Requested path family | batch38 ns | batch39 final ns |
| --- | ---: | ---: |
| D-cache metadata write enable, all9 WE pins | -0.316 | +0.021 |
| D-cache probe payload capture, all D/CE pins | -0.280 | +0.402 |
| D-cache victim payload capture, all D/CE pins | -0.278 | +0.280 |
| offerPc -> offerPc self-feedback, D/CE | -0.260 | +0.006 |
| Any source -> offerPc admission, D/CE | -0.260 | -0.017 |
| DT -> atomic state admission, D/CE | -0.251 | +0.023 |

Thus the requested metadata/probe/victim andpure PC self-feedback families
are positive under the current constraints, butPC admission from I-cache
is still negative. PC andmetadata positive slack are also small. Queryr1
stopped on an incorrect D-cache instance path; its partial evidence is kept,
andqueryr2 uses the actual `/coherent/cache/` payload hierarchy. Neither query
changes implementation, clocks or exceptions; there was no new synth/route.

Remaining reported negatives include I-cache/native return -> aligner,
CSR snapshot -> PC, IT/PMP -> bareFastValid and EX ALU result control.
Positive hold is only3ps; do not describe this as comfortable timing margin.

DDR UI250 remains setup+0.165/hold+0.010ns; AON/UART50 remains+2.477/+0.019ns.
Pulse-width slack+0.081ns; no hold or pulse-width failing endpoints.
Final full-board resources93624 LUT (27.43%),55121 CLB registers (55120 FF
plus one AND/OR),BRAM62.5,DSP31. Relative to batch38 final route this is
+642 LUT (+0.69%) and-29 registers; logical register declarations remain
EXACTLY6999 and memory declarations89. Same-stage linked synthesis is
94407LUT/54475registers vs93883/54457 previously, not to be confused with
post-route totals. Home final11772LUT/3788FF; each directory bank remains
582LUT including480LUTRAM andzeroFF. Predictor1334LUT including480LUTRAM,
128FF. The single-writer directory/resource fix is retained.

All137383 routable nets are fully routed withzero routing errors. DRC has
40 Warning instances,zero Error/Critical: DSP pipelining recommendations,
three LUT-equation warnings andone no-routable-load warning. All20 reported
bus-skew checks pass; minimum reported slack+2.467ns. No-clock,
unconstrained-internal, multiple/generated-clock and combinational/latch
loop counts arezero. Existing board boundary exceptions remain explicit:
button_n/sys_rst_n lack input_delay, c0_ddr4_reset_n lacks output_delay,
uart_rxd has partial input_delay. No broad false path was added.

The final routed CDC report retains EXACTLY the same nine Critical
source/destination pairs (three CDC-10,six CDC-11) and377 CDC-15 warnings.
Per-instance reset audit verifies allnine three-stage ASYNC_REG chains,
same destination clocks anddirect Q->D links. Seven branches with functional
reset loads have positive max/min recovery/removal slack; the smallest
functional removal slack is+0.110ns. Gate/raw-RX branches have ONLY
synchronizer reset loads under pre-existing exceptions, explicitly marked
SYNC_RESET_ONLY_EXISTING_EXCEPTION_REVIEW, not inferred PASS from empty
slack. Structure/release audit does not waive Criticals, qualify unilateral
hot reset, or assert broad CDC signoff. Historical balanced BUFGCE/mailbox
andactual serial-TAP tests remain source/artifact-checked andunchanged.

Final provenance recheck:385 source hashes,379 exported RTL/board/script
hashes,11 exporter/build/audit resource hashes and32 copied IP hashes all
match; allthree board XDC files equal batch38, andthe strict37-check receipt
still validates. Original OoO/shared RTL, multiclock topology,32+32KiB,
two DDR read/one write slot,64-bit AXI,2GiB DDR andUSER2/65 are unchanged.
No MAC/general DMA was added. No bit, board qualification, commit or push.
Machine-readable physical review: `dev2-r3/physical-review.json` (separate
from the immutable staged board manifest). Small reports, receipts, logs,
tools andsource snapshots are archived outside the repository at
`/home/openion/Valence-inorder-evidence/batch39-board-routed-20261017-r1`;
large DCP/IP caches remain in the original E: candidate, not in source control.

## 2026-10-17 batch40: remove impossible IT turnover and shorten return/PMP/EX logic

This batch targets the actual batch39 routed negative paths, not a cache/slot
increase. The original OoO core, multiclock topology, fpga8 profile, I/D32KiB,
DDR two-read/one-write slots and Home directory RAM interface remain unchanged.

- The registered C parcel aligner cannot offer a new word request while it is
  ready to consume an old word response. Its integrated IT now excludes that
  impossible same-edge turnover from request READY, removing old I-cache VALID
  from the PC admission feedback. A live assertion checks the contract; the
  generic translator keeps its original turnover capability by default.
- Parcel payload capture depends on its existing first/second-wait ownership,
  not late response VALID. Reply visibility, word-reuse validity and state
  transitions still require the actual handshake. No pipeline edge is added.
- Registered coherent-cache hit VALID is factored directly from stored reply,
  known hit and late-classifying hit terms. The old expression is independently
  retained as a cycle-by-cycle equivalence assertion, without new storage.
- Staged PMP uses local four-entry priority groups with global lower-index
  priority; exact legacy grant equivalence is asserted. Partial overlap and
  locked M-mode restrictions are retained, rather than permission bypasses.
- The FPGA ALU uses independently computed 16-bit carry alternatives and
  lookahead selection. Other timing math keeps its previous default chunking;
  RV32 remains native. No new registers, RAM, queue slots or retirement delay.

CPU-to-CPU hold uncertainty is increased from0.050 to0.080ns. This is30ps
additional guard, not a relaxed clock or false path. Final hold numbers must
be reported together with this changed guard; no placement success is implied.

Short qualification PASS: `build/gsim/i1-bandwidth40-20261017-r1/receipt.json`,
SHA256 `8a5d659d40cc5f60277ac6fff9e0da2839e64d4ce958dd720f84350181bdb22f`.
All49 checks,13 same-workload performance gates and17 Scala cases pass.
PMP direct/staged RV32/64 each check65536 queries; each staged case also
checks768 held-input-noise cases. Execute RV32/64 each check44128 cases.
All corresponding injected-error controls reject. Six Bare/Sv39 stream
records and O3 CoreMark match batch39 field-for-field: ROI646056 ticks,
345517 ROI instructions, total687500 cycles/367211 retired; no formal score.

Strict `audit_batch40_short.py` rehashes386 sources/210 artifacts. Exact6999
register and89 memory declarations are unchanged, withfour directory write
ports andzero added payload RAM. Actual single-writer LUTRAM leaf identity,
JTAG andbalanced reset proofs are retained, not replaced by behavioral tests.
The38 FPGA tooling unit tests pass, including complete batch40 negative-test
and state/performance/schema guards. No source or flow changes after PASS.

Fresh full-board candidate staged after this complete audit:
`E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261017-dev2-r4`.
Only MIG/Clock Wizard/AXI CDC IP are reused; CPU/SoC synthesis is fresh.
Physical qualification remains pending; batch39 reports do not qualify this RTL.

Fresh synthesis completed19:25:33 CST, withzero Error/Critical Warning.
Linked actual-board post-synthesis usage is94594 LUT,54480 registers,
BRAM62.5,DSP31; against batch39 at the SAME linked stage this is+187LUT
(+0.20%) and+5registers. Home remains11379LUT/3773FF andeach ofitsfour
directory banks582LUT (480LUTRAM)/zeroFF. Synthesis mapping differences
are not additional architectural state and not final routed resource totals.
Full implementation started19:26:31 CST; no second synthesis was launched.
An initial command-line argument-order error exited before opening the
project or starting synthesis; its original vivado.log/jou are retained.

Initial complete route finished19:55:07 CST: WNS-0.100ns/TNS-1.480ns,
47 setup-failing endpoints, WHS+0.010ns withthe80ps hold guard, zero hold
or pulse-width failures (WPWS+0.081ns). Worst path is addrPacket_address[26]
toD-cache metadata RAM WE,11LUT levels/2.942ns data delay (70.9% routing).
DDR UI250 is+0.358/+0.010ns; AON/UART50 is+0.619/+0.040ns.
Initial routed resource totals93785LUT/55189registers/BRAM62.5/DSP31.
This result still FAILS300MHz; the earlier+0.009ns pre-route estimate is
not signoff. One bounded ExploreWithHoldFix pass starts fromthiscompleted
routed DCP, followed bypreserving route with-no_psir; no synth/place/RTL,
clock orconstraint change. Base reports remain untouched underreports/.

### batch40 final routed result: setup/hold PASS, borderline setup margin

The bounded post-route pass finished20:00:58 CST. The final selected result
is `dev2-r4/postroute-r1/real_board_routed.dcp`, SHA256
`e6b5cb3fd23cc28d1c6fae8a2a02f6621e01172e979b1dcf6dc66356bb82ccb0`.
The original route SHA256 is
`23c09629c5fe982b542a3acfad614cee5c57f68bb15e7b8627b7beda419f179d`.
No new synthesis, placement, RTL, clocks or exceptions were applied inthispass.

| Actual routed domain | Setup slack ns | Hold slack ns |
| --- | ---: | ---: |
| CPU300 | 0.000(MET) | +0.010 |
| DDR UI250 | +0.358 | +0.010 |
| AON/UART50 | +0.619 | +0.040 |

Global TNS/THS/TPWS arezero; setup/hold/pulse failing endpoints allzero,
WPWS+0.081ns. CPU hold already includes80ps extrauncertainty (previously50ps).
The worst setup is ownershipCut head-address feedback toitsCE,10logic levels,
3.069ns datapath (73.9% routing). CPU minimum hold is DSP tile-product to
row accumulation. A0.000ns MET result meets theconstraints but givesalmost
no additional setup margin; neither higher Fmax nor board stability is claimed.

Final full-board resources:93788LUT(27.48%),55189registers(55188FF+oneAND/OR),
62.5BRAM,31DSP. Relative tobatch39 finalroute:+164LUT(+0.18%),+68registers;
the exact architectural FIR register/memory declarations remain unchanged.
Home11776LUT/3779FF; fourdirectory banks eachretain480LUTRAM/zeroFF
(total LUT582,581,581,582). Predictor1316LUT including480LUTRAM,128FF.

All137741 routable nets arefullyrouted,zero routing errors. DRC40warnings,
zero Error/Critical. All20bus-skew checks pass(min+2.127ns). No-clock,
unconstrained-internal,multiple/generated-clock andloop counts remainzero.
The existing no-input-delay reset pins, MIG reset output andpartial UART
input-delay exceptions remain explicit, not a blanket I/O timing qualification.

CDC Critical exactsource/destination pairs matchbatch39:threeCDC-10,sixCDC-11;
377CDC-15 warnings. Allnine3-stage ASYNC_REG/directchains checked. Seven
functional reset-release branches havepositive recovery/removal slack(min
functional removal+0.200ns); two synchronizer-only branches retainexisting
exceptions andarenotassigned artificial PASS. No CDC waiver,new clock,
unilateral-hot-reset qualification or broad CDC signoff was added.

Read-only same-period DCP queries in`dev2-r4/path-review-postroute-r1/`
compare thecomplete endpoint families, not only a handpicked formerworstbit:

| Path family | batch39 ns | batch40 ns |
| --- | ---: | ---: |
| PC all admission D/CE | -0.017 | +0.006 |
| Aligner result D/CE | -0.015 | +0.019 |
| IT PMP -> bare fast valid | -0.012 | +0.143 |
| EX result D/CE | -0.011 | +0.002 |
| PC self-feedback | +0.006 | +0.048 |
| DT metadata WE | +0.021 | +0.038 |
| D probe capture | +0.402 | +0.329 |
| D victim capture | +0.280 | +0.198 |
| DT -> atomic admission | +0.023 | +0.157 |

Not every positive path improved; probe/victim slack decreased but stays
positive. PC admission andEX remain near thelimit. The new global worst
ownershipCut feedback isoutside these nine queriedfamilies andisexplicitly
included inthe fullglobalSTA. No extra physical experiment followed PASS.

Machine-readable result: `dev2-r4/physical-review.json`, separate fromthe
immutable staged manifest andshortreceipt. Provenance closure rechecks386
source files,210 shortartifacts,379 exported files,12 toolresources and32
IPfiles; thethree board pin/XDC files equalbatch39. Small reports,receipts,
logs,scripts andsource snapshots arearchived outside theworktree at
`/home/openion/Valence-inorder-evidence/batch40-board-routed-20261017-r1`.
Large DCP/IP/compiled caches stay inoriginal outputs. No bit,commit,push or
original OoO change. Next hardware acceptance isboard testing plus explicit
closure ofremaining CDC/boundary reviews, not anunconditionalproductionclaim.

### batch40 bit delivery and cleanup

On the user's subsequent request, bit generation completed at
2026-10-17 20:14:41 CST from the accepted `postroute-r1/real_board_routed.dcp`.
No RTL, clocks, constraints, synthesis, placement or routing were changed.
Vivado write_bitstream finished with zero errors or critical warnings.

Delivery root:
`E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261017-dev2-r4`.
The bit is
`bitstream/orbital_i1_rv64gc_cpu300_i32k_d32k_uart460800_jtag65_nomac.bit`
(28,700,920 bytes), SHA256
`9ac868f6cfa25bdcc1d544f7496e4564a09d5384d5891cf33a17a5a4d7a1632d`.
`bitstream/delivery.json` records bit, DCP and proof hashes, configuration and
cleanup results. Frozen `board-manifest.json` and `physical-review.json` retain
their earlier pre-bit fields; the new delivery record reports the later step.

The candidate keeps CPU300 / DDR UI250 / AON+UART50 MHz, I/D32KiB, RV64GC,
Sv39, PLIC, CMU, actual MIG and AXI CDC, and DDR2GiB. UART is460800 baud.
It includes the USER2 scan-length fix: board65 clocks accepted,66 rejected,
generic default64 unchanged. Actual dual-TAP RTL simulation has12 passing
cases and the protocol proof has3 cases. This is not a real-board JTAG-download
qualification. No MAC, network DMA or general DMA is in this candidate; the
PHY stays reset and Ethernet/network boot are unavailable.

Routed WNS remains0.000ns MET and WHS+0.010ns, with zero failing setup/hold
endpoints. Setup is borderline, not comfortable margin. The9 documented
existing CDC critical findings are not waived. Hardware runtime and full
CDC/boundary signoff still need their own acceptance; bit generation alone
does not close those gates. Bare/Sv39 and O3 CoreMark remain the batch40 short
comparison results, not newly measured board performance.

After the GUI was saved and closed,31 obsolete WSL project/temporary
directories and18 old I1 Windows output directories were removed only after
archive-content verification and a second source-content check. Archives:
`/home/openion/Valence-inorder-evidence/cleanup-20261017-bit40-r1`.

- `wsl-old-candidates.tar.gz`: all files/symlink targets, including dirty files
  and standalone Git objects; SHA256
  `b6cf3603c2c4a08e1d3b9e21ce898bfd928fc360e19fd880596c0cd39c999ec0`.
- `windows-old-candidates.tar.gz`:12,880 RTL/report/script/configuration and
  other retained entries; SHA256
  `485e7a10e634346c4b5b85ed546321435dd8cbba4ee6ae1633f2fd7800efdea6`.
  The1,037 omitted regenerable entries include old DCPs and simulation caches;
  these are not recoverable from the archive and must be regenerated.
- Scope manifests record exact paths, content hashes and Git/worktree metadata.
  `RECOVERY.txt` explains worktree recovery without restoring stale .git pointers.

Current `Valence-inorder`, its build/proof closure, original `Valence` with its
dirty changes, dev2-r4, directly referenced dev2-r3/directory38, current evidence,
and existing OoO firmware/JTAG tools were retained. All386 source hashes,
210 short artifacts,379 exported files,12 source resources and32 IP files
were rechecked after cleanup; the3 board pin/XDC files still match the baseline.
The cleanup removed10,932,102,719 bytes of old files while retaining
1,776,973,809 bytes in compressed archives (excluding small manifests).
No WSL VHDX compaction was performed. Source publication to `dev2` excludes
bit/DCP, generated RTL, build/out and local evidence archives; original OoO
source and the `dev`/`main` branch tips are not part of this publication.
