    .section .text.start,"ax",@progbits
    .globl _start
_start:
    ld a0, 0(sp)
    addi a1, sp, 8
    call main
    li a7, 93
    ecall
1:  j 1b
