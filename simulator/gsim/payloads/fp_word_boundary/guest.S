/* Short real-SoC RV64GC smoke; no C runtime and no numerical DUT oracle.
 * Exact arithmetic anchors complement the full independent SoftFloat suite.
 * S-mode save/restore proves hardware context mechanisms, NOT Linux scheduling.
 */
.option norelax
.option norvc
.section .text.start,"ax"
.globl _start
_start:
    la sp, __app_stack_top
    addi sp, sp, -16
    sd ra, 0(sp)
    la t0, failure
    csrw mtvec, t0
    csrr t0, misa
    li t1, 0x800000000014112d
    bne t0, t1, failure
    li t0, 0x2000
    csrs mstatus, t0
    /* I/M exact integer anchors. */
    li t0, 7
    li t1, 9
    mul t2, t0, t1
    li t3, 63
    bne t2, t3, failure
    div t2, t3, t0
    bne t2, t1, failure
    rem t2, t3, t0
    bnez t2, failure
    .option rvc
    li t2, 1
    c.addi t2, 1
    .option norvc
    li t3, 2
    bne t2, t3, failure
    /* A travels through the production coherent cache / atomic memory. */
    la t0, atomic_word
    sd zero, 0(t0)
    li t1, 5
    amoadd.d t2, t1, (t0)
    bnez t2, failure
    lr.d t2, (t0)
    bne t2, t1, failure
    li t1, 9
    sc.d t2, t1, (t0)
    bnez t2, failure
    ld t2, 0(t0)
    bne t2, t1, failure
    fence rw, rw
    fence.i
    /* IEEE exact anchors: 1.5 + 2.0 = 3.5, (1.5 * 2.0) + 1.5 = 4.5. */
    li t0, 0x3fc00000
    fmv.w.x f0, t0
    li t0, 0x40000000
    fmv.w.x f1, t0
    fadd.s f2, f0, f1, rne
    fmv.x.w t0, f2
    li t1, 0x40600000
    bne t0, t1, failure
    fmadd.s f2, f0, f1, f0, rne
    fmv.x.w t0, f2
    li t1, 0x40900000
    bne t0, t1, failure
    li t0, 0x3ff8000000000000
    fmv.d.x f0, t0
    li t0, 0x4000000000000000
    fmv.d.x f1, t0
    fadd.d f2, f0, f1, rne
    fmv.x.d t0, f2
    li t1, 0x400c000000000000
    bne t0, t1, failure
    fsub.d f2, f2, f0, rne
    fmv.x.d t0, f2
    li t1, 0x4000000000000000
    bne t0, t1, failure
    fmul.d f2, f0, f1, rne
    fdiv.d f2, f2, f1, rne
    fmv.x.d t0, f2
    li t1, 0x3ff8000000000000
    bne t0, t1, failure
    fmadd.d f2, f0, f1, f0, rne
    fmv.x.d t0, f2
    li t1, 0x4012000000000000
    bne t0, t1, failure
    li t0, 0x4010000000000000
    fmv.d.x f2, t0
    fsqrt.d f2, f2, rne
    fmv.x.d t0, f2
    li t1, 0x4000000000000000
    bne t0, t1, failure
    fcvt.s.d f2, f2, rne
    fmv.x.w t0, f2
    li t1, 0x40000000
    bne t0, t1, failure
    fcvt.d.s f2, f2
    fcvt.l.d t0, f2, rne
    li t1, 2
    bne t0, t1, failure
    csrr t0, fflags
    bnez t0, failure
    /* Independent fixed literal W/WU result + fflags checks. */
    /* 0: positive signed overflow */
    csrw fflags, zero
    li t0, 0x41e0000000000000
    fmv.d.x f0, t0
    .globl fp_convert_case_0
fp_convert_case_0:
    fcvt.w.d t0, f0, rne
    la t4, fp_boundary_expected
    ld t1, 0(t4)
    bne t0, t1, failure
    csrr t0, fflags
    li t1, 16
    bne t0, t1, failure
    .globl fp_convert_pass_0
fp_convert_pass_0:
    nop
    /* 1: unsigned bit31 must sign extend */
    csrw fflags, zero
    li t0, 0x41e0000000000000
    fmv.d.x f0, t0
    .globl fp_convert_case_1
