#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
extern int coremark_main(void);
extern volatile uint64_t bench_errors,bench_crc_pack,bench_iterations,bench_final,bench_fields;
void start_time(void){}
void stop_time(void){}
int main(int argc,char**argv){
 if(argc!=2)return 2;
 uint64_t expected=strtoull(argv[1],0,16);
 coremark_main();
 printf("errors=%llu crc_pack=%016llx iterations=%llu crc_final=%04llx fields=%llu\n",(unsigned long long)bench_errors,(unsigned long long)bench_crc_pack,(unsigned long long)bench_iterations,(unsigned long long)bench_final,(unsigned long long)bench_fields);
 return bench_errors||bench_crc_pack!=expected||bench_iterations!=1||bench_fields!=63;
}
