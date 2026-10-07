/* Bounded production-SoC test: same instruction-cache address is granted,
 * revoked, traps precisely without executing, then is granted and executes.
 * MRET/PMP barriers must invalidate any captured permissions and raw hints.
 */
.option norelax
.option norvc
.section .text.start,"ax"
.globl _start
_start:
    la sp, __app_stack_top
    la t0, failure
    csrw mtvec, t0
    csrr t0, misa
    li t1, 0x800000000014112d
    bne t0, t1, failure
    li s0, 0
    li s1, 0
    li t0, -1
    csrw pmpaddr0, t0
    li t0, 0x0f
    csrw pmpcfg0, t0
    la t0, trap_entry
    csrw mtvec, t0
enter_supervisor:
    la t0, shared_gate
    csrw mepc, t0
    li t0, 0x1800
    csrc mstatus, t0
    li t0, 0x0800
    csrs mstatus, t0
    mret
.balign 64
shared_gate:
    .option rvc
    c.addi s1, 1
    c.nop /* adjacent compressed retirements independently witness 2-byte PCs */
    .option norvc
gate_ecall:
    ecall
    j failure
.option push
.option rvc
.balign 4
.option pop
trap_entry:
    csrr t0, mcause
    li t1, 1
    beq s0, t1, denied_entry
    li t1, 9
    bne t0, t1, failure
    csrr t0, mepc
    la t1, gate_ecall
    bne t0, t1, failure
    beqz s0, revoke_execute
    li t0, 2
    bne s0, t0, failure
    bne s1, t0, failure
    la a0, pass_text
    j print_result
revoke_execute:
    li t0, 1
    bne s1, t0, failure
    mv s0, t0
    li t0, 0x0b
    csrw pmpcfg0, t0
    j enter_supervisor
denied_entry:
    /* Must not retire the previously cached compressed increment. */
    bne t0, t1, failure
    bne s1, t1, failure
    csrr t0, mepc
    la t1, shared_gate
    bne t0, t1, failure
    csrr t0, mtval
    bne t0, t1, failure
    li s0, 2
    li t0, 0x0f
    csrw pmpcfg0, t0
    j enter_supervisor
.option push
.option rvc
.balign 4
.option pop
failure:
    la a0, fail_text
print_result:
    li t0, 0x10000000
1:  lbu t1, 0(a0)
    beqz t1, 3f
2:  lbu t2, 5(t0)
    andi t2, t2, 32
    beqz t2, 2b
    sb t1, 0(t0)
    addi a0, a0, 1
    j 1b
3:  j 3b
.section .rodata,"a"
pass_text: .asciz "FETCH PERMISSION PASS\r\n"
fail_text: .asciz "FETCH PERMISSION FAIL\r\n"