fp_convert_case_1:
    fcvt.wu.d t0, f0, rne
    li t1, 0xffffffff80000000
    bne t0, t1, failure
    csrr t0, fflags
    li t1, 0
    bne t0, t1, failure
    .globl fp_convert_pass_1
fp_convert_pass_1:
    nop
    /* 2: negative signed endpoint exact */
    csrw fflags, zero
    li t0, 0xc1e0000000000000
    fmv.d.x f0, t0
    .globl fp_convert_case_2
fp_convert_case_2:
    fcvt.w.d t0, f0, rne
    li t1, 0xffffffff80000000
    bne t0, t1, failure
    csrr t0, fflags
    li t1, 0
    bne t0, t1, failure
    .globl fp_convert_pass_2
fp_convert_pass_2:
    nop
    /* 3: negative signed overflow */
    csrw fflags, zero
    li t0, 0xc1e0000000200000
    fmv.d.x f0, t0
    .globl fp_convert_case_3
fp_convert_case_3:
    fcvt.w.d t0, f0, rtz
    li t1, 0xffffffff80000000
    bne t0, t1, failure
    csrr t0, fflags
    li t1, 16
    bne t0, t1, failure
    .globl fp_convert_pass_3
fp_convert_pass_3:
    nop
    /* 4: negative fraction rounds zero */
    csrw fflags, zero
    li t0, 0xbfd0000000000000
    fmv.d.x f0, t0
    .globl fp_convert_case_4
fp_convert_case_4:
    fcvt.wu.d t0, f0, rtz
    li t1, 0x0000000000000000
    bne t0, t1, failure
    csrr t0, fflags
    li t1, 1
    bne t0, t1, failure
    .globl fp_convert_pass_4
fp_convert_pass_4:
    nop
    /* 5: negative fraction rounds below unsigned range */
    csrw fflags, zero
    li t0, 0xbfd0000000000000
    fmv.d.x f0, t0
    .globl fp_convert_case_5
fp_convert_case_5:
    fcvt.wu.d t0, f0, rdn
    li t1, 0x0000000000000000
    bne t0, t1, failure
    csrr t0, fflags
    li t1, 16
    bne t0, t1, failure
    .globl fp_convert_pass_5
fp_convert_pass_5:
    nop
    /* 6: negative unsigned integer */
    csrw fflags, zero
    li t0, 0xbff0000000000000
    fmv.d.x f0, t0
    .globl fp_convert_case_6
fp_convert_case_6:
    fcvt.wu.d t0, f0, rne
    li t1, 0x0000000000000000
    bne t0, t1, failure
    csrr t0, fflags
    li t1, 16
    bne t0, t1, failure
    .globl fp_convert_pass_6
fp_convert_pass_6:
    nop
    /* 7: signed last half rounds down */
    csrw fflags, zero
    li t0, 0x41dfffffffe00000
    fmv.d.x f0, t0
    .globl fp_convert_case_7
fp_convert_case_7:
    fcvt.w.d t0, f0, rtz
    li t1, 0x000000007fffffff
    bne t0, t1, failure
    csrr t0, fflags
    li t1, 1
    bne t0, t1, failure
    .globl fp_convert_pass_7
fp_convert_pass_7:
    nop
    /* 8: signed last half rounds outside; NV suppresses NX */
    csrw fflags, zero
    li t0, 0x41dfffffffe00000
    fmv.d.x f0, t0
    .globl fp_convert_case_8
fp_convert_case_8:
    fcvt.w.d t0, f0, rne
    li t1, 0x000000007fffffff
    bne t0, t1, failure
    csrr t0, fflags
    li t1, 16
    bne t0, t1, failure
    .globl fp_convert_pass_8
fp_convert_pass_8:
    nop
    /* 9: unsigned endpoint exact */
    csrw fflags, zero
    li t0, 0x41efffffffe00000
    fmv.d.x f0, t0
    .globl fp_convert_case_9
fp_convert_case_9:
    fcvt.wu.d t0, f0, rne
    li t1, 0xffffffffffffffff
    bne t0, t1, failure
    csrr t0, fflags
    li t1, 0
    bne t0, t1, failure
    .globl fp_convert_pass_9
