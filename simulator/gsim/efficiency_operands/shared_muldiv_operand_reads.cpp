#include "SharedMulDivOperandReadsGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>

static void sources(SSharedMulDivOperandReadsGsim &d,unsigned i,unsigned a,unsigned b){
#define PORT(N) case N:d.set_io$$source1$$r##N(a);d.set_io$$source2$$r##N(b);return
    switch(i){PORT(0);PORT(1);PORT(2);PORT(3);PORT(4);PORT(5);PORT(6);PORT(7);
        PORT(8);PORT(9);PORT(10);PORT(11);PORT(12);PORT(13);PORT(14);PORT(15);}
#undef PORT
    throw std::runtime_error("SOURCE_PORT_RANGE");
}
int main(int argc,char **argv){try{
    const std::string mode=argc==2?argv[1]:"";
    SSharedMulDivOperandReadsGsim d;
    std::array<uint64_t,48> rf{};
    std::array<unsigned,16> a{},b{};
    for(unsigned i=0;i<16;++i){a[i]=(i*3+1)%48;b[i]=(i*5+2)%48;}
    uint64_t checked=0,empty=0,bothAvailable=0,onlyMultiply=0,onlyDivide=0,collisions=0,wraps=0,invalidUnused=0;
    bool injected=false;
    auto tick=[&](bool reset,uint16_t m,uint16_t v,unsigned head,bool mr,bool dr,
                  bool w0,unsigned wa0,uint64_t wd0,bool w1,unsigned wa1,uint64_t wd1,const std::string &label){
        if((m&v)&&mode!="--overlap-class")throw std::runtime_error("HOST_CLASS_OVERLAP");
        d.set_reset(reset);d.set_io$$multiply(m);d.set_io$$divide(v);d.set_io$$head(head);
        d.set_io$$multiplyReady(mr);d.set_io$$divideReady(dr);
        d.set_io$$write0(w0);d.set_io$$address0(wa0);d.set_io$$data0(wd0);
        d.set_io$$write1(w1);d.set_io$$address1(wa1);d.set_io$$data1(wd1);
        for(unsigned i=0;i<16;++i)sources(d,i,a[i],b[i]);
        d.step();
        // Scan age order procedurally; never reproduce a one-hot/prefix tree.
        int selected=-1;unsigned kind=0;
        for(unsigned age=0;age<16;++age){const unsigned slot=(head+age)%16;
            if(((m>>slot)&1)&&mr){selected=slot;kind=1;break;}
            if(((v>>slot)&1)&&dr){selected=slot;kind=2;break;}}
        auto first=[&](uint16_t mask){for(unsigned age=0;age<16;++age){unsigned i=(head+age)%16;if((mask>>i)&1)return i;}return 0u;};
        const unsigned id1=selected<0?0:a[selected],id2=selected<0?0:b[selected];
        auto read=[&](unsigned id){return id<48?rf[id]:0;};
        const uint64_t expectedLeft=selected<0?0:read(id1),expectedRight=selected<0?0:read(id2);
        unsigned index=d.get_io$$selectedIndex(),grant=d.get_io$$grant();
        uint64_t sharedLeft=d.get_io$$sharedLeft(),sharedRight=d.get_io$$sharedRight();
        if(!reset){
            if(!injected&&mode=="--inject-oldest"&&label=="age-wrap"){index=(index+1)%16;injected=true;}
            if(!injected&&mode=="--inject-grant"&&label=="both-ready"){grant^=3;injected=true;}
            if(!injected&&mode=="--inject-left"&&label=="data"){sharedLeft^=1;injected=true;}
            if(!injected&&mode=="--inject-right"&&label=="data"){sharedRight^=1;injected=true;}
            if(!injected&&mode=="--inject-zero"&&label=="zero"){sharedLeft=1;injected=true;}
            if(bool(d.get_io$$valid())!=(selected>=0)||grant!=kind)throw std::runtime_error("MD_GRANT:"+label);
            if(selected>=0&&index!=unsigned(selected))throw std::runtime_error("MD_OLDEST:"+label);
            if(m&&d.get_io$$multiplyIndex()!=first(m))throw std::runtime_error("MD_MULTIPLY_RANK:"+label);
            if(v&&d.get_io$$divideIndex()!=first(v))throw std::runtime_error("MD_DIVIDE_RANK:"+label);
            if(d.get_io$$selectedSource1()!=id1||d.get_io$$selectedSource2()!=id2)throw std::runtime_error("MD_SOURCE_ADDRESS:"+label);
            if(sharedLeft!=expectedLeft||sharedRight!=expectedRight)throw std::runtime_error("MD_SHARED_DATA:"+label);
            if(d.get_io$$oldLeft()!=expectedLeft||d.get_io$$oldRight()!=expectedRight)throw std::runtime_error("MD_OLD_DATA:"+label);
            ++checked;empty+=selected<0;bothAvailable+=m&&v&&mr&&dr;
            onlyMultiply+=kind==1;onlyDivide+=kind==2;wraps+=selected>=0&&unsigned(selected)<head;
        }
        // Reads are pre-edge OLD values; only afterward apply actual two writer order.
        if(reset)rf.fill(0);
        else{
            if(w0&&wa0&&wa0<48)rf[wa0]=wd0;
            if(w1&&wa1&&wa1<48)rf[wa1]=wd1;
            if(w0&&w1&&wa0==wa1&&wa0){++collisions;
                if(mode=="--wrong-write-priority"){rf[wa0]=wd0;injected=true;}}
        }
    };
    auto simple=[&](uint16_t m,uint16_t v,unsigned h,bool mr,bool dr,const std::string &s){
        tick(false,m,v,h,mr,dr,false,63,0,false,63,0,s);};
    tick(true,0,0,0,false,false,false,63,0,false,63,0,"reset");
    tick(true,0,0,0,false,false,false,63,0,false,63,0,"reset");
    if(mode=="--invalid-write") {
        tick(false,0,0,0,false,false,true,48,1,false,0,0,"invalid-write");
        throw std::runtime_error("INVALID_WRITE_NOT_REJECTED");
    }
    if(mode=="--overlap-class") {
        tick(false,1,1,0,true,false,false,0,0,false,0,0,"overlap-class");
        throw std::runtime_error("OVERLAP_CLASS_NOT_REJECTED");
    }
    for(unsigned i=1;i<48;++i)tick(false,0,0,0,false,false,true,i,0xaabb000000000000ULL+i,false,63,0,"populate");
    simple(1,2,0,true,true,"both-ready");
    simple(uint16_t(1u<<2),uint16_t(1u<<15),14,true,true,"age-wrap");
    simple(1,2,0,true,false,"data");
    auto savedA=a[0];a[0]=0;simple(1,0,0,true,false,"zero");a[0]=savedA;
    a[0]=3;b[0]=4;
    tick(false,1,0,0,true,false,true,3,0x1111,true,3,0x2222,"old-read-before-collision");
    simple(1,0,0,true,false,"collision-result");
    // Exhaust all single-owner class choices, availability pairs and circular heads.
    for(unsigned h=0;h<16;++h)for(unsigned mi=0;mi<16;++mi)for(unsigned di=0;di<16;++di)if(mi!=di)
        for(unsigned available=0;available<4;++available)
            simple(uint16_t(1u<<mi),uint16_t(1u<<di),h,available&1,available&2,"bounded-owner-pairs");
    std::mt19937_64 rng(0x20261026d00dULL);
    for(unsigned n=0;n<12000;++n){
        uint16_t m=rng(),v=uint16_t(rng())&~m;
        for(unsigned i=0;i<16;++i){a[i]=rng()%48;b[i]=rng()%48;}
        unsigned wa0=rng()%48,wa1=n%5?rng()%48:wa0;
        tick(false,m,v,rng()%16,n%3!=0,n%7!=0,n%11!=0,wa0,rng(),n%13!=0,wa1,rng(),"random");
    }
    // Invalid IDs are safe only when unselected; compact PRF must not alias them.
    for(unsigned live=0;live<16;++live){a.fill(63);b.fill(62);a[live]=5;b[live]=9;
        simple(uint16_t(1u<<live),0,(live+3)%16,true,true,"unused-poison");++invalidUnused;
        simple(0,0,live,true,true,"empty-poison");++invalidUnused;}
    if(!mode.empty()&&!injected)throw std::runtime_error("UNKNOWN_OR_UNEXERCISED_NEGATIVE");
    if(!empty||!bothAvailable||!onlyMultiply||!onlyDivide||!collisions||!wraps||invalidUnused!=32)
        throw std::runtime_error("MD_DIRECTED_COVERAGE_MISSING");
    std::cout<<"PASS_SHARED_MULDIV_READS checks="<<checked<<" empty="<<empty<<" bothAvailable="<<bothAvailable
        <<" mul="<<onlyMultiply<<" div="<<onlyDivide<<" collisions="<<collisions<<" wraps="<<wraps
        <<" invalidUnused="<<invalidUnused<<" sideTicketAndFullOwnerIntegration=NOT_COVERED\n";
    return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
