# Real A1 guest. No request/token/ACK is injected. All rate writes are eight-byte
# aligned SD through the ordinary CPU/Home/MMIO path and the real reply CDC.
.option norvc
.option norelax
.section .text.start,"ax"
.globl _start, guest_done, guest_fail
_start:
    li s0, 0x10080800
    li s1, 50000000
    li s2, 100000000
    li s3, 0
    li s5, 0x80200000
    li s6, 1024
    li s7, 1024
    li s10, 0
    li s11, 0
boot_wait:
    ld t0, 8(s0)
    bne t0, s1, boot_wait
    ld t0, 88(s0)
    bnez t0, boot_wait
    jal ra, telemetry_check
    li s4, 1
    li t0, 0x0a280a
    sd t0, 48(s0)
    sd s2, 0(s0)
wait_up:
    ld t0, 80(s0)
    bne t0, s4, wait_up
    ld t0, 24(s0)
    bnez t0, guest_fail
    ld t0, 8(s0)
    bne t0, s2, guest_fail
    bnez s3, measured_fabric_up
    li s6, 2048
    j measured_up
measured_fabric_up:
    li s7, 2048
measured_up:
    jal ra, telemetry_check
    li s4, 2
    li t0, 0x14280a
    sd t0, 48(s0)
    sd s1, 0(s0)
wait_down:
    ld t0, 80(s0)
    bne t0, s4, wait_down
    ld t0, 24(s0)
    bnez t0, guest_fail
    ld t0, 8(s0)
    bne t0, s1, guest_fail
    li s6, 1024
    li s7, 1024
    jal ra, telemetry_check
    bnez s3, guest_done
    addi s0, s0, 128
    li s3, 1
    j boot_wait
guest_done:
    j guest_done
guest_fail:
    j guest_fail

# Real cache-miss DDR read, then coherent CPU/fabric snapshots through guest LD.
# Test-only window1024 AON edges; production remains50000. No configured-Hz
# register contributes to the measured-edge oracle below.
telemetry_check:
    mv s9, ra
    ld t0, 0(s5)
    li t1, 0x13579bdf2468ace0
    bne t0, t1, guest_fail
    addi s5, s5, 64
cpu_sample_retry:
    li a0, 0x10080900
    ld a1, 0(a0)
    ld t0, 40(a0)
    li t1, 0x544d002000000002
    bne t0, t1, guest_fail
    ld t0, 16(a0)
    bne t0, s1, guest_fail
    ld t0, 24(a0)
    li t1, 1024
    bne t0, t1, guest_fail
    ld a2, 8(a0)
    ld a3, 64(a0)
    ld a4, 136(a0)
    ld a5, 144(a0)
    ld a6, 152(a0)
    ld a7, 168(a0)
    ld t0, 0(a0)
    bne a1, t0, cpu_sample_retry
    andi a2, a2, 5
    li t0, 1
    bne a2, t0, cpu_sample_retry
    beqz a4, cpu_sample_retry
    beqz a5, cpu_sample_retry
    bleu a6, s10, cpu_sample_retry
    beqz a7, cpu_sample_retry
    addi t0, s6, -4
    bltu a3, t0, guest_fail
    addi t0, s6, 4
    bltu t0, a3, guest_fail
    mv s10, a6
fabric_sample_retry:
    li a0, 0x10080a00
    ld a1, 0(a0)
    ld a2, 8(a0)
    ld a3, 64(a0)
    ld a4, 136(a0)
    ld a5, 168(a0)
    ld t0, 0(a0)
    bne a1, t0, fabric_sample_retry
    andi a2, a2, 5
    li t0, 1
    bne a2, t0, fabric_sample_retry
    bleu a4, s11, fabric_sample_retry
    slli t0, a4, 3
    bne a5, t0, fabric_sample_retry
    addi t0, s7, -4
    bltu a3, t0, guest_fail
    addi t0, s7, 4
    bltu t0, a3, guest_fail
    mv s11, a4
    # Retired marker independently counted by the testbench, not a DUT force.
    addi zero, zero, 0x5a1
    jr s9