fp_convert_pass_9:
    nop
    /* 10: unsigned last half rounds outside */
    csrw fflags, zero
    li t0, 0x41effffffff00000
    fmv.d.x f0, t0
    .globl fp_convert_case_10
fp_convert_case_10:
    fcvt.wu.d t0, f0, rne
    li t1, 0xffffffffffffffff
    bne t0, t1, failure
    csrr t0, fflags
    li t1, 16
    bne t0, t1, failure
    .globl fp_convert_pass_10
fp_convert_pass_10:
    nop
    /* 11: negative quiet NaN clips positive */
    csrw fflags, zero
    li t0, 0xfff8000000000001
    fmv.d.x f0, t0
    .globl fp_convert_case_11
fp_convert_case_11:
    fcvt.wu.d t0, f0, rne
    li t1, 0xffffffffffffffff
    bne t0, t1, failure
    csrr t0, fflags
    li t1, 16
    bne t0, t1, failure
    .globl fp_convert_pass_11
fp_convert_pass_11:
    nop
    /* 12: nonzero discarded bits narrow overflow suppresses NX */
    csrw fflags, zero
    li t0, 0x41dfffffffffffef
    fmv.d.x f0, t0
    .globl fp_convert_case_12
fp_convert_case_12:
    fcvt.w.d t0, f0, rne
    li t1, 0x000000007fffffff
    bne t0, t1, failure
    csrr t0, fflags
    li t1, 16
    bne t0, t1, failure
    .globl fp_convert_pass_12
fp_convert_pass_12:
    nop
    /* 13: single positive signed overflow */
    csrw fflags, zero
    li t0, 0x4f000000
    fmv.w.x f0, t0
    .globl fp_convert_case_13
fp_convert_case_13:
    fcvt.w.s t0, f0, rne
    li t1, 0x000000007fffffff
    bne t0, t1, failure
    csrr t0, fflags
    li t1, 16
    bne t0, t1, failure
    .globl fp_convert_pass_13
fp_convert_pass_13:
    nop
    /* 14: single unsigned sign extension */
    csrw fflags, zero
    li t0, 0x4f000000
    fmv.w.x f0, t0
    .globl fp_convert_case_14
fp_convert_case_14:
    fcvt.wu.s t0, f0, rne
    li t1, 0xffffffff80000000
    bne t0, t1, failure
    csrr t0, fflags
    li t1, 0
    bne t0, t1, failure
    .globl fp_convert_pass_14
fp_convert_pass_14:
    nop
    /* 15: single negative endpoint */
    csrw fflags, zero
    li t0, 0xcf000000
    fmv.w.x f0, t0
    .globl fp_convert_case_15
fp_convert_case_15:
    fcvt.w.s t0, f0, rne
    li t1, 0xffffffff80000000
    bne t0, t1, failure
    csrr t0, fflags
    li t1, 0
    bne t0, t1, failure
    .globl fp_convert_pass_15
fp_convert_pass_15:
    nop
    /* 16: single negative fraction zero */
    csrw fflags, zero
    li t0, 0xbe800000
    fmv.w.x f0, t0
    .globl fp_convert_case_16
fp_convert_case_16:
    fcvt.wu.s t0, f0, rtz
    li t1, 0x0000000000000000
    bne t0, t1, failure
    csrr t0, fflags
    li t1, 1
    bne t0, t1, failure
    .globl fp_convert_pass_16
fp_convert_pass_16:
    nop
    /* 17: single negative fraction invalid */
    csrw fflags, zero
    li t0, 0xbe800000
    fmv.w.x f0, t0
    .globl fp_convert_case_17
fp_convert_case_17:
    fcvt.wu.s t0, f0, rdn
    li t1, 0x0000000000000000
    bne t0, t1, failure
    csrr t0, fflags
    li t1, 16
    bne t0, t1, failure
    .globl fp_convert_pass_17
fp_convert_pass_17:
    nop
    /* 18: single positive infinity */
    csrw fflags, zero
    li t0, 0x7f800000
    fmv.w.x f0, t0
    .globl fp_convert_case_18
