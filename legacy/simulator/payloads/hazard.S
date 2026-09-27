.section .text.init
.globl _start

_start:
    li   t0, 0x10010000
    li   t1, 'H'
    sb   t1, 0(t0)

    li   t0, 0x12345000
    li   t1, 0x12345000
    bne  t0, t1, fail

    li   t0, 1
    addi t0, t0, 1
    li   t1, 2
    bne  t0, t1, fail

    la   t0, hazard_store
    li   t1, 0x55aa
    sb   t1, 0(t0)

    la   t0, hazard_data
    li   t1, 0x1122334455667788
    sd   t1, 0(t0)
    ld   t2, 0(t0)
    bne  t2, t1, fail

    li   t3, 4
    amoadd.d t4, t3, (t0)
    bne  t4, t1, fail
    ld   t5, 0(t0)
    add  t6, t1, t3
    bne  t5, t6, fail

    csrr t0, mhartid
    li   t1, 0
    bne  t0, t1, fail

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
hazard_data:
    .dword 0
hazard_store:
    .dword 0
