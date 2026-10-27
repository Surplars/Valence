#include "IdentityFetchHorizonGsim.h"
#include <array>
#include <deque>
#include <map>
#include <optional>
#include <random>
#include <stdexcept>
#include <string>
#include <iostream>
#include <cstdint>
#ifndef IDENTITY_HORIZON_ENABLED
#define IDENTITY_HORIZON_ENABLED 1
#endif
namespace {
void need(bool x,const std::string& why) { if(!x) throw std::runtime_error(why); }
struct Packet { uint64_t data=0; unsigned errors=0,pages=0; };
struct Owner { uint64_t base=0; unsigned context=0,mask=0; bool stale=false; };
struct Entry { bool valid=false; uint64_t base=0; unsigned context=0; Packet packet; };
struct Input { uint64_t pc=0x80200000,limit=0; unsigned privilege=3,cfg=0; bool vm=false,enable=true,pause=false,invalidate=false,ready=true,reply=false; };
unsigned patternMode=0;
uint16_t half(uint64_t address) {
    if(patternMode==1)return 0x0001; // all compressed
    if(patternMode==2)return (address&2)?0x0123:0x0093; // all 32-bit
    // Address 6 is always a 32-bit low half, spanning the packet boundary.
    switch(address&7) {case 0:return 0x1234;case 2:return 0x0001;case 4:return 0x0085;default:return 0x0093;}
}
Packet payload(const Owner& o) {
    Packet p;
    for(unsigned i=0;i<4;++i)p.data|=uint64_t(half(o.base+2*i))<<(16*i);
    p.errors=(~o.mask)&3;
    // Word-selective injected transport faults, independent of DUT payload.
    if((o.base&0x1f8)==0x58)p.errors|=1;
    if((o.base&0x1f8)==0x78)p.errors|=2;
    if((o.base&0x1f8)==0x98)p.pages|=1;
    if((o.base&0x1f8)==0xb8)p.pages|=2;
    return p;
}
bool eligible(uint64_t base,bool vm) {
    if(!IDENTITY_HORIZON_ENABLED||vm)return false;
    using W=unsigned __int128; W lo=W(base)+16,hi=lo+7;
    if(hi>UINT64_MAX)return false;
    for(auto region:std::array<std::pair<uint64_t,uint64_t>,3>{{{0,4096},{0x80200000,8192},{0x180200000,8192}}})
        if(lo>=region.first&&hi<W(region.first)+region.second)return true;
    return false;
}
unsigned mask(const Input& i,uint64_t base) {
    // This fixture uses OFF or execute-allowed TOR only. M bypasses unlocked
    // matches; a locked execute-allowed match and an unmatched M access allow.
    if(i.vm || i.privilege==3)return 3;
    unsigned m=0;
    for(unsigned w=0;w<2;++w)if((i.cfg&0x1f)==0x0c && base+4*w<i.limit &&
        (unsigned __int128)(base+4*w)+4<=i.limit)m|=1U<<w;
    return m;
}
struct Model {
    std::array<std::array<Entry,2>,16> cache{};
    std::array<unsigned,16> replace{};
    std::deque<Owner> owners;
    std::optional<Owner> held;
    std::map<uint64_t,Packet> window;
    unsigned windowContext=0;
    unsigned cycles=0,offers=0,returns=0,third=0,heldCycles=0,turnover=0,full=0;
    unsigned faults=0,straddles=0,oldContextFill=0,invalidations=0;
    Entry* hit(uint64_t base,unsigned context) {
        auto& set=cache[(base>>3)&15];
        for(auto& e:set)if(e.valid&&e.base==base&&e.context==context)return &e;
        return nullptr;
    }
    void tick(SIdentityFetchHorizonGsim& d,const Input& i,const std::string& mutation) {
        const uint64_t base=i.pc&~7ULL;const unsigned context=(i.vm?4:0)|i.privilege;
        const bool reply=i.reply&&!owners.empty();
        const Owner ret=reply?owners.front():Owner{};
        const Packet data=payload(ret);
        std::map<uint64_t,Packet> queried;
        std::array<bool,3> covered{};
        for(unsigned k=0;k<3;++k) {
            const uint64_t at=base+8*k;
            if(auto* e=hit(at,context))queried.emplace(at,e->packet);
            else if(reply&&!ret.stale&&ret.context==context&&ret.base==at)queried.emplace(at,data);
            covered[k]=queried.count(at);
            for(const auto& o:owners)covered[k]|=!o.stale&&o.base==at&&o.context==context;
        }
        const bool guard=eligible(base,i.vm);
        unsigned pick=!covered[0]?0:(!covered[1]||!guard?1:2);
        bool all=covered[0]&&covered[1]&&(!guard||covered[2]);
        const bool credit=owners.size()<2||reply;
        const bool newOffer=i.enable&&!i.pause&&!i.invalidate&&credit&&!all;
        std::optional<Owner> expected=held;
        if(!expected&&newOffer)expected=Owner{base+8*pick,context,mask(i,base+8*pick),false};
        d.set_io$$pc(i.pc);d.set_io$$enable(i.enable);d.set_io$$pause(i.pause);
        d.set_io$$invalidate(i.invalidate);d.set_io$$privilege(i.privilege);d.set_io$$virtualized(i.vm);
        d.set_io$$pmpCfg0(i.cfg);d.set_io$$pmpAddr0(i.limit>>2);d.set_io$$requestReady(i.ready);
        d.set_io$$responseValid(reply);d.set_io$$responseData(data.data);
        d.set_io$$responseErrors(data.errors);d.set_io$$responsePages(data.pages);d.step();
        const std::string at=" cycle="+std::to_string(cycles)+" pc="+std::to_string(i.pc);
        bool gotValid=d.get_io$$requestValid();uint64_t gotAddress=d.get_io$$requestAddress();
        unsigned gotMask=d.get_io$$requestMask();
        if(mutation=="address"&&expected)gotAddress^=8;
        if(mutation=="third"&&expected&&pick==2&&!held)gotValid=false;
        if(mutation=="held"&&held)gotMask^=1;
        need(gotValid==bool(expected),"offer-valid"+at);
        if(expected)need(gotAddress==expected->base&&gotMask==expected->mask,"old-state address/mask"+at);
        need(d.get_io$$responseReady(),"response ready"+at);
        need(bool(d.get_io$$quiescent())==(owners.empty()&&!held),"quiescent"+at);
        // The previous edge's independently captured address-tagged window is
        // the only source for lane expectations; live response is not a bypass.
        auto get=[&](uint64_t address)->std::optional<Packet>{
            auto x=window.find(address&~7ULL);
            if(windowContext!=context||x==window.end()||i.invalidate)return {};
            return x->second;
        };
        uint64_t lanePc=i.pc;bool preceding=true;
        for(unsigned lane=0;lane<2;++lane) {
            auto a=get(lanePc),b=get(lanePc+2);
            unsigned h=a?unsigned(a->data>>((lanePc&7)*8))&65535:0;
            bool shortInsn=(h&3)!=3;
            bool valid=i.enable&&preceding&&bool(a)&&(shortInsn||bool(b));
            bool gv=lane?d.get_io$$lane1$$valid():d.get_io$$lane0$$valid();
            need(gv==valid,"registered window lane-valid"+at);
            if(valid) {
                unsigned hi=shortInsn?0:unsigned(b->data>>(((lanePc+2)&7)*8))&65535;
                uint32_t ins=h|(hi<<16);
                uint32_t got=lane?d.get_io$$lane1$$bits():d.get_io$$lane0$$bits();
                if(mutation=="data")got^=1;
                need(got==ins,"mixed-width instruction bytes"+at);
                bool e=(a->errors>>((lanePc>>2)&1))&1,p=(a->pages>>((lanePc>>2)&1))&1;
                bool firstFault=e||p;
                if(!shortInsn){e|=(b->errors>>(((lanePc+2)>>2)&1))&1;p|=(b->pages>>(((lanePc+2)>>2)&1))&1;}
                unsigned ge=(d.get_io$$errors()>>lane)&1,gp=(d.get_io$$pages()>>lane)&1;
                if(mutation=="fault"&&(e||p))ge^=1;
                need(ge==e&&gp==p,"precise selected word fault"+at);
                if(e||p) {
                    uint64_t tval=lane?d.get_io$$fault1():d.get_io$$fault0();
                    need(tval==(firstFault?lanePc:lanePc+2),"fault byte address"+at);++faults;
                }
                straddles+=!shortInsn&&(lanePc&7)==6;
            }
            preceding=valid;lanePc+=shortInsn?2:4;
        }
        if(held)++heldCycles;if(owners.size()==2)++full;
        if(reply&&expected&&i.ready)++turnover;
        if(i.invalidate) {for(auto& set:cache)for(auto& e:set)e.valid=false;for(auto& o:owners)o.stale=true;if(held)held->stale=true;++invalidations;}
        if(reply) {
            owners.pop_front();++returns;
            if(!ret.stale&&!i.invalidate) {
                auto& set=cache[(ret.base>>3)&15];unsigned index=(ret.base>>3)&15;
                unsigned victim;
                bool protect0=i.enable&&set[0].valid&&set[0].base==base&&set[0].context==context;
                bool protect1=i.enable&&set[1].valid&&set[1].base==base&&set[1].context==context;
                if(protect0)victim=1;else if(protect1)victim=0;
                else if(!set[0].valid)victim=0;else if(!set[1].valid)victim=1;else victim=replace[index];
                set[victim]={true,ret.base,ret.context,data};replace[index]=!victim;
                oldContextFill+=ret.context!=context;
            }
        }
        if(expected) {
            expected->stale|=i.invalidate||(held&&held->stale);
            if(i.ready) {owners.push_back(*expected);held.reset();++offers;if(!covered[2]&&guard&&expected->base==base+16)++third;}
            else if(!held)held=expected;
        }
        need(owners.size()+bool(held)<=2,"independent credit reservation");
        window=i.invalidate?std::map<uint64_t,Packet>{}:queried;windowContext=context;++cycles;
    }
};
void reset(SIdentityFetchHorizonGsim& d) {
    d.set_io$$pc(0);d.set_io$$enable(0);d.set_io$$pause(0);d.set_io$$invalidate(0);
    d.set_io$$privilege(3);d.set_io$$virtualized(0);d.set_io$$pmpCfg0(0);d.set_io$$pmpAddr0(0);
    d.set_io$$requestReady(0);d.set_io$$responseValid(0);d.set_io$$responseData(0);
    d.set_io$$responseErrors(0);d.set_io$$responsePages(0);d.set_reset(1);d.step();d.step();d.set_reset(0);
}
}
int main(int argc,char**argv) {try {
    std::string mutation=argc==2?argv[1]:"";
    need(argc<=2&&(mutation.empty()||mutation=="address"||mutation=="third"||mutation=="held"||mutation=="data"||mutation=="fault"),"bad mutation");
    SIdentityFetchHorizonGsim d;reset(d);Model m;
    auto run=[&](Input i,unsigned n){for(unsigned k=0;k<n;++k)m.tick(d,i,mutation);};
    Input i;
    run(i,3);i.reply=true;run(i,10); // two old owners, turnover into third, then quiet.
    i.pc+=6;run(i,6);i.pc=0x80200056;run(i,14); // straddle plus word0 fault.
    i.pc=0x80200076;run(i,14);i.pc=0x80200096;run(i,14);i.pc=0x802000b6;run(i,14);
    i.pc=0x80200400;i.ready=false;i.reply=false;run(i,2);
    i.pc=0x180200400;i.privilege=1;i.cfg=0x0c;i.limit=0x180200404;run(i,3);
    i.invalidate=true;run(i,1);i.invalidate=false;i.pause=true;i.ready=true;i.reply=true;run(i,8);
    i=Input{};i.reply=true;
    for(uint64_t pc:{0ULL,0xff0ULL,0xff8ULL,0x80200ff0ULL,0x80201ff0ULL,0x80201ff8ULL,
                    0x10000ULL,0x10000000ULL,0x280200000ULL,0xfffffffffffffff0ULL,0xfffffffffffffff8ULL}) {
        i.pc=pc;run(i,12);i.vm=true;i.privilege=1;run(i,12);i.vm=false;i.privilege=3;
    }
    // Same identity RAM across a page boundary, with each word's own TOR permission.
    for(unsigned privilege:{1U,0U,3U})for(unsigned offset:{0U,4U,8U,12U,16U,20U,24U}) {
        i.pc=0x80200ff0;i.privilege=privilege;i.cfg=0x8c;i.limit=i.pc+offset;
        i.invalidate=true;run(i,1);i.invalidate=false;run(i,14);
    }
    std::mt19937_64 rng(0xb8f219);
    for(unsigned cycle=0;cycle<12000;++cycle) {
        if(cycle%19==0) {i.pc=(cycle%3==0?0x180200000ULL:0x80200000ULL)+((rng()%1024)&~1ULL);
            i.privilege=unsigned(rng()%4);i.vm=(rng()%5)==0;i.cfg=(rng()%2)?0x8c:0;
            i.limit=(i.pc&~7ULL)+4*(rng()%9);}
        else if(cycle%7==0)i.pc+=2*(1+rng()%5);
        i.enable=rng()%13!=0;i.pause=rng()%11==0;i.invalidate=rng()%97==0;
        i.ready=rng()%4!=0;i.reply=rng()%3!=0;m.tick(d,i,mutation);
        if(cycle==4000||cycle==8000) { // abandon accepted and held obligations through real reset.
            reset(d);m.cache={};m.replace={};m.owners.clear();m.held.reset();m.window.clear();
        }
    }
    for(unsigned pattern:{1U,2U}) {
        reset(d);m.cache={};m.replace={};m.owners.clear();m.held.reset();m.window.clear();patternMode=pattern;
        i=Input{};i.reply=true;
        for(unsigned packet=0;packet<32;++packet) {i.pc=0x80200000+packet*8;run(i,8);}
    }
    i.enable=false;i.pause=true;i.ready=true;i.reply=true;i.invalidate=false;run(i,8);
    need(m.owners.empty()&&!m.held,"final drain");
    need(m.heldCycles&&m.turnover&&m.full&&m.faults&&m.straddles&&m.oldContextFill&&m.invalidations,"coverage");
    need(!IDENTITY_HORIZON_ENABLED||m.third,"third horizon never observed");
    std::cout<<"PASS_IDENTITY_HORIZON enabled="<<IDENTITY_HORIZON_ENABLED<<" cycles="<<m.cycles
        <<" offers="<<m.offers<<" returns="<<m.returns<<" third="<<m.third<<" held="<<m.heldCycles
        <<" turnover="<<m.turnover<<" full="<<m.full<<" faults="<<m.faults<<" straddles="<<m.straddles
        <<" oldContextFill="<<m.oldContextFill<<" invalidations="<<m.invalidations<<" reset=5 finalDrain=1\n";
    return 0;
} catch(const std::exception& e){std::cerr<<"IDENTITY_HORIZON_FAIL "<<e.what()<<'\n';return 1;}}
