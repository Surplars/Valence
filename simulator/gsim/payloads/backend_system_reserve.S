.option norvc
.section .text.start,"ax",@progbits
.globl _start
_start:
 li t0,-1
 csrw pmpaddr0,t0
 li t0,31
 csrw pmpcfg0,t0
 la t0,trap_stop
 csrw mtvec,t0
 li t0,0x8000000000080300
 csrw satp,t0
 sfence.vma x0,x0
 la t0,supervisor_start
 csrw mepc,t0
 li t0,(1<<11)
 csrw mstatus,t0
 mret
supervisor_start:
 li s0,0x40000000
 ld s1,0(s0)
 nop
 li t0,-1
 li t1,7
 divu t2,t0,t1
.globl reserve_csr
reserve_csr:
 csrw sscratch,t2
.globl younger_load
younger_load:
 ld s2,8(s0)
 li t0,0x80600000
 sd s2,0(t0)
 csrr t1,sscratch
 sd t1,8(t0)
 fence.i
 fence rw,rw
.globl terminal_ecall
terminal_ecall:
 ecall
trap_stop:
 j trap_stop
