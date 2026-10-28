.option norvc
.option norelax
.section .text
.globl _start, roi_begin, roi_end, benchmark_complete, benchmark_terminal, self_pointer
_start:
 csrw mie, zero
 la t0, self_pointer
roi_begin:
 ld t0, 0(t0)
 .rept 63
 ld t0, 0(t0)
 .endr
roi_end:
 ld t0, 0(t0)
benchmark_complete:
benchmark_terminal:
 ebreak
 .rept 128
 nop
 .endr
.section .data
.balign 64
self_pointer:
 .dword self_pointer
 .zero 56
