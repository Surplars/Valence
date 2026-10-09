/* Reconstructed header: ABI offsets are recovered; file identity is new. */
#ifndef RECOVERED_MMU_DIAGNOSTIC_H
#define RECOVERED_MMU_DIAGNOSTIC_H
#define MMU_CAUSE 0
#define MMU_TVAL 8
#define MMU_EPC 16
#define MMU_TRAP_SP 24
#define MMU_RETURN 32
#define MMU_SATP 40
#define MMU_STACK 48
#ifndef __ASSEMBLER__
#include <stdint.h>
struct mmu_run {
    uint64_t cause,tval,epc,trap_sp,returned,satp,stack;
    volatile uint64_t *source,*destination;
    uint64_t count,passes,sweep,operation,ticks,tail,sum;
};
void mmu_diagnostic_enter(struct mmu_run *);
void mmu_diagnostic_supervisor_entry(void);
void mmu_diagnostic_return_ecall(void);
void mmu_diagnostic_supervisor(struct mmu_run *);
int mmu_diagnostic(void);
#endif
#endif
