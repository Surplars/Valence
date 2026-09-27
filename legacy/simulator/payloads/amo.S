.section .text.init
.globl _start

_start:
    li   t0, 0x10010000
    li   t1, 'A'
    sb   t1, 0(t0)

    la   t0, amo_data
    li   t1, 7
    sd   t1, 0(t0)

    li   t2, 5
    amoadd.d t3, t2, (t0)
    li   t4, 7
    bne  t3, t4, fail
    ld   t3, 0(t0)
    li   t4, 12
    bne  t3, t4, fail

    lr.d t3, (t0)
    li   t4, 12
    bne  t3, t4, fail
    li   t2, 0x55
    sc.d t3, t2, (t0)
    bnez t3, fail
    ld   t3, 0(t0)
    bne  t3, t2, fail

    li   t2, 0xaa
    sc.d t3, t2, (t0)
    beqz t3, fail

    la   t0, amo_word
    li   t1, 0x80000001
    sw   t1, 0(t0)
    li   t2, 0x12345678
    amoswap.w t3, t2, (t0)
    li   t4, -2147483647
    bne  t3, t4, fail
    lw   t3, 0(t0)
    bne  t3, t2, fail

pass:
    li   t0, 0x10010000
    li   t1, 'P'
    sb   t1, 0(t0)
    li   a7, 93
    li   a0, 0
pass_spin:
    j    pass_spin

fail:
    li   t0, 0x10010000
    li   t1, 'F'
    sb   t1, 0(t0)
    li   a7, 93
    li   a0, 1
fail_spin:
    j    fail_spin

.section .data
.align 3
amo_data:
    .dword 0
amo_word:
    .word 0
    .word 0
