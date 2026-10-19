.option norvc
.option norelax
.section .text.start
.globl _start
_start:
    csrw mie, zero
    csrw mstatus, zero
    li a0, 0
    li a1, 0x80500000
    li a2, 0
    li t0, 0x80280000
    jr t0
