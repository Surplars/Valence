# HS data patterns and backpressure: focused GSIM addendum

This adds tests only. It links a small independent C++ driver against the exact
sealed, sanitizer-built `HypervisorPlatformGsim` object. No RTL, generated model,
production selection, or existing archive is changed. The H platform remains
explicit opt-in, and `misa.H` remains clear.

## Finite scope

Each of 36 cases retires 79 HS-origin H-memory operations:

- SPVP=U with VS.U=1, and SPVP=S with VS.U=0.
- Six input/store patterns: all zero, all one, repeated 0x7f, repeated 0x80,
  alternating 0xa5/0x5a, and mixed 0x80ff7f000102feff. The mixed store value
  additionally varies by operation width and byte offset.
- Three external service schedules: continuously allowed requests/responses and
  retirement; deterministic pseudorandom stalls; and long periodic blocking.
- Patterns 0, 2 and 4 load at page offset 0 and store at offset 32. Patterns
  1, 3 and 5 load at page offset 4088 and store at offset 4064. All widths use
  every naturally aligned byte position within that eight-byte beat. This
  checks valid page-end accesses, not accesses crossing a page boundary.
- HLV.B/BU/H/HU/W/WU/D, HLVX.HU/WU, HSV.B/H/W/D. Stores have signed and unsigned
  readback where applicable. HLVX reads a separate execute-only VS/G page;
  its initial data is the reverse-indexed member of the same six-pattern list.

M-mode performs configuration only and returns to HS with MPP=S and MPV=0.
No guest-memory instruction executes in M-mode. No fault case is introduced.

The independent instruction oracle checks retired PC, instruction, next PC,
write enable and destination/value. Architectural byte memory and physical
request-time byte memory are separate copies. Checks cover exact physical byte
address, width, mask, shifted store data, full aligned response beat, FIFO owner,
request/response stability, expected operation count and final stored bytes.
Both stall schedules must observe backpressure on each native lane. The
continuously allowed schedule does not claim zero internal backpressure.

The pseudorandom schedule uses xorshift64, seeded by pattern, context and
schedule. The long schedule enables native request lanes in the last 36 cycles
of periods 149 and 163, response lanes in the last 34 cycles of periods 173 and
181, and retirement in the last 30 cycles of period 97. These are service
windows within one simulator clock domain, not independent clocks.

A negative run changes the first architectural expected data bit only. It must
exit 1 specifically at `independent architectural data`, not merely fail.
All 13 opcode encodings are checked against an independent GNU assembler.
ASan and UBSan are enabled for the model and driver.

## Reproduction

Apply `HS_PATTERNS_ADDITIVE.diff` after the 86-file platform candidate. This
addendum does not depend on the HS-width or portable-entry addendum, although
it can coexist with both. Run from the repository containing these new files:

```
python3 simulator/gsim/platform_hs_patterns.py \
  --platform-root /path/to/recovery-1106-hypervisor-platform \
  --output /new/output/directory \
  --cxx /path/to/clang++-19 \
  --assembler /path/to/riscv64-unknown-elf-as
```

Optional `--objdump` and `--library-path` select matching existing tools.
No tool installation, fetch, Mill invocation or model regeneration occurs.
The runner rejects an existing output directory, checks the known model and
archive hashes, verifies all 86 source entries inside the sealed archive,
and compares every input hash before and after execution. The platform archive
must have SHA256 `7545358c2e23815275b749d03ef5b281e049925d403686060a09dd9a20623a12`.
The reused model object must have SHA256
`405245eec623c0c5d34278fa401a97a3d46c3b81a28e5efb48f22c120dd891bc`.

## Boundaries

This is finite positive HS-origin instruction/data/transport coverage on the
single-clock tile plus actual shared fabric and RAM. The sentinel follows all
H operations and data responses, but instruction-side activity may still be
pending. CPU enable remains high after startup. There is no idle, parking,
quiescence, independent-clock CDC, external DDR/DMA, timing, throughput,
architectural H completeness, atomic/FP integration, guest OS, or FPGA claim.
The separate restricted M-origin fault review remains unperformed.
