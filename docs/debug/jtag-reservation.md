# FPGA-next JTAG/debug reservation

This adds real transport hardware and an explicit future-core boundary. It does **not** implement a RISC-V Debug Module, halt/resume, single stepping, breakpoints, register access, program buffer, system-bus debug access, GDB operation, or board pin assignments. The legacy debug hardware is not imported. Existing `BoardSocTop` is untouched.

## Configuration and integration

`src/main/scala/ip/debug/JtagDebugReservation.scala` exports `JtagDebugReservation(JtagDebugParams(...))`. Default `enabled=false` elaborates to constants with no instances, registers, blackbox or resource file. Thus the default does not add debug logic or CPU timing fanout. Enabled mode includes `src/main/resources/debug/ValenceJtagDebugPort.sv` through `HasBlackBoxResource`.

- Default enabled transport: `JtagDebugParams(enabled=true)`. The internal unavailable endpoint returns DMI failure for **every** operation, including `dmstatus` and `dmcontrol`.
- Future DM integration: `enabled=true, externalDmi=true`; connect `DebugDmiPort` in `debugClock` and reset that endpoint with `dmiResetN`. Never reset one mailbox endpoint with CPU warm reset. `dmiResetN` resets/cancels the **transaction interface**, not the future DM's persistent architectural registers. A real DM must preserve its separate specification-defined power-up/dmactive reset policy.
- Address width is configurable from 1 to 32, default 7; IR width is fixed at 5. DMI width is `addressBits + 34`, default 41.
- IDCODE defaults to `0x00000001`, an unassigned simulation/test placeholder. Its manufacturer field is zero. This does not claim a registered JEDEC identity or production IDCODE compliance. A board/product owner must supply its legitimately assigned manufacturer/part/version identity before release.
- `idleHint` defaults to 7. It is a conservative TCK-cycle hint for the tested clock ratios, **not** a guarantee for arbitrary system-clock speed, endpoint latency or stopped clocks. Debuggers must handle busy.
- All public top signals remain plain digital signals; no FPGA-vendor I/O/clock primitive is assumed.

`HartDebugReservationPort` is a typed **declaration only** for future `haltRequest`, `resumeRequest`, `halted`, `resumeAck`, `resetAck` and dcsr/dpc access request/response. It is not instantiated or tied into the CPU. Future core support must define a precise retirement boundary, exceptions/interrupt ordering, outstanding-memory drain, privilege checks, and one-shot resume acknowledgment before enabling a real DM. Do not scatter asynchronous halt gating into pipeline registers.

## Implemented wire protocol

