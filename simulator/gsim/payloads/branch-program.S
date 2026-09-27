.option norvc
.option norelax
.section .text
.global _start
_start:
    jal x0, .Lmain
.Lfunction:
    addi x6, x6, 7
    jalr x0, 0(x5)
.Lmain:
    addi x1, x0, 64
    addi x2, x0, 0
    addi x3, x0, -1
    addi x4, x0, 1
.Lloop:
    addi x2, x2, 1
    xor x9, x2, x3
    blt x2, x1, .Lloop
    bne x2, x1, .Lfail
    beq x3, x4, .Lfail
    bge x3, x4, .Lfail
    bltu x3, x4, .Lfail
    bgeu x4, x3, .Lfail
    beq x2, x1, .Lequal
    .word 0
.Lequal:
    bne x3, x4, .Lnotequal
    .word 0
.Lnotequal:
    blt x3, x4, .Lsigned
    .word 0
.Lsigned:
    bge x4, x3, .Lunsigned
    .word 0
.Lunsigned:
    bltu x4, x3, .Lunsigned2
    .word 0
.Lunsigned2:
    bgeu x3, x4, .Lcall
    .word 0
.Lcall:
    jal x5, .Lfunction
.Lbase:
    auipc x7, %pcrel_hi(.Ltarget)
    addi x7, x7, %pcrel_lo(.Lbase)
    ori x7, x7, 1
.Ljalr:
    jalr x7, 0(x7)
    .word 0
.Ltarget:
    auipc x8, %pcrel_hi(.Ljalr+4)
    addi x8, x8, %pcrel_lo(.Ltarget)
    bne x7, x8, .Lfail
    addi x10, x0, 0
.rept 12
    addi x10, x10, 1
.endr
    beq x10, x10, .LoldTarget
    jal x0, .LyoungTarget
.rept 6
    .word 0
.endr
.LyoungTarget:
.rept 8
    addi x11, x11, 1
.endr
    jal x0, .Lfail
.LoldTarget:
    addi x12, x0, 12
    bne x10, x12, .Lfail
    addi x10, x0, 42
    jal x0, .Lend
.Lfail:
    .word 0
.Lend:
