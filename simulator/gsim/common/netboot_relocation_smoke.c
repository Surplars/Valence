/* Test-only high-linked code. Production relocation and launch assembly unchanged. */
#include <stdint.h>
static volatile uint64_t initialized=0x123456789abcdef0ULL;
static volatile uint64_t cleared[16];
static const uint64_t constant=0xfedcba9876543210ULL;
static uint64_t function(uint64_t x){return x^constant;}
static uint64_t (* volatile pointer)(uint64_t)=function;
extern void stage_trap(void);
extern void stage_launch(uint32_t) __attribute__((noreturn));
static void check(int ok){if(!ok)stage_trap();}
void stage_main(void){
    uintptr_t sp,gp,mtvec;
    __asm__ volatile("mv %0,sp":"=r"(sp));
    __asm__ volatile("mv %0,gp":"=r"(gp));
    __asm__ volatile("csrr %0,mtvec":"=r"(mtvec));
    check(sp>=0xffe1c000UL && sp<=0xffe20000UL);
    check(gp>=0xffe00000UL && gp<0xffe1c000UL);
    check(mtvec==(uintptr_t)stage_trap);
    check((uintptr_t)&initialized>=0xffe00000UL);
    check(initialized==0x123456789abcdef0ULL);
    for(unsigned i=0;i<16;i++)check(cleared[i]==0);
    check((uintptr_t)pointer>=0xffe00000UL);
    check(pointer(initialized)==0xece8ece0ece8ece0ULL);
    initialized=0x55aa55aa55aa55aaULL;
    check(initialized==0x55aa55aa55aa55aaULL);
    stage_launch(0x80210000U);
}
