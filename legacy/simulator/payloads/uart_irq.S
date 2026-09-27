.section .text.init
.globl _start

.equ UART_BASE,       0x10010000
.equ UART_RBR_THR,    0x0
.equ UART_IER,        0x1
.equ UART_LCR,        0x3
.equ PLIC_PRIORITY1,  0x0c000004
.equ PLIC_ENABLE_M,   0x0c002000
.equ PLIC_THRESHOLD,  0x0c200000
.equ PLIC_CLAIM,      0x0c200004

_start:
    la   t0, trap_handler
    csrw mtvec, t0

    # UART IRQ is wired into PLIC source 1. Enable received-data interrupt
    # after programming the PLIC so the harness-injected byte can trap.
    li   t0, PLIC_PRIORITY1
    li   t1, 3
    sw   t1, 0(t0)

    li   t0, PLIC_ENABLE_M
    li   t1, 0x2
    sw   t1, 0(t0)

    li   t0, PLIC_THRESHOLD
    sw   zero, 0(t0)

    li   t0, UART_BASE
    li   t1, 0x03        # 8n1, DLAB=0
    sb   t1, UART_LCR(t0)
    li   t1, 0x01        # IER.RDI
    sb   t1, UART_IER(t0)

    li   t0, 0x800       # mie.MEIE
    csrw mie, t0
    li   t0, 0x8         # mstatus.MIE
    csrs mstatus, t0

wait_irq:
    j    wait_irq

.balign 4
trap_handler:
    csrr t0, mcause
    li   t1, 1
    slli t1, t1, 63
    ori  t1, t1, 11
    bne  t0, t1, fail

    li   t0, PLIC_CLAIM
    lw   t1, 0(t0)
    li   t2, 1
    bne  t1, t2, fail

    li   t3, UART_BASE
    lbu  t4, UART_RBR_THR(t3)
    li   t5, 'Z'
    bne  t4, t5, fail

    li   t4, 'U'
    sb   t4, UART_RBR_THR(t3)

    # Reading RBR clears the UART level before completion, so the PLIC gateway
    # should not redeliver this source after the complete write.
    sw   t1, 0(t0)

    li   t4, 'P'
    sb   t4, UART_RBR_THR(t3)
    li   a7, 93
    li   a0, 0
pass_spin:
    j    pass_spin

fail:
    li   t0, UART_BASE
    li   t1, 'F'
    sb   t1, UART_RBR_THR(t0)
    li   a7, 93
    li   a0, 1
fail_spin:
    j    fail_spin
