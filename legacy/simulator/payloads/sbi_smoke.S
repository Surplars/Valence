.section .text.init
.globl _start

_start:
    la   t0, msg
1:
    lbu  a0, 0(t0)
    beqz a0, 2f
    li   a7, 1              # legacy SBI console_putchar
    ecall
    addi t0, t0, 1
    j    1b

2:
    li   a7, 93             # simulator exit sentinel
    li   a0, 0
3:
    j    3b

.section .rodata
msg:
    .asciz "IonSoC SBI smoke\n"
