.option norvc
.option norelax
.section .text.start,"ax"
.globl _start, boot_trigger, boot_done
_start:
    li sp, 0x80011000
    li s0, 0x80010000
    mv t0, s0
1:  sd zero, 0(t0)
    addi t0, t0, 8
    bltu t0, sp, 1b
    la t0, boot_trap
    csrw mtvec, t0
    call boot_workload
    sd a0, 8(s0)
    li s1, 0x02004000
    li s2, 0x0200bff8
    sd zero, 0(s2)
    ld t0, 0(s2)
    bnez t0, boot_fail
    lwu t0, 4(s2)
    bnez t0, boot_fail
    li t0, -1
    sw t0, 0(s1)
    sw zero, 4(s1)
    li t0, 100
    sw t0, 0(s1)
    ld t1, 0(s1)
    bne t0, t1, boot_fail
    # Unsupported access sizes and an unimplemented register must fault precisely.
    lb t0, 0(s2)
    sb zero, 0(s2)
    ld t0, 8(s1)
    li t0, 128
    csrw mie, t0
    csrsi mstatus, 8
boot_trigger:
    ld t0, 0(s0)
    li t1, 2
    bne t0, t1, boot_trigger
    ld a0, 8(s0)
    li t1, 376
    bne a0, t1, boot_fail
    ld t0, 0(s1)
    li t1, -1
    bne t0, t1, boot_fail
    csrr t0, mip
    andi t0, t0, 128
    bnez t0, boot_fail
boot_done:
    j boot_done
boot_fail:
    j boot_fail
.section .text.trap,"ax"
.globl boot_trap
boot_trap:
    csrr s10, mcause
    bltz s10, 2f
    csrr t3, mepc
    addi t3, t3, 4
    csrw mepc, t3
    mret
2:  andi t3, s10, 15
    li t4, 7
    bne t3, t4, boot_fail
    csrr t3, mip
    andi t3, t3, 128
    beqz t3, boot_fail
    ld t4, 0(s0)
    addi t4, t4, 1
    sd t4, 0(s0)
    li t3, 2
    beq t4, t3, 3f
    li t3, 200
    sd t3, 0(s1)
    mret
3:  li t3, -1
    sd t3, 0(s1)
    mret
