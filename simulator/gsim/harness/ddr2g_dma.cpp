#include "MemoryCopyDma.h"
#include <deque>
#include <iostream>
#include <map>
#include <random>
#include <stdexcept>
#include <tuple>
static void require(bool b, const char *m) { if (!b) throw std::runtime_error(m); }
struct Test {
    SMemoryCopyDma d;
    std::map<uint64_t,uint64_t> mem;
    struct Reply { unsigned due; uint64_t data; };
    std::deque<Reply> replies;
    std::mt19937 rng{7219};
    unsigned cycle=0, requests=0, peak=0;
    bool held=false;
    std::tuple<uint64_t,uint64_t,bool> offer;
    Test() {
        d.set_io$$control$$request$$valid(0); d.set_io$$control$$response$$ready(0);
        d.set_io$$control$$request$$bits$$size(3); d.set_io$$control$$request$$bits$$byteEnable(255);
        d.set_reset(1); tick(); tick(); d.set_reset(0);
    }
    void tick() {
        bool ready=rng()%4!=0, valid=!replies.empty()&&replies.front().due<=cycle;
        d.set_io$$memory$$request$$ready(ready); d.set_io$$memory$$response$$valid(valid);
        d.set_io$$memory$$response$$bits$$data(valid?replies.front().data:0);
        d.set_io$$memory$$response$$bits$$error(0);
        d.step(); ++cycle;
        if(valid&&d.get_io$$memory$$response$$ready()) replies.pop_front();
        auto next=std::make_tuple(uint64_t(d.get_io$$memory$$request$$bits$$address()),
             uint64_t(d.get_io$$memory$$request$$bits$$data()),bool(d.get_io$$memory$$request$$bits$$write()));
        if(held) require(d.get_io$$memory$$request$$valid()&&offer==next,"held DMA changed");
        held=d.get_io$$memory$$request$$valid()&&!ready; offer=next;
        if(d.get_io$$memory$$request$$valid()&&ready) {
            auto [address,data,write]=next;
            require(address>=0x80200000ULL&&address<=0x1001ffff8ULL&&!(address&7),"DMA narrowed/out-of-range address");
            require(d.get_io$$memory$$request$$bits$$size()==3&&d.get_io$$memory$$request$$bits$$byteEnable()==255,"DMA access width");
            if(write) mem[address]=data;
            replies.push_back({cycle+6+unsigned(rng()%5),write?0:mem[address]});
            ++requests; peak=std::max(peak,unsigned(replies.size()));
            require(replies.size()<=4,"DMA credit overflow");
        }
        if(d.get_io$$irq()) require(replies.empty()&&!held,"early DMA IRQ");
    }
    uint64_t reg(unsigned offset, bool write=false, uint64_t value=0) {
        d.set_io$$control$$request$$bits$$address(0x10001000+offset);
        d.set_io$$control$$request$$bits$$write(write);d.set_io$$control$$request$$bits$$data(value);
        d.set_io$$control$$request$$valid(1);
        unsigned limit=cycle+500;
        do{tick();require(cycle<limit,"DMA CSR accept timeout");}while(!d.get_io$$control$$request$$ready());
        d.set_io$$control$$request$$valid(0);
        do{tick();require(cycle<limit,"DMA CSR reply timeout");}while(!d.get_io$$control$$response$$valid());
        require(!d.get_io$$control$$response$$bits$$error(),"DMA CSR error");
        uint64_t result=d.get_io$$control$$response$$bits$$data();
        d.set_io$$control$$response$$ready(1);tick();d.set_io$$control$$response$$ready(0);
        return result;
    }
    void copy(uint64_t src,uint64_t dst,uint64_t bytes,bool error=false) {
        reg(0,true,src);reg(8,true,dst);reg(16,true,bytes);reg(24,true,7);
        unsigned limit=cycle+20000;
        while(!d.get_io$$irq()){tick();require(cycle<limit,"DMA drain timeout");}
        require(reg(32)==(error?6:2),"DMA status mismatch");
        reg(24,true,2);tick();require(!d.get_io$$irq(),"DMA IRQ not cleared");
    }
};
int main(int argc,char**) {
    try {
        Test t; unsigned cases=0;
        for(auto [src,dst,bytes] : {
            std::tuple<uint64_t,uint64_t,unsigned>{0x80200000ULL,0x100000000ULL,512},
            {0xffffff00ULL,0x100001000ULL,512},
            {0x100001000ULL,0x80201000ULL,512},
            {0x80201000ULL,0x1001ffe00ULL,512}}) {
            for(unsigned n=0;n<bytes;n+=8) t.mem[src+n]=0xabcdef0123456789ULL^(src+n);
            auto expected=t.mem; for(unsigned n=0;n<bytes;n+=8) expected[dst+n]=t.mem[src+n];
            if(argc>1) expected[dst]^=1;
            t.copy(src,dst,bytes);require(t.mem==expected,"DDR2G DMA independent data oracle");++cases;
        }
        for(auto [src,dst,bytes] : {
            std::tuple<uint64_t,uint64_t,uint64_t>{0x80200000ULL,0x1001ffff8ULL,16},
            {0x80200000ULL,0x100200000ULL,8},
            {0x80200000ULL,0x180200000ULL,8},
            {0xfffffffffffffff8ULL,0x80201000ULL,16},
            {0x80200000ULL,0x80201000ULL,0x80000000ULL},
            {0x100000000ULL,0x100000008ULL,64}}) {
            auto before=t.requests; t.copy(src,dst,bytes,true);
            require(t.requests==before,"invalid DMA descriptor touched memory");++cases;
        }
        require(t.peak==4,"missing four-credit coverage");
        std::cout<<"DDR2G DMA PASS cases="<<cases<<" requests="<<t.requests<<" peak="<<t.peak<<"\n";
    } catch(const std::exception&e) { std::cerr<<e.what()<<"\n";return 1; }
}
