.option norvc
.option norelax
.section .text
.global _start
_start:
    addi x1, x0, -1
    lui x2, 0x80000
    auipc x3, 0xfffff
    addiw x4, x2, -1
    slli x5, x1, 63
    srli x6, x5, 63
    srai x7, x5, 63
    add x8, x6, x7
    subw x9, x4, x2
    slt x10, x1, x0
    sltu x11, x1, x0
    addi x12, x0, 31
    sllw x13, x6, x12
    srlw x14, x13, x12
    sraw x15, x13, x12
    addi x16, x0, 42
.rept 64
    add x17, x16, x4
    xor x18, x17, x3
    slli x19, x18, 7
    srli x20, x18, 57
    or x16, x19, x20
    addw x4, x4, x9
.endr
    andi x21, x16, 255
    xori x22, x21, -1
    ori x23, x22, 42
    slti x24, x23, 0
    sltiu x25, x24, -1
    slliw x26, x25, 31
    srliw x27, x26, 31
    sraiw x28, x26, 31
    add x0, x28, x27
    addi x10, x0, 42
