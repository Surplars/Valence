# Native tri-speed integration candidate

Base: CPU/DMA source `66c06d786275dc28c099301162cd09e70497f6eb`, tree
`b3b9b20ecd094666c114af855147fd3116a34e39`. This batch changes export tooling
and prepared physical constraints only. It does not change Scala hardware,
packet-DMA ownership, firmware, package pins or the default profile. The frozen
local Vivado input is separate and must not be replaced by this candidate.

## Closed source-integration gaps

The prior tri-speed exporter emitted the SoC RTL but staged a matched native
wrapper only when BSCAN was also enabled. Its source receipt omitted the native
clock, pad, reset and timing inputs. The default board constraint entry point
also assumes the legacy fixed-frequency RX MMCM and cannot qualify this top.

The exporter now always stages the tri-speed wrapper for the explicit
`--experimental-trispeed-ethernet` option, with the optional existing BSCAN
transformation. It checks every generated top port against the wrapper and
freezes the exact native dependency set in the export receipt. The new
`board-synthesis-files.f` is separate from the generated SoC file list.

The staged `board/trispeed-integration.json` binds:

- The shared REF500, RAW125 and PAD250 clock generator, common TX word-reset
  boundary, and quarter-clock RGMII adapter. The rejected delay-cascade adapter
  and a second MDIO writer are never selected.
- The original 15 carrier package assignments and electrical properties,
  separated from the legacy fixed-1G timing section. Changed pins or an
  unexpected timing command in the pin-only section are rejected.
- One explicit 10/100/1000 timing scenario, with RXC periods 400/40/8 ns and
  fixed nominal 2 ns skew. The inherited both-edge RX +/-1.050 ns and TX
  +/-1.250 ns budgets remain unchanged; PCB skew remains an assumption.
- A fail-closed mapped-topology recipe checking direct RX IBUF/BUFG capture,
  fixed-125 MHz complete-packet readout, common clock/reset ODDR topology,
  cold-reset-only retained owners, and the physical-only ingress epoch.
- Scoped 8 ns Gray-bus, FIFO-payload and held-mailbox constraints for three
  FIFOs and nine mailboxes, including speed requests and diagnostic counters.
  The budget stays 8 ns in the slow-rate scenarios. No clock groups,
  byte-enable multicycle assumption or broad data-path exception is added.

The helper is not a drop-in replacement for complete board constraints. Actual
management/control synchronizers, reset recovery/removal, IP clocks, internal
BSCAN timing and all other endpoints still need netlist-specific review. The
script deliberately reports that complete CDC/RDC/STA remains required.

## Preserved traffic contract

The existing hardware-managed RTL8211F manager remains the sole configuration
writer and negotiates full-duplex 10/100/1000. Rate mailboxes must return actual
consumption acknowledgments before reopening admission. Complete RX banks and
framed CDC/DMA owners retain cold reset only; speed changes reset only incomplete
physical ingress. DMA STOP does not authorize dropping a completed owner, and
blocked retained traffic cannot be silently cleared by a timeout.

This is an ownership-preservation contract, not a promise that a cable loss or
speed change delivers an in-flight wire frame. Partial TX/RX frames can be
explicitly aborted and counted. A packet-DMA completion transfers ownership to
the MAC stream; it is not a wire-delivery acknowledgment. The inherited module
proofs are documented in `tri-speed-mac.md` and `tx-buffer-bandwidth.md`; they are
not fresh proof of the current combined CPU/DMA/JTAG top.

## Short qualification

Host-only checks, using existing tools:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s fpga/next -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 simulator/jtag/test_export_contract.py
python3 -B fpga/firmware/linux_net/test_media_stats.py build/media-host-UNIQUE --cc gcc
```

The four exporter-flag matrix cases in `test_media_integration.py` use a
deliberately synthetic emitter to test Python packaging branches. Tcl command
stubs check argument budgets and fail-closed behavior. Neither is hardware
simulation, real mapped topology, elaboration or a timing result.

After a cloud compile slot is available, the exact optional combined export is:

```sh
python3 -B fpga/next/export.py --output build/media-bscan-UNIQUE \
  --experimental-trispeed-ethernet --experimental-jtag-bscan 2 --emit
