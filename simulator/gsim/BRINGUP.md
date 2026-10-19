# Bounded functional bring-up

`python3 simulator/gsim/bringup.py` prints the named-profile plan and starts no
build or simulation. This entry is separate from existing historical pin gates.
It never selects an FPGA timing/performance candidate implicitly, fetches tools,
invokes Verilator/Vivado, runs Linux, or runs the broad GSIM batch.

## I1 compact ROM fixture

`i1-compact-rom` executes the existing `inorder.FiveStageSocGsimMain` and
`harness/five_stage_soc.cpp` independent host oracle, with the checked
`inorder/soc_smoke.S` guest. It is RV64I/Zicsr/Zifencei compact5, one DDR slot,
no M, no cache or predictor, a checked/rebuilt 4 KiB BootROM, and a sparse host
memory serving the 2 GiB DDR address window. It uses one CPU/fabric clock.

The bounded positive run checks reset/clock-lock and DDR-ready gating, ROM
retirement and entry into DDR code, RAM byte lanes and the last DDR word, real
UART internal loopback, MSIP, MTIP, PLIC source 3 claim/complete, MRET, and precise
MMIO/AXI access faults. Completion is the guest's successful EBREAK path plus
host memory/trap-count checks, not a UART banner or synthetic tohost response.
The same model then runs `--inject`, which must fail specifically with
`bare SoC guest fail path` after corrupted DDR data. A crash or sanitizer finding
cannot pass that negative control.

This is a functional fixture, not the batch44/300 MHz profile, independent-clock
CDC qualification, JTAG validation, OoO execution, NEMU difftest, or board proof.
The single-clock result may serve as a reference before a separately scoped CDC
change; it cannot establish equivalence to an OoO platform that has not run.

`ooo-board-rom` is deliberately blocked in the plan. The legacy
`BoardSocGsimMain` omits the now-required actual `configurationCheck` and its
`board_boot.cpp` oracle expects V0.1/manual `g`, while current firmware uses
V0.2/AUTOBOOT and return-lock. A separately reviewed, explicit baseline wrapper
and current-protocol oracle are needed; bypassing configuration assertions is
not a repair.

## OoO local-ROM fixture

`ooo-local-rom` selects the new `ooo.BaselineBoardGsimMain` wrapper and
`harness/baseline_board_boot.cpp` oracle. It is separate from the blocked legacy
`ooo-board-rom` entry. The wrapper fixes early-issue, two-wide RV64IMAC, 40 MHz,
128 KiB ROM, 1 MiB local RAM and 1.5 Mbaud UART (divisor 1, 24 MHz baud reference),
with actual core-configuration assertions. It does not choose an FPGA-next
performance profile. Registered interrupt handling is enabled in the core
configuration, but IRQ delivery is explicitly NOT COVERED by this fixture.

Use the same explicit tool arguments with `--preflight ooo-local-rom` or
`--run ooo-local-rom --output /evidence/unique-ooo-run`. The direct classpath must
contain `ooo.BaselineBoardGsimMain`; the fallback Mill module is `IonSoC`.
The firmware builder uses the supplied absolute `riscv64-unknown-elf-` prefix;
`objcopy` must match that prefix, and `size` must be present beside `gcc`.
The runner verifies the resulting plain, non-DDR, non-netboot firmware contract:
AUTOBOOT enabled, manual launch removed, return requires reset, exact clock/UART
settings and ROM hash. The wrapper, independent host and firmware sources are
included in the run's frozen hashes.

The host's planned checks include the V0.2 reset banner plus real ROM retirement,
whole-image bad CRC without RAM execution, chunk CRC retry, actual downloaded RAM
bytes, sample application AUTOBOOT, APP RETURN and the reset-only lock, then a
hardware reset and a fresh byte/halfword/word/doubleword RAM-signature guest.
Progress receipts distinguish firmware build, model elaboration/generation,
compilation, and boot execution. A profile's `executable_fixture` status alone is
not a passed result: only its fresh successful execution receipt establishes
these checks. An incomplete stage retains its failure evidence.

IRQ delivery, DDR, Linux, independent CPU/fabric clocks, physical CDC and board
validation remain NOT COVERED. A separate independent TileLink transport
component does not make this a complete independent-clock CPU platform.

## Tool selection and execution

All simulator and compiler paths are explicit. Source a suitable tool environment
first when tools need runtime libraries. Example (substitute your verified paths):

```sh
python3 -B simulator/gsim/bringup.py --preflight i1-compact-rom \
  --gsim-source /tools/gsim --gsim-bin /tools/gsim/build/gsim/gsim \
  --cxx /tools/clang++-19 --gcc /tools/riscv64-unknown-elf-gcc \
  --objcopy /tools/riscv64-unknown-elf-objcopy \
  --java-classpath-file /evidence/java-classpath.txt --java /tools/jdk/bin/java
```

Replace `--preflight i1-compact-rom` with
`--run i1-compact-rom --output /evidence/unique-bringup-run` to execute.
An existing output directory is rejected; no prior artifacts are deleted.
The output contains individual command logs/receipts, firmware, generated model,
and `receipt.json` with profile, source/tool/artifact hashes and measured counters.
Failure also leaves a receipt and all partial artifacts.

