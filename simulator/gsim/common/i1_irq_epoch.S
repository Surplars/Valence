# Dedicated real-I1 interrupt/epoch guest. No synthetic IRQ or state injection.
.option norvc
.option norelax
.section .text.start,"ax"
.globl _start, configured, loop_previous, loop_previous_compare, loop_increment, loop_store, loop_load
.globl loop_compare, loop_pending, loop_jump, guest_fail
.globl irq_handler, irq_epc, irq_status, irq_claim, irq_increment, irq_store, irq_load, irq_compare, irq_mret
_start:
    li s0, 0x80200000
    li s1, 0x0c000000
    li t0, 6
    sw t0, 4(s1)
    sw t0, 8(s1)
    sw t0, 12(s1)
    li s2, 0x0c003000
    li t0, 11
    sw t0, 4(s2)
    li t0, 12
    sw t0, 8(s2)
    li t0, 13
    sw t0, 12(s2)
    li s3, 0x0c002000
    li t0, 1
    sw t0, -292(s3)
    li t0, 2
    sw t0, -292(s3)
    li t0, 3
    sw t0, -292(s3)
    li t0, 0x100
    sw t0, 0(s1)
    li t0, 0xc0
    csrw 0x350, t0
    li t0, 0x3800
    csrw 0x351, t0
    li t0, 0x72
    csrw 0x350, t0
    csrw 0x351, zero
    li t0, 0x70
    csrw 0x350, t0
    li t0, 1
    csrw 0x351, t0
    la t0, irq_handler
    csrw 0x305, t0
    li s4, 0
    li s8, 0
    sd s4, 0(s0)
    sd s8, 8(s0)
    li t0, 0x800
    csrw 0x304, t0
    csrsi 0x300, 8
configured:
loop_previous:
    ld s7, 0(s0)
loop_previous_compare:
    bne s4, s7, guest_fail
loop_increment:
    addi s4, s4, 1
loop_store:
    sd s4, 0(s0)
loop_load:
    ld s5, 0(s0)
loop_compare:
    bne s4, s5, guest_fail
loop_pending:
    csrr s6, 0x300
loop_jump:
    j loop_previous
guest_fail:
    ebreak
    j guest_fail
irq_handler:
    csrr s9, 0x342
irq_epc:
    csrr s10, 0x341
irq_status:
    csrr s11, 0x300
irq_claim:
    csrrw t3, 0x35c, zero
irq_increment:
    addi s8, s8, 1
irq_store:
    sd s8, 8(s0)
irq_load:
    ld t4, 8(s0)
irq_compare:
    bne s8, t4, guest_fail
    # Keep a real linear handler window for independently clocked prepare.
    .rept 48
    nop
    .endr
irq_mret:
    mret
