/* Separate tiny architectural check; never replaces the fixed COPY guest. */
.section .text.start
.option norvc
.option norelax
.globl _start
_start:
    csrw mie, zero
    csrw mideleg, zero
    csrw medeleg, zero
    csrw satp, zero
    csrw pmpcfg0, zero
    la t0, trap_handler
    csrw mtvec, t0
    la t0, target_word
    srli t0, t0, 2
    csrw pmpaddr0, t0
    li t0, 0x15 /* Unlocked NA4, R+X, permits exactly target_word..target_word+3. */
    csrw pmpcfg0, t0
    la t0, target_pc
    csrw mepc, t0
    li t0, 0x800 /* MPP=S; interrupts and MPRV are clear. */
    csrw mstatus, t0
    mret
.org 0x100
.globl target_word, target_pc
 target_word:
    .2byte 0x0001
 target_pc:
#if SHORT_INSTRUCTION
    .2byte 0x0001 /* C.NOP must retire before a fault at the following parcel. */
    .4byte 0x00000013
#else
    .4byte 0x00100293 /* ADDI x5,x0,1 straddles the allowed NA4 end. Must not retire. */
#endif
.org 0x180
.globl trap_handler, finished_ecall
 trap_handler:
    csrr t0, mcause
    li t4, 11
    beq t0, t4, terminal_loop
    li t3, 0x80210000
    csrr t1, mepc
    csrr t2, mtval
    sd t0, 0(t3)
    sd t1, 8(t3)
    sd t2, 16(t3)
    li t0, 0x504d50
    sd t0, 24(t3)
    fence rw, rw
    fence.i /* Publish dirty mailbox data through the existing coherent flush. */
 finished_ecall:
    ecall
 terminal_loop:
    j terminal_loop
