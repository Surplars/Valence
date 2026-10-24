.option norvc
.option norelax
.section .text
.globl _start
_start:
    bnez a0,failed
    bnez a1,failed
    csrr t0,mie
    bnez t0,failed
    csrr t0,satp
    bnez t0,failed
.globl passed
passed:
    j passed
failed:
    ebreak
