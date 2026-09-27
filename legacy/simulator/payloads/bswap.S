.section .text.init
.globl _start

.equ UART_BASE, 0x10010000

_start:
    li   t0, UART_BASE
    li   t1, 'B'
    sb   t1, 0(t0)

    la   t0, be_word
    lw   a2, 0(t0)
    li   t2, 0x04000000
    bne  a2, t2, fail

    lui  a4, 0x10
    addi a4, a4, -256
    srli a5, a2, 8
    srliw a3, a2, 24
    and  a5, a5, a4
    and  a4, a4, a2
    slli a2, a2, 24
    slli a4, a4, 8
    or   a3, a3, a5
    or   a2, a2, a4
    or   a2, a2, a3
    slli a2, a2, 32
    srli a2, a2, 32

    li   t2, 4
    bne  a2, t2, fail

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

.section .rodata
.balign 4
be_word:
    .byte 0x00, 0x00, 0x00, 0x04
