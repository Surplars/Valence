#include "I1CacheQuiescenceFixture.h"
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>

#define S(n,v) d.set_io$$##n(v)
#define G(n) d.get_io$$##n()
static constexpr uint64_t base=0x80200000ULL;
static void check(bool x,const char* why){if(!x)throw std::runtime_error(why);}
struct Request {uint64_t address=base,data=0;unsigned mask=255;bool write=false,bypass=false;};
struct Reply {unsigned opcode=0;uint64_t data=0;unsigned due=0;};
struct Expected {uint64_t data;bool write;};
struct Native {uint64_t data;unsigned due;};
static uint64_t merge(uint64_t old,uint64_t data,unsigned mask){
    for(unsigned b=0;b<8;++b)if(mask&(1U<<b)){
        const uint64_t lane=0xffULL<<(b*8);
        old=(old&~lane)|(data&lane);
    }
    return old;
}
struct Test{
    SI1CacheQuiescenceFixture d;
    unsigned cycle=0,accepted=0,returned=0,readCollisions=0,probeCollisions=0,bypassCollisions=0;
    unsigned dirtyBeats=0,releaseBeats=0,flushes=0,probes=0,acquires=0;
    bool valid=false,ready=true,flush=false,holdC=false,wrong=false,mutated=false;
    bool earlyPending=false;
    bool holdE=false,holdD=false,holdRelease=false,holdNative=false;
    unsigned grantBeats=0;
    bool lastAcceptedWrite=false,fired=false,bfired=false,rfired=false;
    Request request;
    std::optional<uint64_t> probe,probing;
    unsigned probeBeat=0,releaseBeat=0;
    uint64_t releaseAddress=0;
    std::deque<Reply> replies;
    std::deque<Expected> expected;
    std::optional<Native> native;
    std::map<uint64_t,uint64_t> backing,golden;
    uint64_t word(const std::map<uint64_t,uint64_t>& m,uint64_t a)const{
        a&=~7ULL;auto it=m.find(a);
        return it==m.end()?(0x71b9568a2384cdefULL^(a*0x9e3779b97f4a7c15ULL)):it->second;
    }
    Test(){
        S(request$$valid,0);S(response$$ready,0);S(flush,0);
        d.set_reset(1);tick();tick();d.set_reset(0);tick();
    }
    void tick(){
        check(cycle<100000,"independent write-commit cycle bound");
        S(request$$valid,valid);S(request$$bits$$address,request.address);
        S(request$$bits$$write,request.write);S(request$$bits$$data,request.data);
        S(request$$bits$$mask,request.mask);S(request$$bits$$size,3);
        S(request$$bits$$atomic,0);S(request$$bits$$atomicOp,0);
        S(request$$bits$$virtualized,0);S(request$$bits$$uncached,request.bypass);
        S(response$$ready,ready);S(flush,flush);S(earlyPending,earlyPending);
        S(tl$$a$$ready,1);S(tl$$c$$ready,!holdC);S(tl$$e$$ready,!holdE);
        const bool dv=!replies.empty()&&replies.front().due<=cycle && !holdD &&
            !(holdRelease && replies.front().opcode==6);
        const Reply dr=dv?replies.front():Reply{};
        S(tl$$d$$valid,dv);S(tl$$d$$bits$$opcode,dr.opcode);
        S(tl$$d$$bits$$param,0);S(tl$$d$$bits$$size,6);S(tl$$d$$bits$$source,0);
        S(tl$$d$$bits$$sink,0);S(tl$$d$$bits$$denied,0);
        S(tl$$d$$bits$$data,dr.data);S(tl$$d$$bits$$corrupt,0);
        S(tl$$b$$valid,bool(probe));S(tl$$b$$bits$$opcode,6);S(tl$$b$$bits$$param,2);
        S(tl$$b$$bits$$size,6);S(tl$$b$$bits$$source,3);
        S(tl$$b$$bits$$address,probe.value_or(base));S(tl$$b$$bits$$mask,255);
        S(tl$$b$$bits$$data,0);S(tl$$b$$bits$$corrupt,0);
        const bool nr=native&&native->due<=cycle&&!holdNative;
        S(native$$request$$ready,!native);S(native$$response$$valid,nr);
        S(native$$response$$bits$$data,nr?native->data:0);
        S(native$$response$$bits$$error,0);S(native$$response$$bits$$pageFault,0);
        d.step();
        fired=valid&&G(request$$ready);bfired=probe&&G(tl$$b$$ready);
        rfired=G(response$$valid)&&ready;
        if(fired){
            if(request.write)golden[request.address&~7ULL]=merge(
                word(golden,request.address),request.data,request.mask);
            else if(lastAcceptedWrite){
                if(request.bypass)++bypassCollisions;else ++readCollisions;
            }
            uint64_t value=request.write?0:word(golden,request.address);
            if(wrong&&!mutated&&!request.write&&lastAcceptedWrite){value^=1;mutated=true;}
            expected.push_back({value,request.write});++accepted;
        }
        if(rfired){
            check(!expected.empty()&&!G(response$$bits$$error),"write-commit response ownership/error");
            check(G(response$$bits$$data)==expected.front().data,
                "independent masked store/read collision oracle");
            expected.pop_front();++returned;
        }
        if(bfired){
            check(!probing,"overlapped independent probe owner");
            if(lastAcceptedWrite)++probeCollisions;
            probing=probe;probe.reset();probeBeat=0;++probes;
        }
        if(dv&&G(tl$$d$$ready)){if(dr.opcode==5)++grantBeats;replies.pop_front();}
        if(nr&&G(native$$response$$ready))native.reset();
        if(G(tl$$a$$valid)){
            ++acquires;
            check(G(tl$$a$$bits$$opcode)==6&&G(tl$$a$$bits$$size)==6,
                "write-commit independent acquire geometry");
            const uint64_t address=G(tl$$a$$bits$$address);
            for(unsigned b=0;b<8;++b)replies.push_back({5,word(backing,address+8*b),cycle+3+b});
        }
        if(G(tl$$c$$valid)&&!holdC){
            const unsigned op=G(tl$$c$$bits$$opcode);
            const uint64_t address=G(tl$$c$$bits$$address),data=G(tl$$c$$bits$$data);
            if(op==5){
                check(probing&&address==*probing,"write-commit probe response address");
                backing[address+8*probeBeat]=data;++dirtyBeats;
                if(++probeBeat==8)probing.reset();
            }else if(op==4){check(bool(probing),"unowned clean probe reply");probing.reset();}
            else if(op==7){
                if(releaseBeat==0)releaseAddress=address;
                check(address==releaseAddress,"write-commit release address changed");
                backing[address+8*releaseBeat]=data;++releaseBeats;
                if(++releaseBeat==8){releaseBeat=0;replies.push_back({6,0,cycle+2});}
            }else if(op==6){replies.push_back({6,0,cycle+2});}
            else throw std::runtime_error("unexpected cache C opcode");
        }
        if(G(native$$request$$valid)&&!native){
            const uint64_t a=G(native$$request$$bits$$address);
            const bool write=G(native$$request$$bits$$write);
            if(write)backing[a&~7ULL]=merge(word(backing,a),
                G(native$$request$$bits$$data),G(native$$request$$bits$$mask));
            native=Native{write?0:word(backing,a),cycle+3};
        }
        lastAcceptedWrite=fired&&request.write;
        ++cycle;
    }
    void drain(){
        valid=false;ready=true;
        for(unsigned i=0;i<4000&&(!expected.empty()||probing||probe);++i)tick();
        check(expected.empty()&&!probing&&!probe,"write-commit drain bound");
    }
    void transact(Request r){
        request=r;valid=true;ready=true;
        for(unsigned i=0;i<4000;++i){tick();if(fired){valid=false;break;}}
        check(!valid,"write-commit request bound");drain();
    }
    void flushAll(){
        drain();flush=true;tick();
        for(unsigned i=0;i<10000&&!G(flushDone);++i)tick();
        check(G(flushDone),"write-commit flush bound");flush=false;tick();++flushes;
        for(const auto& [a,v]:golden)check(word(backing,a)==v,
            "independent masked store/probe/eviction byte oracle");
    }
};
int main(int argc,char**argv){
    try{
        Test t;
        const std::string negative=argc>1?argv[1]:"";
        auto busy=[&](const char* stage){
            const bool observed=negative==std::string("--wrong-")+stage ? true : t.G(quiescent);
            check(!observed,"independent live-owner quiescence oracle");
        };
        auto until=[&](auto condition,const char* why){
            for(unsigned n=0;n<12000&&!condition();++n)t.tick();
            check(condition(),why);
        };
        until([&]{return t.G(quiescent);},"initial idle missing");
        t.earlyPending=true; t.tick();
        check(!t.G(quiescent),"early owner without late physical offer was omitted");
        t.earlyPending=false; t.tick();
        until([&]{return t.G(quiescent);},"early-only owner failed to drain");
        // Cold miss: partial D, held E, then held native CPU response.
        t.request={base};t.valid=true;t.ready=false;t.holdE=true;
        until([&]{return t.fired;},"cold request acceptance");t.valid=false;
        until([&]{return t.grantBeats==3;},"partial refill did not arrive");
        t.holdD=true;for(unsigned n=0;n<12;++n){t.tick();busy("partial");}
        t.holdD=false;
        until([&]{return t.G(tl$$e$$valid);},"GrantAck not offered");
        for(unsigned n=0;n<12;++n){t.tick();busy("e");}
        t.holdE=false;
        until([&]{return t.G(response$$valid);},"CPU response not offered");
        for(unsigned n=0;n<12;++n){t.tick();busy("reply");}
        t.drain();until([&]{return t.G(quiescent);},"miss did not drain");
        // Back-to-back write-hit/read-hit collides with the actual synchronous
        // bank commit. The inherited byte oracle checks forwarding separately.
        t.request={base,0x123456789abcdef0ULL,255,true,false};t.valid=true;t.tick();
        until([&]{return t.fired;},"collision store acceptance");
        t.request={base};t.tick();
        until([&]{return t.fired;},"collision read acceptance");
        t.valid=false;t.drain();
        check(t.readCollisions>0,"same-address write/read collision not exercised");
        // Dirty publication cannot finish before the real ReleaseAck.
        t.transact({base,0xabcdeffedcba1234ULL,255,true,false});
        until([&]{return t.G(quiescent);},"store metadata did not drain");
        t.flush=true;t.holdRelease=true;t.tick();
        until([&]{return !t.replies.empty()&&t.replies.front().opcode==6;},"dirty release missing");
        check(t.releaseBeats==8,"dirty release omitted bytes");
        for(unsigned n=0;n<12;++n){t.tick();busy("release");check(!t.G(flushDone),"flush crossed ReleaseAck");}
        t.holdRelease=false;
        until([&]{return t.G(flushDone)&&t.G(quiescent);},"flush did not complete and drain");
        check(t.word(t.backing,base)==t.word(t.golden,base),"independent dirty byte oracle");
        // Sticky flush completion is NOT quiescence: a new B owns a C reply.
        t.probe=base;t.holdC=true;t.tick();
        until([&]{return t.G(tl$$c$$valid);},"post-flush probe reply missing");
        for(unsigned n=0;n<12;++n){t.tick();check(t.G(flushDone),"completed flush not sticky");busy("probe");}
        t.holdC=false;t.drain();until([&]{return t.G(quiescent);},"probe did not drain");
        t.flush=false;t.tick();
        // Accepted bypass still owns the actual native response.
        t.request={base+(1ULL<<44)};t.valid=true;t.holdNative=true;t.tick();
        until([&]{return t.fired;},"bypass acceptance");t.valid=false;
        until([&]{return bool(t.native);},"native request missing");
        for(unsigned n=0;n<12;++n){t.tick();busy("native");}
        t.holdNative=false;t.drain();until([&]{return t.G(quiescent);},"native did not drain");
        std::cout<<"I1_CACHE_QUIESCENCE_PASS partial=12 e=12 reply=12 release=12 probe=12 native=12\n";
        return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}
}
