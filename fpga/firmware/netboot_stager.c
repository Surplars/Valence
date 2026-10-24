/* Dedicated-boot RAM stage2, no clock change and no new network protocol.
 * All executable code/data/RX/stack is linked above the accepted image limit.
 * The existing verified (not pending) netboot path owns DMA drain + RAM CRC.
 */
#include <stdint.h>
#include "netboot.h"
#include "board_memory.h"
_Static_assert(BOARD_MONITOR_BASE==0xffe00000UL,"stager protection boundary");
_Static_assert(IMAGE_LIMIT==0x7fc00000UL,"stager image limit");
extern void stage_launch(uint32_t entry) __attribute__((noreturn));
static void message(const char *s) {
    volatile uint8_t *u=(volatile uint8_t *)0x10000000UL;
    while(*s){while(!(u[5]&0x20)){}u[0]=(uint8_t)*s++;}
}
void stage_main(void) {
    uint32_t entry=0,length=0;
    message("\r\nRAM NETBOOT STAGER CANDIDATE; CPU/fabric unchanged; reset required on failure.\r\n");
    message("Executing at FFE00000; requesting linux.vld into [80200000,FFE00000).\r\n");
    if(board_netboot(&entry,&length)!=1 || !length ||
       entry<RAM_BASE || (uint64_t)entry>=RAM_BASE+(uint64_t)length ||
       length>IMAGE_LIMIT || (entry&3) || !board_netboot_quiet()) {
        message("STAGER FAILED; no launch; reset required.\r\n");
        return;
    }
    message("STAGER RAM CRC VERIFIED; DMA quiet; launching checked payload.\r\n");
    board_netboot_jump(entry,length);
    /* Flush this brief message before transferring ownership. */
    volatile uint8_t *u=(volatile uint8_t *)0x10000000UL;
    while(!(u[5]&0x40)){}
    stage_launch(entry);
}
