# Common-platform JTAG RAM-download option

This is the first bounded peripheral-composition axis for configurable SoCs. It
is **not** a new CPU size/performance family, hart debugger, board qualification,
or a claim that every legal combination has been behaviorally tested.

## Configuration contract

`CommonPeripheralConfig(jtagDownload = true)` is separate from
`CommonCpuProfile`: CPU geometry and reviewed CPU-profile equality are unchanged.
The common platform takes this typed configuration as a trailing defaulted
constructor parameter. Its resolved features drive the real fabric and MMIO
region list. The old fixed `CommonCpuProfile.features` value is removed rather
than retaining two authorities for peripheral membership.

The production exporter accepts `--jtag-download=on|off`, default `on`, alongside
its existing CPU, clock, ROM and compile-receipt options. For example, append
`--jtag-download=off` to an otherwise valid static A1 export command. The exporter
records `jtagDownload`, nullable `jtagDmiAddressBits`, and the effective
`cpuMmioRegions`. These report configuration, not measured performance.

| Choice | Loader / DMI | Other peripherals | Runtime debug admission |
|---|---|---|---|
| `on` (default) | Present | Unchanged | Existing restrictions apply |
| `off` | Loader and DMI interface omitted | Unchanged | Rejected |

`off` leaves the existing `0x10003000` JTAG aperture unused. Remaining addresses
and IRQ identities are not renumbered. UART, ordinary DMA, Ethernet, packet DMA,
CMU, timer and interrupt controllers remain present. The independent-debug-clock
pin and existing fixed-domain qualification constraints are retained; when JTAG
is absent its DMI clock boundary is not instantiated. Runtime network admission
continues to require runtime debug admission; no alternate dynamic owner protocol
is introduced. This option does not implement hart halt/resume or RISC-V debug.

The software-facing output changed here is the emission manifest. The inspected
Linux network DT template does not advertise this loader; no unrelated DT or
firmware nodes were changed. There is not yet one arbitrary-device/count schema
that regenerates all firmware and board wrappers.

## Bounded validation (2026-10-28)

Baseline: public `0c48b927c6da7cf24e802277558edb3ac8c0b005`, tree
`524693725e48c3b127eaaefb7776271028871100`. Separate baseline/candidate worktrees
were compiled freshly, serially. Generation used Java 21, Mill 1.1.7,
Scala 2.13.17, Chisel 7.3.0 and firtool 1.135.0.

- Four pure configuration tests and two focused elaboration tests passed.
  These cover the preserved default, stable remaining regions, explicit option
  parsing, runtime dependency rejection, and actual fabric loader/DMI presence.
- Three whole-platform structural exports used A1, `hardwareClocks=false`,
  `independentDebugClock=false`, identical CPU/cache/owner geometry: baseline-on,
  candidate-on and candidate-off. This generated RTL, not an executable CPU model.
- Baseline-on and candidate-on lowered SystemVerilog are **byte-identical**:
  SHA256 `9a07752e8ae264569b8db34c7125db35ba1e5984205a0dcfb4f41b9d708aee26`.
  The raw diff is empty. The same normal `--strip-debug-info` lowering was used;
  no arbitrary logic normalization was applied.
- Candidate-off omits the actual loader and DMI ports while retaining the A1
  tile, managed peripheral bank, MAC, both DMAs, interrupts and coherent Home.
  This static pair already lacked a DMI CDC module when enabled: conditional CDC
  exclusion is source-reviewed, **not** a measured CDC-removal result here.
- Two real-fabric GSIM configurations passed short transactions. ON checks a
  fixed independent DMI capability value, eight cycles of response backpressure,
  and both scalar lanes reading the loader aperture. OFF checks reads/writes to
  the fixed absent window return errors with preserved owner/page-fault status,
  no external peripheral/DDR traffic, no duplicate response and no retained
  obligation. Both observer-negative injections failed with their exact expected
  diagnostics. ASAN/UBSAN were active; no sanitizer failure occurred.

The short checks took 31 cycles (ON) and 21 (OFF), but perform different work:
**those counts are not a speedup comparison**. No CPU execution, boot, Linux,
physical synthesis/timing, area savings or board result is claimed. Other CPU and
clock combinations are not newly behavior-qualified. Matched structural exports
used the explicit test-only emitter. An additional actual
`CommonMachinePlatformMain` invocation with A1/production, `--jtag-download=off`,
`--programmable`, `--emit-chirrtl-only` and the successful current compile receipt
passed. Its emitted manifest reports JTAG absent, no DMI address width, the eight
remaining MMIO windows, and unchanged two-wide/32 KiB two-way cache geometry; its
FIR has no loader/DMI and retains the other platform modules. The public CLI fixes
`hardwareClocks=true` and requires programmable or Vivado ROM, unlike the matched
structural exports (`hardwareClocks=false`, nonprogrammable ROM). Therefore no
whole-FIR equality between these different configurations is claimed. This extra
run verifies the real user entrypoint and manifest, not physical clocks or boot.

One initial runner preflight failed because its reader expected the restored tool
receipt's file hashes in the wrong JSON shape. It launched no DUT/model build.
That failed attempt and its runner are retained separately; correcting the
receipt reader did not alter RTL or test-source bytes. The fresh bounded gate
then passed. GSIM used the pinned source revision with the already-qualified
initialization-span fix, not an implicit tool setup or random-initialization claim.

Reproducible test entrypoints:
- `platform.CommonPeripheralConfigSpec`
- `platform.CommonPeripheralElaborationSpec`
- `platform.CommonJtagPlatformElaborationMain <fresh-output> on|off`
- `platform.CommonMachineFabricJtagOptionGsimMain <fresh-output> on|off`
- `fabric_machine.cpp`, `ENABLE_JTAG=1|0`, `--jtag-option-only` and
  `--jtag-option-only --inject-mismatch`

Private build evidence contains raw FIR/SV, source/classpath and tool hashes,
owned-process resource receipts, exact positive/negative outputs and the failed
preflight. Native execution was serial and bounded; the 4 GiB process-tree RSS
limit was sampled, not a kernel hard-cgroup guarantee.
