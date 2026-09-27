.section .text.boot, "ax"
.globl _start

_start:
    la t0, __riscv_test_start
    jr t0
