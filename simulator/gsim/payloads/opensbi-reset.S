    .section .text.start, "ax"
    .globl _start
_start:
    li a0, 0
    li a1, 0
    li t0, 0x80040000
    jr t0