By default the source must be clean at the repository's existing GSIM revision.
For a separately qualified patched build, additionally supply
`--gsim-qualification /evidence/qualification.json`. The runner verifies the
same upstream pin, upstream repository, exact tracked patch hash and modified
file set, every patched-source hash, GSIM binary hash, compiler hash, and the
receipt's focused/upstream-runtime/sanitizer evidence. This explicitly records
use of that qualified tool, without treating it as the historical binary or
changing old runners' pin/cleanliness checks. Receipts are evidence supplied by
the operator, not cryptographic attestation of how a tool was compiled.

The direct Java classpath route records hashes of compiled classes and JARs;
it checks them unchanged after execution and does not silently recompile stale
classes. Use a classpath from the matching
completed compile. Mill can list absent optional `resources`/`compile-resources`
directories; those are explicitly recorded as absent and Java ignores them.
Other missing entries fail. If no classpath is supplied, the runner uses
`mill -i -j2 OrbitalI1.test.runMain`; an explicit invocation such as
`--mill-command 'bash /tools/mill-1.1.7 -i -j2'` is supported without a shell.

A hard 4 GiB free-disk floor is checked before and throughout every child.
Cross-assembly/preflight and firmware commands are bounded to 120 seconds,
elaboration and GSIM generation to 600 seconds, and compilation to 900 seconds.
I1 simulations are bounded to 180 seconds/2M host cycles; the OoO functional boot
sequence is bounded to 600 seconds/30M host cycles.
The guard terminates the child's process group on timeout or low disk and keeps
its evidence. There is no cleanup/overwrite fallback or hidden parallel build.

## Host-only runner tests

```sh
python3 -B simulator/gsim/test_bringup.py
```

These verify default-plan safety, named profile and output requirements, blocked
OoO status, per-profile dispatch and positive chain markers, qualification
hash/patch checks, selected-emitter classpath validation/drift, firmware clock and
protocol contracts, disk-floor refusal, preserved negative logs and timeout handling.
They do not build a hardware model or claim hardware coverage.

## Historical physical evidence catalog

The manifest's `historical_evidence` entries are a reading of existing repository
records, not commands executed by this runner. The merged `f1013f21` source and
this candidate both have `physical_requalified: false`.

- [I1 batch44](../../fpga/inorder/README.md): no MAC; CPU300/UI250/AON50/UART50,
  I/D 32 KiB, two DDR slots, USER2/65-bit JTAG. Recorded bit SHA-256 is
  `bb974f17ec03bd5d51eb5df56bc858beb7a5e9051cffedcce4b4c95fe2c0aea7`.
  Recorded setup WNS is 0.000 ns and hold +0.007 ns, with nine reset CDC Critical
  findings still separately disclosed. The user reported a small JTAG-loaded
  program executing and printing over UART. That is the scope of the board
  evidence; it is not Linux, long-term stability or full CDC qualification.
- [OoO netboot-drain-r1, 2026-10-07](../../fpga/zu15eg/README.md): recorded
  100 MHz RV64GC, 2 GiB DDR, UART460800; generated bit with setup +0.001 ns and
  hold +0.009 ns. Real board boot/handoff and stability remain unverified.
- Older DDR50 board feedback has no verified bit identity in this task. The
  historical README includes a rejected-download-header report. It cannot mark
  a newly generated artifact as board-passed.

No historical routed margin, bit identity or user board report is automatically
transferred to the compact single-clock fixture or a future CDC candidate.

## Separate experimental entry catalog

These entries are listed in the manifest under `experimental_entries`, all with
`selected_by_bringup: false`. None was executed by this bring-up run, and none is
a selectable `bringup.py --run` profile.

- [fpga/next/board_final.py](../../fpga/next/board_final.py): default52 CPU option
  bundle with native MAC T1/JTAG USER2. Its source-declared status is
  `SOURCE_CONFIG_BOUND_NOT_PHYSICALLY_QUALIFIED`. Default action is source/config
  preflight; explicit `--emit` requests native export. Listing it does not claim
  that its source-binding checks were rerun against the current candidate.
- [ooo.CpuMatchingBoardProfileGsimMain](../../src/test/scala/ooo/CpuMatchingBoardProfileGsimMain.scala):
  the full-population candidate requires an explicit selected/reference/candidate
  topology, complete compatible board-profile options, tri-speed Ethernet,
  BSCAN USER2 and explicit native-physical-service models. Its assembly JSON
  does not prove BSCAN or CDC primitive simulation.
- [ooo.CurrentSocTimingMain](../../src/test/scala/ooo/CurrentSocTimingMain.scala):
  out-of-context SystemVerilog timing fixture, optionally compact with named
  structural switches. It is not a BootROM functional acceptance entry.

## Actual I1 independent-clock short boot

The separately named [native independent-clock entry](../cdc/I1_INDEPENDENT_BOOT.md)
uses the real I1 CPU/cache and original fabric/peripherals, with explicit
`test-only` or `full-cpu` geometry and a matching single-clock control. It always
selects the recovered II=1 held-response FIFOs. No small profile or II=2 fallback
is chosen implicitly. Pinned GSIM cannot evaluate these independent clock edges,
so this bounded entry uses the native Icarus exception; `bringup.py` does not
silently dispatch to another simulator. Full board maintenance/managed clocks,
physical qualification and a common A1/I1 platform ABI remain separate gates.
