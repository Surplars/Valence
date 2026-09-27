.section .text.init
.globl _start

.equ UART_BASE, 0x10010000

_start:
#ifdef ION_DEFAULT_BOOT_ARGS
    li   a0, 0
    li   a1, ION_DEFAULT_DTB_ADDR
    li   a2, ION_DEFAULT_PAYLOAD_ADDR
#endif
    mv   s3, a0
    mv   s4, a1
    mv   s5, a2

    la   t0, early_trap
    csrw mtvec, t0

    la   t0, boot_msg
    mv   a0, t0
    jal  ra, puts

    mv   a0, s3
    mv   a1, s4
    mv   a2, s5
    li   t0, 0x40000000
    jr   t0

.balign 4
early_trap:
    csrr s0, mcause
    csrr s1, mepc
    csrr s2, mtval

    la   a0, trap_msg
    jal  ra, puts
    mv   a0, s0
    jal  ra, puthex64

    la   a0, mepc_msg
    jal  ra, puts
    mv   a0, s1
    jal  ra, puthex64

    la   a0, mtval_msg
    jal  ra, puts
    mv   a0, s2
    jal  ra, puthex64

    li   a0, '\n'
    jal  ra, putc
1:
    j    1b

puts:
    mv   t4, ra
    mv   t3, a0
1:
    lbu  a0, 0(t3)
    beqz a0, 2f
    jal  ra, putc
    addi t3, t3, 1
    j    1b
2:
    jr   t4

puthex64:
    mv   t1, ra
    mv   t3, a0
    li   a0, '0'
    jal  ra, putc
    li   a0, 'x'
    jal  ra, putc
    li   t4, 16
1:
    srli t5, t3, 60
    li   t6, 10
    bltu t5, t6, 2f
    addi a0, t5, 87
    j    3f
2:
    addi a0, t5, 48
3:
    jal  ra, putc
    slli t3, t3, 4
    addi t4, t4, -1
    bnez t4, 1b
    jr   t1

putc:
    li   t6, UART_BASE
    sb   a0, 0(t6)
    ret

boot_msg:
    .asciz "ROM->SRAM\n"
trap_msg:
    .asciz "MTRAP mcause="
mepc_msg:
    .asciz " mepc="
mtval_msg:
    .asciz " mtval="
