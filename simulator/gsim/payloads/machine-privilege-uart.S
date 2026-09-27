.option norvc
.option norelax
.section .text.start,"ax"
.globl _start, boot_trigger, boot_done, boot_trap
_start:
    li sp, 0x80011000
    li s0, 0x80010000
    sd zero, 0(s0)
    sd zero, 8(s0)
    sd zero, 16(s0)
    la t0, boot_trap
    csrw mtvec, t0
    la t0, supervisor_trap
    csrw stvec, t0
    li t0, (1 << 8) | (1 << 2) | (1 << 1) # U ECALL, illegal and fetch access fault to S.
    li t1, (1 << 5) | (1 << 7) # Load/store access faults to S.
    or t0, t0, t1
    csrw medeleg, t0
    la t0, forbidden_word       # A higher-priority NA4 entry forbids this one instruction.
    srli t0, t0, 2
    csrw pmpaddr0, t0
    li t0, 0x200003ff           # 8 KiB ROM: R/X.
    csrw pmpaddr1, t0
    li t0, 0x200041ff           # 4 KiB RAM: R/W.
    csrw pmpaddr2, t0
    li t0, 0x04000000           # 8-byte UART register window: R/W.
    csrw pmpaddr3, t0
    li t0, 0x1b1b1d91         # Lock the NA4 deny-X entry; permit remaining ROM/RAM/UART.
    csrw pmpcfg0, t0
    csrw pmpaddr0, zero       # Locked NA4 address must remain unchanged.
    csrr t0, pmpaddr0
    la t1, forbidden_word
    srli t1, t1, 2
    bne t0, t1, boot_fail
    li t0, 0x1b1b1d00
    csrw pmpcfg0, t0          # Locked byte must remain 0x91.
    csrr t0, pmpcfg0
    li t1, 0x1b1b1d91
    bne t0, t1, boot_fail
    li t0, 0x24000000       # Unused TOR lower bound at 0x90000000.
    csrw pmpaddr14, t0
    li t0, 0x24000400       # Unused TOR upper bound at 0x90001000.
    csrw pmpaddr15, t0
    li t0, 0x8b00000000000000 # Locked TOR R/W in entry 15.
    csrw pmpcfg2, t0
    csrw pmpaddr14, zero    # Locked TOR also freezes its predecessor address.
    csrr t0, pmpaddr14
    li t1, 0x24000000
    bne t0, t1, boot_fail
    csrw pmpcfg2, zero
    csrr t0, pmpcfg2
    li t1, 0x8b00000000000000
    bne t0, t1, boot_fail
    li a2, 0x0c000000
    li t0, 0x20000           # MPRV=1, MPP=U: data uses U PMP permissions.
    csrw mstatus, t0
    lw t1, 0(a2)             # Must trap in M without reaching APLIC.
    ld t1, 16(s0)
    li t0, 1
    bne t1, t0, boot_fail
    li s1, 0x10000000
    li t0, 0x83
    sb t0, 3(s1)
    li t0, 1
    sb t0, 0(s1)
    sb zero, 1(s1)
    li t0, 3
    sb t0, 3(s1)
    la t0, supervisor_start
    csrw mepc, t0
    li t0, 0x800             # mstatus.MPP = S; interrupts remain disabled.
    csrw mstatus, t0
    mret

boot_trigger:
supervisor_start:
    li t0, 'S'
    sb t0, 0(s1)
    la t0, user_start
    csrw sepc, t0
    csrw sstatus, zero       # SPP = U.
    sret

user_start:
    li a0, 42
    ecall                    # First S trap returns to U.
    csrr t0, sstatus        # Forbidden in U: delegated illegal instruction.
    li a2, 0x0c000000
    lw t0, 0(a2)            # PMP has no matching APLIC region: access fault.
    sw zero, 0(a2)          # Denied store must never reach the device or store buffer.
    la a3, forbidden_word
    jalr zero, -4(a3)       # Allowed first word, denied second word in one fetch packet.
user_after_forbidden:
    ecall                    # Second S trap returns to S.
boot_fail:
    j boot_fail

supervisor_done:
    li t0, 10
    sb t0, 0(s1)
    sd a0, 8(s0)
    # Let the final 8N1 frame leave the shift register before the test stops.
    li t0, 1000
1:  addi t0, t0, -1
    bnez t0, 1b
boot_done:
    j boot_done

.section .text.trap,"ax"
boot_trap:
    csrr t0, mcause
    li t1, 5
    bne t0, t1, boot_fail
    csrr t0, mtval
    bne t0, a2, boot_fail
    li t1, 1
    sd t1, 16(s0)
    csrr t0, mepc
    addi t0, t0, 4
    csrw mepc, t0
    li t0, 0x1800            # MPP=M, clear MPRV before MRET.
    csrw mstatus, t0
    mret

supervisor_trap:
    csrr t0, scause
    ld t1, 0(s0)
    beqz t1, first_ecall
    li t2, 1
    beq t1, t2, illegal_csr
    li t2, 2
    beq t1, t2, denied_load
    li t2, 3
    beq t1, t2, denied_store
    li t2, 4
    beq t1, t2, denied_fetch
    li t2, 5
    beq t1, t2, second_ecall
    j boot_fail

first_ecall:
    li t2, 8
    bne t0, t2, boot_fail
    li t2, 42
    bne a0, t2, boot_fail
    li t2, 'U'
    sb t2, 0(s1)
    li t1, 1
    sd t1, 0(s0)
    csrr t0, sepc
    addi t0, t0, 4
    csrw sepc, t0
    sret

illegal_csr:
    li t2, 2
    bne t0, t2, boot_fail
    csrr t2, stval
    li t3, 0x100022f3      # csrr t0, sstatus, checked independently.
    bne t2, t3, boot_fail
    li t2, '!'
    sb t2, 0(s1)
    li t1, 2
    sd t1, 0(s0)
    csrr t0, sepc
    addi t0, t0, 4
    csrw sepc, t0
    sret

denied_load:
    li t2, 5
    bne t0, t2, boot_fail
    csrr t2, stval
    bne t2, a2, boot_fail
    li t1, 3
    sd t1, 0(s0)
    csrr t0, sepc
    addi t0, t0, 4
    csrw sepc, t0
    sret

denied_store:
    li t2, 7
    bne t0, t2, boot_fail
    csrr t2, stval
    bne t2, a2, boot_fail
    li t1, 4
    sd t1, 0(s0)
    csrr t0, sepc
    addi t0, t0, 4
    csrw sepc, t0
    sret

denied_fetch:
    li t2, 1
    bne t0, t2, boot_fail
    csrr t2, stval
    bne t2, a3, boot_fail
    li t1, 5
    sd t1, 0(s0)
    la t0, user_after_forbidden
    csrw sepc, t0
    sret

second_ecall:
    li t2, 8
    bne t0, t2, boot_fail
    li t1, 6
    sd t1, 0(s0)
    la t0, supervisor_done
    csrw sepc, t0
    li t0, 0x100
    csrs sstatus, t0        # SPP = S, so SRET resumes supervisor code.
    sret

.align 3
allowed_predecessor:
    addi t0, zero, 0
forbidden_word:
    j boot_fail
