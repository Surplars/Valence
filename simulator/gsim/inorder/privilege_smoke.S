.option norvc
.option norelax
.section .text.start
.globl _start
_start:
    la t0, machine_handler
    csrw mtvec, t0
    li s10, 0x80210000
    li t0, 64
    mv t1, s10
1:  sd zero, 0(t1)
    addi t1, t1, 8
    addi t0, t0, -1
    bnez t0, 1b
    # Zero three page tables using the real CPU, not host-injected translation responses.
    li t0, 0x80220000
    li t1, 1536
2:  sd zero, 0(t0)
    addi t0, t0, 8
    addi t1, t1, -1
    bnez t1, 2b
    li t0, 0x80220000
    li t1, 0xcf
    sd t1, 0(t0)               # S identity MMIO, 1GiB leaf
    li t1, 0x20088401          # root[1] -> L1=80221000
    sd t1, 8(t0)
    li t1, 0x200000cf          # root[2] -> identity 80000000, 1GiB
    sd t1, 16(t0)
    li t0, 0x80221000
    li t1, 0x20088801          # L1[0] -> L0=80222000
    sd t1, 0(t0)
    li t0, 0x80222000
    li t1, 0x200808db          # U RX code=80202000
    sd t1, 0(t0)
    li t1, 0x2008c0d7          # U RW data=80230000
    sd t1, 8(t0)
    li t1, 0x2008c4c7          # S-only data=80231000
    sd t1, 16(t0)
    li t1, 0x2008c8d9          # U execute-only=80232000
    sd t1, 24(t0)
    li t1, 0x2008cc17          # U RW A/D clear=80233000
    sd t1, 32(t0)
    li t1, 0x200900d7          # U RW outside PMP=80240000
    sd t1, 40(t0)
    li t0, 0x80230000
    li t1, 0x112233
    sd t1, 0(t0)
    li t0, 0x80232000
    li t1, 0x4567
    sd t1, 0(t0)
    li t0, 0x80233000
    li t1, 0xbeef
    sd t1, 0(t0)
    li t0, 0x20090000          # PMP TOR end=80240000, R/W/X
    csrw pmpaddr0, t0
    li t0, 15
    csrw pmpcfg0, t0
    li t0, 7
    csrw mcounteren, t0
    csrw scounteren, t0
    li t0, 0xb1ff             # Delegate exceptions except S/M ECALL
    csrw medeleg, t0
    li t0, 0x222
    csrw mideleg, t0
    li t0, 0x8000000000080220
    csrw satp, t0
    sfence.vma
    la t0, supervisor_start
    csrw mepc, t0
    li t0, 0x800
    csrw mstatus, t0
    mret

.align 2
machine_handler:
    csrr t4, mcause
    li t5, 9
    bne t4, t5, fail
    li t5, 2
    beq a7, t5, finish
    ld t5, 240(s10)
    addi t5, t5, 1
    sd t5, 240(s10)
    li t5, 3
    beq a7, t5, machine_mprv
    li t5, 1
    bne a7, t5, fail
    li t5, 32
    csrs mip, t5               # SBI-style supervisor timer injection, no Sstc
    j machine_return
machine_mprv:
    li t5, 0x20000
    csrs mstatus, t5
    li t5, 0x40001000
    ld t5, 0(t5)               # MPRV+MPP=S, SUM inherited, data uses Sv39
    li t6, 0xbeef
    bne t5, t6, fail
    li t5, 0x20000
    csrc mstatus, t5
machine_return:
    csrr t5, mepc
    addi t5, t5, 4
    csrw mepc, t5
    mret
finish:
    li t5, 0x564c100
    sd t5, 248(s10)
    li a0, 0
    ebreak
fail:
    li a0, 1
    ebreak

.section .text.supervisor
.align 12
supervisor_start:
    la t0, supervisor_handler
    csrw stvec, t0
    csrr t0, mstatus            # Illegal S read of M CSR, delegated
    li t0, 0x40001000
    ld t1, 0(t0)               # S SUM=0 must reject U data
    li t1, 0x40000
    csrs sstatus, t1
    ld t1, 0(t0)
    li t2, 0x112233
    bne t1, t2, fail
    li t0, 0x40003000
    ld t1, 0(t0)               # Execute-only is unreadable without MXR
    li t1, 0x80000
    csrs sstatus, t1
    ld t1, 0(t0)
    li t2, 0x4567
    bne t1, t2, fail
    li t0, 0x40004000
    ld t1, 0(t0)               # A=0 -> Svade load page fault
    li t1, 0x80222020
    ld t2, 0(t1)
    ori t2, t2, 64
    sd t2, 0(t1)
    sfence.vma t0, zero
    ld t2, 0(t0)
    li t3, 0xbeef
    bne t2, t3, fail
    sd t3, 0(t0)               # D=0 -> precise store page fault
    ld t2, 0(t1)
    ori t2, t2, 128
    sd t2, 0(t1)
    sfence.vma
    sd t3, 0(t0)
    li t0, 0x40005000
    ld t1, 0(t0)               # Valid PTE, final PMP denies -> access fault
    li t0, 0x40000000
    sd zero, 0(t0)             # Read/execute-only U code; no write may reach AXI
    la s8, after_user_fetch
    jalr zero, 0(t0)           # S cannot execute U code, even with SUM
