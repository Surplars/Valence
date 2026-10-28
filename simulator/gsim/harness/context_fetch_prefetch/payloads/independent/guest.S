.option norvc
.option norelax
.section .text
.globl _start, roi_begin, roi_end, benchmark_complete, benchmark_terminal, self_pointer
_start:
 csrw mie, zero
 la t0, self_pointer
roi_begin:
 ld x6, 0(t0)
 ld x7, 0(t0)
 ld x8, 0(t0)
 ld x9, 0(t0)
 ld x10, 0(t0)
 ld x11, 0(t0)
 ld x12, 0(t0)
 ld x13, 0(t0)
 ld x6, 0(t0)
 ld x7, 0(t0)
 ld x8, 0(t0)
 ld x9, 0(t0)
 ld x10, 0(t0)
 ld x11, 0(t0)
 ld x12, 0(t0)
 ld x13, 0(t0)
 ld x6, 0(t0)
 ld x7, 0(t0)
 ld x8, 0(t0)
 ld x9, 0(t0)
 ld x10, 0(t0)
 ld x11, 0(t0)
 ld x12, 0(t0)
 ld x13, 0(t0)
 ld x6, 0(t0)
 ld x7, 0(t0)
 ld x8, 0(t0)
 ld x9, 0(t0)
 ld x10, 0(t0)
 ld x11, 0(t0)
 ld x12, 0(t0)
 ld x13, 0(t0)
 ld x6, 0(t0)
 ld x7, 0(t0)
 ld x8, 0(t0)
 ld x9, 0(t0)
 ld x10, 0(t0)
 ld x11, 0(t0)
 ld x12, 0(t0)
 ld x13, 0(t0)
 ld x6, 0(t0)
 ld x7, 0(t0)
 ld x8, 0(t0)
 ld x9, 0(t0)
 ld x10, 0(t0)
 ld x11, 0(t0)
 ld x12, 0(t0)
 ld x13, 0(t0)
 ld x6, 0(t0)
 ld x7, 0(t0)
 ld x8, 0(t0)
 ld x9, 0(t0)
 ld x10, 0(t0)
 ld x11, 0(t0)
 ld x12, 0(t0)
 ld x13, 0(t0)
 ld x6, 0(t0)
 ld x7, 0(t0)
 ld x8, 0(t0)
 ld x9, 0(t0)
 ld x10, 0(t0)
 ld x11, 0(t0)
 ld x12, 0(t0)
 ld x13, 0(t0)
roi_end:
 ld x6, 0(t0)
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
