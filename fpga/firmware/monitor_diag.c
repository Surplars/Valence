#include <stdint.h>
#include "board_memory.h"
#include "monitor_diag.h"
extern void run_image(uintptr_t entry);
extern uintptr_t saved_boot_sp;
extern const uint8_t monitor_diag_blob_start[],monitor_diag_blob_end[];
static void say(const char *s) {volatile uint8_t *u=(volatile uint8_t *)0x10000000UL;while(*s){while(!(u[5]&32)){}u[0]=(uint8_t)*s++;}}
int monitor_memory_dma_idle(void) {__asm__ volatile("fence iorw,iorw":::"memory");return !(*(volatile uint64_t *)0x10001020UL&1);}
void monitor_run_diagnostic(unsigned command,unsigned image_length) {
    if(monitor_external_state_untrusted()){say("EXTERNAL STATE LOCKED; BOARD RESET REQUIRED\r\n");return;}
    uintptr_t bytes=(uintptr_t)monitor_diag_blob_end-(uintptr_t)monitor_diag_blob_start;
    if(!monitor_memory_dma_idle()){say("MEMORY DMA BUSY; RESET REQUIRED\r\n");return;}
    if(!bytes||bytes>0x1c000UL||image_length>IMAGE_LIMIT||DIAG_BASE<0x80310000UL||
       DIAG_BASE+0x80000UL!=BOARD_MONITOR_BASE){say("DIAGNOSTIC RANGE REJECTED\r\n");return;}
    volatile uint8_t *dst=(volatile uint8_t *)DIAG_BASE;
    for(uintptr_t i=0;i<bytes;i++)dst[i]=monitor_diag_blob_start[i];
    for(uintptr_t i=0;i<bytes;i++)if(dst[i]!=monitor_diag_blob_start[i]){say("DIAGNOSTIC COPY VERIFY FAIL\r\n");return;}
    *(volatile uint64_t *)(DIAG_BASE+0x7ff00UL)=command;
    __asm__ volatile("fence rw,rw\nfence.i\nfence rw,rw":::"memory");
    uintptr_t before_sp,before_gp,after_sp,after_gp,status,satp,mie;
    __asm__ volatile("mv %0,sp\nmv %1,gp":"=r"(before_sp),"=r"(before_gp)::"memory");
    run_image(DIAG_BASE);
    __asm__ volatile("mv %0,sp\nmv %1,gp\ncsrr %2,mstatus\ncsrr %3,satp\ncsrr %4,mie":
        "=r"(after_sp),"=r"(after_gp),"=r"(status),"=r"(satp),"=r"(mie)::"memory");
    if(before_sp!=after_sp || before_gp!=after_gp || saved_boot_sp!=before_sp-128 ||
       after_sp<BOARD_MONITOR_BASE+8192 || after_sp>BOARD_MONITOR_BASE+16384 ||
       (status&0x20008UL) || satp || mie) {
        say("DIAGNOSTIC RETURN STATE FAIL; RESET REQUIRED\r\n");for(;;){}
    }
    say("DIAGNOSTIC RETURN STATE PASS sp_gp_saved_sp_mstatus_satp_mie=1\r\n");
    say("DIAGNOSTIC RETURN\r\n");
}
