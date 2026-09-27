.section .text.init
.option rvc
.globl _start

.equ UART_BASE, 0x10010000

_start:
    li   t0, UART_BASE
    li   t1, 'C'
    sb   t1, 0(t0)

    c.li   s0, 7
    c.addi s0, -2
    li     t1, 5
    bne    s0, t1, fail

    c.li    s1, -1
    c.addiw s1, 2
    li      t1, 1
    bne     s1, t1, fail

    c.lui s2, 1
    li    t1, 0x1000
    bne   s2, t1, fail

    c.mv  s3, s0
    c.add s3, s0
    li    t1, 10
    bne   s3, t1, fail

    c.li   s4, 1
    c.slli s4, 5
    li     t1, 32
    bne    s4, t1, fail

    li     s1, 0x80
    c.srli s1, 2
    li     t1, 0x20
    bne    s1, t1, fail

    li     s1, -32
    c.srai s1, 2
    li     t1, -8
    bne    s1, t1, fail

    li     s1, 0x3f
    c.andi s1, 0x15
    li     t1, 0x15
    bne    s1, t1, fail

    c.li   s0, 7
    c.li   s1, 3
    c.sub  s0, s1
    li     t1, 4
    bne    s0, t1, fail
    c.xor  s0, s1
    li     t1, 7
    bne    s0, t1, fail
    c.or   s0, s1
    li     t1, 7
    bne    s0, t1, fail
    c.and  s0, s1
    li     t1, 3
    bne    s0, t1, fail

    li     s0, -1
    c.li   s1, 1
    c.subw s0, s1
    li     t1, -2
    bne    s0, t1, fail
    c.addw s0, s1
    li     t1, -1
    bne    s0, t1, fail

    la   s0, c_data
    c.ld s1, 0(s0)
    li   t1, 0x0123456789abcdef
    bne  s1, t1, fail

    c.lw s1, 8(s0)
    li   t1, 0xffffffff80000001
    bne  s1, t1, fail

    la   s0, c_store
    c.sd s1, 0(s0)
    ld   t1, 0(s0)
    bne  t1, s1, fail

    li   s1, 0x11223344
    c.sw s1, 8(s0)
    lw   t1, 8(s0)
    bne  t1, s1, fail

    la     sp, stack_area_end
    li     s1, 0x556677
    c.swsp s1, 0(sp)
    c.lwsp s2, 0(sp)
    bne    s2, s1, fail

    li     s1, 0x0123456789abcdef
    c.sdsp s1, 8(sp)
    c.ldsp s2, 8(sp)
    bne    s2, s1, fail

    c.li   s0, 0
    c.beqz s0, 1f
    j      fail
1:
    c.li   s0, 1
    c.bnez s0, 2f
    j      fail
2:
    c.j    3f
    j      fail
3:
    la     t0, jr_target
    c.jr   t0
    j      fail
jr_target:
    c.li   s0, 9
    la     t0, jalr_target
    c.jalr t0
    j      after_jalr
jalr_target:
    c.li   s0, 11
    c.jr   ra
after_jalr:
    li     t1, 11
    bne    s0, t1, fail

pass:
    li   t0, UART_BASE
    li   t1, 'P'
    sb   t1, 0(t0)
    li   a7, 93
    li   a0, 0
1:
    j    1b

fail:
    li   t0, UART_BASE
    li   t1, 'F'
    sb   t1, 0(t0)
    li   a7, 93
    li   a0, 1
1:
    j    1b

.section .data
.align 3
c_data:
    .dword 0x0123456789abcdef
    .word 0x80000001
    .word 0

.align 3
c_store:
    .dword 0
    .dword 0

.align 4
stack_area:
    .space 64
stack_area_end:
