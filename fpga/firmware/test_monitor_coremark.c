#include <stdint.h>
#include "coremark.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
extern volatile int32_t seed4_volatile;
extern int coremark_main(void);
unsigned diagnostic_short=1;
static char output[16384];static unsigned used;
static uint64_t test_step=100;
uint64_t diagnostic_port_test_tick(void){static uint64_t t;return t+=test_step;}
void diagnostic_port_test_putc(char c){assert(used<sizeof output-1);output[used++]=c;}
int main(void){seed4_volatile=1;coremark_main();
 assert(strstr(output,"2K performance run parameters"));
 assert(strstr(output,"0xe9f5")&&strstr(output,"0xe714")&&strstr(output,"0x1fd7")&&strstr(output,"0x8e3a"));
 assert(!strstr(output,"ERROR! list")&&!strstr(output,"ERROR! matrix")&&!strstr(output,"ERROR! state"));
 assert(!strstr(output,"Iterations/Sec")&&!strstr(output,"CoreMark 1.0"));
 assert(strstr(output,"COREMARK_SHORT_CRC_PASS")&&!strstr(output,"Errors detected"));
 fwrite(output,1,used,stdout);
 core_portable port;portable_init(&port,0,0);ee_printf("seedcrc : 0x%04x\n",0xe9f5);ee_printf("[%d]crclist : 0x%04x\n",0,0xe715);ee_printf("[%d]crcmatrix : 0x%04x\n",0,0x1fd7);ee_printf("[%d]crcstate : 0x%04x\n",0,0x8e3a);portable_fini(&port);assert(strstr(output,"COREMARK_SHORT_CRC_FAIL"));
 unsigned cases=0;
 const uint64_t durations[]={9999,10000,10001,10001,10001,10001};
 for(unsigned scenario=0;scenario<6;++scenario){
  used=0;memset(output,0,sizeof output);diagnostic_short=0;portable_init(&port,0,0);
  test_step=durations[scenario];start_time();stop_time();
  ee_printf("Iterations/Sec : %f\n",1.0); /* Never publish a provisional score. */
  if(scenario!=4)ee_printf("seedcrc : 0x%04x\n",0xe9f5);
  ee_printf("[%d]crclist : 0x%04x\n",0,scenario==3?0xe715:0xe714);
  ee_printf("[%d]crcmatrix : 0x%04x\n",0,0x1fd7);ee_printf("[%d]crcstate : 0x%04x\n",0,0x8e3a);
  if(scenario==5)ee_printf("ERROR! independent failure\n");
  ee_printf("Correct operation validated.\n");ee_printf("CoreMark 1.0 : %f",1.0);ee_printf(" / %s","test");ee_printf("\n");portable_fini(&port);
  assert(!strstr(output,"Iterations/Sec"));
  if(scenario==2){assert(strstr(output,"COREMARK_FORMAL_PASS")&&strstr(output,"CoreMark 1.0"));}
  else{assert(strstr(output,"COREMARK_FORMAL_FAIL")&&!strstr(output,"CoreMark 1.0")&&!strstr(output,"Correct operation validated"));}
  ++cases;
 }
 printf("MONITOR_COREMARK_FORMAL_GATE_PASS cases=%u strict_gt10s=1 all_crc_required=1 provisional_score_suppressed=1 host_not_performance=1\n",cases);
 puts("MONITOR_COREMARK_SHORT_PASS standard2000=1 official_crc=1 score_suppressed=1 host_time_not_performance=1");return 0;}
