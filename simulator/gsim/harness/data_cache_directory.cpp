// Supplemental full-directory boundary witness using the same small RTL model.
#define main existing_dma_main
#include "ethernet_packet_dma.cpp"
#undef main
#ifndef DCACHE_CAPACITY
#error DCACHE_CAPACITY must be explicitly 32 or 64
#endif
static_assert(DCACHE_CAPACITY==32 || DCACHE_CAPACITY==64);
int main(int argc,char **argv) {
    try {
        for(unsigned seed:{17U,31U,919U}) {
            Test t(seed);
            const auto initial=t.memory;
            constexpr unsigned sets=DCACHE_CAPACITY/2;
            constexpr uint64_t stride=sets*64ULL;
            auto value=[](unsigned i){return 0x9182736455aa0000ULL^i;};
            for(unsigned i=0;i<DCACHE_CAPACITY;++i)t.cpuAccess(ram+64*i,true,value(i));
            check(t.reads==8*DCACHE_CAPACITY&&t.writes==0,"full-directory fill evicted or skipped a line");
            check(t.memory==initial,"dirty full-directory fill reached backing before probe");
            const uint64_t high=ram+64*(DCACHE_CAPACITY-1);
            auto reads=t.reads;
            check(t.cpuAccess(high)==value(DCACHE_CAPACITY-1)&&t.reads==reads,"high directory line did not remain resident");
            t.startTx(high,8);t.finish(false,false,true,false);
            std::vector<uint8_t> expected;
            for(unsigned b=0;b<8;++b)expected.push_back(value(DCACHE_CAPACITY-1)>>(8*b));
            if(argc>1)expected[0]^=1;
            check(t.dataOut==expected,"full-directory DMA independent byte mismatch");
            check(t.writes==8,"high directory probe did not write eight dirty beats");
            reads=t.reads;
            check(t.cpuAccess(high)==value(DCACHE_CAPACITY-1)&&t.reads==reads+8,"high owner failed probe invalidation/reacquire");
            // With high MRU, the first-way line of the same set is the dirty LRU.
            const uint64_t low=ram+64*(sets-1),extra=high+stride;
            const auto writes=t.writes;
            t.cpuAccess(extra,true,0xf0e1d2c3b4a59687ULL);
            check(t.writes==writes+8,"full-directory same-set dirty replacement missing");
            uint64_t backing=0;for(unsigned b=0;b<8;++b)backing|=uint64_t(t.memory[low-ram+b])<<(8*b);
            check(backing==value(sets-1),"full-directory replacement lost victim bytes");
            reads=t.reads;
            check(t.cpuAccess(low)==value(sets-1)&&t.reads==reads+8,"full-directory victim did not reacquire");
            std::cout<<"DCACHE_FULL_DIRECTORY_PASS lines="<<DCACHE_CAPACITY<<" highest_slot="<<DCACHE_CAPACITY-1
                     <<" seed="<<seed<<" fills="<<DCACHE_CAPACITY<<" initial_evictions=0 dirty_probe_beats=8 replacement=1 reacquire=1 cycles="<<t.cycle<<"\n";
        }
        return 0;
    } catch(const std::exception &e) {
        std::cerr<<"DCACHE_FULL_DIRECTORY_FAIL "<<e.what()<<"\n";return 1;
    }
}
