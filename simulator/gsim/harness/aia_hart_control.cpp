#include "AiaHartControl.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>

// Independent specification oracle. Rank is computed by interrupt category rather
// than copying the DUT's priority-encoder structure or reading generated constants.
static unsigned rank(unsigned id) {
    if (id >= 40 && id <= 47) { unsigned n=47-id; return n+(n+1)/2; }
    if (id >= 20 && id <= 23) return 1+(23-id)*3;
    constexpr std::array<unsigned,11> standard{11,3,7,9,1,5,12,10,2,6,13};
    for (unsigned i=0;i<standard.size();++i) if (id==standard[i]) return 12+i;
    if (id >= 32 && id <= 39) { unsigned n=39-id; return 23+n+(n+1)/2; }
    if (id >= 16 && id <= 19) return 24+(19-id)*3;
    if (id==14 || id==15) return 35+id-14;
    if (id >= 24 && id <= 31) return 37+id-24;
    if (id >= 48) return 45+id-48;
    return id==0 ? 61 : id==4 ? 62 : 63;
}
static uint64_t physical(uint64_t mask) {
    if (!mask) return 0;
    unsigned best=0, bestRank=100;
    for (unsigned id=0;id<64;++id) if ((mask>>id)&1) {
        if (rank(id)<bestRank) { best=id; bestRank=rank(id); }
    }
    return (uint64_t(best)<<16)|1;
}
struct Candidate { unsigned id, priority; int order; };
static int priorityKey(const Candidate& c) {
    return c.priority ? int(c.priority) : c.order<0 ? -1 : 4096;
}
static uint64_t virtualTop(uint64_t pending,uint64_t enable,unsigned ctl,unsigned vgein,
                           bool validFile,unsigned topei,bool wrongPriority) {
    std::array<Candidate,65> candidates{};unsigned count=0;
    bool vti=(ctl>>30)&1;unsigned iid=(ctl>>16)&63,priority=ctl&255;
    uint64_t active=pending&enable;
    if (active&(uint64_t(1)<<9)) {
        unsigned external=256;
        if (validFile&&topei) external=topei&2047;
        else if (!vgein&&iid==9&&priority) external=priority;
        candidates[count++]={9,external,0};
    }
    if (vti) {
        if (iid!=9) candidates[count++]={iid,priority,((ctl>>9)&1)?1:-1};
    } else for (unsigned id=0;id<64;++id) {
        if (id!=9&&((active>>id)&1)) candidates[count++]={id,0,int(rank(id))-int(rank(9))};
    }
    if (!count) return 0;
    Candidate best=candidates[0];
    for (unsigned i=1;i<count;++i) {
        Candidate other=candidates[i];
        if (priorityKey(other)<priorityKey(best)||
            (priorityKey(other)==priorityKey(best)&&other.order<best.order)) best=other;
    }
    unsigned reported=1;
    if ((ctl>>8)&1) reported=best.priority ? (best.priority>255?255:best.priority) : best.order<0?0:255;
    if (wrongPriority && vti && iid==63 && priority==127) reported^=1;
    return (uint64_t(best.id)<<16)|reported;
}
struct Driver {
    SAiaHartControl d;
    unsigned ctl=0,checks=0;bool negative;
    Driver(bool wrong):negative(wrong) {
        d.set_io$$mCandidates(0);d.set_io$$hsCandidates(0);
        d.set_io$$vsip(0);d.set_io$$vsie(0);d.set_io$$vgein(0);
        d.set_io$$guestFileValid(0);d.set_io$$guestTopei(0);
        d.set_io$$commit(0);d.set_io$$hvictlWrite$$valid(0);d.set_io$$hvictlWrite$$bits(0);
        d.set_reset(1);d.step();d.step();d.set_reset(0);d.step();
        compare(d.get_io$$hvictl(),0,"reset hvictl");
    }
    void compare(uint64_t actual,uint64_t expected,const char* what) {
        ++checks;if(actual==expected)return;
        std::cerr<<what<<": check="<<checks<<" actual=0x"<<std::hex<<actual
                 <<" expected=0x"<<expected<<" hvictl=0x"<<ctl<<std::dec<<'\n';
        throw std::runtime_error("independent AIA hart control oracle");
    }
    void write(uint64_t value,bool commit=true,bool valid=true) {
        d.set_io$$commit(commit);d.set_io$$hvictlWrite$$valid(valid);
        d.set_io$$hvictlWrite$$bits(value);d.step();
        d.set_io$$hvictlWrite$$valid(0);d.step();
        if(commit&&valid)ctl=unsigned(value)&0x403f03ff;
        compare(d.get_io$$hvictl(),ctl,"hvictl WARL/commit");
        compare(d.get_io$$vti(),(ctl>>30)&1,"VTI export");
    }
    void sample(uint64_t m,uint64_t hs,uint64_t p,uint64_t e,unsigned vgein=0,
                bool validFile=false,unsigned identity=0) {
        unsigned topei=(identity<<16)|identity;
        d.set_io$$mCandidates(m);d.set_io$$hsCandidates(hs);
        d.set_io$$vsip(p);d.set_io$$vsie(e);d.set_io$$vgein(vgein);
        d.set_io$$guestFileValid(validFile);d.set_io$$guestTopei(topei);d.step();
        compare(d.get_io$$mtopi(),physical(m),"mtopi");
        compare(d.get_io$$stopi(),physical(hs),"stopi");
        compare(d.get_io$$vstopi(),virtualTop(p,e,ctl,vgein,validFile,topei,negative),"vstopi");
    }
};
static uint64_t random64(uint64_t& state) {
    state^=state<<13;state^=state>>7;state^=state<<17;return state;
}
int main(int argc,char**argv) { try {
    Driver t(argc>1&&std::string(argv[1])=="--wrong-priority");
    const uint64_t all=std::numeric_limits<uint64_t>::max(),sei=uint64_t(1)<<9;
    t.sample(0,0,0,0);t.write(all);t.write(0,false);t.write(0,true,false);t.write(0);
    for(unsigned bit=0;bit<64;++bit)t.write(uint64_t(1)<<bit);
    for(unsigned iid=0;iid<4096;++iid)t.write((uint64_t(iid)<<16)|0x400003ff);
    t.write(0);
    // Every single identity and all pairwise physical/normal-VS competitions.
    for(unsigned a=0;a<64;++a)for(unsigned b=0;b<64;++b) {
        uint64_t mask=(uint64_t(1)<<a)|(uint64_t(1)<<b);
        t.sample(mask,mask,mask,all);
    }
    // Explicit threshold edge values and invalid/no-guest fallback paths.
    constexpr std::array<unsigned,9> priorities{0,1,2,63,127,254,255,256,2047};
    for(unsigned iid=0;iid<64;++iid)for(unsigned p:priorities)if(p<256)
    for(unsigned vti=0;vti<2;++vti)for(unsigned dpr=0;dpr<2;++dpr)
    for(unsigned mode=0;mode<2;++mode) {
        t.write((vti<<30)|(iid<<16)|(dpr<<9)|(mode<<8)|p);
        t.sample(0,0,0,0); // VTI injection ignores both pending and enable masks.
        t.sample(0,0,sei,all,0,false,0);
        t.sample(0,0,sei,all,63,false,0); // Invalid nonzero VGEIN must use 256.
        t.sample(0,0,sei,all,1,true,0); // Valid but empty guest file also uses 256.
        for(unsigned ext:priorities)if(ext) {
            t.sample(0,0,sei,all,1,true,ext);
            t.sample(0,0,sei|2|32,all,1,true,ext);
        }
    }
    // Every IPRIO encoding and all six-bit injected IDs, at/either side of ties.
    for(unsigned p=0;p<256;++p)for(unsigned iid:std::array<unsigned,4>{0,9,43,63})
    for(unsigned dpr=0;dpr<2;++dpr) {
        t.write(0x40000100|(iid<<16)|(dpr<<9)|p);
        for(unsigned ext:std::array<unsigned,3>{p?p-1:1,p?p:1,p+1})
            t.sample(0,0,sei,all,1,true,ext);
    }
    uint64_t seed=0xa1a100c0ffee1234ULL;
    for(unsigned n=0;n<4096;++n) {
        t.write(random64(seed));
        uint64_t m=random64(seed),hs=random64(seed),p=random64(seed),e=random64(seed);
        unsigned guest=unsigned(random64(seed))&63;
        t.sample(m,hs,p,e,guest,guest>0&&guest<3,unsigned(random64(seed))&2047);
    }
    t.write(0);t.sample(0,0,0,0);
    std::cout<<"PASS AIA hart control: "<<t.checks<<" comparisons; bounded module-only GSIM coverage\n";
    return 0;
} catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;} }
