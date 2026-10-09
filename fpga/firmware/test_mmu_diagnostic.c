/* New recovery-only native checks. These do not execute RISC-V privilege code. */
#define MMU_DIAGNOSTIC_TEST 1
#include "mmu_diagnostic.c"
#include <assert.h>
#include <stdio.h>
unsigned mmu_test_drop_read,mmu_test_drop_write;
static uint64_t fake_time,flushes;
uint64_t mmu_test_tick(void){return ++fake_time;}
void mmu_test_flush(void){++flushes;}
static uint64_t a[16384],b[16384],tables[2048];
static uint64_t want(uint64_t n){return UINT64_C(0x729ad0513fe68bc4)^(n*UINT64_C(0x0102040810204081));}
static int oracle(const struct mmu_run*r){
    uint64_t sum=0;
    for(uint64_t n=0;n<r->count;n++)sum+=want(r->sweep?n*520:n);
    if(!r->operation&&r->sum!=sum*r->passes)return 0;
    for(uint64_t n=0;n<16384;n++){
        unsigned touched=r->sweep?(n%520==0&&n/520<r->count):n<r->count;
        uint64_t aw=(r->operation==1&&!touched)?~want(n):want(n);
        uint64_t bw=(r->operation==2&&touched)?want(n):~want(n);
        if(a[n]!=aw||b[n]!=bw)return 0;
    }
    return 1;
}
static void initialize(unsigned op){for(unsigned n=0;n<16384;n++){a[n]=op==1?~want(n):want(n);b[n]=~want(n);}}
static unsigned page_tables(void){
    const uint64_t sizes[]={0x20000000ULL,0x40000000ULL,0x80000000ULL};unsigned cases=0;
    for(unsigned z=0;z<3;z++)for(unsigned huge=0;huge<2;huge++){
        uint64_t monitor=RAM_BASE+sizes[z]-0x4000ULL;
        if(monitor>0xffff8000ULL)monitor=0xffff8000ULL;
        uint64_t base=monitor-0x80000ULL,pa=base+0x20000,pb=base+0x40000,pt=base+0x60000;
        build_tables(tables,base,huge);
        for(unsigned n=0;n<2048;n++){
            uint64_t expected=0;
            if(n==base>>30)expected=((base&~0x3fffffffULL)>>2)|0xcf;
            if(n==1)expected=((pt+4096)>>2)|1;
            if(n==512)expected=huge?((pa&~0x1fffffULL)>>2)|0xc7:((pt+8192)>>2)|1;
            if(n==513)expected=huge?((pb&~0x1fffffULL)>>2)|0xc7:((pt+12288)>>2)|1;
            if(!huge&&n>=1024+((pa>>12)&511)&&n<1024+((pa>>12)&511)+32)expected=((pa+(n-1024-((pa>>12)&511))*4096)>>2)|0xc7;
            if(!huge&&n>=1536+((pb>>12)&511)&&n<1536+((pb>>12)&511)+32)expected=((pb+(n-1536-((pb>>12)&511))*4096)>>2)|0xc7;
            assert(tables[n]==expected);
        }++cases;
    }
    return cases;
}
int main(void){
    _Static_assert(sizeof(struct mmu_run)==128,"run ABI size");
    _Static_assert(offsetof(struct mmu_run,source)==56,"source ABI");
    _Static_assert(offsetof(struct mmu_run,destination)==64,"destination ABI");
    _Static_assert(offsetof(struct mmu_run,count)==72,"count ABI");
    _Static_assert(offsetof(struct mmu_run,passes)==80,"passes ABI");
    _Static_assert(offsetof(struct mmu_run,sweep)==88,"stride ABI");
    _Static_assert(offsetof(struct mmu_run,operation)==96,"operation ABI");
    _Static_assert(offsetof(struct mmu_run,ticks)==104,"ticks ABI");
    _Static_assert(offsetof(struct mmu_run,tail)==112,"tail ABI");
    _Static_assert(offsetof(struct mmu_run,sum)==120,"sum ABI");
    unsigned cases=0,negative=0;
    for(unsigned mode=0;mode<3;mode++)for(unsigned test=0;test<6;test++)for(unsigned op=0;op<3;op++){
        unsigned pages=test<2?0:4U<<(test-2);struct mmu_run r={0};
        r.source=a;r.destination=b;r.count=pages?pages:test?16384:1024;r.passes=pages?128:test?1:8;r.sweep=pages!=0;r.operation=op;
        initialize(op);flushes=0;mmu_diagnostic_supervisor(&r);
        assert(oracle(&r)&&verify(&r,a,b)&&r.ticks==1&&r.tail==(op?1:0)&&flushes==(op?1:0));++cases;
        b[14999]^=1;assert(!oracle(&r)&&!verify(&r,a,b));b[14999]^=1;++negative;
        initialize(op);mmu_test_drop_read=op==0;mmu_test_drop_write=op!=0;
        mmu_diagnostic_supervisor(&r);assert(!oracle(&r)&&!verify(&r,a,b));++negative;
        mmu_test_drop_read=mmu_test_drop_write=0;
    }
    assert(reject_context(0,0,0,0)==0);
    assert(reject_context(0x80,0,0,0)==1&&reject_context(0,0x8000,0,0)==1);
    assert(reject_context(0,0,8ULL<<60,0)==2&&reject_context(0,0,0,0x20000)==4&&reject_context(0,0,0,8)==8);
    assert(reject_context(0x80,0,8ULL<<60,0x20008)==15);
    printf("RECOVERY_NATIVE_PASS algorithm_cases=%u negative_checks=%u pte_layout_cases=%u context_predicate_cases=7 RISC_V_execution=0 original_ROM_identity=0\n",cases,negative,page_tables());
}
