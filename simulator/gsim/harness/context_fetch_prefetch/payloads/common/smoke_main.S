.section .text
.globl main
main:
addi sp,sp,-16
sd ra,0(sp)
call start_time
li t0,0x80208100
li t3,0x11
sd t3,0(t0)
li t0,0x8020c100
li t3,0x22
sd t3,0(t0)
li t0,0x80210100
li t3,0x33
sd t3,0(t0)
li t0,0x80214100
li t3,0x44
sd t3,0(t0)
li t0,0x80218100
li t3,0x55
sd t3,0(t0)
fence rw,rw
li s3,0
li t0,0x80208100
li t1,0x11
li t2,5
smoke_loop:
ld s0,0(t0)
bne s0,t1,smoke_fail
add s3,s3,s0
li t4,0x4000
add t0,t0,t4
addi t1,t1,0x11
addi t2,t2,-1
bnez t2,smoke_loop
li s4,0xff
bne s3,s4,smoke_fail
li s5,0
j smoke_done
smoke_fail:
li s5,1
smoke_done:
call stop_time
la t0,bench_errors
sd s5,0(t0)
la t0,bench_crc_pack
li t1,0x1122334455
sd t1,0(t0)
la t0,bench_iterations
li t1,1
sd t1,0(t0)
la t0,bench_final
sd s3,0(t0)
la t0,bench_fields
li t1,63
sd t1,0(t0)
ld ra,0(sp)
addi sp,sp,16
ret
.section .bss
.balign 8
.globl bench_errors,bench_crc_pack,bench_iterations,bench_final,bench_fields
bench_errors: .zero 8
bench_crc_pack: .zero 8
bench_iterations: .zero 8
bench_final: .zero 8
bench_fields: .zero 8
