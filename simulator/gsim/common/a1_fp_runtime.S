# A1 implements WFI as an immediate hint, not a sleeping architectural owner.
# Actual APLIC -> IMSIC and mtime -> MTIP are enabled; no synthetic IRQ input.
.option norvc
.option norelax
.section .text.start,"ax"
.globl fp_dcheck, fp_scheck, _start, idle_wfi, irq_timer, irq_external, irq_claim, irq_mret, guest_fail
_start:
    li s8, 0
    li s9, 0
    li s0, 0x02004000
    li t0, 1
    sd t0, 0(s0)                # mtimecmp=1; test clock tick remains disabled.
    li s1, 0x0c000000
    li t0, 6
    sw t0, 4(s1)
    li s2, 0x0c003000
    li t0, 11
    sw t0, 4(s2)
    li s3, 0x0c002000
    li t0, 1
    sw t0, -292(s3)
    li t0, 0x100
    sw t0, 0(s1)
    li t0, 0xc0
    csrw 0x350, t0
    li t0, 0x800
    csrw 0x351, t0
    li t0, 0x70
    csrw 0x350, t0
    li t0, 1
    csrw 0x351, t0
    la t0, irq_handler
    csrw 0x305, t0
    li t0, 0x880
    csrw 0x304, t0
    li t0, 0x6000
    csrs 0x300, t0               # Explicit FS=Dirty for F/D instructions.
    li t0, 0x4018000000000000    # Binary64 6.0.
    fmv.d.x f0, t0
    li t0, 0x4000000000000000    # Binary64 2.0.
    fmv.d.x f1, t0
    li t0, 0x40c00000           # Binary32 6.0.
    fmv.w.x f3, t0
    li t0, 0x40000000           # Binary32 2.0.
    fmv.w.x f4, t0
    csrsi 0x300, 8
idle_wfi:
    wfi
    fdiv.d f2, f0, f1
fp_dcheck:
    fmv.x.d s10, f2
    li t2, 0x4008000000000000
    bne s10, t2, guest_fail
    fdiv.s f5, f3, f4
fp_scheck:
    fmv.x.w s11, f5
    li t2, 0x40400000
    bne s11, t2, guest_fail
    j idle_wfi
irq_handler:
    csrr t0, 0x342
    li t1, 0x8000000000000007
    beq t0, t1, timer_handler
    li t1, 0x800000000000000b
    bne t0, t1, guest_fail
irq_claim:
    csrrw t3, 0x35c, zero
irq_external:
    addi s9, s9, 1
    j irq_mret
timer_handler:
    li t0, -1
    sd t0, 0(s0)               # Deassert MTIP through the actual timer MMIO.
irq_timer:
    addi s8, s8, 1
irq_mret:
    mret
guest_fail:
    ebreak
    j guest_fail