fp_convert_case_18:
    fcvt.w.s t0, f0, rne
    li t1, 0x000000007fffffff
    bne t0, t1, failure
    csrr t0, fflags
    li t1, 16
    bne t0, t1, failure
    .globl fp_convert_pass_18
fp_convert_pass_18:
    nop
    /* 19: single negative quiet NaN */
    csrw fflags, zero
    li t0, 0xffc00001
    fmv.w.x f0, t0
    .globl fp_convert_case_19
fp_convert_case_19:
    fcvt.wu.s t0, f0, rne
    li t1, 0xffffffffffffffff
    bne t0, t1, failure
    csrr t0, fflags
    li t1, 16
    bne t0, t1, failure
    .globl fp_convert_pass_19
fp_convert_pass_19:
    nop
    csrw fflags, zero
    /* Allow S-mode memory, enter S-mode with bare satp through real MRET. */
    li t0, -1
    csrw pmpaddr0, t0
    li t0, 0x0f
    csrw pmpcfg0, t0
    la t0, supervisor_done
    csrw mtvec, t0
    la t0, supervisor
    csrw mepc, t0
    li t0, 0x1800
    csrc mstatus, t0
    li t0, 0x0800
    csrs mstatus, t0
    mret
supervisor:
    csrr t0, sstatus
    andi t0, t0, 2
    bnez t0, failure
    /* Two 1-GiB Sv39 leaves: code/stack remain identity-mapped at VA 0x80000000;
     * VA 0x40000000 aliases PA 0x80000000. Root is at PA 0x80210000.
     * FP context VA 0x40220000 must therefore access PA 0x80220000, not itself.
     * A bypassed translation reaches an invalid DDR aperture and cannot pass.
     */
    li t0, 0x80210000
    li t1, 0x200000cf
    sd t1, 8(t0)
    sd t1, 16(t0)
    fence rw, rw
    li t1, 0x8000000000080210
    csrw satp, t1
    sfence.vma
    csrr t2, satp
    bne t2, t1, failure
    li t0, 0x40220000
    li t1, 0x3ff0000000000000
    .irp n,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31
    addi t2, t1, \n
    fmv.d.x f\n, t2
    .endr
    li t1, 0x41
    csrw fcsr, t1
    /* Exact save layout: FPR[32] x 8 followed by fcsr; f0 is not special. */
    .irp n,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31
    fsd f\n, (\n * 8)(t0)
    .endr
    csrr t1, fcsr
    sd t1, 256(t0)
    /* Integer access via the identity view must observe the FP alias store. */
    li t2, 0x80220000
    ld t3, 0(t2)
    li t1, 0x3ff0000000000000
    bne t3, t1, failure
    li t1, 0x4000000000000000
    .irp n,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31
    addi t2, t1, \n
    fmv.d.x f\n, t2
    .endr
    li t1, 0x83
    csrw fcsr, t1
    .irp n,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31
    fld f\n, (\n * 8)(t0)
    .endr
    ld t1, 256(t0)
    csrw fcsr, t1
    csrr t2, fcsr
    li t1, 0x41
    bne t2, t1, failure
    li t1, 0x3ff0000000000000
    .irp n,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31
    fmv.x.d t2, f\n
    addi t3, t1, \n
    bne t2, t3, failure
    .endr
    csrr t0, sstatus
    li t1, 0x8000000000006000
    and t0, t0, t1
    bne t0, t1, failure
    ecall
supervisor_done:
    csrr t0, mcause
    li t1, 9
    bne t0, t1, failure
    /* The exact board model exposes an idle external UART service. Terminate
     * through public retirement PCs without altering that service contract. */
    .globl fp_guest_success
fp_guest_success:
    nop
    j fp_guest_success
failure:
    .globl fp_guest_failure
fp_guest_failure:
    nop
    j fp_guest_failure
.section .rodata,"a"
.balign 8
fp_boundary_marker: .ascii "FPWORD_EXPECT_R1"
.balign 8
.globl fp_boundary_expected
fp_boundary_expected: .quad 0x000000007fffffff
pass_text: .asciz "RV64GC PASS\r\n"
fail_text: .asciz "RV64GC FAIL\r\n"
.section .bss,"aw",@nobits
.balign 64
atomic_word: .zero 64
