.section .text.start,"ax",@progbits
.globl _start
_start:
.option push
.option norelax
la gp,__global_pointer$
.option pop
la sp,__stack_top
la t0,__bss_start
la t1,__bss_end
1: bgeu t0,t1,2f
sd zero,0(t0)
addi t0,t0,8
j 1b
2:
csrw mie,zero
call main
j benchmark_complete
.globl start_time,roi_begin
start_time:
roi_begin:
nop
ret
.globl stop_time,roi_end
stop_time:
roi_end:
nop
ret
.globl benchmark_complete
benchmark_complete:
la t0,bench_errors
ld a0,0(t0)
la t0,bench_crc_pack
ld a1,0(t0)
la t0,bench_iterations
ld a2,0(t0)
la t0,bench_final
ld a3,0(t0)
la t0,bench_fields
ld a4,0(t0)
li a5,0x434d41524b
.globl benchmark_terminal
benchmark_terminal:
ebreak
j benchmark_terminal
