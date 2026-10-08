/* Same kernels as the existing DDR application, one bounded 64KiB working set.
 * Cold preparation, verification and UART stay outside the marker intervals. */
#define main archived_ddr_bench_main
#include "../../../fpga/firmware/ddr_bench.c"
#undef main
__attribute__((noinline, noclone)) static uint64_t steady_start(void) {
    uint64_t v; __asm__ volatile("fence rw,rw\nrdtime %0" : "=r"(v) :: "memory"); return v;
}
__attribute__((noinline, noclone)) static uint64_t steady_stop(void) {
    uint64_t v; __asm__ volatile("fence rw,rw\nrdtime %0\nnop" : "=r"(v) :: "memory"); return v;
}
static void result(const char *phase, uint64_t kernel, uint64_t tail, uint64_t complete, int ok) {
    if (!ok || !kernel || complete < kernel + tail) ++errors;
    text("STEADY phase="); text(phase); text(" bytes=65536 reps=3 kernel="); decimal(kernel);
    text(" flush_tail="); decimal(tail); text(" complete="); decimal(complete);
    text(ok && kernel ? " PASS\r\n" : " FAIL\r\n");
}
int main(void) {
    volatile uint64_t *src=(volatile uint64_t *)SRC_BASE, *dst=(volatile uint64_t *)DST_BASE;
    const size_t bytes=65536, words=bytes/8;
    uint64_t begin, end, tail_begin, tail_end, sum;
    errors=0;
    stream_write(src,words,1); sync_ddr();
    observed=stream_read(src,words,1); /* full traversal before steady repeated stream */
    begin=steady_start(); sum=stream_read(src,words,3); end=steady_stop(); observed=sum;
    result("read",end-begin,0,end-begin,sum==expected_sum(words,3));
    for(size_t i=0;i<words;++i) src[i]=~(SEED+i); /* dirty poison, no hidden final eviction */
    begin=steady_start(); stream_write(src,words,3); end=steady_stop();
    tail_begin=steady_start(); sync_ddr(); tail_end=steady_stop();
    result("write",end-begin,tail_end-tail_begin,tail_end-begin,verify(src,words));
    for(size_t i=0;i<words;++i) dst[i]=~(SEED+i);
    sync_ddr(); observed=stream_read(src,words,1);
    begin=steady_start(); stream_copy(dst,src,words,3); end=steady_stop();
    tail_begin=steady_start(); sync_ddr(); tail_end=steady_stop();
    result("copy",end-begin,tail_end-tail_begin,tail_end-begin,verify(dst,words));
    build_chain(CHAIN_BASE,bytes); sync_ddr(); observed=walk_chain(CHAIN_BASE,bytes/64);
    begin=steady_start(); uintptr_t last=walk_chain(CHAIN_BASE,3*bytes/64); end=steady_stop(); observed=last;
    result("chase",end-begin,0,end-begin,last==CHAIN_BASE);
    sync_ddr(); text(errors ? "STEADY FAIL\r\n" : "STEADY PASS\r\n");
    return 0;
}
