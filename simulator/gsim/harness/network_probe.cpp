#include "NetworkProbeGsim.h"
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <stdexcept>
#define S(n,v) d.set_io$$##n(v)
#define G(n) d.get_io$$##n()
static void check(bool ok,const char* m) { if(!ok) throw std::runtime_error(m); }
static constexpr uint64_t base=0x80200000ULL, dirty=0x8877665544332211ULL;
struct Reply { unsigned due; uint64_t data; };
struct Test {
    SNetworkProbeGsim d;
    std::array<uint8_t,8192> memory{};
    std::deque<Reply> replies;
    unsigned cycle=0,cpuCount=0,dmaCount=0,bypassCount=0;
    uint64_t cpuData=0,dmaData=0;
    bool cpuReady=true,dmaReady=true;
    Test() {
        for(unsigned i=0;i<memory.size();++i) memory[i]=uint8_t(i*13+5);
        S(cpu$$request$$valid,0); S(dma$$request$$valid,0); S(holdProbe,0);
#define INIT(p) S(p##$$request$$bits$$address,base); S(p##$$request$$bits$$size,3); \
        S(p##$$request$$bits$$mask,255); S(p##$$request$$bits$$write,0); \
        S(p##$$request$$bits$$data,0); S(p##$$request$$bits$$atomic,0); \
        S(p##$$request$$bits$$atomicOp,0); S(p##$$request$$bits$$uncached,0); \
        S(p##$$request$$bits$$virtualized,0)
        INIT(cpu); INIT(dma);
        d.set_reset(1); tick(); tick(); d.set_reset(0);
    }
    uint64_t word(unsigned offset) const {
        uint64_t v=0; for(unsigned i=0;i<8;++i) v|=uint64_t(memory.at(offset+i))<<(8*i); return v;
    }
    void tick() {
        bool ready=cycle%5!=0, valid=!replies.empty() && cycle>=replies.front().due;
        S(memory$$request$$ready,ready); S(memory$$response$$valid,valid);
        S(memory$$response$$bits$$data,valid?replies.front().data:0); S(memory$$response$$bits$$error,0);
        S(cpu$$response$$ready,cpuReady); S(dma$$response$$ready,dmaReady);
        d.step(); ++cycle;
        if(valid&&G(memory$$response$$ready)) replies.pop_front();
        if(G(memory$$request$$valid)&&ready) {
            uint64_t address=G(memory$$request$$bits$$address); unsigned n=1U<<G(memory$$request$$bits$$size);
            check(address>=base && address+n<=base+memory.size() && n<=8,"backing memory address/size");
            unsigned off=address-base; uint64_t v=word(off);
            if(G(memory$$request$$bits$$write)) {
                unsigned mask=G(memory$$request$$bits$$byteEnable); auto data=G(memory$$request$$bits$$data);
                for(unsigned i=0;i<8;++i) if(mask&(1U<<i)) memory.at(off+i)=data>>(8*i);
                v=0;
            }
            replies.push_back({cycle+7+cycle%4,v});
        }
        if(G(cpu$$response$$valid)&&cpuReady) {
            check(!G(cpu$$response$$bits$$error)&&!G(cpu$$response$$bits$$pageFault),"CPU response fault");
            cpuData=G(cpu$$response$$bits$$data); ++cpuCount;
        }
        if(G(dma$$response$$valid)&&dmaReady) {
            check(!G(dma$$response$$bits$$error),"DMA response fault");
            dmaData=G(dma$$response$$bits$$data); ++dmaCount;
        }
        bypassCount+=G(bypassPending);
    }
    void cpuAccess(uint64_t address,bool write=false,uint64_t data=0) {
        S(cpu$$request$$bits$$address,address); S(cpu$$request$$bits$$write,write);
        S(cpu$$request$$bits$$data,data); S(cpu$$request$$valid,1);
        unsigned start=cycle,target=cpuCount+1;
        do { tick(); check(cycle-start<2000,"CPU request timeout"); } while(!G(cpu$$request$$ready));
        S(cpu$$request$$valid,0);
        while(cpuCount!=target) { tick(); check(cycle-start<2000,"CPU response timeout"); }
    }
    void collision(bool atomic,bool dirtyLine,bool holdReply,bool negative) {
        uint64_t initial=word(0), y=word(64);
        cpuAccess(base); if(dirtyLine) cpuAccess(base,true,dirty);
        check(word(0)==initial,"dirty-cache witness absent");
        unsigned cpuTarget=cpuCount+1;
        S(holdProbe,1);
        S(dma$$request$$bits$$address,base); S(dma$$request$$valid,1);
        unsigned start=cycle;
        do { tick(); check(cycle-start<2000,"DMA enqueue timeout"); } while(!G(dma$$request$$ready));
        S(dma$$request$$valid,0);
        S(cpu$$request$$bits$$address,base+64); S(cpu$$request$$bits$$write,0);
        S(cpu$$request$$bits$$atomic,atomic); S(cpu$$request$$bits$$uncached,!atomic);
        S(cpu$$request$$valid,1);
        if(atomic) S(holdProbe,0); // AMO request.ready waits for the older DMA owner.
        do { tick(); check(cycle-start<2000,"CPU bypass enqueue timeout"); } while(!G(cpu$$request$$ready));
        S(cpu$$request$$valid,0);
        // Atomics exclude DMA until ordinary response owners have drained. Only
        // ordinary uncached CPU requests can be accepted behind this DMA read.
        if(!atomic) while(!bypassCount) { tick(); check(cycle-start<2000,"CPU bypass never reached FIFO"); }
        tick(); tick(); // CPU has entered response wait while DMA owns the home.
        S(holdProbe,0); cpuReady=!holdReply; dmaReady=!holdReply;
        for(unsigned n=0; n<80 && holdReply; ++n) tick();
        cpuReady=true; dmaReady=true;
        while(cpuCount<cpuTarget||dmaCount!=1) { tick(); check(cycle-start<2000,"DMA/CPU/home circular wait"); }
        uint64_t want=dirtyLine?dirty:initial; if(negative) want^=1;
        check(dmaData==want,"DMA independent dirty/clean byte oracle mismatch");
        check(cpuData==y,"CPU bypass response/order mismatch");
        S(cpu$$request$$bits$$atomic,0); S(cpu$$request$$bits$$uncached,0);
        cpuAccess(base); check(cpuData==(dirtyLine?dirty:initial),"probe/refill lost CPU data");
        check(replies.empty(),"accepted memory replies left pending");
    }
};
int main(int argc,char**) { try {
    unsigned cases=0;
    for(bool atomic:{false,true}) for(bool dirtyLine:{false,true}) for(bool hold:{false,true}) {
        Test t; t.collision(atomic,dirtyLine,hold,argc>1); ++cases;
    }
    std::cout<<"NETWORK_PROBE_FIFO_HOME_PASS cases="<<cases<<" independent_memory=1 bounded_cycles=2000\n";
    return 0;
} catch(const std::exception& e) { std::cerr<<"NETWORK_PROBE_FAIL "<<e.what()<<"\n"; return 1; } }
