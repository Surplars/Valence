.option norvc
.option norelax
.section .boot,"ax"
.globl _start
_start:
    csrw mie,zero
    csrw satp,zero
    csrw pmpcfg0,zero
    csrw pmpcfg2,zero
    la sp,__stack
    la gp,__global_pointer$
    la t0,perf_fail
    csrw mtvec,t0
    # Test-only external DDR preload supplies identical code/table bytes.
    fence.i
    call perf_main
    j perf_fail
.section .text.markers,"ax"
.globl mark_begin,mark_end,mark_crc_begin,mark_crc_end,perf_fail,perf_done
mark_begin: mv t6,a0
    ret
mark_end: mv t6,a0
    ret
mark_crc_begin: mv t6,a0
    ret
mark_crc_end: mv t6,a0
    ret
perf_fail: j perf_fail
perf_done: j perf_done
