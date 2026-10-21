# Test-only real I1 guest. Real M-APLIC MMIO routes sources 1..3 to IMSIC
# identities 11..13. Machine interrupt delivery remains disabled so a pending
# bitmap can be observed without claims, synthetic IRQs, or CPU-state injection.
.option norvc
.option norelax
.section .text.start,"ax"
.globl _start, configured, loop_previous, loop_previous_compare, loop_increment, loop_store, loop_load
.globl loop_compare, loop_pending, loop_jump, guest_fail
_start:
    li s0, 0x80200000
    li s1, 0x0c000000
    li t0, 6                     # Active-high level source mode.
    sw t0, 4(s1)
    sw t0, 8(s1)
    sw t0, 12(s1)
    li s2, 0x0c003000
    li t0, 11
    sw t0, 4(s2)
    li t0, 12
    sw t0, 8(s2)
    li t0, 13
    sw t0, 12(s2)
    li s3, 0x0c002000
    li t0, 1
    sw t0, -292(s3)              # SETIENUM at M-APLIC + 0x1edc.
    li t0, 2
    sw t0, -292(s3)
    li t0, 3
    sw t0, -292(s3)
    li t0, 0x100                 # DOMAINCFG delivery enable.
    sw t0, 0(s1)
    li t0, 0x80                  # IMSIC EIP0, not EIE or TOPEI.
    csrw 0x350, t0               # Real miselect.
    li s4, 0
    sd s4, 0(s0)                # Initial value for the independent persistence read.
configured:
loop_previous:
    ld s7, 0(s0)                # Observe the preceding store before overwriting it.
loop_previous_compare:
    bne s4, s7, guest_fail
loop_increment:
    addi s4, s4, 1
loop_store:
    sd s4, 0(s0)
loop_load:
    ld s5, 0(s0)
loop_compare:
    bne s4, s5, guest_fail
loop_pending:
    csrr s6, 0x351               # Real mireg response retires into x22.
loop_jump:
    j loop_previous
guest_fail:
    ebreak
    j guest_fail
