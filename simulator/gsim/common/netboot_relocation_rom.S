.option norvc
.option norelax
.section .text
.globl _start
_start:
    csrw mie,zero
    csrw satp,zero
    csrw pmpcfg0,zero
    csrw pmpcfg2,zero
    li t0,0x80200000
    fence.i
    jr t0
