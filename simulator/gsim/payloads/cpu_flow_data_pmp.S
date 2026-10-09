.option norvc
.section .text.start,"ax",@progbits
.globl _start
_start:
    li s0, 0x80400000
    li s2, 0
    la t0, handler
    csrw mtvec, t0
    srli t0, s0, 2
    csrw pmpaddr0, t0
    li t0, -1
    csrw pmpaddr1, t0
    li t0, 0x1f18
    csrw pmpcfg0, t0
    ld s1, 0(s0)
    li t0, 0x1122334455667788
    bne s1, t0, fail
    la t0, supervisor
    csrw mepc, t0
    li t0, 0x1800
    csrc mstatus, t0
    li t0, 0x800
    csrs mstatus, t0
    mret
supervisor:
.globl denied_s
 denied_s:
    ld t1, 0(s0)
    ld t1, 8(s0)
    li t0, 0x7766554433221100
    bne t1, t0, fail
.globl supervisor_ecall
 supervisor_ecall:
    ecall
    j fail
machine_after:
    li t0, 0x1800
    csrc mstatus, t0
    li t0, 0x20800
    csrs mstatus, t0
.globl denied_mprv
 denied_mprv:
    ld t1, 0(s0)
    li t0, 0x20000
    csrc mstatus, t0
    ld t1, 0(s0)
    li t0, 0x1122334455667788
    bne t1, t0, fail
    li t0, 3
    bne s2, t0, fail
    li t0, 0x80600000
    sd s2, 0(t0)
    sd t1, 8(t0)
    fence rw, rw
    fence.i
    fence rw, rw
.globl done
 done:
    nop
    j done
handler:
    addi s2, s2, 1
    csrr t0, mcause
    li t1, 9
    beq t0, t1, return_machine
    li t1, 5
    bne t0, t1, fail
    csrr t0, mtval
    bne t0, s0, fail
    csrr t0, mepc
    addi t0, t0, 4
    csrw mepc, t0
    mret
return_machine:
    la t0, machine_after
    csrw mepc, t0
    li t0, 0x1800
    csrs mstatus, t0
    mret
.globl fail
fail:
    ebreak
    j fail
