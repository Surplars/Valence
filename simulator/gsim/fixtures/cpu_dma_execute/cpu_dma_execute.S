# ROM-resident executed RV64I CPU + coherent line-copy DMA integration.
# No host DataPort injection; every CPU/DMA control access below is an instruction.
.option norvc
.option norelax
.section .text.start
.globl _start, exec_generation_done, exec_error_done, exec_done, exec_fail
_start:
    li s0, 0x10001000
    li s1, 0x80210000
    li s2, 0x80211000
    li s3, 0x80212000
    li s4, 0x1122334400000000
    li s5, 0x01010101
    li s6, 1
next_generation:
    mv t0, s1
    mv t1, s2
    mv t2, s4
    li t3, 512
initialize_dirty:
    sd t2, 0(t0)
    not t4, t2
    sd t4, 0(t1)
    add t2, t2, s5
    addi t0, t0, 8
    addi t1, t1, 8
    addi t3, t3, -1
    bnez t3, initialize_dirty
    mv t0, s3
    li t1, 0x55779900
    li t2, 8
initialize_scratch:
    sd t1, 0(t0)
    addi t0, t0, 8
    addi t1, t1, 1
    addi t2, t2, -1
    bnez t2, initialize_scratch
    # Ordinary FENCE drains CPU store ordering; intentionally no FENCE.I/cache flush.
    fence iorw, iorw
    sd s1, 0(s0)
    sd s2, 8(s0)
    li t0, 4096
    sd t0, 16(s0)
    li t0, 3
    sd t0, 24(s0)
    li s7, 0
    li s8, 128
cpu_during_dma:
    mv t0, s3
    li t1, 0x55779900
    add t1, t1, s7
    li t2, 8
scratch_word:
    ld t3, 0(t0)
    bne t3, t1, exec_fail
    addi t3, t3, 1
    sd t3, 0(t0)
    addi t0, t0, 8
    addi t1, t1, 1
    addi t2, t2, -1
    bnez t2, scratch_word
    addi s7, s7, 1
    bne s7, s8, cpu_during_dma
wait_success:
    ld t0, 32(s0)
    andi t1, t0, 1
    bnez t1, wait_success
    li t1, 2
    bne t0, t1, exec_fail
    fence iorw, iorw
    # Reload both lines through the actual CPU cache. Destination had old dirty data.
    mv t0, s1
    mv t1, s2
    mv t2, s4
    li t3, 512
verify_generation:
    ld t4, 0(t0)
    bne t4, t2, exec_fail
    ld t4, 0(t1)
    bne t4, t2, exec_fail
    add t2, t2, s5
    addi t0, t0, 8
    addi t1, t1, 8
    addi t3, t3, -1
    bnez t3, verify_generation
exec_generation_done:
    addi s6, s6, 1
    li t0, 3
    beq s6, t0, error_case
    li t0, 0x100000000
    add s4, s4, t0
    j next_generation
error_case:
    # Host denies the first cold 64-byte read. Other accepted owners must drain.
    li t0, 0x80230000
    sd t0, 0(s0)
    li t0, 0x80234000
    sd t0, 8(s0)
    li t0, 512
    sd t0, 16(s0)
    li t0, 3
    sd t0, 24(s0)
wait_error:
    ld t0, 32(s0)
    andi t1, t0, 1
    bnez t1, wait_error
    li t1, 6
    bne t0, t1, exec_fail
exec_error_done:
    # Reuse the exact descriptor only after failed busy has drained. START+CLEAR
    # must discard the old error state; the host removes its one read denial.
    li t0, 3
    sd t0, 24(s0)
wait_restart:
    ld t0, 32(s0)
    andi t1, t0, 1
    bnez t1, wait_restart
    li t1, 2
    bne t0, t1, exec_fail
    fence iorw, iorw
    li t0, 0x80234000
    li t1, 0x8877665500000000
    li t2, 64
verify_restart:
    ld t3, 0(t0)
    bne t3, t1, exec_fail
    addi t0, t0, 8
    add t1, t1, s5
    addi t2, t2, -1
    bnez t2, verify_restart
    # Final visibility/drain occurs only after all dirty-coherence cases finish.
    fence.i
    fence rw, rw
exec_done:
    j exec_done
exec_fail:
    j exec_fail
