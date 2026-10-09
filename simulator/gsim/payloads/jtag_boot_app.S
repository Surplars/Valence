.option norvc
.option norelax
.section .text
.globl _start
_start:
    li s10, 0x5a5
    lwu t1, 64(s1)
    li t0, 0x22334455
    bne t1, t0, fail
    lwu t1, 128(s1)
    li t0, 0x66778899
    bne t1, t0, fail
    li s11, 0x600
1:  j 1b
fail:
    li s11, 0xbad
2:  j 2b
.org 64
.word 0x22334455
.org 128
.word 0x66778899
.org 192
