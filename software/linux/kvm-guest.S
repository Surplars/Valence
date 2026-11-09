.option norvc
.section .text
.global _start
_start:
    li t0, 0x10000000
    li t1, 0x4b564d31
    sw t1, 0(t0)
1:  j 1b
