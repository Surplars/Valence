# Transport-only RAM download with OpenOCD

This loader copies one raw contiguous binary into the advertised RAM window,
performs a separate byte-exact readback pass, and asks the ROM to verify and
launch it. It does not implement hart debugging. There is no native RISC-V
OpenOCD target, halt/resume, GPR access, abstract command support, `load_image`,
GDB loading, or ELF relocation. Do not create a fake `riscv` target for this
endpoint: its DM identity deliberately reports version zero.

The entry ABI is the ROM's bare-binary `run_image` path: M mode, `a0 = a1 = 0`,
with the ROM's `fence.i` before entry. This is not a Linux/OpenSBI/DTB boot ABI.
A raw Linux `Image` should not be assumed bootable through this interface.

## Select the actual transport

- `openocd-ram-loader.cfg`: direct Valence DTM TAP, IR length 5, IDCODE instruction
  1, DTMCS instruction 16 and DMI instruction 17. The default IDCODE
  `0x00000001` is an unassigned project test identity, not a registered FPGA ID.
  The wire DTMCS must advertise version 1 and `abits = 7`.
- `openocd-ram-loader-bscan.cfg`: custom 64-bit USER-register endpoint behind
  BSCANE2. The board must have declared the physical FPGA TAP and must set
  `VALENCE_RAM_TAP`, `VALENCE_RAM_FPGA_PART`, `VALENCE_RAM_FPGA_IRLEN`,
  `VALENCE_RAM_JTAG_CHAIN`, `VALENCE_RAM_USER_IR`, and `VALENCE_RAM_FPGA_IDCODE`
  before sourcing it. The exact supported part is `xczu15eg-ffvb1156-2-i`, IR12.
  Explicit USER2/3/4 pairs are respectively `2/0x903`, `3/0x922`, `4/0x923`;
  USER1 is rejected because both inspected routed checkpoints assign it to
  dbg_hub. `ram-loader-xczu15eg.tcl` validates these supplied values before
  adapter-related config commands and again at startup and each DMI/poll/scan entry. The loader checks
  OpenOCD's cached observed IDCODE using `jtag cget`, comparing BSDL fixed bits
  `0x04750093` with mask `0x0fffffff` (revision nibble ignored only).
  The custom USER capability is `0x00000701`.

Both configurations require the user's selected adapter/board configuration
first. They supply no adapter, pins, voltage, TCK speed, physical reset wiring,
FPGA chain order, or USER opcode guesses. In particular, a physical FPGA TAP
is not the direct IR-5 Valence DTM. A multi-TAP/long-IR FPGA board must use its
actual chain declaration and full USER instruction. The USER backend is not
OpenOCD's SiFive `riscv use_bscan_tunnel` protocol.

The exact-part constants come from offline Vivado 2025.1 BSDL inspection, SHA-256
`13554c795fac67e7a4ab6fde86a59d6252b48a1ca17501e4dde1680e5b4e2613`;
PRIVATE USER instructions require a configured FPGA. They do not establish the
board chain order or other TAP/DAP widths and are not actual SMT2 scan results.
The explicit IR-length variable must match the independently verified physical
TAP declaration; the loader does not query an unsupported `jtag cget -irlen`.
The new-image post-synthesis BSCANE2/debug-hub collision guard remains mandatory.
See [exact BSDL values and configuration](../../docs/debug/bscan-user-transport.md).

When a board has already declared the direct DTM TAP, set `VALENCE_RAM_TAP` to
that TAP name; no duplicate TAP is created. `VALENCE_RAM_IDCODE` can specify the
actual direct-DTM identity. Do not load both loader configurations into one
OpenOCD process.

## Safe startup and explicit download

1. Program the intended design and start its ROM normally using the board's
   documented flow. Supply the verified board/adapter configuration.
2. Initialize OpenOCD and let it verify the scan chain **before typing `j`**.
   OpenOCD `init` normally resets the TAP. A TAP/transport reset invalidates the
   current download session, so do not initialize again after arming the ROM.
