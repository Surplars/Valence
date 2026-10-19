.option rvc
.option norelax
.section .text.start
.globl _start
_start:
    li sp, 0x80250000
    la t0, machine_handler
    csrw mtvec, t0
    li s0, 0x80230000
    li t0, 64
    mv t1, s0
1:  sd zero, 0(t1)
    addi t1, t1, 8
    addi t0, t0, -1
    bnez t0, 1b
    # Exercise compressed stack, register, jump and word arithmetic on actual CPU state.
    li s1, -7
    addi sp, sp, -32
    sd s1, 8(sp)
    ld s2, 8(sp)
    bne s1, s2, fail
    addi sp, sp, 32
    c.mv s2, s1
    c.add s2, s1
    li t0, -14
    bne s2, t0, fail
    c.addiw s2, 1
    li t0, -13
    bne s2, t0, fail
    # 32-bit op at PC%4=2, then at PC%8=6; neither is an instruction misalignment.
    .balign 8
    c.nop
    .4byte 0x00500513
    li t0, 5
    bne a0, t0, fail
    .balign 8
    c.nop
    c.nop
    c.nop
    .4byte 0x00600513
    li t0, 6
    bne a0, t0, fail
    li a0, 0
    # LR/SC W upper lane and D, explicit success/failure, all AMOs and aq/rl.
    li s3, 0x80231000
    li t0, 0x80000001
    sw t0, 4(s3)
    addi s4, s3, 4
    lr.w.aq t1, (s4)
    li t2, -2147483647
    bne t1, t2, fail
    li t0, 17
    sc.w.rl t1, t0, (s4)
    bnez t1, fail
    sc.w t1, zero, (s4)
    li t2, 1
    bne t1, t2, fail
    lr.d t1, (s3)
    li t0, 0x123456789abcdef0
    sc.d.aqrl t1, t0, (s3)
    bnez t1, fail
    lr.d t1, (s3)
    sb zero, 0(s3)
    sc.d t1, t0, (s3)
    li t2, 1
    bne t1, t2, fail
    li t0, 5
    sd t0, 0(s3)
    li t0, 3
    amoadd.d.aqrl t1, t0, (s3)
    li t2, 5
    bne t1, t2, fail
    li t0, 0xf
    amoxor.d t1, t0, (s3)
    li t2, 8
    bne t1, t2, fail
    li t0, 0x10
    amoor.d t1, t0, (s3)
    li t2, 7
    bne t1, t2, fail
    li t0, 0x1f
    amoand.d t1, t0, (s3)
    li t2, 0x17
    bne t1, t2, fail
    li t0, -3
    amomin.d t1, t0, (s3)
    bne t1, t2, fail
    li t0, 9
    amomax.d t1, t0, (s3)
    li t2, -3
    bne t1, t2, fail
    li t0, 4
    amominu.d t1, t0, (s3)
    li t2, 9
    bne t1, t2, fail
    li t0, 33
    amomaxu.d t1, t0, (s3)
    li t2, 4
    bne t1, t2, fail
    amoswap.d t1, zero, (s3)
    li t2, 33
    bne t1, t2, fail
    fence rw, rw
    # Exact 16-bit illegal EPC and misaligned LR/AMO faults; handler advances the real length.
    .balign 4
    c.nop
    .2byte 0
    # Unsupported >=48-bit prefix is rejected from parcel one. No invented high bits in mtval.
    .2byte 0x001f
    .2byte 0
    c.nop
    addi t0, s3, 1
    lr.w t1, (t0)
    amoadd.d t1, zero, (t0)
    # Atomics to MMIO have no device side effects.
    li t0, 0x10000000
    lr.w t1, (t0)
    amoswap.w t1, zero, (t0)
    # Actual MPRV Sv39 alias LR/SC: physical reservation survives PTW/cache conflicts.
    li t0, 0x40080000
    csrw pmpaddr0, t0
    li t0, 15
    csrw pmpcfg0, t0
    li t0, 0x80220000
    li t1, 1536
2:  sd zero, 0(t0)
    addi t0, t0, 8
    addi t1, t1, -1
    bnez t1, 2b
    li t0, 0x80220008
    li t1, 0x20088401
    sd t1, 0(t0)
    li t0, 0x80220010
    li t1, 0x200000cf
    sd t1, 0(t0)
    li t0, 0x80221000
    li t1, 0x200800cf          # 2MiB alias 40000000 -> 80200000
    sd t1, 0(t0)
    li t0, 0x8000000000080220
    csrw satp, t0
    sfence.vma
    li s4, 0x40031000
    li t0, 0x20800
    csrs mstatus, t0
    lr.d t1, (s3)
    li t0, 42
    sc.d t1, t0, (s4)
    bnez t1, fail
    li t0, 0x20000
    csrc mstatus, t0
    ld t1, 0(s3)
    li t0, 42
    bne t1, t0, fail
    sd t1, 256(s0)
    # Replace alias by a 4KiB execute-only S leaf. Page two is invalid.
    li t0, 0x80221000
    li t1, 0x20088801
    sd t1, 0(t0)
    li t0, 0x80222000
    li t1, 0x200810cb          # RX/A/D S code physical 80204000
    sd t1, 0(t0)
    sfence.vma
    li t0, 0x8020f000
    ld t1, 0(t0)              # host selects 16-bit vs 32-bit prefix at end of page
    li s9, 0x40000ffe
    beqz t1, 3f
    addi s9, s9, 2
3:  la t0, supervisor_handler
    csrw stvec, t0
    li t0, 0x1000
    csrw medeleg, t0
    li t0, 0x40000ffe
    csrw mepc, t0
    li t0, 0x800
    csrw mstatus, t0
    mret
.balign 4
supervisor_handler:
    csrr t0, scause
    li t1, 12
    bne t0, t1, fail
    csrr t0, sepc
    bne t0, s9, fail
    csrr t0, stval
    li t1, 0x40001000
    bne t0, t1, fail
    sd t0, 264(s0)
    la t0, supervisor_finish
    csrw sepc, t0
    sret
supervisor_finish:
    ecall
.balign 4
machine_handler:
    csrr t4, mcause
    li t5, 9
    beq t4, t5, finish
    li t5, 0x20000
    csrc mstatus, t5
    slli t5, t4, 3
    add t5, s0, t5
    ld t6, 0(t5)
    addi t6, t6, 1
    sd t6, 0(t5)
    csrr t4, mepc
    lhu t5, 0(t4)
    li t6, 31
    bne t5, t6, 6f
    csrr t6, mtval
    bnez t6, fail
6:
    andi t5, t5, 3
    li t6, 3
    beq t5, t6, 4f
    addi t4, t4, 2
    j 5f
4:  addi t4, t4, 4
5:  csrw mepc, t4
    mret
finish:
    li t0, 0x434150415353
    sd t0, 272(s0)
    li a0, 0
    ebreak
fail:
    li a0, 1
    ebreak