The target format is the ratified [RISC-V Debug 1.0 JTAG DTM](https://docs.riscv.org/reference/debug/v1.0/dtm.html), revised 2025-02-21. Its DTM wire version is **1**, shared with Debug 0.13; it is not version 2. This is a transport implementation target, not a claim of whole-system debug compliance. Field positions were checked against the [official register XML](https://github.com/riscv/riscv-debug-spec/blob/main/xml/jtag_registers.xml).

The TAP implements all 16 standard states, five-TMS-high reset, IR capture `00001`, IR update on falling TCK, LSB-first shift, pause/exit/update paths, IDCODE (`IR=0x01`), DTMCS (`0x10`), DMI (`0x11`), and a one-bit BYPASS for every other instruction. Reset selects IDCODE. TDO and its output-enable change on falling TCK; the adapter samples the captured LSB before the following rising-edge shift. No EXTEST/SAMPLE or boundary-scan cells exist.

DTMCS is 32 bits: version `[3:0]=1`, abits `[9:4]`, dmistat `[11:10]`, idle `[14:12]`, dmireset bit 16, dtmhardreset bit 17. Optional errinfo and reserved fields read zero; reset bits read zero. DMI is `{address, data[31:0], op[1:0]}`. Only read=1/write=2 dispatch. Nop=0 never dispatches; reserved op=3 is rejected with failure. Reading before completion sets sticky busy=3. Endpoint failure=2 is sticky; reserved endpoint status=1 is converted to failure. Sticky status prevents subsequent dispatch until cleared. `dmireset` clears sticky status without canceling the outstanding transaction. `dtmhardreset` cancels transport work and resets its endpoint. Side effects already committed by a future DM cannot be undone.

## CDC and reset contract

There is one outstanding DMI transaction across a bundled-data mailbox. Request payload stays in TCK-domain holding registers until the response is consumed. Request/response toggle synchronizers have two stages; destination request and source response are locally registered. Ready/valid payloads remain stable while stalled; a new transaction cannot overlap its predecessor. There is no pulse-only crossing and no independent per-bit bus synchronizer.

`debugPorN` and optional `trstN` asynchronously reset both mailbox endpoints. Reset release takes three local edges per domain. CPU warm reset is independent and must not drive these resets. Holding TCK or the system debug clock stopped does not lose a held mailbox payload. Whole-debug reset while either clock is stopped cancels outstanding work without replay. A TAP reset also resets the transport. Hard-reset assertion lasts a complete TCK period and reaches the stopped destination asynchronously; local synchronized release prevents unilateral re-entry.

An external endpoint must:
1. Use the exported `dmiResetN` for transaction-interface state and discard any pending request/response on assertion. No unsolicited/stale responses after reset. Do not wire this to the full future DM architectural-state reset; TRST/DTM hard reset do not authorize resetting that persistent state.
2. Accept requests only on `valid && ready`, and produce exactly one held response per accepted request.
3. Hold a response until `valid && ready`; a combinational single-cycle pulse on the request acceptance edge is insufficient.
4. Avoid reporting successful hart-control operations until their architectural effect is complete.

RTL edge simulation cannot model metastability. Physical implementation still needs ASYNC_REG recognition, bounded bundled-data route delays/skew, reset-domain review, clock-capable pin routing and timing signoff. `fpga/constraints/jtag-reservation.xdc.example` is deliberately inactive and has no package pins or guessed voltages. Its hierarchy collections fail closed when names/counts differ. Do not replace the scoped constraints with whole-clock false paths that hide bundled-data timing.

## Verification and reproducibility

Run from the repository root with existing approved tools:

```
source scripts/cloud/env.sh
mill -i IonSoC.test.testOnly debug.JtagDebugReservationSpec
mill -i IonSoC.test.runMain debug.JtagDebugReservationExport off build/jtag/off
mill -i IonSoC.test.runMain debug.JtagDebugReservationExport stub build/jtag/stub
mill -i IonSoC.test.runMain debug.JtagDebugReservationExport external build/jtag/external
python3 simulator/jtag/run.py
```

`make -f simulator/jtag/targets.mk jtag-test` combines the focused Scala/export/constraint/native/mutation checks. The standalone targets do not modify the existing Makefile. Export closure can also be checked using `check_export.py <directory> --mode off|stub|external`; `rtl-manifest.json` is the exact synthesis-resource allowlist. firtool adds its provenance comment to copied resources, so closure normalizes only that first comment and the final newline before comparing content.

`run.py` accepts `IVERILOG` and `VVP` paths, never installs tools, and writes `build/jtag/native/results.json`. Missing native tools return exit 77 with `status=blocked`; no behavioral pass is inferred from source inspection. The enabled test uses independently advancing clocks and a scoreboard, with all 32 TAP arcs, all 32 instruction values, IDCODE/IR/BYPASS shift order, mid-scan pause, reset-by-TMS, DTMCS fields, read/write responses, sticky errors, hung endpoint, both resets, halted clocks, random ratios/backpressure and 200 randomized transactions. Separate tests cover response backpressure, reset without stale replay, and address widths 1/7/32. `python3 simulator/jtag/mutations.py` checks detection of six deliberately injected protocol faults without modifying source RTL. A 100-request batch records actual TCK costs; these are protocol metrics, not FPGA Fmax. An elaborated variable/process census verifies disabled elision and reports enabled storage without calling it synthesized LUT/FF area.

The existing GSIM independent-clock probe was rerun for this work. All seven edge-scheduling cases and asynchronous reset failed the intended capability contract. Results are in `build/gsim/debug-clock-capability/results.json`. GSIM is still used for the project's supported synchronous CPU tests; this result only disqualifies it as evidence for this independently clocked transport. No retired simulator was used.

## Optional OpenOCD transport exploration

`python3 simulator/jtag/remote_bitbang.py` runs the native SV stub on loopback only, then `openocd -f simulator/jtag/openocd-transport-only.cfg` can inspect the TAP/DTM and observe the expected failed `dmstatus` access. This optional example declares **no RISC-V target or GDB service**. It follows the official [OpenOCD scan commands](https://openocd.org/doc/html/JTAG-Commands.html) and [remote_bitbang interface](https://openocd.org/doc/html/Debug-Adapter-Configuration.html#Adapter-Configuration). It is not a verified OpenOCD/hardware/GDB compatibility claim unless separately run and recorded. No tool installation or real target connection is performed by the test runner.

## Remaining acceptance gates

- A real Debug Module plus precise core integration, abstract-register access and halt/resume tests.
- Board-specific top composition, legal IDCODE, connector/pins/voltages/TCK routing and I/O constraints.
- Native simulation results when Icarus is available; until recorded, multi-clock RTL correctness remains unverified.
- Physical CDC/RDC, synthesis/place-and-route, resource/Fmax comparison, real JTAG adapter and OpenOCD/GDB tests.
