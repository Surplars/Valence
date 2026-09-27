.option norvc
.option norelax
.section .text.start,"ax"
.globl _start, boot_trigger, boot_done
_start:
    li sp, 0x80011000
    li s0, 0x80010000
    sd zero, 0(s0)
    sd zero, 8(s0)
    sd zero, 16(s0)
    sd zero, 24(s0)

    li t0, 0x200003ff           # 8 KiB executable ROM.
    csrw pmpaddr0, t0
    li t0, 0x200041ff           # 4 KiB read/write RAM.
    csrw pmpaddr1, t0
    li t0, 0x1b1d
    csrw pmpcfg0, t0

    la t0, boot_trap
    csrw stvec, t0
    li t0, 32
    csrw mideleg, t0
    csrw mie, t0
    li t0, 2
    csrw mcounteren, t0
    li t0, 1
    slli t0, t0, 63
    csrw 0x30a, t0             # menvcfg.STCE
    li t0, 5
    csrw 0x14d, t0             # stimecmp
    la t0, supervisor_entry
    csrw mepc, t0
    li t0, 1
    slli t0, t0, 11
    csrw mstatus, t0           # MPP=S, SIE=0
    mret

supervisor_entry:
    csrsi sstatus, 2
boot_trigger:
    ld t0, 0(s0)
    beqz t0, boot_trigger
    li t1, 1
    bne t0, t1, boot_fail
    ld t0, 8(s0)
    srli t1, t0, 63
    beqz t1, boot_fail
    andi t0, t0, 63
    li t1, 5
    bne t0, t1, boot_fail
    ld t0, 16(s0)
    bne t0, t1, boot_fail      # timer driver stops at time=5
    ld t0, 24(s0)
    andi t0, t0, 32
    bnez t0, boot_fail
    li a0, 42
boot_done:
    j boot_done
boot_fail:
    j boot_fail

.section .text.trap,"ax"
.globl boot_trap
boot_trap:
    csrr t0, scause
    sd t0, 8(s0)
    srli t1, t0, 63
    beqz t1, boot_fail
    andi t1, t0, 63
    li t2, 5
    bne t1, t2, boot_fail
    csrr t3, 0xc01            # time CSR must match the platform mtime
    sd t3, 16(s0)
    li t3, 100
    csrw 0x14d, t3            # move the comparison into the future
    nop
    nop
    nop
    nop
    csrr t4, sip
    sd t4, 24(s0)
    andi t4, t4, 32
    bnez t4, boot_fail
    li t0, 1
    sd t0, 0(s0)
    sret
