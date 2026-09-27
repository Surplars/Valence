.section .text.init
.globl _start

_start:
    mv   s0, a0
    mv   s1, a1
    mv   s2, a2

    la   a0, banner
    jal  ra, puts

    la   a0, a0_msg
    jal  ra, puts
    mv   a0, s0
    jal  ra, puthex64
    li   a0, '\n'
    jal  ra, putc

    la   a0, a1_msg
    jal  ra, puts
    mv   a0, s1
    jal  ra, puthex64
    li   a0, '\n'
    jal  ra, putc

    la   a0, a2_msg
    jal  ra, puts
    mv   a0, s2
    jal  ra, puthex64
    li   a0, '\n'
    jal  ra, putc

    li   a0, 0
    li   a7, 93
1:
    j    1b

puts:
    mv   t4, ra
    mv   t3, a0
2:
    lbu  a0, 0(t3)
    beqz a0, 3f
    jal  ra, putc
    addi t3, t3, 1
    j    2b
3:
    jr   t4

puthex64:
    mv   t1, ra
    mv   t3, a0
    li   a0, '0'
    jal  ra, putc
    li   a0, 'x'
    jal  ra, putc
    li   t4, 16
4:
    srli t5, t3, 60
    li   t6, 10
    bltu t5, t6, 5f
    addi a0, t5, 87
    j    6f
5:
    addi a0, t5, 48
6:
    jal  ra, putc
    slli t3, t3, 4
    addi t4, t4, -1
    bnez t4, 4b
    jr   t1

putc:
    li   t6, 0x10010000
    sb   a0, 0(t6)
    ret

.section .rodata
banner:
    .asciz "IonSoC firmware probe\n"
a0_msg:
    .asciz "a0="
a1_msg:
    .asciz "a1="
a2_msg:
    .asciz "a2="
