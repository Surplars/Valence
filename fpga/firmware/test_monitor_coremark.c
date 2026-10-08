#include <stdint.h>
#include "coremark.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
extern volatile int32_t seed4_volatile;
extern int coremark_main(void);
unsigned diagnostic_short=1;
static char output[16384];static unsigned used;
uint64_t diagnostic_port_test_tick(void){static uint64_t t;return t+=100;}
void diagnostic_port_test_putc(char c){assert(used<sizeof output-1);output[used++]=c;}
int main(void){seed4_volatile=1;coremark_main();
 assert(strstr(output,"2K performance run parameters"));
 assert(strstr(output,"0xe9f5")&&strstr(output,"0xe714")&&strstr(output,"0x1fd7")&&strstr(output,"0x8e3a"));
 assert(!strstr(output,"ERROR! list")&&!strstr(output,"ERROR! matrix")&&!strstr(output,"ERROR! state"));
 assert(!strstr(output,"Iterations/Sec")&&!strstr(output,"CoreMark 1.0"));
 assert(strstr(output,"COREMARK_SHORT_CRC_PASS")&&!strstr(output,"Errors detected"));
 fwrite(output,1,used,stdout);
 core_portable port;portable_init(&port,0,0);ee_printf("seedcrc : 0x%04x\n",0xe9f5);ee_printf("[%d]crclist : 0x%04x\n",0,0xe715);ee_printf("[%d]crcmatrix : 0x%04x\n",0,0x1fd7);ee_printf("[%d]crcstate : 0x%04x\n",0,0x8e3a);portable_fini(&port);assert(strstr(output,"COREMARK_SHORT_CRC_FAIL"));
 puts("MONITOR_COREMARK_SHORT_PASS standard2000=1 official_crc=1 score_suppressed=1 host_time_not_performance=1");return 0;}