after_user_fetch:
    # Remap a warmed U data alias, preserve physical cache correctness, global legal over-fence.
    li t0, 0x80222008
    li t1, 0x2008ccd7
    sd t1, 0(t0)
    sfence.vma zero, zero
    li t0, 0x40001000
    ld t1, 0(t0)
    li t2, 0xbeef
    bne t1, t2, fail
    li a7, 3
    ecall
    # Actual UART loopback -> PLIC context 1 -> delegated SEIP, not a host fake IRQ.
    li t0, 0x0c00000c
    li t1, 1
    sw t1, 0(t0)
    li t0, 0x0c002080
    li t1, 8
    sw t1, 0(t0)
    li t0, 0x0c201000
    sw zero, 0(t0)
    li t0, 0x220
    csrw sie, t0
    csrsi sstatus, 2
    li t0, 0x10000000
    li t1, 7
    sb t1, 2(t0)
    li t1, 16
    sb t1, 4(t0)
    li t1, 1
    sb t1, 1(t0)
    li t1, 0x4b
    sb t1, 0(t0)
    li t3, 20000
3:  ld t1, 200(s10)           # IRQ9 at index 16+9
    bnez t1, 4f
    addi t3, t3, -1
    bnez t3, 3b
    j fail
4:  li a7, 1
    ecall
    li t3, 20000
5:  ld t1, 168(s10)           # IRQ5 at index 16+5
    bnez t1, 6f
    addi t3, t3, -1
    bnez t3, 5b
    j fail
6:  csrw sie, zero
    li t0, 0x40000000
    csrw sepc, t0
    csrci sstatus, 2
    li t0, 0x100
    csrc sstatus, t0
    sret

user_return:
    li t0, 0x80233008
    ld t1, 0(t0)
    li t2, 0xabc
    bne t1, t2, fail
    li a7, 2
    ecall

.align 2
supervisor_handler:
    csrr t4, scause
    bltz t4, supervisor_irq
    slli t5, t4, 3
    add t5, s10, t5
    ld t6, 0(t5)
    addi t6, t6, 1
    sd t6, 0(t5)
    li t5, 8
    beq t4, t5, user_ecall
    li t5, 12
    beq t4, t5, user_fetch_fault
    csrr t5, sepc
    addi t5, t5, 4
    csrw sepc, t5
    sret
user_fetch_fault:
    csrr t5, stval
    li t6, 0x40000000
    bne t5, t6, fail
    csrw sepc, s8
    sret
user_ecall:
    la t5, user_return
    csrw sepc, t5
    li t5, 0x100
    csrs sstatus, t5
    sret
supervisor_irq:
    andi t4, t4, 15
    addi t5, t4, 16
    slli t5, t5, 3
    add t5, s10, t5
    ld t6, 0(t5)
    addi t6, t6, 1
    sd t6, 0(t5)
    li t5, 5
    beq t4, t5, supervisor_timer
    li t5, 9
    bne t4, t5, fail
    li t5, 0x0c201004
    lw t6, 0(t5)
    li t4, 3
    bne t6, t4, fail
    li t4, 0x10000000
    lbu t4, 0(t4)
    li t6, 0x4b
    bne t4, t6, fail
    li t6, 3
    sw t6, 0(t5)
    sret
supervisor_timer:
    li t5, 32
    csrc sie, t5
    sret

.section .text.user
.align 12
user_start:
    li s11, 0x40001000
    ld t1, 0(s11)
    li t2, 0xbeef
    bne t1, t2, user_fail
    li t1, 0xabc
    sd t1, 8(s11)
    rdtime t1
    li t0, 0x40002000
    ld t1, 0(t0)               # U must reject S-only page
    csrr t1, satp               # U CSR privilege check
    mret                       # U cannot return from M
    wfi                        # U cannot execute WFI
    ecall
user_fail:
    li a0, 1
    ecall
