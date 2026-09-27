.section .text.init
.globl _start

.equ UART_BASE, 0x10010000

_start:
    li   t0, UART_BASE
    li   t1, 'M'
    sb   t1, 0(t0)

    li   t0, 0x12345678
    li   t1, -3
    mul  t2, t0, t1
    li   t3, 0xffffffffc962fc98
    bne  t2, t3, fail

    li   t0, -2
    li   t1, 3
    mulh t2, t0, t1
    li   t3, -1
    bne  t2, t3, fail

    li   t0, -1
    li   t1, 2
    mulhu t2, t0, t1
    li   t3, 1
    bne  t2, t3, fail

    li    t0, -2
    li    t1, 3
    mulhsu t2, t0, t1
    li    t3, -1
    bne   t2, t3, fail

    li   t0, -7
    li   t1, 3
    div  t2, t0, t1
    li   t3, -2
    bne  t2, t3, fail
    rem  t2, t0, t1
    li   t3, -1
    bne  t2, t3, fail

    li   t0, -1
    li   t1, 2
    divu t2, t0, t1
    li   t3, 0x7fffffffffffffff
    bne  t2, t3, fail
    remu t2, t0, t1
    li   t3, 1
    bne  t2, t3, fail

    li   t0, 0x8000000000000000
    li   t1, -1
    div  t2, t0, t1
    bne  t2, t0, fail
    rem  t2, t0, t1
    bne  t2, zero, fail

    li   t0, 123
    div  t2, t0, zero
    li   t3, -1
    bne  t2, t3, fail
    rem  t2, t0, zero
    bne  t2, t0, fail

    li   t0, 0x00010002
    li   t1, 0x00030004
    mulw t2, t0, t1
    li   t3, 0x000a0008
    bne  t2, t3, fail

    li   t0, -7
    li   t1, 3
    divw t2, t0, t1
    li   t3, -2
    bne  t2, t3, fail
    remw t2, t0, t1
    li   t3, -1
    bne  t2, t3, fail

    li    t0, -1
    li    t1, 2
    divuw t2, t0, t1
    li    t3, 0x7fffffff
    bne   t2, t3, fail
    remuw t2, t0, t1
    li    t3, 1
    bne   t2, t3, fail

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
