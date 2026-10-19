/* One native binary, both CMU CPU profiles; independent integer arithmetic oracle. */
#define BOARD_CMU_CLOCKS 1
#define VALENCE_CMU_TEST 1
#define TIMEBASE_HZ 250000000 /* Deliberately no ULL suffix: catch 32-bit products. */
#define main original_menu_main
#include "test_bootrom_menu.c"
#undef main
static uint64_t cmu[128];
static unsigned cmu_reads;
uint64_t valence_cmu_test_read(unsigned offset) {
    assert(!(offset & 7) && offset / 8 < sizeof cmu / sizeof cmu[0]);
    ++cmu_reads;
    return cmu[offset / 8];
}
static void set_cmu(uint64_t cpu) {
    memset(cmu,0,sizeof cmu);
    cmu[0]=VALENCE_CMU_ID;cmu[1]=(UINT64_C(50000000)<<32)|(7<<16)|7;
    cmu[2]=0x7f;
    const uint64_t clocks[]={50000000,cpu,250000000,50000000,250000000,125000000,125000000};
    for(unsigned n=0;n<7;n++){
        cmu[(0x100+n*0x40)/8]=n;
        cmu[(0x108+n*0x40)/8]=clocks[n];
        cmu[(0x110+n*0x40)/8]=1;
    }
}
int main(void) {
    for(unsigned profile=0;profile<2;profile++) {
        uint64_t cpu=profile?300000000:100000000;
        set_cmu(cpu);
        assert(CPU_CLOCK_HZ==cpu && valence_cmu_nominal_hz(CMU_FABRIC)==250000000);
        assert(valence_cmu_nominal_hz(CMU_DDR_UI)==250000000);
        assert(!original_menu_main(0,0));
        reset();monitor_info();
        assert(has(profile?"cpu_clock_hz=0x0000000011e1a300":"cpu_clock_hz=0x0000000005f5e100"));
        assert(has("timebase_hz=0x000000000ee6b280"));
        assert(has("cpu_clock_source=CMU_nominal cpu_identity=unspecified"));
    }
    assert(board_seconds_to_ticks(10)==UINT64_C(2500000000));
    assert(board_seconds_to_ticks(20)==UINT64_C(5000000000));
    assert(board_seconds_to_ticks(60)==UINT64_C(15000000000));
    /* Intervals beyond the old ticks*1e9 overflow and above 32-bit tick range. */
    const uint64_t ticks[]={0,1,249999999,250000000,250000001,UINT64_C(5000000000),
        UINT64_C(60000000000),UINT64_C(3600000000000),UINT64_MAX};
    const unsigned units[]={1000,1000000,1000000000};
    unsigned arithmetic=0;
    for(unsigned t=0;t<sizeof ticks/sizeof ticks[0];t++) {
        for(unsigned u=0;u<sizeof units/sizeof units[0];u++) {
            __uint128_t expected=(__uint128_t)ticks[t]*units[u]/250000000;
            assert(board_ticks_to_units(ticks[t],units[u])==(expected>UINT64_MAX?UINT64_MAX:(uint64_t)expected));
            ++arithmetic;
        }
        for(uint64_t bytes=8192;bytes<=16777216;bytes*=2) {
            uint64_t expected=ticks[t]?(__uint128_t)bytes*250000000*1000/ticks[t]/1048576:0;
            assert(board_milli_mib_per_second(bytes,ticks[t])==expected);++arithmetic;
        }
    }
    unsigned negative=0;
    set_cmu(300000000);cmu[0]^=1;assert(CPU_CLOCK_HZ==0);++negative;
    set_cmu(300000000);cmu[1]=1<<16;assert(CPU_CLOCK_HZ==0);++negative;
    set_cmu(300000000);cmu[2]&=~UINT64_C(2);assert(CPU_CLOCK_HZ==0);++negative;
    set_cmu(300000000);cmu[0x140/8]=2;assert(CPU_CLOCK_HZ==0);++negative;
    set_cmu(300000000);cmu[0x150/8]=0;assert(CPU_CLOCK_HZ==0);++negative;
    set_cmu(UINT64_C(1)<<32);assert(CPU_CLOCK_HZ==0);++negative;
    set_cmu(0);assert(CPU_CLOCK_HZ==0);++negative;
    cmu_reads=0;assert(valence_cmu_nominal_hz(16)==0 && cmu_reads==0);++negative;
    printf("SHARED_ROM_CLOCKS_PASS profiles=2 same_native_binary=1 arithmetic=%u negative=%u timebase=250000000 host_only=1\n",arithmetic,negative);
    return 0;
}
