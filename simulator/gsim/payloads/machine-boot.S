#ifdef TIMER_BOOT
#include "machine-timer.S"
#else
#ifdef DMA_COPY
#define SOURCE_ID 4
#define SOURCE_CONFIG 16
#define SOURCE_TARGET 0x0c003010
#define SOURCE_ENABLE 16
#else
#define SOURCE_ID 3
#define SOURCE_CONFIG 12
#define SOURCE_TARGET 0x0c00300c
#define SOURCE_ENABLE 8
#endif
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
#ifdef UART_CONSOLE
    li s1, 0x10000000
    li t0, 0x83
    sb t0, 3(s1)
    li t0, 1
    sb t0, 0(s1)
    sb zero, 1(s1)
    li t0, 3
    sb t0, 3(s1)
    li t0, 0x5a
    sb t0, 7(s1)
    lbu t1, 7(s1)
    bne t0, t1, boot_fail
    li t0, 'O'
    sb t0, 0(s1)
    li t0, 'K'
    sb t0, 0(s1)
    li t0, 10
    sb t0, 0(s1)
    li t0, 1
    sb t0, 1(s1)
#endif
#ifdef DMA_COPY
    li s1, 0x10001000
    addi t0, s0, 256
    li t1, 1
    li t2, 129
3:  sd t1, 0(t0)
    addi t0, t0, 8
    addi t1, t1, 1
    bne t1, t2, 3b
    fence iorw, iorw
    addi t0, s0, 256
    sd t0, 0(s1)
    li t0, 0x80010800
    sd t0, 8(s1)
    li t0, 1024
    sd t0, 16(s1)
#ifdef COHERENT_DMA_PROBE
    # Hold clean destination lines in the CPU L1 before DMA overwrites them.
    li t0, 0x80010800
    li t1, 16
6:  ld t2, 0(t0)
    bnez t2, boot_fail
    addi t0, t0, 64
    addi t1, t1, -1
    bnez t1, 6b
#endif
#endif
#ifdef ATOMIC_BOOT
    # Normal store -> AMO -> normal load, W high lane and x0 destination.
    addi s2, s0, 64
    li t0, -1
    sd t0, 0(s2)
#ifdef COHERENT_ATOMIC_PROBE
    ld t2, 0(s2)
    bne t2, t0, boot_fail
#endif
    li t1, 3
    amoadd.d.aqrl t2, t1, (s2)
    bne t2, t0, boot_fail
    ld t2, 0(s2)
    li t0, 2
    bne t2, t0, boot_fail
    addi s3, s2, 4
    amoswap.w.aq zero, t1, (s3)
    lr.w.aq t2, (s3)
    sc.w.rl t2, t1, (s3)
    bnez t2, boot_fail
    # Three precise traps return past the fault; external MMIO must not be touched.
    addi s3, s2, 1
    lr.d t2, (s3)
    amoadd.d t2, t1, (s3)
    li s3, 0x10000000
    amoswap.d t2, t1, (s3)
#endif
    li a2, 0x0c000000
#if defined(UART_CONSOLE) || defined(DMA_COPY)
    li t0, 6
#else
    li t0, 4
#endif
    sw t0, SOURCE_CONFIG(a2)
    li t1, SOURCE_TARGET
    li t0, SOURCE_ID
    sw t0, 0(t1)
    li t1, 0x0c001edc
    sw t0, 0(t1)
    li t0, 256
    sw t0, 0(a2)
    lw t0, 0(a2)
    lwu t1, 0(a2)
    lw t2, SOURCE_CONFIG(a2)
    li t1, SOURCE_TARGET
    lw t0, 0(t1)
    li t1, 0x0c001e00
    lw t0, 0(t1)
    lb t0, 0(a2)
    ld t0, 0(a2)
    sb zero, 0(a2)
    li t0, 0xc0
    csrw 0x350, t0
    li t0, SOURCE_ENABLE
    csrw 0x351, t0
    li t0, 0x70
    csrw 0x350, t0
    csrwi 0x351, 1
    li t0, 2048
    csrw mie, t0
    csrsi mstatus, 8
#ifdef ATOMIC_BOOT
    li s3, 0x80010800
    lr.d s4, (s3)
#endif
#ifdef DMA_COPY
    li t0, 7
    sd t0, 24(s1)
    # Independent CPU memory traffic during DMA; source/destination are disjoint.
    li t0, 64
4:  sd t0, 32(s0)
#ifdef ATOMIC_BOOT
    addi s2, s0, 32
    amoadd.d.aqrl t1, zero, (s2)
    bne t0, t1, boot_fail
#endif
    ld t1, 32(s0)
    bne t0, t1, boot_fail
    addi t0, t0, -1
    bnez t0, 4b
#endif
boot_trigger:
    ld t0, 0(s0)
    beqz t0, boot_trigger
    li t1, 1
    bne t0, t1, boot_fail
    ld a0, 8(s0)
    li t1, 376
    bne a0, t1, boot_fail
#ifdef UART_CONSOLE
    ld t0, 16(s0)
    li t1, 0x5a
    bne t0, t1, boot_fail
#endif
#ifdef DMA_COPY
    fence iorw, iorw
    li t0, 0x80010800
    li t1, 1
    li t2, 129
5:  ld t5, 0(t0)
    bne t5, t1, boot_fail
    addi t0, t0, 8
    addi t1, t1, 1
    bne t1, t2, 5b
#endif
#ifdef ATOMIC_BOOT
    li s3, 0x80010800
    sc.d.rl t0, zero, (s3)
    li t1, 1
    bne t0, t1, boot_fail
    ld t0, 0(s3)
    bne t0, t1, boot_fail
#endif
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
2:  lw t6, 0(a2)
    sw zero, 0(a2)
#ifdef UART_CONSOLE
    lbu t4, 2(s1)
    li t3, 4
    bne t4, t3, boot_fail
    lbu t4, 0(s1)
    sd t4, 16(s0)
#endif
#ifdef DMA_COPY
    ld t4, 32(s1)
    li t3, 2
    bne t4, t3, boot_fail
    li t3, 6
    sd t3, 24(s1)
#endif
    csrrw t5, 0x35c, zero
    li t3, 0x80010000
    ld t4, 0(t3)
    addi t4, t4, 1
    sd t4, 0(t3)
    mret

#endif
