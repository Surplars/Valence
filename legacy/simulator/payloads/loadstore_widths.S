.section .text.init
.globl _start

.equ UART_BASE, 0x10010000

_start:
    li   t0, UART_BASE
    li   t1, 'W'
    sb   t1, 0(t0)

    la   t0, load_data

    lb   t1, 0(t0)
    li   t2, -128
    bne  t1, t2, fail

    lbu  t1, 0(t0)
    li   t2, 0x80
    bne  t1, t2, fail

    lh   t1, 2(t0)
    li   t2, 0xffffffffffff8001
    bne  t1, t2, fail

    lhu  t1, 2(t0)
    li   t2, 0x8001
    bne  t1, t2, fail

    lw   t1, 4(t0)
    li   t2, 0xffffffff80000001
    bne  t1, t2, fail

    lwu  t1, 4(t0)
    li   t2, 0x80000001
    bne  t1, t2, fail

    ld   t1, 8(t0)
    li   t2, 0x0123456789abcdef
    bne  t1, t2, fail

    la   t0, store_data
    li   t1, 0x1122334455667788
    sd   t1, 0(t0)

    li   t1, 0xaa
    sb   t1, 1(t0)
    ld   t2, 0(t0)
    li   t3, 0x112233445566aa88
    bne  t2, t3, fail

    li   t1, 0xbbcc
    sh   t1, 2(t0)
    ld   t2, 0(t0)
    li   t3, 0x11223344bbccaa88
    bne  t2, t3, fail

    li   t1, 0xddeeff00
    sw   t1, 4(t0)
    ld   t2, 0(t0)
    li   t3, 0xddeeff00bbccaa88
    bne  t2, t3, fail

    li   t1, 0x0123456789abcdef
    sd   t1, 8(t0)
    ld   t2, 8(t0)
    bne  t2, t1, fail

pass:
    li   t0, UART_BASE
    li   t1, 'P'
    sb   t1, 0(t0)
    li   a7, 93
    li   a0, 0
1:
    j    1b

fail:
    li   t0, UART_BASE
    li   t1, 'F'
    sb   t1, 0(t0)
    li   a7, 93
    li   a0, 1
1:
    j    1b

.section .data
.align 3
load_data:
    .byte 0x80, 0x7f
    .half 0x8001
    .word 0x80000001
    .dword 0x0123456789abcdef

.align 3
store_data:
    .dword 0
    .dword 0
