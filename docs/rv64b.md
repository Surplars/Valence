# RV64 B implementation contract

Scope: B 1.0.0, all RV64 Zba/Zbb/Zbs encodings (40). Zbc and crypto extensions are outside this change.
Normative reference: https://docs.riscv.org/reference/isa/v20240411/unpriv/b-st-ext.html
Encoding audit: official riscv-opcodes rv_zba/rv64_zba, rv_zbb/rv64_zbb, rv_zbs/rv64_zbs.

Each existing integer lane computes one combinational B result per cycle, with the same registered
completion/retirement path as base integer ALU operations. No extra queue, issue port, result port or
state is introduced. Default issue width remains two, shared with LSU and M starts. Existing completion
arbitration can withhold ALU issue. ROB token ownership and branch recovery apply unchanged.

Unsigned-word address operations zero-extend rs1[31:0] before XLEN computation and do not sign-extend
the result. W counts/rotates ignore upper input bits and sign-extend the low result. Unary encoding
selectors are not register dependencies. Register and immediate bit indices wrap modulo XLEN.

The datapath uses balanced leading/trailing zero selection, population count reduction, a shared
six-stage mux rotate network (not six cycles), byte wiring/reductions, and one shared fixed-shift
address adder. It is replicated per integer lane; wider issue increases its area. Added operand/result
muxing and count/rotate paths require Vivado measurement. Fmax, LUT/FF and routing remain unverified;
cycle throughput is not a claim of optimal FPGA timing or area.

## Focused validation

`make gsim-core-test` passed for ROB8/PRF36 and ROB32/PRF64. Each configuration runs 278 programs,
380,406 normal commits, 185,224 decoder inputs and 19 precise stops. The B suite covers all 40
encodings, 7,680 operand pairs (boundaries, all single-bit positions and random full-width values),
3,000 mixed random B instructions, register aliases/x0, and 40 recovery/contention programs.
Every normal commit is checked against an independent unsigned C++ instruction interpreter and
pinned NEMU. Decoder tests additionally sweep all 4,096 upper instruction fields for the relevant
OP/OP-32/OP-IMM/OP-IMM-32 funct3 values, covering unary selectors and reserved neighbours.

The NEMU configuration enables CONFIG_RVB and keeps FPU/vector/hypervisor disabled. CONFIG_RVB
adds no register-copy fields in the pinned source; the existing 408-byte reference ABI is unchanged.
NEMU has a broader B/crypto instruction decoder than this DUT; acceptance remains limited to the
explicit Zba/Zbb/Zbs software table. No upstream reference source or generated outputs were edited.

| Benchmark (2,049 instructions) | ROB8 / PRF36 cycles / IPC | ROB32 / PRF64 cycles / IPC |
| --- | --- | --- |
| Independent RORI | 1,539 / 1.331384 | 1,027 / 1.995131 |
| Dependent RORI | 2,051 / 0.999025 | 2,051 / 0.999025 |
| Independent CLZ | 1,539 / 1.331384 | 1,027 / 1.995131 |
| Dependent CLZ | 2,051 / 0.999025 | 2,051 / 0.999025 |

These use ideal two-wide instruction supply, include setup and pipeline fill/drain, and are not
whole-system application performance. The smaller physical register file limits independent
throughput. All 36 previous IPC measurement records are exactly unchanged; eight B records are
added. Before/after artifacts: `build/gsim/ipc-before-rv64b.json`, `build/gsim/ipc.json`.
Focused log: `build/gsim/rv64b-focused.log`.



## Final acceptance

`make test` passed: all 19 Scala checks and full GSIM acceptance, including NEMU mismatch injection,
store-buffer contract injection, synchronous ROM/RAM platform, ROB tag/recovery checks and integer
backend tests. Raw backend tests now also reject unassigned six-bit controls and illegal B/W
combinations. Each core configuration retains the focused counts above and passes independent/dependent
B throughput assertions. The synchronous C platform remains 1,310 instructions / 1,529 cycles at seed 0.
Log: `build/gsim/rv64b-final.log`. Verilator was not invoked.

`make fpga-platform-rtl FPGA_IMAGE=build/gsim/bare-program.bin` also passed; the integrated FPGA
platform exports the B decoder/datapath. Log: `build/gsim/rv64b-export.log`. Vivado synthesis,
implementation and timing analysis remain unavailable and unverified.