```

The existing USER2 guard remains mandatory and has not been run on a new
netlist. Load a matching JTAG BootROM to use the boot-only RAM downloader.
Architectural halt, step and breakpoints are separate future functionality.

Independent-clock behavioral tests already have prepared benches at
`fpga/next/run_native_media.py`. Existing Icarus is required; no tool installation
or simulator substitution is part of this work. These benches still do not
replace vendor primitive simulation or board qualification.

Required remaining gates: source-matched enabled/default exports, focused
combined packet/DMA stop/restart checks as needed for changed dependencies,
native reset/epoch/pad simulation, complete actual CDC/RDC constraints, all
three rates' routed setup/hold and bus-skew reports, and partner-controlled
on-board rate/loss/restart/credit-recovery traffic. No synthesis, route,
bitstream or board success follows from the prepared integration recipe.

## Combined source-bound export checkpoint (2026-10-09)

At source `020edf892f65df4259ad471e3fb7f2c30fd20ee4`, both the enabled and
exact-default complete SoC exports pass. The
[combined evidence manifest](../../fpga/next/evidence/mac-jtag-native-integration.json) binds source files, actual
export receipts, artifacts, and short host checks. This checkpoint includes
the inactive hart-debug contract; no HartDebug module is instantiated in RTL.

The enabled command additionally preserves the prior CPU/DMA candidate:

```sh
python3 -B fpga/next/export.py --output build/mac-jtag-integration-020edf8/native-enabled \
  --physical-load-ingress-flow --dma-line-transfers --dma-line-entries 4 \
  --experimental-trispeed-ethernet --experimental-jtag-bscan 2 --emit
python3 -B fpga/next/export.py --output build/mac-jtag-integration-020edf8/native-default --emit
```

Both use LSU2; virtual precheck and prechecked flow are off. Enabled DMA line
depth is 4, yield is 0, while the exact default keeps those options disabled.
The enabled top retains the full production packet DMA, 2048-byte maximum
frames, four MAC RX banks and two MAC TX banks. Generated MAC memories are
2048x32 RX and 1024x32 TX, each with one synchronous read and one write port.
This is RTL geometry, not FPGA BRAM mapping.

The enabled native wrapper matches all 76 actual SoC ports and uses no extra
JTAG package pins. Both selected-storage censuses pass. All 263 generated
default artifacts are byte-identical to the earlier CPU/DMA native-default
export, whose stored artifact hashes were rechecked before comparison.
The 35 host Python/Tcl tests, 6 existing JTAG exporter tests, and 120 BSCAN
wire-codec vectors pass. These checks do not establish hardware CDC behavior.

The source-matched export gate above is now closed; combined runtime,
independent-clock/vendor simulation, complete actual constraints, per-rate
routed timing and on-board qualification are still pending. The local frozen
Vivado run and all default hardware remain untouched.

The later xsim preparation merge at `20a3a06d04ccef7ae9d1136f9386f13b993a9dfc`
preserves all 223 inputs to both completed top exports. All 283 enabled and 263
default artifacts were rehashed. Its one new test-only Scala emitter now also
compiles and exports the source-bound production loader with a 64-cycle timeout
and a 4 KiB test aperture. Protocol (7 cases), installed-model profiling (1),
and loader-drain (3 clock phases plus 1 owner-reset negative) plans are prepared,
not simulated. See the [final dependency and fixture binding](../../fpga/next/evidence/mac-jtag-final-binding.json).

## Publication pin-check hardening

The source publication adds a strict complete-statement allowlist to the
pin-only packaging helper. It rejects extra or malformed pin assignments,
electrical/control changes, appended Tcl commands and line continuations,
including continuations hidden in comments. The current reviewed XDC and all
staged board files remain byte-identical to the completed enabled export.
The [new helper receipt](../../fpga/next/evidence/mac-pin-validation.json)
binds that replay and its negative tests.

Historical export receipts remain unchanged: their 223-file input inventories
contain the earlier helper hash. Of those inputs, only the Python packaging
helper changes; Scala, SV, board constraints and other export inputs are
unchanged. This host-only replay does not imply a new RTL, xsim, UNISIM,
CDC/RDC, timing or board qualification.
