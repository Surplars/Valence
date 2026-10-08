# Short ROM-resident DMA latency-window stimulus. Data backing is initialized by
# the independent host oracle, so no CPU cache owner/probe hides the cold-read case.
.option norvc
.section .text.start
.globl _start
_start:
    li s0, 0x10001000
    li t0, 0x80210000
    sd t0, 0(s0)
    li t0, 0x80220000
    sd t0, 8(s0)
    li t0, 512
    sd t0, 16(s0)
    fence iorw, iorw
    li t0, 3
    sd t0, 24(s0)
1:
    ld t0, 32(s0)
    andi t1, t0, 1
    bnez t1, 1b
    andi t1, t0, 4
    bnez t1, fail
    andi t1, t0, 2
    beqz t1, fail
    fence iorw, iorw
    li a0, 'D'
    j print
fail:
    li a0, 'F'
print:
    li t0, 0x10000000
2:
    lbu t1, 5(t0)
    andi t1, t1, 32
    beqz t1, 2b
    sb a0, 0(t0)
3:
    j 3b
