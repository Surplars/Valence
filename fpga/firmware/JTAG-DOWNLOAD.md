# Optional cooperative JTAG RAM download

`build.py --jtag-download` adds the `j` command to both the legacy BootROM loop
and the interactive `--boot-menu` monitor. This must be paired with the matching
JTAG downloader RTL. The feature is absent by default and does not probe MMIO,
arm the host write path, or execute a JTAG image during ordinary startup.
All verified download paths now auto-boot. Legacy `--netboot` still tries
network at reset; `--boot-menu` waits for the user to select a download source.
The menu has no independent Run Image action. JTAG still requires explicit `j`
and the current session host COMMIT; it never opens automatically at reset.

Example firmware build for the 2 GiB board profile:

```sh
python3 fpga/firmware/build.py --jtag-download --boot-menu \
  --ddr --ddr-bytes 0x80000000 --cpu-hz 100000000 --crc-mode byte \
  --uart-reference-hz 7372800 --uart-baud 460800 --out <fresh-output>
```

The menu build needs the already-pinned official CoreMark source, as before.
The optional `--netboot --netboot-posted-rx` flags can be combined with this
configuration. Building a ROM alone does not update an FPGA bitstream.

The host uses [openocd-ram-loader.cfg](../../simulator/jtag/openocd-ram-loader.cfg)
and [ram-loader.tcl](../../simulator/jtag/ram-loader.tcl). Initialize OpenOCD and
the transport **before** entering `j`: OpenOCD initialization resets the TAP,
which invalidates a session that was already armed. See the transport's own
instructions for selecting the matching direct or FPGA BSCAN route.

## Session and launch contract

1. At the UART monitor, enter `j`. BootROM rejects unknown external-image
   peripheral ownership, closes and drains any stale JTAG session, quiets the
   existing memory-DMA/network owners, and calls `firmware_ram_prepare` before
   `OPEN`.
2. Before allowing host writes, ROM requires hardware `RAM_BASE=0x80200000` and
   a nonempty hardware aperture ending at or below its own `RAM_BASE+IMAGE_LIMIT`.
   A narrower hardware whitelist is accepted. An overly broad whitelist is a
   hard rejection before `OPEN`, so mismatched RTL cannot overwrite the ROM
   stack or menu diagnostics before a later metadata check.
3. `OPEN` increments the 32-bit generation and enables the host write path.
   BootROM prints `JTAG WAIT` and stays in this command. No other monitor
   commands or diagnostics run while JTAG owns RAM admission.
4. The host downloads a flat image at `0x80200000`, using aligned 32-bit writes.
   It zero-pads the last word but records the logical, unpadded length and
   reflected IEEE CRC32. Entry must be 4-byte aligned and within the logical
   image. Both hardware and firmware enforce bounds, including the rounded-up
   final word.
5. Host `COMMIT` explicitly requests verification **and execution**. It closes
   admission and freezes metadata. ROM waits until `BUSY` clears, checks the
   generation and metadata, prepares RAM again using the existing cache
   maintenance policy, and calculates its own CRC over actual logical image
   bytes. It checks cancellation and generation between CRC batches.
6. After CRC and `fence.i`, ROM makes an atomic epoch-bound `CLAIM`. This is the
   irreversible launch point: hardware accepts it only while the same
   generation is committed, drained, and linked. Abort/reset before this point
   prevents launch. After successful `CLAIM`, host abort cannot revoke launch,
   and `CLAIMED` prevents further host writes or reopening until coordinated
   hardware reset.
7. ROM invokes the existing `run_image` ABI: M-mode, bare addressing, interrupts
   and unlocked PMP disabled, `a0=0`, `a1=0`, and the existing final `fence.i`.
   There is no new Linux/OpenSBI entry ABI. A returning or trapping external
   image keeps the existing unknown-peripheral-ownership reset requirement.

The existing coherent DMA path and `firmware_ram_prepare` are required parts
of this design. A compiler barrier, volatile access, or generic `fence.i`
alone is not a claim of DMA/cache coherence. CRC is an integrity check, not
authentication or a secure-boot boundary. The host's COMMIT response is not
proof that CRC passed or that the application actually ran; inspect UART and
the payload's own success output.

## Abort, drain, and recovery

UART Esc or Ctrl-C before launch requests `CLOSE`. Host ABORT, link reset, generation
changes, invalid metadata, or CRC failure also cause ROM to close the session.
`BUSY` includes presented but unaccepted requests as well as accepted requests:
ROM must see `ARMED=COMMITTED=BUSY=0` before returning to the command parser.
Only then does it print `JTAG CLOSED; retry with j`.

The close/drain wait is bounded to two seconds of the configured timebase.
If ownership does not drain, or a downloader MMIO access traps, ROM prints
`JTAG OWNERSHIP UNKNOWN; BOARD RESET REQUIRED` and remains in a reset-only
loop. It does not resume normal monitoring, diagnostics, UART loading, or
network loading. Hardware must retain the memory owner through any pending
response; transport reset must not release that owner early. A newly entered
`j` cannot revive an already claimed session.

## CPU register interface

Base: `0x10003000`. CPU accesses are aligned 64-bit loads/stores with full
write strobes. Offsets are bytes.

| Offset | Register | Meaning |
| --- | --- | --- |
| `0x00` | STATUS | bit0 ARMED; bit1 COMMITTED; bit2 CANCELLED; bit3 BUSY; bit4 FAULT; bit5 LINK_UP; bit6 CLAIMED |
| `0x08` | COMMAND | `1=OPEN`, `2=CLOSE`, `(generation<<32)\|3=CLAIM` |
| `0x10` | ENTRY | Frozen 32-bit entry |
| `0x18` | LENGTH | Logical 32-bit byte length |
| `0x20` | CRC32 | IEEE CRC32 of logical image bytes |
| `0x28` | GENERATION | 32-bit epoch, increments on OPEN, wraps modulo 2^32 |
| `0x30` | RAM_BASE | Hardware whitelist start |
| `0x38` | RAM_END | Hardware whitelist exclusive end |

The CPU interface has no capability register in these first 64 bytes. The
host-side DMI capability is separate. An absent or incompatible MMIO target
is not treated as a recoverable download failure.

## Focused software acceptance

```sh
python3 fpga/firmware/check_jtag_download.py --cc clang-19 --out <fresh-test-output>
```

The runner uses ASan/UBSan by default, runs the actual BootROM implementation
with callback-modeled MMIO in four menu/network combinations, and reruns the
existing menu, UART recovery, and pending-command tests. It writes per-case
logs and `receipt.json`, including source hashes. `--cc` can select an existing
compiler; `--no-sanitize` is an explicit reduced-check option.

Covered cases include safe launch, padded tails, generation wrap, stale-session
drain, committed-but-busy drain, bounds and hardware-aperture mismatch,
independent CRC failures, quiet/preparation failures, Ctrl-C, host abort/fault,
reset or generation changes during metadata/CRC/fencing/final CLAIM, denied
CLAIM traps, stuck or ignored CLOSE, external ownership lock, retry only after
drain, and no JTAG access at startup.

These are software/model checks. They do not establish CDC correctness, real
OpenOCD interoperability, routed timing, JTAG electrical operation, or execution
on physical DDR/FPGA hardware. Matching RTL tests and eventual board acceptance
are separate requirements.
