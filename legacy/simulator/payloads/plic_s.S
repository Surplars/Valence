.section .text.init
.globl _start

.equ UART_BASE,       0x10010000
.equ PLIC_PRIORITY2,  0x0c000008
.equ PLIC_ENABLE_S,   0x0c002080
.equ PLIC_THRESHOLD_S,0x0c201000
.equ PLIC_CLAIM_S,    0x0c201004

_start:
    la   t0, fail
    csrw mtvec, t0
    la   t0, supervisor_trap
    csrw stvec, t0

    # No-MMU supervisor smoke tests need M-mode firmware to open PMP before
    # mret. This single NAPOT entry grants S-mode access to the simulated
    # physical address space.
    li   t0, -1
    csrw pmpaddr0, t0
    li   t0, 0x1f        # R/W/X, NAPOT
    csrw pmpcfg0, t0

    li   t0, PLIC_PRIORITY2
    li   t1, 3
    sw   t1, 0(t0)

    li   t0, PLIC_ENABLE_S
    li   t1, 0x4
    sw   t1, 0(t0)

    li   t0, PLIC_THRESHOLD_S
    sw   zero, 0(t0)

    li   t0, 0x200        # delegate SEIP
    csrw mideleg, t0
    csrw sie, t0

    la   t0, supervisor_entry
    csrw mepc, t0
    li   t0, 0x800        # mstatus.MPP=S
    csrs mstatus, t0
    mret

supervisor_entry:
    li   t0, UART_BASE
    li   t1, 'S'
    sb   t1, 0(t0)
    li   t0, 0x2          # sstatus.SIE
    csrs sstatus, t0
wait_external:
    j    wait_external

.balign 4
supervisor_trap:
    csrr t0, scause
    li   t1, 1
    slli t1, t1, 63
    ori  t1, t1, 9
    bne  t0, t1, fail

    li   t0, PLIC_CLAIM_S
    lw   t1, 0(t0)
    li   t2, 2
    bne  t1, t2, fail

    li   t3, UART_BASE
    li   t4, 'I'
    sb   t4, 0(t3)

    li   t4, 'P'
    sb   t4, 0(t3)
    li   a7, 93
    li   a0, 0
pass_spin:
    j    pass_spin

.balign 4
fail:
    li   t0, UART_BASE
    li   t1, 'F'
    sb   t1, 0(t0)
    li   a7, 93
    li   a0, 1
fail_spin:
    j    fail_spin
