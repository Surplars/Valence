# Native I1 independent-clock boot fixture. Derived from the public soc_smoke.S.
# Same reset/ROM/RAM/UART/IRQ/fault contract, plus real LR/SC clear coverage.
.section .text.start
.globl _start
_start:
    la t0, handler
    csrw mtvec, t0
    li s0, 0x80210000
    sd zero, 0(s0)
    sd zero, 8(s0)
    sd zero, 16(s0)
    sd zero, 24(s0)
    sd zero, 32(s0)
    sd zero, 40(s0)
    sd zero, 48(s0)
    sd zero, 56(s0)
    sd zero, 64(s0)
    # Interleaved read/write DDR byte lanes, cold line fills, dependent forwarding.
    li t0, 0x80211000
    li t1, 128
    li t2, 0x123456789abcdef0
1:  sd t2, 0(t0)
    ld t3, 0(t0)
    bne t2, t3, fail
    addi t0, t0, 8
    addi t2, t2, 1
    addi t1, t1, -1
    bnez t1, 1b
    li t0, 0x1001ffff8
    li t1, 0x5a
    sd t1, 0(t0)
    ld t2, 0(t0)
    bne t1, t2, fail
    li t1, 0x7c
    sb t1, 3(t0)
    lbu t2, 3(t0)
    bne t1, t2, fail
    # Timer high/low half accesses retain byte offset and right-justified MMIO.
    li t0, 0x02004000
    li t1, 0x1122334455667788
    sd t1, 0(t0)
    lwu t2, 4(t0)
    li t3, 0x11223344
    bne t2, t3, fail
    li t3, 0x76543210
    sw t3, 4(t0)
    ld t2, 0(t0)
    li t3, 0x7654321055667788
    bne t2, t3, fail
    li t1, -1
    sd t1, 0(t0)
    # MSIP + precise MRET, then MTIP.
    li t0, 0x888
    csrw mie, t0
    csrsi mstatus, 8
    li t0, 0x02000000
    li t1, 1
    sw t1, 0(t0)
    li t4, 20000
2:  ld t1, 0(s0)
    bnez t1, 3f
    addi t4, t4, -1
    bnez t4, 2b
    j fail
3:  li t0, 0x0200bff8
    ld t1, 0(t0)
    addi t1, t1, 200
    li t0, 0x02004000
    sd t1, 0(t0)
    li t4, 20000
4:  ld t1, 8(s0)
    bnez t1, 5f
    addi t4, t4, -1
    bnez t4, 4b
    j fail
5:  # Standard PLIC M-context, UART source 3. Timer/MSIP do not go through PLIC.
    li t0, 0x0c00000c
    li t1, 1
    sw t1, 0(t0)
    li t0, 0x0c002000
    li t1, 8
    sw t1, 0(t0)
    li t0, 0x0c200000
    sw zero, 0(t0)
    # Reused 16550 loopback RX IRQ, no fake UART response supplied by host.
    li t0, 0x10000000
    li t1, 7
    sb t1, 2(t0)
    li t1, 16
    sb t1, 4(t0)
    li t1, 1
    sb t1, 1(t0)
    li t1, 0x4b
    sb t1, 0(t0)
    li t4, 30000
6:  ld t1, 16(s0)
    bnez t1, 7f
    addi t4, t4, -1
    bnez t4, 6b
    j fail
7:  csrci mstatus, 8
    # Exact denied MMIO load fault; handler advances mepc once.
    li t0, 0x10020000
fault_mmio:
    ld t1, 0(t0)
    # Last-beat AXI read error must invalidate the whole fill; B error is a precise store fault.
    li t0, 0x80218000
fault_axi_read:
    ld t1, 0(t0)
    # AMO uses the uncached atomic path: its read at +8 succeeds,
    # and the AW/B transaction at +8 is deliberately denied by the host.
    addi t0, t0, 8
fault_axi_write:
    amoswap.d zero, t1, (t0)
    ld t1, 24(s0)
    li t2, 2
    bne t1, t2, fail
    li t2, 1
    ld t1, 32(s0)
    bne t1, t2, fail
    ld t1, 0(s0)
    bne t1, t2, fail
    ld t1, 8(s0)
    bne t1, t2, fail
    ld t1, 16(s0)
    bne t1, t2, fail
    # Real success first: all-SC-fail behavior must not pass.
    j atomic_begin
    .balign 64
atomic_begin:
    li t0, 0x80214000
    li t2, 0x55aa
    li t4, 256
atomic_retry:
    lr.d t1, (t0)
    sc.d t3, t2, (t0)
    beqz t3, atomic_success
    addi t4, t4, -1
    bnez t4, atomic_retry
    j fail
atomic_success:
    ld t1, 0(t0)
    bne t1, t2, fail
    sd t1, 48(s0)
    # A precise M-mode ECALL and MRET must clear the LR reservation.
    lr.d t1, (t0)
fault_ecall:
    ecall
    li t2, 0x66bb
    sc.d t3, t2, (t0)
    beqz t3, fail
    ld t1, 0(t0)
    li t2, 0x55aa
    bne t1, t2, fail
    li t1, 1
    sd t1, 56(s0)
    # An ordinary cached store also clears across the ordered D event path.
    lr.d t1, (t0)
    sd zero, 72(s0)
    sc.d t3, t2, (t0)
    beqz t3, fail
    li t1, 3
    sd t1, 56(s0)
    ld t1, 40(s0)
    li t2, 1
    bne t1, t2, fail
    csrr t1, time
    beqz t1, fail
    sd t1, 64(s0)
    li a0, 0
success_break:
    ebreak
success_park:
    j success_park
fail:
    li a0, 1
    ebreak
.align 2
handler:
    # Handler uses only reserved s7..s11; no clobber of interrupted test operands.
    csrr s7, mcause
    li s8, 3
    beq s7, s8, success_park
    li s8, 0x8000000000000003
    beq s7, s8, software
    li s8, 0x8000000000000007
    beq s7, s8, timer
    li s8, 0x800000000000000b
    beq s7, s8, uart
    li s8, 11
    beq s7, s8, ecall_clear
    li s8, 5
    beq s7, s8, load_error
    li s8, 7
    bne s7, s8, fail
    csrr s8, mtval
    li s9, 0x80218008
    bne s8, s9, fail
    li s10, 32
    j skip_fault
ecall_clear:
    li s10, 40
    j skip_fault
load_error:
    csrr s8, mtval
    li s9, 0x10020000
    beq s8, s9, load_count
    li s9, 0x80218000
    bne s8, s9, fail
load_count:
    li s10, 24
skip_fault:
    csrr s8, mepc
    addi s8, s8, 4
    csrw mepc, s8
    j counted
software:
    li s8, 0x02000000
    sw zero, 0(s8)
    li s10, 0
    j counted
timer:
    li s8, 0x02004000
    li s9, -1
    sd s9, 0(s8)
    li s10, 8
    j counted
uart:
    li s8, 0x0c200004
    lwu s9, 0(s8)
    li s11, 3
    bne s9, s11, fail
    li s8, 0x10000000
    lbu s9, 0(s8)
    li s11, 0x4b
    bne s9, s11, fail
    sb zero, 1(s8)
    li s8, 0x0c200004
    li s9, 3
    sw s9, 0(s8)
    li s10, 16
counted:
    add s8, s0, s10
    ld s9, 0(s8)
    addi s9, s9, 1
    sd s9, 0(s8)
    mret
