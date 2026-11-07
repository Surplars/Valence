#include "HypervisorGuestInterrupts.h"
#include <cstdint>
#include <cstring>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <type_traits>
#ifndef GEILEN
#error GEILEN required
#endif
static constexpr uint64_t mask=GEILEN==63?~uint64_t(1):((uint64_t(1)<<(GEILEN+1))-2);
struct Input {
    uint64_t external=0,data=0,hie=0,hideleg=0;
    unsigned address=0,read=0,selection=0,privilege=3;
    bool commit=false,write=false,setSelection=false,platform=false,timer=false,v=false,hs=false,vs=false,reset=false;
};
struct Model {
    uint64_t enabled=0,injected=0;unsigned selection=0;
    void edge(const Input& in) {
        if(in.reset){enabled=0;injected=0;selection=0;return;}
        if(!in.commit)return;
        if(in.setSelection)selection=in.selection<=GEILEN?in.selection:0;
        if(!in.write)return;
        if(in.address==0x607)enabled=in.data&mask;
        if(in.address==0x645)injected=in.data&0x444;
        if(in.address==0x644)injected=(injected&~uint64_t(4))|(in.data&4);
    }
};
class Bench {
    SHypervisorGuestInterrupts dut;Model model;uint64_t checks=0;
    void equal(uint64_t actual,uint64_t expected,const char* what) {
        if(actual!=expected){std::cerr<<"check="<<checks<<" "<<what<<" got="<<std::hex<<actual<<" expected="<<expected<<std::dec<<"\n";throw std::runtime_error(what);}
    }
public:
    Bench(){static_assert(std::is_trivially_copyable_v<SHypervisorGuestInterrupts>);std::memset(&dut,0,sizeof(dut));dut.LOG_START=1;dut.activateAll();}
    void tick(Input in) {
        dut.set_reset(in.reset);dut.set_io$$guestExternal(in.external & (mask>>1));
        dut.set_io$$platformVirtualExternal(in.platform);dut.set_io$$virtualTimer(in.timer);
        dut.set_io$$commit(in.commit);dut.set_io$$write$$valid(in.write);
        dut.set_io$$write$$bits$$address(in.address);dut.set_io$$write$$bits$$data(in.data);
        dut.set_io$$setVgein$$valid(in.setSelection);dut.set_io$$setVgein$$bits(in.selection);
        dut.set_io$$readAddress(in.read);dut.set_io$$hie(in.hie);dut.set_io$$hideleg(in.hideleg);
        dut.set_io$$privilege(in.privilege);dut.set_io$$virtualized(in.v);
        dut.set_io$$hsGlobalEnable(in.hs);dut.set_io$$vsGlobalEnable(in.vs);
        if(in.reset)model.edge(in); // The pinned GSIM reset epoch precedes evaluation.
        dut.step(); // Other combinational observations use pre-edge register state.
        const uint64_t geip=(in.external<<1)&mask;
        const bool summary=(geip&model.enabled)!=0;
        const bool external=((model.injected>>10)&1)||((geip>>model.selection)&1)||in.platform;
        const bool timer=((model.injected>>6)&1)||in.timer;
        const uint64_t hip=(uint64_t(summary)<<12)|(uint64_t(external)<<10)|(uint64_t(timer)<<6)|(model.injected&4);
        const uint64_t deleg=in.hideleg&0x444;
        const uint64_t hs=hip&in.hie&(GEILEN?0x1444:0x444)&~deleg,vs=hip&in.hie&deleg;
        const bool hsAllowed=in.privilege==0||(in.privilege==1&&(in.v||in.hs));
        const bool vsAllowed=in.v&&(in.privilege==0||(in.privilege==1&&in.vs));
        equal(dut.get_io$$hgeip(),geip,"hgeip");equal(dut.get_io$$hgeie(),model.enabled,"hgeie");
        equal(dut.get_io$$hvip(),model.injected,"hvip");equal(dut.get_io$$hip(),hip,"hip");
        equal(dut.get_io$$vgein(),model.selection,"VGEIN");equal(dut.get_io$$vsip(),(hip&deleg)>>1,"vsip");
        equal(dut.get_io$$hsPending(),hs&&hsAllowed,"HS eligibility");
        equal(dut.get_io$$vsPending(),vs&&vsAllowed,"VS eligibility");
        equal(dut.get_io$$hsCause(),(hs&0x1000)?12:(hs&0x400)?10:(hs&4)?2:6,"HS priority");
        equal(dut.get_io$$vsCause(),(vs&0x400)?9:(vs&4)?1:5,"VS cause translation");
        bool known=true;uint64_t read=0;
        switch(in.read){case 0x607:read=model.enabled;break;case 0xe12:read=geip;break;
            case 0x644:read=hip;break;case 0x645:read=model.injected;break;default:known=false;}
        equal(dut.get_io$$readKnown(),known,"CSR read decode");equal(dut.get_io$$readData(),read,"CSR read data");model.edge(in);checks++;
    }
    uint64_t count()const{return checks;}
};
int main(){try{
    Bench b;Input in;in.reset=true;b.tick(in);in.reset=false;b.tick(in);
    // Exhaustively separate guest selection from summary enables, including unsupported indices.
    for(unsigned selected=0;selected<64;selected++)for(unsigned pending=0;pending<64;pending++) {
        in={};in.commit=true;in.setSelection=true;in.selection=selected;
        in.write=true;in.address=0x607;in.data=uint64_t(1)<<((pending+1)%64);
        in.external=uint64_t(1)<<pending;in.hie=~uint64_t(0);in.hideleg=0x444;
        in.privilege=1;in.v=true;in.vs=true;in.read=0xe12;b.tick(in);
    }
    // All injected combinations, interrupt enables, delegation, privilege, global-enable combinations.
    for(unsigned bits=0;bits<8;bits++)for(unsigned ie=0;ie<16;ie++)for(unsigned deleg=0;deleg<8;deleg++)
    for(unsigned mode=0;mode<8;mode++)for(unsigned global=0;global<4;global++) {
        in={};in.commit=true;in.write=true;in.address=0x645;
        in.data=((bits&1)?4:0)|((bits&2)?0x40:0)|((bits&4)?0x400:0);
        in.hie=((ie&1)?4:0)|((ie&2)?0x40:0)|((ie&4)?0x400:0)|((ie&8)?0x1000:0);
        in.hideleg=((deleg&1)?4:0)|((deleg&2)?0x40:0)|((deleg&4)?0x400:0)|0x1000;
        in.privilege=mode&3;in.v=mode>>2;in.hs=global&1;in.vs=global&2;in.read=0x645;b.tick(in);
    }
    // Read-only writes, hip writable alias, no-commit cancellation, dynamic IRQ sources and resets.
    std::mt19937_64 rng(0x4856494e54455252ULL);
    unsigned addresses[]={0x607,0xe12,0x644,0x645,0x600,0x604,0x244,0x144};
    for(unsigned n=0;n<12000;n++) {
        in={};in.external=rng();in.data=rng();in.hie=rng();in.hideleg=rng();
        in.address=addresses[rng()%8];in.read=addresses[rng()%8];
        in.selection=rng()%64;in.privilege=rng()%4;in.commit=rng()%2;in.write=rng()%2;
        in.setSelection=rng()%2;in.platform=rng()%2;in.timer=rng()%2;in.v=rng()%2;
        in.hs=rng()%2;in.vs=rng()%2;in.reset=n%257==0;b.tick(in);
    }
    std::cout<<"H_GUEST_INTERRUPTS_PASS GEILEN="<<GEILEN<<" edges="<<b.count()<<" independent_checks="<<b.count()*12<<"\n";
    return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
