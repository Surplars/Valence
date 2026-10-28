// Test-only common-host envelope. The included branch body is unchanged.
#include "branch-program.S"
.globl roi_begin, roi_end, benchmark_complete, benchmark_terminal
.set roi_begin, _start
roi_end:
    addi x0, x0, 0
benchmark_complete:
    addi x0, x0, 0
benchmark_terminal:
    ebreak
.rept 128
    addi x0, x0, 0
.endr
