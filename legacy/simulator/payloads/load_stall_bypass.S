.section .text.init
.option rvc
.globl _start

.equ UART_BASE, 0x10010000

_start:
    li   t0, UART_BASE
    li   s0, 0x20

    # Regression for a RustSBI jump-table failure.  The sequence below creates
    # an ALU result for a0, then a cache load to the same rd.  While the load
    # stalls, the old EX bypass entry must not override the real load response.
    la   a1, table
    add  a0, a1, a1
    ld   a0, 0(a1)
    ld   s1, 8(s0)
    add  a0, a0, a1

    la   t1, target
    bne  a0, t1, fail

pass:
    li   t1, 'B'
    sb   t1, 0(t0)
    li   t1, 'P'
    sb   t1, 0(t0)
    li   a0, 0
    li   a7, 93
1:
    j    1b

fail:
    li   t1, 'B'
    sb   t1, 0(t0)
    li   t1, 'F'
    sb   t1, 0(t0)
    li   a0, 1
    li   a7, 93
2:
    j    2b

.section .data
.align 3
table:
    .dword target - table
target:
    .dword 0
