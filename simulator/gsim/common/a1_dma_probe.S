# Real common memory-copy DMA and real APLIC source4 -> IMSIC identity14.
# Dirty source/destination/guard lines must remain coherent across runtime park.
.option norvc
.option norelax
.section .text.start,"ax"
.globl _start, dma_start, dma_value, dma_guard, irq_claim, irq_count, irq_mret, guest_done, guest_fail
_start:
    li s8, 0
    li s0, 0x80200000
    li s1, 0x80200100
    li s2, 0x10001000
    li t0, 0x1122334455667788
    sd t0, 0(s0)
    li t0, 0xdeadbeef12345678
    sd t0, 0(s1)
    li t0, 0xa5a5a5a5b6b6b6b6
    sd t0, 8(s1)
    li s3, 0x0c000000
    li t0, 6
    sw t0, 16(s3)
    li s4, 0x0c003000
    li t0, 14
    sw t0, 16(s4)
    li s5, 0x0c002000
    li t0, 4
    sw t0, -292(s5)
    li t0, 0x100
    sw t0, 0(s3)
    li t0, 0xc0
    csrw 0x350, t0
    li t0, 0x4000
    csrw 0x351, t0
    li t0, 0x70
    csrw 0x350, t0
    li t0, 1
    csrw 0x351, t0
    la t0, irq_handler
    csrw 0x305, t0
    li t0, 0x800
    csrw 0x304, t0
    csrsi 0x300, 8
    sd s0, 0(s2)
    sd s1, 8(s2)
    li t0, 8
    sd t0, 16(s2)
    li t0, 5                   # Start plus interrupt enable.
dma_start:
    sd t0, 24(s2)
wait_irq:
    beqz s8, wait_irq
dma_value:
    ld s5, 0(s1)
    li t0, 0x1122334455667788
    bne s5, t0, guest_fail
dma_guard:
    ld s6, 8(s1)
    li t0, 0xa5a5a5a5b6b6b6b6
    bne s6, t0, guest_fail
guest_done:
    j guest_done
irq_handler:
    csrr t0, 0x342
    li t1, 0x800000000000000b
    bne t0, t1, guest_fail
irq_claim:
    csrrw t3, 0x35c, zero
    li t0, 6                   # Clear DMA done; no second start.
    sd t0, 24(s2)
irq_count:
    addi s8, s8, 1
irq_mret:
    mret
guest_fail:
    ebreak
    j guest_fail
