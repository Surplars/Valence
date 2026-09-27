.section .text.init
.globl _start

.equ UART_BASE, 0x10010000

_start:
    li   t0, UART_BASE
    li   t1, 'M'
    sb   t1, 0(t0)

    la   t0, data_words
    addi t0, t0, 4
    ld   t1, 0(t0)
    li   t2, 0x99aabbcc11223344
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
data_words:
    .dword 0x1122334455667788
    .dword 0xddeeff0099aabbcc