3. Type `j` at the ROM UART prompt. The ROM parks the CPU and explicitly arms
   host RAM access. Normal ROM/menu activity is not authorization to write RAM.
4. In an existing local OpenOCD control session, explicitly run:

   ```tcl
   valence_download_and_run /absolute/path/image.bin 0x80200000
   ```

   The file must exist on the host running OpenOCD. Quoting a filename containing
   spaces follows normal Tcl rules. The entry must be 4-byte aligned and inside
   the logical unpadded file range starting at `0x80200000`.
5. The return `state commit_accepted` means the one COMMIT request was accepted.
   The ROM independently checks CRC, performs `fence.i`, and claims launch. To
   observe that separate step, explicitly call `valence_wait_claimed`. Even
   `state claimed` does not prove the guest executed successfully. Use the
   guest's own UART/output or another independent functional check.

The configs disable GDB, Tcl RPC and telnet listeners by default. They do not
call `init`, download, reset, or launch merely when sourced. One deliberately
enabled **loopback-only** interactive example is:

```sh
openocd -f /path/to/verified-board.cfg \
  -f simulator/jtag/openocd-ram-loader.cfg \
  -c 'bindto 127.0.0.1; telnet port 4444; init'
```

Then use a local telnet client to `127.0.0.1:4444`, arm with UART `j`, and enter
the download command above. Substitute the BSCAN config when that is the actual
transport. The board config must not create a native `riscv` target or initialize
before the loader's configuration is sourced. These are usage instructions,
not evidence of a physical adapter/OpenOCD run in this change.

## Loader contract

- Capability `0x40 = 0x564c0101`; STATUS `0x41` bits ARMED 0, COMMITTED 1,
  CANCELLED 2, BUSY 3, FAULT 4, LINK_UP 5, CLAIMED 6.
- COMMAND `0x42`: ABORT 1, COMMIT 2. ENTRY `0x43`, LENGTH `0x44`, CRC32 `0x45`,
  GENERATION `0x46`, BASE `0x47`, END_EXCLUSIVE `0x48`, EXPECTED_GENERATION `0x49`.
- BASE must be `0x80200000`; END_EXCLUSIVE must be a nonwrapping, aligned 32-bit
  upper bound. File length must be positive. `round_up(length, 4)` must fit.
  The final memory word is zero-padded, while CRC covers only original file bytes.
- CRC is CRC-32/ISO-HDLC: reflected polynomial `0xedb88320`, initial/final XOR
  `0xffffffff`, standard `123456789` check `0xcbf43926`.
- SBA uses `sbcs` `0x38`, `sbaddress0` `0x39`, `sbdata0` `0x3c`. It requires SBA
  version 1, 32-bit addresses, and only 32-bit access support. Every memory
  operation is followed by bounded busy/error polling. Write mode disables
  read side effects; verification uses read-on-address, with read-on-data and
  autoincrement disabled so the last read cannot accidentally access beyond RAM.
- Host memory access requires ARMED and LINK_UP, with no cancelled/fault/claimed
  state. Generation and status are checked before/after each chunk and before
  each metadata write. The original generation is written to `0x49`; COMMIT
  atomically checks it to reject re-arm races between host observations.
- COMMIT seals host memory access. Generation remains stable through COMMIT and
  CLAIM. CLAIM is the irreversible launch point; full reset is required before
  another download after CLAIM.

## Failures and cancellation

There is never a blind retry of an accepted memory write or COMMIT. Direct DTM
busy responses are handled by DTMCS `dmireset` (bit 16), then NOP collection of
the outstanding response. The original request is not submitted again. USER
busy is polled with NOP frames; protocol errors fail closed. No backend issues
`dtmhardreset`, USER hard reset, TRST, TAP reset, or system reset during transfer.

DMI and SBA polling are bounded. A timeout is an uncertain observation, not
proof that the bus transfer disappeared. The loader latches transport
uncertainty and blocks another download from implicitly retrying it. It does
not automatically abort on a timeout. If cancellation is intended, explicitly
call:

