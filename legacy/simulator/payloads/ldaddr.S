.section .text.init
.globl _start

.equ UART_BASE, 0x10010000

_start:
    li   t0, UART_BASE
    li   t1, 'L'
    sb   t1, 0(t0)

    la   t0, rel_src
    li   t2, 0
    ld   t4, 0(t0)
    ld   t5, 8(t0)
    add  t4, t4, t2
    add  t5, t5, t2
    sd   t5, 0(t4)

    la   t0, target
    ld   t1, 0(t0)
    li   t2, 8
    bne  t1, t2, fail

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
2:
    j    2b

.section .data
.align 3
rel_src:
    .dword target
    .dword 8
target:
    .dword 0
