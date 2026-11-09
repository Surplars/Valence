# Real CPU ROM-to-DDR copy. PERF_BODY is the hash-verified original 360B binary.
.option norvc
.option norelax
.section .text.start,"ax"
.globl _start, loader_fence, loader_jump, loader_fail, perf_body
_start:
    la t0, loader_fail
    csrw mtvec, t0
    la s0, perf_body
    li s1, 0x80200000
    li t0, 45
1:
    ld t1, 0(s0)
    sd t1, 0(s1)
    addi s0, s0, 8
    addi s1, s1, 8
    addi t0, t0, -1
    bnez t0, 1b
loader_fence:
    fence.i
    li t0, 0x80200000
loader_jump:
    jr t0
loader_fail:
    j loader_fail
.org 0x1000
perf_body:
.incbin PERF_BODY
