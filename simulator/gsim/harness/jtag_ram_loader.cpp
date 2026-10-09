#include "JtagRamLoader.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <tuple>
static void check(bool ok,const char *why) { if(!ok) throw std::runtime_error(why); }
static constexpr uint64_t base=0x80200000ULL, end=base+4096, control=0x10003000ULL;
struct Rig {
    SJtagRamLoader d;
    std::array<uint8_t,4096> ram{};
    struct Reply { unsigned remaining; uint64_t data; bool error; };
    using Req=std::tuple<uint64_t,uint64_t,unsigned,unsigned,bool>;
    std::optional<Reply> reply;
    std::optional<Req> stalled;
    unsigned cycle=0,requests=0,writes=0,delay=4;
    bool allow=true,respond=true,errorNext=false,corrupt=false;
    Rig() {
        d.set_io$$dmi$$request$$valid(0);d.set_io$$dmi$$response$$ready(1);
        d.set_io$$control$$request$$valid(0);d.set_io$$control$$response$$ready(1);
        d.set_io$$linkUp(1);d.set_reset(1);tick();tick();d.set_reset(0);tick();
    }
    void tick() {
        d.set_io$$memory$$request$$ready(allow);
        bool valid=reply&&reply->remaining==0&&respond;
        d.set_io$$memory$$response$$valid(valid);
        d.set_io$$memory$$response$$bits$$data(reply?reply->data:0);
        d.set_io$$memory$$response$$bits$$error(reply&&reply->error);
        d.step();++cycle;
        auto req=Req{d.get_io$$memory$$request$$bits$$address(),d.get_io$$memory$$request$$bits$$data(),
            unsigned(d.get_io$$memory$$request$$bits$$size()),unsigned(d.get_io$$memory$$request$$bits$$byteEnable()),
            bool(d.get_io$$memory$$request$$bits$$write())};
        bool offered=d.get_io$$memory$$request$$valid();
        if(stalled)check(offered&&req==*stalled,"stalled request changed or withdrawn");
        stalled=offered&&!allow?std::optional{req}:std::nullopt;
        if(valid&&d.get_io$$memory$$response$$ready())reply.reset();
        if(offered&&allow) {
            check(!reply,"multiple memory owners"); ++requests;
            auto [address,data,size,mask,write]=req;
            check(address>=base&&address+4<=end&&!(address&3),"whitelist/alignment violation");
            check(size==2&&mask==15,"memory access shape");
            uint64_t v=0;for(unsigned n=0;n<4;++n)v|=uint64_t(ram.at(address-base+n))<<(8*n);
            if(write&&!errorNext) {++writes;for(unsigned n=0;n<4;++n)ram.at(address-base+n)=data>>(8*n);}
            reply=Reply{delay,corrupt&&!write?v^1:v,errorNext};errorNext=false;
        }
        if(reply&&reply->remaining)--reply->remaining;
    }
    void ticks(unsigned n){while(n--)tick();}
    std::pair<unsigned,uint32_t> dmi(unsigned op,unsigned address,uint32_t value=0) {
        d.set_io$$dmi$$request$$bits$$op(op);d.set_io$$dmi$$request$$bits$$address(address);
        d.set_io$$dmi$$request$$bits$$data(value);d.set_io$$dmi$$request$$valid(1);
        bool sent=false;for(unsigned i=0;i<100;++i){tick();if(d.get_io$$dmi$$request$$ready()){sent=true;break;}}
        check(sent,"DMI request stuck");d.set_io$$dmi$$request$$valid(0);
        for(unsigned i=0;i<100;++i){tick();if(d.get_io$$dmi$$response$$valid())return {
            unsigned(d.get_io$$dmi$$response$$bits$$status()),uint32_t(d.get_io$$dmi$$response$$bits$$data())};}
        throw std::runtime_error("DMI response missing");
    }
    uint32_t rd(unsigned a){auto [s,v]=dmi(1,a);check(s==0,"DMI read failed");return v;}
    void wr(unsigned a,uint32_t v){auto status=dmi(2,a,v).first;if(status)throw std::runtime_error("DMI write failed address="+std::to_string(a)+" value="+std::to_string(v)+" cycle="+std::to_string(cycle));}
    std::pair<bool,uint64_t> cpu(unsigned off,bool write=false,uint64_t value=0) {
        d.set_io$$control$$request$$bits$$address(control+off);d.set_io$$control$$request$$bits$$write(write);
        d.set_io$$control$$request$$bits$$data(value);d.set_io$$control$$request$$bits$$size(3);
        d.set_io$$control$$request$$bits$$byteEnable(255);d.set_io$$control$$request$$valid(1);
        for(unsigned i=0;;++i){check(i<100,"CPU control request stuck");tick();if(d.get_io$$control$$request$$ready())break;}
        d.set_io$$control$$request$$valid(0);
        for(unsigned i=0;i<100;++i){tick();if(d.get_io$$control$$response$$valid())return {
            bool(d.get_io$$control$$response$$bits$$error()),uint64_t(d.get_io$$control$$response$$bits$$data())};}
        throw std::runtime_error("CPU response missing");
    }
    unsigned open(){check(!cpu(8,true,1).first,"OPEN rejected");check(rd(0x41)&1,"not armed");return rd(0x46);}
    void idle(){for(unsigned i=0;i<100;++i){auto s=rd(0x38);if(!(s&(1U<<21)))return;}throw std::runtime_error("SBA stuck");}
    void clean(uint32_t cfg=2U<<17){wr(0x38,cfg|(1U<<22)|(7U<<12));}
    unsigned err(){return(rd(0x38)>>12)&7;}
    void store(uint32_t at,uint32_t value){wr(0x39,at);wr(0x3c,value);idle();check(err()==0,"SBA store failed");}
    uint32_t load(uint32_t at){wr(0x38,(2U<<17)|(1U<<20));wr(0x39,at);idle();check(err()==0,"SBA load failed");return rd(0x3c);}
    void metadata(unsigned gen,uint32_t len=16,uint32_t at=base){wr(0x43,at);wr(0x44,len);wr(0x45,0x12345678);wr(0x49,gen);}
};
int main(int argc,char**argv)try {
    bool negative=argc>1&&std::string(argv[1])=="--corrupt-readback";
    Rig r;check(r.rd(0x40)==0x564c0101,"capability mismatch");check(r.rd(0x11)==0,"false DM conformance");
    // Held DMI response is not a pulse and cannot change with backpressure.
    r.d.set_io$$dmi$$response$$ready(0);r.d.set_io$$dmi$$request$$bits$$op(1);
    r.d.set_io$$dmi$$request$$bits$$address(0x40);r.d.set_io$$dmi$$request$$bits$$data(0);
    r.d.set_io$$dmi$$request$$valid(1);
    do{r.tick();}while(!r.d.get_io$$dmi$$request$$ready());
    r.d.set_io$$dmi$$request$$valid(0);r.tick();
    for(unsigned n=0;n<8;++n){r.tick();check(r.d.get_io$$dmi$$response$$valid()&&
        r.d.get_io$$dmi$$response$$bits$$data()==0x564c0101&&r.d.get_io$$dmi$$response$$bits$$status()==0,
        "DMI held response changed");}
    r.d.set_io$$dmi$$response$$ready(1);r.tick();
    r.d.set_io$$control$$response$$ready(0);r.d.set_io$$control$$request$$valid(1);
    r.d.set_io$$control$$request$$bits$$address(control+48);r.d.set_io$$control$$request$$bits$$write(0);
    r.d.set_io$$control$$request$$bits$$size(3);r.d.set_io$$control$$request$$bits$$byteEnable(255);
    r.d.set_io$$control$$request$$bits$$data(0);
    do{r.tick();}while(!r.d.get_io$$control$$request$$ready());
    r.d.set_io$$control$$request$$valid(0);r.tick();
    for(unsigned n=0;n<8;++n){r.tick();check(r.d.get_io$$control$$response$$valid()&&
        r.d.get_io$$control$$response$$bits$$data()==base&&!r.d.get_io$$control$$response$$bits$$error(),
        "CPU held response changed");}
    r.d.set_io$$control$$response$$ready(1);r.tick();
    check(r.dmi(2,0x10,1).first==2,"fake dmactive accepted");check(r.dmi(1,0x7f).first==2,"unknown register");
    r.wr(0x39,base);r.wr(0x3c,55);check(r.err()==7&&r.requests==0,"unarmed access");
    auto gen=r.open();check(gen==1,"generation initialization");
    check(r.cpu(48).second==base&&r.cpu(56).second==end,"ROM bounds");
    auto cap=r.rd(0x38);check((cap>>29)==1&&((cap>>5)&127)==32&&(cap&31)==4,"SBA capabilities");
    for(unsigned size=0;size<8;++size)if(size!=2){r.clean(size<<17);r.wr(0x39,base);r.wr(0x3c,1);check(r.err()==4,"size error");}
    r.clean();for(unsigned i=1;i<4;++i){r.wr(0x39,base+i);r.wr(0x3c,1);check(r.err()==3,"alignment error");r.clean();}
    for(uint32_t at:{uint32_t(base-4),uint32_t(end),0xfffffffcU,0U,0x10000000U}) {
        r.wr(0x39,at);r.wr(0x3c,1);check(r.err()==2,"address error");r.clean();
    }
    check(r.requests==0,"invalid accesses reached bus");
    check(!r.cpu(8,true,2).first,"close");r.wr(0x3c,1);check(r.err()==7,"closed access error");
    r.wr(0x38,(2U<<17)|(4U<<12));check(r.err()==3,"SBA error W1C not bitwise");
    r.wr(0x3c,2);check(r.requests==0,"sticky error failed to inhibit");gen=r.open();
    // Independent byte-array oracle: no DUT constants/logic are imported.
    std::array<uint32_t,80> expected{};
    r.wr(0x38,(2U<<17)|(1U<<16));r.wr(0x39,base);
    for(unsigned n=0;n<expected.size();++n){expected[n]=0x92731a55U^(n*0x9e3779b9U);r.wr(0x3c,expected[n]);r.idle();}
    check(r.rd(0x39)==base+expected.size()*4,"autoincrement");
    r.corrupt=negative;
    for(unsigned n=0;n<expected.size();++n)check(r.load(base+n*4)==expected[n],"independent RAM readback oracle mismatch");
    r.corrupt=false; r.clean();r.delay=20;r.wr(0x39,base+400);r.wr(0x3c,0x11223344);
    r.wr(0x3c,0xffffffff);check(r.rd(0x38)&(1U<<22),"busy collision not latched");r.idle();
    check(r.writes==81,"busy access issued duplicate");r.clean();r.delay=4;
    // Cancellation preserves a presented, unaccepted bus request.
    r.allow=false;r.wr(0x39,base+404);r.wr(0x3c,0x55667788);r.wr(0x42,1);
    check(r.cpu(8,true,1).first,"OPEN accepted with outstanding offer");r.ticks(70);
    check((r.rd(0x41)&0x1c)==0x1c&&r.err()==1,"timeout did not retain fault/drain");
    auto prior=r.writes;r.allow=true;r.ticks(10);check(r.writes==prior+1,"aborted offer not drained exactly once");
    check(!(r.rd(0x41)&8),"late response not drained");gen=r.open();
    // Transport reset drops DMI responses/session, never presented bus ownership.
    r.allow=false;r.wr(0x39,base+408);r.wr(0x3c,0xaabbccdd);r.d.set_io$$linkUp(0);r.ticks(8);
    check(r.cpu(8,true,1).first,"OPEN allowed while link down");r.allow=true;r.ticks(8);r.d.set_io$$linkUp(1);r.ticks(3);
    check((r.rd(0x41)&7)==4,"link reset left session live");gen=r.open();
    r.respond=false;r.wr(0x39,base+412);r.wr(0x3c,0xabcdef);r.ticks(70);
    check(r.err()==1&&(r.rd(0x41)&8),"accepted timeout lost owner");r.respond=true;r.ticks(4);gen=r.open();
    r.errorNext=true;r.wr(0x39,base);r.wr(0x3c,3);r.idle();check(r.err()==7&&(r.rd(0x41)&0x14)==0x14,"bus error policy");gen=r.open();
    r.metadata(gen-1);check(r.dmi(2,0x42,2).first==2,"stale host generation commit");
    for(uint32_t len:{0U,4097U,0xffffffffU}){r.metadata(gen,len);check(r.dmi(2,0x42,2).first==2,"illegal length committed");}
    for(uint32_t at:{uint32_t(base-4),uint32_t(base+16),uint32_t(base+2)}){r.metadata(gen,16,at);check(r.dmi(2,0x42,2).first==2,"illegal entry committed");}
    r.metadata(gen,15);r.wr(0x42,2);check(r.rd(0x41)&2,"COMMIT not sealed");
    check(r.dmi(2,0x43,base+4).first==2,"committed metadata mutable");
    r.wr(0x42,1);check(r.cpu(8,true,(uint64_t(gen)<<32)|3).first,"cancelled launch accepted");gen=r.open();
    r.metadata(gen);r.wr(0x42,2);check(r.cpu(8,true,(uint64_t(gen-1)<<32)|3).first,"stale CPU CLAIM");
    check(!r.cpu(8,true,(uint64_t(gen)<<32)|3).first,"valid CLAIM rejected");
    check((r.rd(0x41)&0x43)==0x40,"CLAIM state");check(r.cpu(8,true,1).first,"rearm after launch");
    check(r.dmi(2,0x42,1).first==2,"abort claimed launch");
    std::cout<<"JTAG_RAM_LOADER_PASS requests="<<r.requests<<" writes="<<r.writes<<" cycles="<<r.cycle<<"\n";
    return 0;
}catch(const std::exception&e){std::cerr<<"FAIL: "<<e.what()<<"\n";return 1;}
