#include "FloatingPointCpuGsim.h"
#include <array>
#include <cstdint>
#include <deque>
#include <fstream>
#include <iostream>
#include <map>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>
#include "protected_head_payload.h"
struct Vector {unsigned inst,rm,flags;uint64_t a,b,c,integer,value;};
struct Instruction {
    uint64_t pc;uint32_t bits;unsigned bytes;
    bool checkInt=false,writeFp=false;unsigned fp=0;uint64_t value=0;int fcsr=-1;
};
static void check(bool v,const std::string& why) {if(!v) throw std::runtime_error("FP full CPU mismatch: "+why);}
static bool integerResult(unsigned inst) {
    unsigned f=inst>>25;return (f&~1U)==0x60 || (f&~1U)==0x50 || (f&~1U)==0x70;
}
int main(int argc,char** argv) {try {
    if(argc<2) throw std::runtime_error("vectors required");
    bool inject=argc>2;
    std::ifstream input(argv[1]);Vector v{};std::vector<Vector> vectors;
    std::map<unsigned,unsigned> seen;
    while(input>>std::hex>>v.inst>>v.rm>>v.a>>v.b>>v.c>>v.integer>>v.value>>v.flags) {
        // Take edge + random cases for each distinct instruction/rounding encoding.
        const unsigned count=seen[v.inst]++;
        if(count==0 || count==1 || count==19 || count==20 || count==47 || count==80) vectors.push_back(v);
    }
    check(input.eof() && vectors.size()>700,"CPU vector selection");
    std::vector<Instruction> code;std::map<uint64_t,unsigned> at;uint64_t pc=0x80000000;
    auto emit=[&](uint32_t inst,bool ci=false,uint64_t value=0,bool wf=false,unsigned fp=0,int csr=-1,unsigned bytes=4) {
        at[pc]=code.size();code.push_back({pc,inst,bytes,ci,wf,fp,value,csr});pc+=bytes;
    };
    auto constant=[&](unsigned rd,uint64_t value) {
        uint64_t current=value>>55;
        emit((unsigned(current)<<20)|(rd<<7)|0x13,true,current);
        for(int shift=44;shift>=0;shift-=11) {
            current <<=11;emit((11U<<20)|(rd<<15)|(1U<<12)|(rd<<7)|0x13,true,current);
            unsigned part=(value>>shift)&2047;current+=part;
            emit((part<<20)|(rd<<15)|(rd<<7)|0x13,true,current);
        }
    };
    auto move=[&](unsigned rd,unsigned rs,uint64_t value) {
        emit(0xf2000053U|(rs<<15)|(rd<<7),false,value,true,rd);
    };
    emit(0x30102473,true,0x800000000014112dULL); // CSRRS x8,misa,x0; independent RV64 IMAFDC/S/U anchor
    constant(5,0x2000);
    emit(0x3002a073); // CSRS mstatus, x5: FS=Initial
    unsigned vectorCount=0;
    for(const auto& r:vectors) {
        // Initialize raw binary64 FPRs using real instructions, not test-only injection.
        constant(1,r.a);move(1,1,r.a);
        constant(2,r.b);move(2,2,r.b);
        constant(4,r.c);move(3,4,r.c);
        constant(1,r.integer);
        // Exercise dynamic frm on selected static-rm arithmetic vectors.
        bool rounded=(r.inst&127)!=0x53 || ((r.inst>>25)&~1U)==0 || ((r.inst>>25)&~1U)==4 ||
            ((r.inst>>25)&~1U)==8 || ((r.inst>>25)&~1U)==12 || ((r.inst>>25)&~1U)==0x2c ||
            ((r.inst>>25)&~1U)==0x60 || ((r.inst>>25)&~1U)==0x68 || ((r.inst>>25)&~1U)==0x20;
        bool dynamic=rounded && (vectorCount%3==0) && r.rm<5;
        unsigned frm=dynamic?r.rm:0;
        emit(((frm<<5)<<20)|(5U<<7)|0x13,true,frm<<5);
        emit(0x00329073,false,0,false,0,int(frm<<5)); // CSRW fcsr,x5
        unsigned inst=dynamic?((r.inst&~0x7000U)|0x7000U):r.inst;
        bool toInt=integerResult(inst);
        emit(inst,toInt,r.value,!toInt,3,int((frm<<5)|r.flags));
        // Force an integer destination and verify readback of accrued flags.
        emit(0x00302473,true,(frm<<5)|r.flags); // CSRRS x8,fcsr,x0
        ++vectorCount;
    }
    const uint64_t memoryBase=0x80010000, pattern=0x0123456789abcdefULL;
    constant(2,memoryBase);constant(8,memoryBase);
    constant(1,pattern);move(3,1,pattern);move(8,1,pattern);
    emit(0xa00e,false,0,false,0,-1,2); // C.FSDSP f3,0(sp)
    emit(0x2002,false,pattern,true,0,-1,2); // C.FLDSP f0,0(sp); f0 is legal
    emit(0xa400,false,0,false,0,-1,2); // C.FSD f8,8(x8)
    emit(0x2404,false,pattern,true,9,-1,2); // C.FLD f9,8(x8)
    emit(0x13); // final architectural barrier
    SFloatingPointCpuGsim dut;
    dut.set_io$$instruction0$$valid(false);dut.set_io$$instruction1$$valid(false);
    dut.set_io$$commitEnable(false);dut.set_io$$inspectRegister(0);dut.set_io$$inspectFpRegister(0);
    dut.set_io$$memory$$request$$ready(false);dut.set_io$$memory$$response$$valid(false);
    dut.set_io$$memory$$response$$bits$$error(false);dut.set_io$$memory$$response$$bits$$pageFault(false);
    dut.set_io$$memory$$response$$bits$$data(0);dut.set_reset(1);protectedStep(dut);protectedStep(dut);dut.set_reset(0);
    std::array<uint64_t,32> fp{};std::map<uint64_t,uint8_t> memory;
    struct Reply {uint64_t data;unsigned delay;};std::deque<Reply> replies;
    std::mt19937 random(17);uint64_t fetch=0x80000000;
    unsigned committed=0,requests=0,responses=0,cycles=0,fpRetired=0,hold=0;
    unsigned fs=0,fcsr=0;bool done=false;
    for(;cycles<1000000;++cycles) {
        bool allow=hold==0 && random()%5!=0;
        bool supply=random()%7!=0 && !dut.get_io$$pauseFetch();
        bool ready=replies.empty()&&random()%4!=0, reply=!replies.empty()&&replies.front().delay==0;
        dut.set_io$$commitEnable(allow);dut.set_io$$inspectFpRegister(cycles%32);
        dut.set_io$$memory$$request$$ready(ready);dut.set_io$$memory$$response$$valid(reply);
        dut.set_io$$memory$$response$$bits$$data(reply?replies.front().data:0);
        uint64_t offered=fetch;unsigned offeredBytes[2]={0,0};
        for(unsigned lane=0;lane<2;++lane) {
            bool valid=supply&&at.count(offered);unsigned inst=valid?code[at.at(offered)].bits:0;
            if(valid){offeredBytes[lane]=code[at.at(offered)].bytes;offered+=offeredBytes[lane];}else supply=false;
            if(lane==0){dut.set_io$$instruction0$$valid(valid);dut.set_io$$instruction0$$bits(inst);}
            else {dut.set_io$$instruction1$$valid(valid);dut.set_io$$instruction1$$bits(inst);}
        }
        protectedStep(dut);
        check(dut.get_io$$fetchPc()==fetch,"fetch cursor");
        check(dut.get_io$$committedFpValue()==fp[cycles%32],"FPR may only change at exact ROB retirement");
        check(dut.get_io$$fpFcsr()==fcsr && dut.get_io$$fpFs()==fs,"FS/FCSR retirement state");
        check(!dut.get_io$$trap$$valid(),"unexpected precise trap at "+std::to_string(committed));
        // CSR/context writes are idle, irrevocable-head-authorized updates;
        // numerical FPR/flags updates, in contrast, wait for exact ROB retirement.
        if(dut.get_io$$fpCsrWrite()) {
            check(committed<code.size()&&code[committed].bits==0x00329073,"head-authorized FCSR write");
            fcsr=code[committed].fcsr;fs=3;
        }
        if(dut.get_io$$fpSetFs()) {
            check(committed<code.size()&&code[committed].bits==0x3002a073,"head-authorized FS context write");
            fs=1;
        }
        if(hold)--hold;
        if(dut.get_io$$fpStart()) hold=5; // deliberately stall architectural retirement
        if(dut.get_io$$memory$$request$$valid()&&ready) {
            uint64_t address=dut.get_io$$memory$$request$$bits$$address();
            check(address>=memoryBase&&address<memoryBase+16,"compressed FP memory address");
            uint64_t beat=0;
            for(unsigned b=0;b<8;++b) beat|=uint64_t(memory[(address&~7ULL)+b])<<(8*b);
            if(dut.get_io$$memory$$request$$bits$$write()) {
                unsigned mask=dut.get_io$$memory$$request$$bits$$mask();
                uint64_t data=dut.get_io$$memory$$request$$bits$$data();
                for(unsigned b=0;b<8;++b)if(mask>>b&1)memory[(address&~7ULL)+b]=data>>(8*b);
            }
            replies.push_back({beat,unsigned(2+random()%7)});++requests;
        }
        if(reply&&dut.get_io$$memory$$response$$ready()){replies.pop_front();++responses;}
        if(!replies.empty()&&replies.front().delay)--replies.front().delay;
        uint64_t nextFetch=fetch;
        if(dut.get_io$$accepted0())nextFetch+=offeredBytes[0];
        if(dut.get_io$$accepted1())nextFetch+=offeredBytes[1];
        auto commit=[&](bool valid,uint64_t cpc,unsigned inst,bool writes,uint64_t data,uint64_t next) {
            if(!valid)return;
            check(allow&&committed<code.size(),"unauthorized retirement");
            const auto& expected=code[committed];
            check(cpc==expected.pc&&inst==expected.bits&&next==cpc+expected.bytes,"ordered raw instruction/PC length");
            uint64_t wanted=expected.value;
            if(inject&&expected.checkInt&&((inst>>20)&4095)==3){wanted^=1;inject=false;}
            if(expected.checkInt)check(writes&&data==wanted,"independent integer result/flags readback");
            if(expected.writeFp){fp[expected.fp]=expected.value;fs=3;}
            if(expected.fcsr>=0){fcsr=expected.fcsr;fs=3;}
            if(inst==0x3002a073)fs=1;
            bool isFp=(inst&127)==0x53 || (inst&127)==0x43 || (inst&127)==0x47 ||
                (inst&127)==0x4b || (inst&127)==0x4f || expected.bytes==2;
            if(isFp)++fpRetired;
            ++committed;
        };
#define C(n) commit(dut.get_io$$commit##n##$$valid(),dut.get_io$$commit##n##$$bits$$pc(),dut.get_io$$commit##n##$$bits$$instruction(),dut.get_io$$commit##n##$$bits$$writesRd(),dut.get_io$$commit##n##$$bits$$data(),dut.get_io$$commit##n##$$bits$$nextPc())
        C(0);C(1);
#undef C
        if(dut.get_io$$redirect$$valid())nextFetch=dut.get_io$$redirect$$bits$$target();
        fetch=protectedNextFetch(dut);
        if(committed==code.size()){done=true;break;}
    }
    check(done&&requests==4&&responses==4&&replies.empty(),"CPU bounded completion and four compressed memory transfers");
    dut.set_io$$instruction0$$valid(false);dut.set_io$$instruction1$$valid(false);dut.set_io$$commitEnable(false);
    for(unsigned f=0;f<32;++f){dut.set_io$$inspectFpRegister(f);protectedStep(dut);check(dut.get_io$$committedFpValue()==fp[f],"final FPR state");}
    check(fp[0]==pattern&&fp[9]==pattern,"compressed f0/prime FPR result");
    std::cout<<"FP_FULL_CPU_PASS vectors="<<vectorCount<<" commits="<<committed<<" cycles="<<cycles
        <<" compressed_memory=4 fp_retired="<<fpRetired<<" dynamic_frm=1 commit_backpressure=1 misa_gc=1\n";
    return 0;
} catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
