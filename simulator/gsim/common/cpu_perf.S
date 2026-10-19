# Identical bounded performance-observation guest, RV64I loads/stores only.
# DDR test data is supplied by the external synthetic memory, never CPU injection.
.option norvc
.option norelax
.section .text.start,"ax"
.globl _start, perf_fail, perf_done
.globl dep_begin, dep_end, ind_begin, ind_end, copy_begin, copy_end
.globl drain_begin, drain_end, final_fence
_start:
    la t0, perf_fail
    csrw mtvec, t0
    # Warm all 64 lines of the 4 KiB pointer array outside measured windows.
    li s0, 0x80210000
    li t0, 64
warm:
    ld t1, 0(s0)
    addi s0, s0, 64
    addi t0, t0, -1
    bnez t0, warm
    li s0, 0x80210000
    li t0, 256
# Markers are unique retired PCs, not timing-dependent MMIO writes.
dep_begin:
    nop
dependent:
    ld s0, 0(s0)
    addi t0, t0, -1
    bnez t0, dependent
dep_end:
    nop
    li t1, 0x80210800
    bne s0, t1, perf_fail
    li s0, 0x80210000
    li s1, 0
    li t0, 32
ind_begin:
    nop
independent:
    ld a0, 0(s0)
    ld a1, 8(s0)
    ld a2, 16(s0)
    ld a3, 24(s0)
    ld a4, 32(s0)
    ld a5, 40(s0)
    ld a6, 48(s0)
    ld a7, 56(s0)
    add s1, s1, a0
    add s1, s1, a1
    add s1, s1, a2
    add s1, s1, a3
    add s1, s1, a4
    add s1, s1, a5
    add s1, s1, a6
    add s1, s1, a7
    addi s0, s0, 64
    addi t0, t0, -1
    bnez t0, independent
ind_end:
    nop
    li t1, 0x8021040400
    bne s1, t1, perf_fail
    li s0, 0x80220000
    li s1, 0x80230000
    li t0, 64
copy_begin:
    nop
copy_line:
    ld a0, 0(s0)
    ld a1, 8(s0)
    ld a2, 16(s0)
    ld a3, 24(s0)
    ld a4, 32(s0)
    ld a5, 40(s0)
    ld a6, 48(s0)
    ld a7, 56(s0)
    sd a0, 0(s1)
    sd a1, 8(s1)
    sd a2, 16(s1)
    sd a3, 24(s1)
    sd a4, 32(s1)
    sd a5, 40(s1)
    sd a6, 48(s1)
    sd a7, 56(s1)
    addi s0, s0, 64
    addi s1, s1, 64
    addi t0, t0, -1
    bnez t0, copy_line
copy_end:
    nop
# Store retirement is not DDR completion. Measure full maintenance separately.
drain_begin:
    nop
final_fence:
    fence.i
drain_end:
    nop
perf_done:
    j perf_done
perf_fail:
    j perf_fail
