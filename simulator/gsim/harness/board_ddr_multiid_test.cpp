// Host-memory-model unit test only; this does not simulate or substitute for RTL.
#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>
static void check(bool p, const char* m) { if (!p) throw std::runtime_error(m); }
struct Port {
    struct Address { uint64_t addr=0,id=0,len=0,size=3,burst=1; } ar,aw;
    bool arv=false,awv=false,wv=false,rr=false,br=false;
    bool arReady=false,awReady=false,wReady=false,rv=false,bv=false,rl=false,wl=false;
    uint64_t rd=0,rid=0,rresp=0,bid=0,bresp=0,wd=0,wm=255;
    bool get_io$$ddrAxi$$ar$$valid(){return arv;} bool get_io$$ddrAxi$$aw$$valid(){return awv;}
    bool get_io$$ddrAxi$$w$$valid(){return wv;} bool get_io$$ddrAxi$$r$$ready(){return rr;}
    bool get_io$$ddrAxi$$b$$ready(){return br;}
#define ADDR_GET(chan,field) uint64_t get_io$$ddrAxi$$##chan##$$bits$$##field(){return chan.field;}
    ADDR_GET(ar,addr) ADDR_GET(ar,id) ADDR_GET(ar,len) ADDR_GET(ar,size) ADDR_GET(ar,burst)
    ADDR_GET(aw,addr) ADDR_GET(aw,id) ADDR_GET(aw,len) ADDR_GET(aw,size) ADDR_GET(aw,burst)
#undef ADDR_GET
    uint64_t get_io$$ddrAxi$$w$$bits$$data(){return wd;}
    uint64_t get_io$$ddrAxi$$w$$bits$$strb(){return wm;}
    bool get_io$$ddrAxi$$w$$bits$$last(){return wl;}
#define SET(name,field) void set_io$$ddrAxi$$##name(uint64_t v){field=v;}
    SET(ar$$ready,arReady) SET(aw$$ready,awReady) SET(w$$ready,wReady)
    SET(r$$valid,rv) SET(r$$bits$$data,rd) SET(r$$bits$$id,rid) SET(r$$bits$$resp,rresp) SET(r$$bits$$last,rl)
    SET(b$$valid,bv) SET(b$$bits$$id,bid) SET(b$$bits$$resp,bresp)
#undef SET
};
#define BOARD_DDR_BYTES 0x80000000ULL
#include "board_ddr_multiid.h"
int main(int argc,char**argv) {
    try {
        DdrModel m; Port p; uint64_t cycle=0;
        auto tick=[&] {m.drive(p,cycle++);m.sample(p);};
        const std::string negative=argc>1?argv[1]:"";
        if(negative=="--bad-boundary") {DdrModel::address(4096-8,2,3,1);throw std::runtime_error("negative not rejected");}
        std::array<unsigned,4> returned{};
        for(unsigned n=0;n<4;++n)for(unsigned b=0;b<4;++b)m.memory[n*128+b*8]=0x1200000000000000ULL+n*16+b;
        m.denyReadAddress=256;
        for(unsigned n=0;n<4;++n) {
            p.ar={n*128,n,3,3,1};p.arv=true;
            do{tick();}while(!p.arReady);
        }
        p.arv=false;
        if(negative=="--duplicate-id") {
            p.ar={512,1,0,3,1};p.arv=true;do{tick();}while(!p.arReady);
            throw std::runtime_error("negative not rejected");
        }
        check(m.peakReadIds==4,"model did not own four IDs");
        // Stall oldest first response until all four IDs are eligible, then
        // demand independent per-ID beats in arbitrary cross-ID order.
        while(cycle<DDR_READ_LATENCY) {tick();check(!p.rv,"read latency shorter than configured");}
        while(cycle<DDR_READ_LATENCY+20)tick();
        auto held=std::make_tuple(p.rd,p.rid,p.rresp,p.rl);
        for(unsigned n=0;n<5;++n){tick();check(p.rv&&std::make_tuple(p.rd,p.rid,p.rresp,p.rl)==held,"R changed while stalled");}
        p.rr=true;
        while(!m.pendingReads.empty()) {
            m.drive(p,cycle++);
            if(p.rv) {
                check(p.rid<4,"unexpected RID");unsigned n=p.rid,b=returned[n]++;
                check(b<4&&p.rd==(0x1200000000000000ULL+n*16+b),"read byte oracle mismatch");
                check(p.rl==(b==3)&&p.rresp==((n==2&&b==3)?2:0),"read last/error timing mismatch");
            }
            m.sample(p);
        }
        for(auto n:returned)check(n==4,"read lost/duplicate beats");
        check(m.reorderedBeats>0,"model did not reorder IDs");
        // Two-beat partial write, late B, held B, read-after-write byte oracle.
        p.aw={1024,7,1,3,1};p.awv=true;m.denyWriteAddress=1024;
        do{tick();}while(!p.awReady);p.awv=false;
        p.ar={1024,5,1,3,1};p.arv=true;
        for(unsigned b=0;b<2;++b) {
            p.wv=true;p.wd=0xfedcba9876543210ULL+b;p.wm=b?0xaa:0x55;p.wl=b==1;
            do{tick();check(!p.arReady,"AR crossed exclusive write fence");}while(!p.wReady);
        }
        p.wv=false;
        do{tick();check(!p.arReady,"AR crossed B fence");}while(!p.bv);
        for(unsigned n=0;n<5;++n){tick();check(p.bv&&p.bid==7&&p.bresp==2&&!p.arReady,"B changed while stalled");}
        p.br=true;tick();p.br=false;
        do{tick();}while(!p.arReady);p.arv=false;
        unsigned b=0;
        while(!m.pendingReads.empty()) {
            m.drive(p,cycle++);
            if(p.rv){uint64_t expected=0;for(unsigned k=0;k<8;++k)if((b?0xaa:0x55)&(1<<k))expected|=(0xfedcba9876543210ULL+b)&(0xffULL<<(8*k));
                check(p.rd==expected&&p.rid==5&&p.rl==(b==1)&&p.rresp==0,"partial-write/read-after-write oracle mismatch");++b;}
            m.sample(p);
        }
        check(b==2&&m.reads==5&&m.writes==1,"transaction count mismatch");
        // Full-capacity admission and a waiting write cannot consume live IDs.
        DdrModel capacity;Port q;uint64_t c=0;
        for(unsigned n=0;n<DDR_READ_CREDITS;++n) {
            q.ar={n*64,n,0,3,1};q.arv=true;
            do{capacity.drive(q,c++);capacity.sample(q);}while(!q.arReady);
        }
        q.ar={4096,15,0,3,1};
        for(unsigned n=0;n<8;++n){capacity.drive(q,c++);check(!q.arReady,"read capacity exceeded");capacity.sample(q);}
        q.awv=true;q.aw={8192,0,0,3,1};capacity.drive(q,c++);
        check(!q.awReady&&!q.arReady,"waiting write crossed outstanding reads");capacity.sample(q);
        std::cout<<"MULTIID_MEMORY_MODEL_PASS reads="<<m.reads<<" writes="<<m.writes<<" peak="<<m.peakReadIds<<" reordered="<<m.reorderedBeats<<"\n";
    }catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}
}
