.option norvc
.option norelax
.section .text.start
.globl _start
_start:
    li sp,0x80b00000
    li s0,0x80a00000
    sd zero,0(s0)
    sd zero,8(s0)
    la t0,handler
    csrw mtvec,t0
    li s1,0
    li s6,0
    # FS=Off gates both FP instructions and FP CSRs; no partial FP state changes.
    li s7,2
    la s9,after_off
    la t0,off
    lwu s8,0(t0)
off:
    fadd.s f0,f0,f0
after_off:
    la s9,after_csr_off
    la t0,csr_off
    lwu s8,0(t0)
csr_off:
    csrr t0,fcsr
after_csr_off:
    li t0,0x2000
    csrs mstatus,t0
    csrr t1,mstatus
    srli t1,t1,13
    andi t1,t1,3
    li t2,1
    bne t1,t2,fail
    csrw fcsr,zero
    li s2,0x80206000
    # Save/overwrite/restore ALL 32 architectural FPRs, including f0. Payload bits must survive.
    .set offset,0
    .irp r,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31
#if HAVE_D
        li t0,0x3ff0000000000000
        addi t0,t0,offset
        fmv.d.x f\r,t0
        fsd f\r,offset(s2)
        fmv.d.x f\r,zero
        fld f\r,offset(s2)
        fmv.x.d t1,f\r
#else
        li t0,0x3f800000
        addi t0,t0,offset
        fmv.w.x f\r,t0
        fsw f\r,offset(s2)
        fmv.w.x f\r,zero
        flw f\r,offset(s2)
        fmv.x.w t1,f\r
#endif
        bne t0,t1,fail
        addi s1,s1,1
        .set offset,offset+8
    .endr
    li t0,0x75
    csrw fcsr,t0
    csrr t1,fcsr
    bne t0,t1,fail
    csrr t1,mstatus
    srli t2,t1,13
    andi t2,t2,3
    li t3,3
    bne t2,t3,fail
    srli t2,t1,63
    beqz t2,fail
    csrr t1,sstatus
    srli t2,t1,63
    beqz t2,fail
    # NaN payload raw move/store versus computational canonicalization.
    li t0,0x7fa12345
    fmv.w.x f0,t0
    fsw f0,256(s2)
    lwu t1,256(s2)
    bne t0,t1,fail
    fmv.x.w t1,f0
    bne t0,t1,fail
    csrw fflags,zero
    fadd.s f1,f0,f0
    fmv.x.w t1,f1
    li t2,0x7fc00000
    bne t1,t2,fail
    csrr t1,fflags
    li t2,16
    bne t1,t2,fail
    # Dynamic reserved frm is illegal, not a successful placeholder operation.
    li t0,5
    csrw frm,t0
    li s7,2
    la s9,after_rm
    la t0,bad_rm
    lwu s8,0(t0)
bad_rm:
    fadd.s f1,f0,f0,dyn
after_rm:
    csrw frm,zero
    # Misaligned FP accesses preserve destination and cannot update RAM.
    li s7,4
    addi s8,s2,1
    la s9,after_align_load
    flw f0,1(s2)
after_align_load:
    li s7,6
    la s9,after_align_store
    fsw f0,1(s2)
after_align_store:
    li t0,0x7fa12345
    fmv.x.w t1,f0
    bne t0,t1,fail
    # Error must arrive through the real AXI R/B response, with precise FP state.
    li s7,5
    li s8,0x80218000
    la s9,after_read_error
    flw f0,0(s8)
after_read_error:
    li s7,7
    li s8,0x80218008
    la s9,after_write_error
    fsw f0,0(s8)
after_write_error:
    li t0,0x7fa12345
    fmv.x.w t1,f0
    bne t0,t1,fail
#if HAVE_D
    # Real compressed FLDSP f0 / FSDSP (not integer x0 rules).
    addi sp,sp,-16
    fmv.d.x f0,t0
    .option rvc
    c.fsdsp f0,0(sp)
    fmv.d.x f0,zero
    c.fldsp f0,0(sp)
    .option norvc
    fmv.x.d t1,f0
    bne t0,t1,fail
    addi sp,sp,16
    # Unboxed S data in FLEN64 becomes canonical quiet NaN without inventing NV.
    fmv.d.x f0,t0
    csrw fflags,zero
    fadd.s f1,f0,f0
    fmv.x.d t1,f1
    li t2,0xffffffff7fc00000
    bne t1,t2,fail
    csrr t1,fflags
    bnez t1,fail
#else
    # D cannot sneak into the F-only configuration.
    li s7,2
    la s9,after_d_off
    la t0,d_off
    lwu s8,0(t0)
d_off:
    .4byte 0x02000053
after_d_off:
#endif
    # Sv39/MPRV S permissions on the FP LSU, nonidentity alias and page fault.
    li t0,0x3ffffffff
    csrw pmpaddr0,t0
    li t0,0x1f
    csrw pmpcfg0,t0
    li t0,0x80220008
    li t1,0x20088401
    sd t1,0(t0)
    li t0,0x80221000
    li t1,0x200800cf
    sd t1,0(t0)
    li t0,0x8000000000080220
    csrw satp,t0
    sfence.vma
    li t0,0x22800
    csrw mstatus,t0
    li t0,0x40006000
    li t1,0x40400000
    fmv.w.x f0,t1
    fsw f0,320(t0)
    flw f1,320(t0)
    fmv.x.w t2,f1
    bne t1,t2,fail
    li s7,13
    li s8,0x60000000
    la s9,after_page
    flw f1,0(s8)
after_page:
    li t0,0x20000
    csrc mstatus,t0
    csrw satp,zero
    sfence.vma
    li t0,8
#if !HAVE_D
    addi t0,t0,1
#endif
    bne s6,t0,fail
    sd s1,8(s0)
    sd s6,16(s0)
    li t0,0x46504450415353
    sd t0,0(s0)
    li a0,0
    # Park after the completion trap so an independent coherent agent can
    # verify dirty results without the normal fault handler rewriting them.
    la t0,completed
    csrw mtvec,t0
    ebreak
completed:
    j completed
handler:
    csrr t0,mcause
    bne t0,s7,fail
    csrr t0,mtval
    bne t0,s8,fail
    li t0,0x20000
    csrc mstatus,t0
    addi s6,s6,1
    csrw mepc,s9
    mret
fail:
    sd s1,8(s0)
    li t0,0xbad
    sd t0,0(s0)
    li a0,1
    ebreak
