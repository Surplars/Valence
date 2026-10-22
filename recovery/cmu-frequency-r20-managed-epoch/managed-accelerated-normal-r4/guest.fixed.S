# Real I1 network/Home epoch guest. TB initializes only the RAM boot selector;
# CPU owns all DMA configuration, dirty cache data and loader-control setup.
.option norvc
.option norelax
.section .text.start,"ax"
.globl _start, control_open, selector_load, guard_store, tx_init_store
.globl rx_arm, tx_start, configured, net_ready, heartbeat, check_command, rx_check_load, guard_check_load, tx_check_load, net_checked, guest_fail
_start:
    li s0, 0x10002000
    li s1, 0x10003000
    li t0, 1
control_open:
    sd t0, 8(s1)
    li t1, 0x80205000
selector_load:
    ld s2, 0(t1)
    li t1, 0x8020303c
    li t2, 0x55667788
    # RX writes exactly bytes0..59 of this dirty cache line; byte enables must
    # preserve this 32-bit neighboring guard at bytes60..63.
guard_store:
    sw t2, 0(t1)
    li t1, 0x80204000
    li t2, 0
    li t3, 60
1:
    addi t4, t2, 0x20
tx_init_store:
    sb t4, 0(t1)
    addi t1, t1, 1
    addi t2, t2, 1
    blt t2, t3, 1b
    beqz s2, 5f
    jal ra, timer_setup
5:
    bnez s2, 2f
    li t1, 0x80203000
    sd t1, 48(s0)
    li t1, 256
    sd t1, 56(s0)
    li t1, 1
rx_arm:
    sd t1, 64(s0)
    j configured
2:
    li t1, 0x80204000
    sd t1, 16(s0)
    li t1, 60
    sd t1, 24(s0)
    li t1, 1
tx_start:
    sd t1, 32(s0)
configured:
net_ready:
    li s3, 0
    bnez s2, 6f
    jal ra, timer_setup
6:
    li s4, 0x80205008
heartbeat:
    addi s3, s3, 1
.globl timer_heartbeat_read
timer_heartbeat_read:
    ld t6, 0(s6)
check_command:
    ld t0, 0(s4)
    beqz t0, heartbeat
    bnez s2, 3f
    li t1, 0x80203000
rx_check_load:
    ld t2, 0(t1)
    li t3, 0x8786858483828180
    bne t2, t3, guest_fail
    li t1, 0x8020303c
guard_check_load:
    lwu t2, 0(t1)
    li t3, 0x55667788
    bne t2, t3, guest_fail
    j net_checked
3:
    li t1, 0x80204000
tx_check_load:
    ld t2, 0(t1)
    li t3, 0x2726252423222120
    bne t2, t3, guest_fail
net_checked:
    addi s5, zero, 1
    li t1, 3
.globl managed_tx_restart
managed_tx_restart:
    sd t1, 32(s0)
4:
    j 4b
guest_fail:
    ebreak
    j guest_fail

timer_setup:
    li t1, 0x0200bff8
.globl timer_read, timer_compare_store, timer_compare_load
timer_read:
    ld t4, 0(t1)
    beqz t4, guest_fail
    li t1, 0x02004000
    li t4, 0
timer_compare_store:
    sd t4, 0(t1)
timer_compare_load:
    ld t5, 0(t1)
    bnez t5, guest_fail
    li s6, 0x0200bff8
    ret