```tcl
valence_abort
```

ABORT first tries a bounded transport drain with NOPs, then sends ABORT once and
observes bus drain/cancellation. If the transport cannot drain, ABORT cannot be
safely delivered and the message says so. If bus drain stays BUSY, do not assume
RAM access has stopped or re-arm the ROM; inspect board/reset/drain state. ABORT
before CLAIM can cancel launch. ABORT after CLAIM cannot undo it. Resolve the
reported state before choosing any board-specific reset procedure.

The internal limits are positive poll/chunk counts, not wall-clock guarantees:
`valence_ram::dmi_polls` 64, `sb_polls` 1024, `claim_polls` 4096, and
`chunk_words` 256. Raising a bound permits more observation time, not permission
to resend a timed-out write. Reported elapsed milliseconds cover transfer,
readback, metadata and COMMIT observation when Tcl's clock supports them; they
do not include file reading/CRC preparation or prove guest execution.

## Cost and validation limits

The deliberately conservative script performs individual 32-bit SBA operations,
full readback, repeated IR scans and DMI/SBA polling. It prioritizes diagnosable
correctness over throughput. Large images may be slow, particularly over USB;
no fast Linux-image download rate is promised.

`ram-loader-cost.tcl` measures the emitted script commands with the independent
zero-extra-stall model, 256-word chunks, one direct IR-5 TAP:

| File bytes | DMI requests | IR scans | DR scans | Ideal single-TAP TCK |
| ---: | ---: | ---: | ---: | ---: |
| 256 | 427 | 857 | 857 | 52,255 |
| 4,096 | 6,211 | 12,425 | 12,425 | 757,903 |

Counts include initialization, full write/readback, metadata and one COMMIT.
The ideal TCK count includes shifted bits, requested idle clocks, and shortest
RUN/IDLE scan transitions (6 per IR, 5 per DR). It excludes adapter/USB/Tcl
latency, extra chain TAPs, busy stalls, ROM verification and guest execution.
It is a protocol lower bound, not measured board throughput.

Run the independent host checks without OpenOCD, hardware or a network server:

```sh
tclsh simulator/jtag/ram-loader-test.tcl
tclsh simulator/jtag/ram-loader-bscan-test.tcl
tclsh simulator/jtag/ram-loader-config-test.tcl
tclsh simulator/jtag/ram-loader-cost.tcl
```

The models do not import DUT register constants. Coverage includes endian/binary
bytes, odd length/padding, CRC known answers, complete readback, sticky busy and
failure, delayed SBA completion/errors, no duplicate writes/COMMIT, bounds and
entry checks, generation change/re-arm, cancellation/drain, CLAIM, USER framing,
capability/identity checks, and source-only configuration behavior. A stock-Tcl
shim checks the Jim byte-access branch without the optional `binary` command;
it is not a real Jim/OpenOCD interpreter run.

No OpenOCD executable or Jim interpreter was available in this workspace. No
software was installed, no physical adapter was contacted, and no board rate,
FPGA implementation, or on-board guest execution is claimed by these host tests.
OpenOCD commonly embeds a minimal Jim build; the runtime therefore uses its
`pack/unpack` byte primitives when available, not optional `binary`/`zlib`.

Official references checked for script syntax and behavior:

- [OpenOCD raw JTAG commands](https://openocd.org/doc/html/JTAG-Commands.html):
  field splitting, returned scan fields, IR and idle-clock commands.
- [OpenOCD TAP declarations](https://openocd.org/doc/html/TAP-Declaration.html):
  chain declaration and hardware IDCODE query.
- [OpenOCD server configuration](https://openocd.org/doc/html/Server-Configuration.html):
  init/reset ordering and disabling/enabling control ports.
- [OpenOCD general commands](https://openocd.org/doc/html/General-Commands.html):
  loopback binding and distinction from native target memory commands.
- [Jim Tcl manual](https://jim.tcl-lang.org/home/doc/trunk/Tcl_shipped.html):
  `unpack` and raw-byte string handling.
