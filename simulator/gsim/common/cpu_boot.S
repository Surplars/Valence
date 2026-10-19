# Common-platform bounded CPU boot fixture. This is test firmware, not the TUI ROM.
# One identical image executes on full I1 and public Selected A1, without host CPU state injection.
.option norvc
.option norelax
.section .text.start,"ax"
.globl _start, boot_fail, boot_done, fence_first, fence_modified, fence_final
_start:
    la t0, trap_handler
    csrw mtvec, t0
    li s10, 0
    li s11, 0
    li s0, 0x80210000
    # Real managed 16550 endpoint, existing 50 MHz / 460800 default divisor.
    li s1, 0x10000000
    sb zero, 1(s1)
    li t0, 3
    sb t0, 3(s1)
    li t0, 7
    sb t0, 2(s1)
    li t0, 0x5a
    sb t0, 7(s1)
    lbu t1, 7(s1)
    bne t0, t1, boot_fail
    la s2, banner
    li s3, 8
uart_next:
    lbu t0, 5(s1)
    andi t0, t0, 0x20
    beqz t0, uart_next
    lbu t0, 0(s2)
    sb t0, 0(s1)
    addi s2, s2, 1
    addi s3, s3, -1
    bnez s3, uart_next
    # Dirty full lines, dependent forwarding, and untouched DDR line-fill reads.
    li t0, 0x80211000
    li t1, 32
    li t2, 0x123456789abcdef0
memory_loop:
    sd t2, 0(t0)
    ld t3, 0(t0)
    bne t2, t3, boot_fail
    addi t0, t0, 8
    addi t2, t2, 1
    addi t1, t1, -1
    bnez t1, memory_loop
    li t0, 0x80218000
    ld t1, 0(t0)
    bnez t1, boot_fail
    li t1, 0x7c
    sb t1, 3(t0)
    lbu t2, 3(t0)
    bne t1, t2, boot_fail
    # Timer high-half byte offset and right-justified MMIO data.
    li t0, 0x02004000
    li t1, 0x1122334455667788
    sd t1, 0(t0)
    lwu t2, 4(t0)
    li t3, 0x11223344
    bne t2, t3, boot_fail
    li t3, 0x76543210
    sw t3, 4(t0)
    ld t2, 0(t0)
    li t3, 0x7654321055667788
    bne t2, t3, boot_fail
    li t1, -1
    sd t1, 0(t0)
    # IMSIC delivery and identity 7 enable. GENMSI uses the real APLIC MSI channel.
    li t0, 0xc0
    csrw 0x350, t0
    li t0, 128
    csrw 0x351, t0
    li t0, 0x70
    csrw 0x350, t0
    csrwi 0x351, 1
    li t0, 0x880
    csrw mie, t0
    csrsi mstatus, 8
    li t0, 0x0200bff8
    ld t1, 0(t0)
    addi t1, t1, 1000
    li t0, 0x02004000
    sd t1, 0(t0)
    li t2, 20000
wait_timer:
    bnez s10, timer_done
    addi t2, t2, -1
    bnez t2, wait_timer
    j boot_fail
timer_done:
    li t0, 0x0c003000
    li t1, 7
    sw t1, 0(t0)
    li t2, 20000
wait_msi:
    bnez s11, msi_done
    addi t2, t2, -1
    bnez t2, wait_msi
    j boot_fail
msi_done:
    csrci mstatus, 8
    li t0, 1
    bne s10, t0, boot_fail
    bne s11, t0, boot_fail
    sd s10, 0(s0)
    sd s11, 8(s0)
    # Execute original DDR code so both instruction caches contain the old instruction.
    li s2, 0x80204000
    li t0, 0x0000806700900513
    sd t0, 0(s2)
fence_first:
    fence.i
    jalr ra, 0(s2)
    li t0, 9
    bne a0, t0, boot_fail
    # Dirty data store must become visible through real writeback, Home drain,
    # matching maintenance epoch, and instruction invalidation before this fetch.
    li t0, 0x02a00513
    sw t0, 0(s2)
fence_modified:
    fence.i
    jalr ra, 0(s2)
    li t0, 42
    bne a0, t0, boot_fail
    sd a0, 16(s0)
    csrr t0, time
    beqz t0, boot_fail
    sd t0, 24(s0)
fence_final:
    fence.i
boot_done:
    j boot_done
boot_fail:
    j boot_fail
.balign 4
trap_handler:
    # s7..s9 are reserved scratch registers; interrupted main operands are intact.
    csrr s7, mcause
    li s8, 0x8000000000000007
    beq s7, s8, trap_timer
    li s8, 0x800000000000000b
    bne s7, s8, boot_fail
    csrrw s7, 0x35c, zero
    li s8, 0x70007
    bne s7, s8, boot_fail
    addi s11, s11, 1
    mret
trap_timer:
    li s8, 0x02004000
    li s9, -1
    sd s9, 0(s8)
    addi s10, s10, 1
    mret
banner:
    .ascii "COMMON\r\n"
