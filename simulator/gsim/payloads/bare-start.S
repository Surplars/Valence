.option norvc
.option norelax
.section .text.start,"ax"
.global _start
_start:
    la sp, _stack_top
    la a0, _data_start
    call kernel
    li t0, 2208
    bne a0, t0, failed
    li a0, 42
    j _program_end
failed:
    .word 0
