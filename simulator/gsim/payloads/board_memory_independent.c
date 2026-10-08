/* Additional independent-line workload; does not replace standard streams. */
#define main archived_ddr_bench_main
#include "../../../fpga/firmware/ddr_bench.c"
#undef main
__attribute__((noinline, noclone)) static uint64_t steady_start(void) {
    uint64_t v; __asm__ volatile("fence rw,rw\nrdtime %0" : "=r"(v) :: "memory"); return v;
}
__attribute__((noinline, noclone)) static uint64_t steady_stop(void) {
    uint64_t v; __asm__ volatile("fence rw,rw\nrdtime %0\nnop" : "=r"(v) :: "memory"); return v;
}
__attribute__((noinline)) static uint64_t read_lines(unsigned repetitions) {
    const volatile uint64_t *p=(const volatile uint64_t *)SRC_BASE;
    uint64_t a=0,b=0;
    for(unsigned pass=0;pass<repetitions;++pass)
        for(unsigned i=0;i<8192;i+=16) { a+=p[i]; b+=p[i+8]; }
    return a+b;
}
int main(void) {
    stream_write((volatile uint64_t *)SRC_BASE,8192,1);sync_ddr();
    observed=read_lines(1);
    uint64_t begin=steady_start(),sum=read_lines(3),end=steady_stop();observed=sum;
    const uint64_t expected=(1024ULL*SEED+8ULL*1024*1023/2)*3;
    text("INDEPENDENT_LINES working_set=65536 payload_bytes=24576 line_reads=3072 reps=3 ticks=");decimal(end-begin);
    text(sum==expected&&end>begin ? " PASS\r\n" : " FAIL\r\n");
    sync_ddr();text(sum==expected&&end>begin ? "STEADY PASS\r\n" : "STEADY FAIL\r\n");
    return 0;
}
