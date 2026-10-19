#include "I1DataCacheCommitFixture.h"
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
    SI1DataCacheCommitFixture d;
    unsigned cycle=0,accepted=0,returned=0,readCollisions=0,probeCollisions=0,bypassCollisions=0;
    unsigned dirtyBeats=0,releaseBeats=0,flushes=0,probes=0,acquires=0;
    bool valid=false,ready=true,flush=false,holdC=false,wrong=false,mutated=false;
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
        S(response$$ready,ready);S(flush,flush);
        S(tl$$a$$ready,1);S(tl$$c$$ready,!holdC);S(tl$$e$$ready,1);
        const bool dv=!replies.empty()&&replies.front().due<=cycle;
        const Reply dr=dv?replies.front():Reply{};
        S(tl$$d$$valid,dv);S(tl$$d$$bits$$opcode,dr.opcode);
        S(tl$$d$$bits$$param,0);S(tl$$d$$bits$$size,6);S(tl$$d$$bits$$source,0);
        S(tl$$d$$bits$$sink,0);S(tl$$d$$bits$$denied,0);
        S(tl$$d$$bits$$data,dr.data);S(tl$$d$$bits$$corrupt,0);
        S(tl$$b$$valid,bool(probe));S(tl$$b$$bits$$opcode,6);S(tl$$b$$bits$$param,2);
        S(tl$$b$$bits$$size,6);S(tl$$b$$bits$$source,3);
        S(tl$$b$$bits$$address,probe.value_or(base));S(tl$$b$$bits$$mask,255);
        S(tl$$b$$bits$$data,0);S(tl$$b$$bits$$corrupt,0);
        const bool nr=native&&native->due<=cycle;
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
        if(dv&&G(tl$$d$$ready))replies.pop_front();
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
        Test t;t.wrong=argc>1&&std::string(argv[1])=="--wrong-forward";
        t.transact({base});
        const unsigned beforeAliasAcquire=t.acquires,beforeAliasRelease=t.releaseBeats;
        const uint64_t alias=base+(1ULL<<44);
        t.transact({alias});
        t.transact({alias,0xf4e3d2c1b0a99887ULL,0x55,true,false});
        t.transact({base});
        check(t.acquires==beforeAliasAcquire&&t.releaseBeats==beforeAliasRelease,
            "outside-aperture compact-tag alias evicted or modified a resident row");
        // Every lane and word; two masked writers followed by a read. The
        // oracle updates software bytes at accepted stores, never from RTL.
        for(unsigned stall=0;stall<2;++stall){
            unsigned sent=0;
            for(unsigned i=0;i<3000&&sent<192;++i){
                const unsigned group=sent/3,kind=sent%3;
                t.request={base+8*(group%8),0x5381ba920f67c4deULL^(uint64_t(sent)*0x102040810204081ULL),
                    kind==0?(1U<<(group%8)):(0xaaU^(group&1?0xffU:0)),kind!=2,false};
                t.valid=true;t.ready=!stall||(i%7>=3);t.tick();
                if(t.fired)++sent;
            }
            check(sent==192,"masked store/read cohort admission");t.drain();
        }
        check(t.readCollisions>=32,"masked reads never collided with a preceding write");
        // Raw B is intentionally accepted at the EXACT write-commit edge.
        for(unsigned bank=0;bank<8;++bank){
            t.transact({base+bank*8});
            t.request={base+bank*8,0xf1d3b597795b3d1fULL^bank,1U<<bank,true,false};
            t.valid=true;t.ready=true;
            for(unsigned i=0;i<4000;++i){t.tick();if(t.fired)break;}
            check(t.fired,"probe collision store not accepted");
            t.valid=false;t.probe=base;t.holdC=true;t.tick();
            check(t.bfired,"probe was not accepted at the cache write-commit edge");
            t.tick();t.tick();t.holdC=false;t.drain();
            check(t.word(t.backing,base+8*bank)==t.word(t.golden,base+8*bank),
                "independent masked store/probe/eviction byte oracle");
        }
        check(t.probeCollisions==8&&t.dirtyBeats==64,"probe collision coverage incomplete");
        // An immediately following noAllocate owner evicts the exact row
        // being written at its acceptance edge: victim capture needs bypass.
        for(unsigned bank=0;bank<8;++bank){
            t.transact({base+bank*8});
            t.request={base+bank*8,0x1f3d5b7997b5d3f1ULL^bank,0x55,true,false};
            t.valid=true;t.ready=true;
            for(unsigned i=0;i<4000;++i){t.tick();if(t.fired)break;}
            check(t.fired,"victim collision store not accepted");
            t.request={base+bank*8,0,255,false,true};t.tick();
            check(t.fired,"bypass did not replace the consumed store owner");t.drain();
        }
        check(t.bypassCollisions==8&&t.releaseBeats==64,"victim collision coverage incomplete");
        t.flushAll();
        check(t.accepted==t.returned&&t.readCollisions>=32,"write-commit ownership coverage");
        std::cout<<"I1_WRITE_COMMIT_PASS accepted="<<t.accepted<<" returned="<<t.returned
            <<" read_collisions="<<t.readCollisions<<" probe_collisions="<<t.probeCollisions
            <<" bypass_collisions="<<t.bypassCollisions<<" dirty_beats="<<t.dirtyBeats
            <<" release_beats="<<t.releaseBeats<<" flushes="<<t.flushes
            <<" same_owner_slots=1 independent_bytes=1\n";
        return 0;
    }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}
}
