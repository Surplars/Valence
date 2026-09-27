.option arch, +zba,+zbb,+zbs

.section .text.init
.globl _start

.equ UART_BASE, 0x10010000

_start:
    li   t0, UART_BASE
    li   t1, 'B'
    sb   t1, 0(t0)

    li   t0, 0x0123456789abcdef
    rori t1, t0, 8
    li   t2, 0xef0123456789abcd
    bne  t1, t2, fail

    rev8 t1, t0
    li   t2, 0xefcdab8967452301
    bne  t1, t2, fail

    li   t0, 0x000000ff01008000
    orc.b t1, t0
    li   t2, 0x000000ffff00ff00
    bne  t1, t2, fail

    li   t0, 0x0000000012345678
    roriw t1, t0, 4
    li   t2, 0xffffffff81234567
    bne  t1, t2, fail

    li   t0, 0xffffffff00000005
    li   t1, 10
    add.uw t2, t0, t1
    li   t3, 15
    bne  t2, t3, fail

    sh2add.uw t2, t0, t1
    li   t3, 30
    bne  t2, t3, fail

    li   t0, 0
    bseti t0, t0, 40
    li   t1, 0x0000010000000000
    bne  t0, t1, fail
    bexti t2, t0, 40
    li   t3, 1
    bne  t2, t3, fail

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
