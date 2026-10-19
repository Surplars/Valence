#include "I1InstructionCachePmaFixture.h"
#include <cstdint>
#include <deque>
#include <iostream>
#include <map>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <tuple>
#ifndef I1_IF_CACHE_BYTES
#define I1_IF_CACHE_BYTES 32768
#endif
static constexpr uint64_t base=0x80200000ULL, end=base+0x80000000ULL;
static void check(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
#define S(name,value) d.set_io$$##name(value)
#define G(name) d.get_io$$##name()
struct DBeat {unsigned opcode,source;uint64_t data;bool corrupt;unsigned due;};
struct Probe {uint64_t address;unsigned source;};
struct Native {uint64_t data;bool error;unsigned due;};
struct Test {
    SI1InstructionCachePmaFixture d;
    unsigned cycle=0,acquires=0,releases=0,probeAcks=0,natives=0,grantAcks=0,checks=0;
    unsigned accepted=0,returned=0;
    bool valid=false,ready=true,noAllocate=false,holdNative=false,holdC=false,holdD=false;
    bool invalidate=false,wrongHint=false,wrongData=false,failNextFill=false;
    uint64_t address=base;
    unsigned size=1;
    std::deque<DBeat> replies;
    std::optional<Native> native;
    std::optional<Probe> probe,probing;
    std::set<uint64_t> residents;
    std::map<uint64_t,uint64_t> memory;
    std::optional<std::tuple<uint64_t,unsigned,unsigned,bool,uint64_t,unsigned>> heldNative;
    std::optional<std::tuple<unsigned,unsigned,uint64_t,unsigned>> heldC;
    uint64_t lastData=0,lastClasses=0;bool lastError=false,wrongClass=false;
    bool inRam(uint64_t a,unsigned s=1)const{return a>=base&&a<=end-(1ULL<<s);}
    uint64_t word(uint64_t a)const {
        a&=~7ULL;auto i=memory.find(a);
        return i==memory.end()?((a*0x9e3779b97f4a7c15ULL)^(a>>9)^0x5611a09d3254bc87ULL):i->second;
    }
    Test(){
        S(request$$valid,0);S(response$$ready,0);S(invalidate,0);
        d.set_reset(1);tick();tick();d.set_reset(0);tick();
    }
    void tick(){
        check(cycle<200000,"independent coherent IF cycle bound");
        S(request$$valid,valid);S(request$$bits$$address,address);
        S(request$$bits$$write,0);S(request$$bits$$data,0);S(request$$bits$$mask,255);
        S(request$$bits$$size,size);S(request$$bits$$noAllocate,noAllocate);
        S(request$$bits$$atomic,0);S(request$$bits$$atomicOperation,0);
        S(readCacheable,(inRam(address,size)&&!noAllocate)^wrongHint);
        S(response$$ready,ready);S(invalidate,invalidate);
        S(tl$$a$$ready,1);S(tl$$c$$ready,!holdC);S(tl$$e$$ready,1);
        const bool dv=!replies.empty()&&replies.front().due<=cycle&&!holdD;
        const DBeat dr=dv?replies.front():DBeat{};
        S(tl$$d$$valid,dv);S(tl$$d$$bits$$opcode,dr.opcode);
        S(tl$$d$$bits$$param,0);S(tl$$d$$bits$$size,6);S(tl$$d$$bits$$source,dr.source);
        S(tl$$d$$bits$$sink,0);S(tl$$d$$bits$$denied,0);
        S(tl$$d$$bits$$data,dr.data);S(tl$$d$$bits$$corrupt,dr.corrupt);
        S(tl$$b$$valid,bool(probe));S(tl$$b$$bits$$opcode,6);S(tl$$b$$bits$$param,2);
        S(tl$$b$$bits$$size,6);S(tl$$b$$bits$$source,probe?probe->source:0);
        S(tl$$b$$bits$$address,probe?probe->address:base);
        S(tl$$b$$bits$$mask,255);S(tl$$b$$bits$$data,0);S(tl$$b$$bits$$corrupt,0);
        const bool nr=native&&native->due<=cycle;
        S(native$$request$$ready,!holdNative&&!native);
        S(native$$response$$valid,nr);
        S(native$$response$$bits$$data,nr?native->data:0);
        S(native$$response$$bits$$error,nr&&native->error);S(native$$response$$bits$$pageFault,0);
        d.step();
        if(valid&&G(request$$ready))++accepted;
        if(G(response$$valid)&&ready){
            lastData=G(response$$bits$$data);lastError=G(response$$bits$$error);++returned;
#ifdef I1_CACHED_PARCEL_PREDECODE
            lastClasses=G(response$$bits$$parcelClasses);
#endif
        }
        if(dv&&G(tl$$d$$ready))replies.pop_front();
        if(nr&&G(native$$response$$ready))native.reset();
        if(probe&&G(tl$$b$$ready)){check(!probing,"overlapped independent B owner");probing=probe;probe.reset();}
        if(G(tl$$a$$valid)){
            const uint64_t a=G(tl$$a$$bits$$address);
            check(G(tl$$a$$bits$$opcode)==6&&G(tl$$a$$bits$$size)==6&&!(a&63)&&inRam(a,6),
                "independent IF acquire geometry oracle");
            const bool error=failNextFill;failNextFill=false;
            for(unsigned i=0;i<8;++i)replies.push_back({5,unsigned(G(tl$$a$$bits$$source)),
                word(a+8*i),error&&i==3,cycle+3+2*i});
            if(!error)residents.insert(a);
            ++acquires;
        }
        const auto nc=std::make_tuple(uint64_t(G(native$$request$$bits$$address)),
            unsigned(G(native$$request$$bits$$size)),unsigned(G(native$$request$$bits$$mask)),
            bool(G(native$$request$$bits$$write)),uint64_t(G(native$$request$$bits$$data)),
            unsigned(G(native$$request$$bits$$atomic)));
        if(heldNative)check(G(native$$request$$valid)&&nc==*heldNative,
            "retained native IF offer changed or withdrew under B/backpressure");
        if(G(native$$request$$valid)){
            check(!G(native$$request$$bits$$write)&&!G(native$$request$$bits$$atomic),
                "read-only native IF wrote data");
            const uint64_t a=G(native$$request$$bits$$address);
            if(!holdNative&&!nr&&!native){
                check(!residents.count(a&~63ULL),"native IF bypass overtook resident release");
                native=Native{word(a),!inRam(a,G(native$$request$$bits$$size)),cycle+3};
                ++natives;heldNative.reset();
            }else heldNative=nc;
        }else heldNative.reset();
        const auto cc=std::make_tuple(unsigned(G(tl$$c$$bits$$opcode)),
            unsigned(G(tl$$c$$bits$$source)),uint64_t(G(tl$$c$$bits$$address)),
            unsigned(G(tl$$c$$bits$$param)));
        if(heldC)check(G(tl$$c$$valid)&&cc==*heldC,"coherent IF C changed under backpressure");
        if(G(tl$$c$$valid)){
            if(holdC)heldC=cc;
            else{
                heldC.reset();auto[op,source,a,param]=cc;
                if(op==6){
                    check(residents.erase(a)==1&&param==1,"independent clean release owner oracle");
                    replies.push_back({6,source,0,false,cycle+2});++releases;
                }else{
                    check(op==4&&probing&&probing->address==a&&probing->source==source,
                        "independent IF probe source/address oracle");
                    const bool wasResident=residents.erase(a);
                    check(param==(wasResident?1U:5U),"independent IF probe permission oracle");
                    probing.reset();++probeAcks;
                }
            }
        }else heldC.reset();
        if(G(tl$$e$$valid)){check(G(tl$$e$$bits$$sink)==0,"GrantAck sink");++grantAcks;}
        ++cycle;
    }
    void read(uint64_t a,bool scalar=false,bool error=false){
        address=a;noAllocate=scalar;valid=true;ready=true;
        const unsigned before=accepted,done=returned,limit=cycle+6000;
        while(returned==done){
            tick();if(accepted!=before)valid=false;
            check(cycle<limit,"independent coherent IF request progress");
        }
        check(accepted==before+1&&returned==done+1,"one accepted IF owner/response");
        check(lastError==error,"independent coherent IF error oracle");
        if(!error)check((lastData^uint64_t(wrongData))==word(a),"independent coherent IF byte oracle");
#ifdef I1_CACHED_PARCEL_PREDECODE
        if(!error){
            uint64_t expected=0,bits=word(a);
            for(unsigned lane=0;lane<4;++lane){
                unsigned prefix=(bits>>(lane*16))&31;
                expected|=uint64_t((prefix&3)==3&&prefix!=31)<<lane;
                expected|=uint64_t((prefix&3)!=3)<<(lane+4);
            }
            check((lastClasses^uint64_t(wrongClass))==expected,"independent IF parcel metadata oracle");
        }
#endif
        ++checks;valid=false;tick();
    }
    void sendProbe(uint64_t a,bool blockedBypass=false){
        const unsigned before=probeAcks;probe=Probe{a,3};
        holdC=true;
        for(unsigned n=0;n<8;++n)tick();
        check(probing&&!probe,"B owner did not enter probe capture");
        holdC=false;
        const unsigned limit=cycle+200;
        while(probeAcks==before){tick();check(cycle<limit,"IF probe completion");}
        if(blockedBypass)check(heldNative.has_value(),"probe discarded held native bypass owner");
        tick();
    }
};
int main(int argc,char**argv){try{
    Test t;
    for(int n=1;n<argc;++n){std::string a=argv[n];if(a=="--wrong-hint")t.wrongHint=true;
        else if(a=="--wrong-data")t.wrongData=true;else if(a=="--wrong-class")t.wrongClass=true;
        else throw std::runtime_error("unknown option");}
    t.read(base+16);unsigned before=t.acquires;t.read(base+18);check(t.acquires==before,"trusted IF warm hit");
    unsigned releases=t.releases;t.read(base+16,true);
    check(t.releases==releases+1&&t.natives==1,"noAllocate skipped real resident release/native response");
    t.read(base+16);before=t.acquires;releases=t.releases;
    t.read(base+16+(1ULL<<40),false,true);
    check(t.acquires==before&&t.releases==releases,"high alias evicted/cached a real IF line");
    t.read(base+16);check(t.acquires==before,"high alias destroyed real resident");
    t.sendProbe(base+(1ULL<<40));t.read(base+16);check(t.acquires==before,"probe high alias invalidated real line");
    t.memory[base+16]=0xa19f5e873264bc09ULL;t.sendProbe(base);t.read(base+16);
    check(t.acquires==before+1,"probe did not invalidate instruction line");
    // A real held cache-hit response predates the DMA/probe and must retain
    // old bytes, while a following accepted read must observe the new bytes.
    const uint64_t old=t.word(base+16);t.address=base+16;t.noAllocate=false;t.ready=false;t.valid=true;
    unsigned accepted=t.accepted,returned=t.returned;
    do{t.tick();}while(t.accepted==accepted);t.valid=false;
    for(unsigned n=0;n<3;++n)t.tick();
    check(t.G(response$$valid),"held read-only response missing");
    t.memory[base+16]=0x7829a4b3f601de05ULL;t.sendProbe(base);
    check(t.G(response$$valid)&&t.G(response$$bits$$data)==old,"probe withdrew/changed old IF reply");
    t.ready=true;do{t.tick();}while(t.returned==returned);t.read(base+16);
    // A held native offer and B/C must progress independently. Then accept the
    // same offer during probeSend/C completion, with no duplicate owner.
    t.holdNative=true;t.valid=true;t.address=0x10000000;t.noAllocate=false;
    accepted=t.accepted;returned=t.returned;
    do{t.tick();}while(t.accepted==accepted);t.valid=false;
    while(!t.G(native$$request$$valid))t.tick();
    t.sendProbe(base,true);t.holdNative=false;
    while(t.returned==returned)t.tick();
    check(t.lastError,"MMIO independent manager error lost");
    t.read(base+64);t.failNextFill=true;t.read(base+128,false,true);
    before=t.acquires;t.read(base+128);check(t.acquires==before+1,"failed refill installed valid IF tag");
    for(unsigned n=0;n<I1_IF_CACHE_BYTES/64;++n)t.read(base+n*64);
    before=t.acquires;for(unsigned n=0;n<I1_IF_CACHE_BYTES/64;++n)t.read(base+n*64);
    check(t.acquires==before,"full two-way IF capacity lost");
    // One accepted warm hit/cycle: no new lookup/authorization bubble.
    t.address=base+16;t.noAllocate=false;t.valid=true;t.ready=true;
    accepted=t.accepted;returned=t.returned;unsigned start=t.cycle;
    while(t.returned-returned<32){t.valid=t.accepted-accepted<32;t.tick();
        check(t.cycle-start<40,"IF throughput bound");}
    t.valid=false;check(t.accepted-accepted==32&&t.cycle-start==33,"IF hit latency/II regression");
    t.tick();t.invalidate=true;t.tick();t.invalidate=false;
    // Full scan uses existing cache state; read waits for actual maintenance.
    t.read(base+16);check(t.acquires==before+1,"flush did not invalidate resident IF line");
    t.d.set_reset(1);t.valid=false;t.tick();t.tick();t.d.set_reset(0);t.tick();
    t.residents.clear();t.read(base+16);
    check(!t.heldNative&&!t.heldC&&!t.probe&&!t.probing,"test ended with a retained protocol owner");
    std::cout<<"I1_COHERENT_IF_PMA_PASS bytes="<<I1_IF_CACHE_BYTES<<" checks="<<t.checks
        <<" cycles="<<t.cycle<<" acquires="<<t.acquires<<" native="<<t.natives
        <<" probe_acks="<<t.probeAcks<<" hits32_cycles=33 full_capacity_alias_PMA_noAllocate_errors_probe_flush_stalls_reset=PASS\n";
    return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
