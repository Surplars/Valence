// Real CPU instruction stream; independent scalar/IEEE/memory expectations.
#define I1_SPINOR_CPU
#define I1_COREMARK_MEMORY_ONLY
#include "five_stage_coremark.cpp"

struct Expected {
    uint64_t pc, next, value, mask = UINT64_MAX, cause = 0, tval = 0;
    uint32_t instruction;
    unsigned rd, flags = 0;
    bool integer, floating = false, trap = false;
};
struct Offer { uint32_t instruction; uint64_t sequence; std::optional<uint64_t> scalar; };
struct Program {
    std::vector<uint8_t> image = std::vector<uint8_t>(0x12000);
    std::vector<Expected> expected;
    std::vector<Offer> offers;
    unsigned cursor = 0, traps = 0, sequence = 0;
    void bytes(unsigned offset, uint64_t value, unsigned size) {
        for (unsigned n=0;n<size;++n) image.at(offset+n)=value>>(n*8);
    }
    void emit(uint32_t i, unsigned rd=0, uint64_t value=0, bool fp=false, unsigned flags=0,
              uint64_t mask=UINT64_MAX) {
        expected.push_back({BASE+cursor,BASE+cursor+4,value,mask,0,0,i,rd,flags,rd!=0&&!fp,fp,false});
        bytes(cursor,i,4);cursor+=4;
    }
    void vec(uint32_t i, unsigned rd=0, uint64_t value=0, bool fp=false, unsigned flags=0,
             std::optional<uint64_t> scalar={}) {
        offers.push_back({i,sequence++,scalar}); emit(i,rd,value,fp,flags);
    }
    void trap(uint32_t i, bool native) {
        unsigned pc=cursor;
        if(native) offers.push_back({i,sequence,{}});
        ++sequence;
        expected.push_back({BASE+pc,BASE+0x400,0,UINT64_MAX,2,i,i,0,0,false,false,true});
        bytes(cursor,i,4);cursor+=4;
        // One literal handler; append the executed path without changing main cursor.
        unsigned saved=cursor; cursor=0x400;
        emit(ri(0x13,25,0,25,1),25,++traps);
        emit(ri(0x73,26,2,0,0x342),26,2);
        emit(ri(0x73,27,2,0,0x343),27,i);
        emit(ri(0x73,28,2,0,0x341),28,BASE+pc);
        emit(ri(0x13,28,0,28,4),28,BASE+pc+4);
        emit(ri(0x73,0,1,28,0x341));
        emit(0x30200073); expected.back().next=BASE+pc+4;
        cursor=saved;
    }
    Program() {
        bytes(0x2000,0x0000000200000001ULL,8);bytes(0x2008,0x0000000400000003ULL,8);
        bytes(0x2040,0x3f800000,4);
        bytes(0x2050,0x400000003fc00000ULL,8);bytes(0x2058,0x4080000040600000ULL,8);
        bytes(0x2070,0x3380000033800000ULL,8);bytes(0x2078,0x3380000033800000ULL,8);
        emit(0x00000097,1,BASE);emit(ri(0x13,1,0,1,0x400),1,BASE+0x400);
        emit(ri(0x73,0,1,1,0x305));emit(ri(0x13,25,0,0,0),25,0);
        trap(0x0103f357,false); // VS=Off: CPU rejects before native offer.
        emit(0x000022b7,5,0x2000);emit(ri(0x13,5,0,5,0x200),5,0x2200);
        emit(ri(0x73,0,2,5,0x300)); // VS/FS Initial, independent dirty transitions.
        emit(ri(0x13,7,0,0,4),7,4);
        vec(0x0103f357,6,4,false,0,4); // vsetvli e32,m1
        unsigned auipc=cursor;emit(0x00002417,8,BASE+auipc+0x2000);
        emit(ri(0x13,8,0,8,-int(auipc)),8,BASE+0x2000);
        emit(ri(0x03,10,3,8,0x20),10,0); // Prime destination D-cache line.
        vec(0x02046107,0,0,false,0,BASE+0x2000); // vle32.v v2
        vec(0x0221b0d7); // vadd.vi v1,v2,3
        emit(ri(0x13,9,0,8,0x20),9,BASE+0x2020);
        vec(0x0204e0a7,0,0,false,0,BASE+0x2020); // vse32.v v1
        emit(ri(0x03,10,3,9,0),10,0x0000000500000004ULL);
        emit(ri(0x03,11,3,9,8),11,0x0000000700000006ULL);
        emit((2u<<27)|(9<<15)|(2<<12)|(22<<7)|0x2f,22,4); // LR.W
        vec(0x0204e0a7,0,0,false,0,BASE+0x2020);
        emit((3u<<27)|(9<<15)|(2<<12)|(23<<7)|0x2f,23,1); // SC.W fails after vector store.
        vec(ri(0x73,12,2,0,0xc20),12,4);
        vec(ri(0x73,13,2,0,0xc21),13,16);
        vec(ri(0x73,14,2,0,0xc22),14,16);
        vec(ri(0x73,15,2,0,0x008),15,0);
        emit(ri(0x73,16,2,0,0x300),16,0x8000000000002600ULL,false,0,0x8000000000006600ULL);
        emit(ri(0x07,0,2,8,0x40),0,0xffffffff3f800000ULL,true); // FLW f0=1
        emit(ri(0x13,14,0,8,0x50),14,BASE+0x2050);
        vec(0x02076107,0,0,false,0,BASE+0x2050); // vle32.v v2,(x14)
        vec(0x022050d7,0,0,false,0,0xffffffff3f800000ULL); // vfadd.vf v1,v2,f0
        vec(0x0204e0a7,0,0,false,0,BASE+0x2020);
        emit(ri(0x03,10,3,9,0),10,0x4040000040200000ULL);
        emit(ri(0x03,11,3,9,8),11,0x40a0000040900000ULL);
        vec(0x42101057,0,0xffffffff40200000ULL,true); // vfmv.f.s f0,v1
        emit(0xe2000953,18,0xffffffff40200000ULL); // fmv.x.d x18,f0
        emit(ri(0x07,0,2,8,0x40),0,0xffffffff3f800000ULL,true);
        emit(ri(0x73,0,5,3,0x002)); // frm=RUP
        emit(ri(0x73,0,5,0,0x001)); // clear CPU fflags
        emit(ri(0x13,14,0,8,0x70),14,BASE+0x2070);
        vec(0x02076107,0,0,false,0,BASE+0x2070);
        vec(0x022050d7,0,0,false,1,0xffffffff3f800000ULL);
        vec(0x0204e0a7,0,0,false,0,BASE+0x2020);
        emit(ri(0x03,10,3,9,0),10,0x3f8000013f800001ULL);
        emit(ri(0x73,19,2,0,0x001),19,1);
        trap(ri(0x73,0,1,5,0xc22),true); // native read-only CSR exception.
        emit(ri(0x13,20,0,0,1),20,1);
        emit(st(3,8,20,0x180)); // completion sentinel
        emit(0x0000006f); // stop at preceding sentinel retirement
        expected.pop_back();
    }
};

#ifndef I1_SPINOR_PROGRAM_ONLY
int main(int argc,char**argv) {try {
    const bool inject=argc>1&&std::string(argv[1])=="--inject-value";
    const bool injectFlags=argc>1&&std::string(argv[1])=="--inject-flags";
    for(unsigned latency:{1u,12u}) {
        Program p;Model d;Memory memory(d,p.image,latency);
        d.set_reset(1);d.set_io$$time(0);d.set_io$$externalIrq(0);d.set_io$$timerIrq(0);d.set_io$$softwareIrq(0);
        memory.inputs(0);d.step();d.step();d.set_reset(0);
        unsigned checked=0,offered=0,done=0;uint64_t cycle=0;
        for(;cycle<40000 && checked<p.expected.size();++cycle) {
            memory.inputs(cycle);d.set_io$$time(cycle);d.step();memory.outputs(cycle);
            need(!d.get_io$$protocolError(),"Spinor native protocol error");
            if(d.get_observation$$vectorOffer$$valid()) {
                need(offered<p.offers.size(),"unexpected CPU vector command");
                auto o=p.offers.at(offered++);
                auto token=d.get_observation$$vectorOffer$$bits$$token();
                need(uint64_t(token>>64)==0xbeef && uint64_t(token)==o.sequence,"CPU 80-bit vector token oracle");
                need(d.get_observation$$vectorOffer$$bits$$instruction()==o.instruction,"CPU vector command order oracle");
                if(o.scalar) need(d.get_observation$$vectorOffer$$bits$$scalar()==*o.scalar,"CPU native scalar/f0 operand oracle");
            }
            done+=d.get_observation$$vectorDone();
            if(!d.get_observation$$retire$$valid()) continue;
            auto e=p.expected.at(checked);
            if(inject && e.instruction==0x0103f357 && !e.trap)e.value^=1;
            if(injectFlags && e.flags)e.flags^=1;
            const std::string at=" index="+std::to_string(checked)+" pc="+std::to_string(e.pc);
            need(d.get_observation$$retire$$bits$$pc()==e.pc && d.get_observation$$retire$$bits$$instruction()==e.instruction,
                 "CPU vector independent PC/instruction oracle"+at);
            need(bool(d.get_observation$$retire$$bits$$trap())==e.trap,"CPU vector independent trap oracle"+at);
            if(e.trap) need(d.get_observation$$retire$$bits$$cause()==e.cause && d.get_observation$$retire$$bits$$tval()==e.tval,
                           "CPU vector precise cause/tval oracle"+at);
            need(bool(d.get_observation$$retire$$bits$$writesRd())==e.integer,"CPU vector integer enable oracle"+at);
            if(e.integer) {
                const uint64_t got=d.get_observation$$retire$$bits$$data();
                need(d.get_observation$$retire$$bits$$rd()==e.rd && (got&e.mask)==(e.value&e.mask),
                     "CPU vector independent value oracle"+at+" got="+std::to_string(got)+" expected="+std::to_string(e.value));
            }
            need(bool(d.get_observation$$retire$$bits$$floating$$write())==e.floating,"CPU vector FPR enable oracle"+at);
            if(e.floating) need(d.get_observation$$retire$$bits$$rd()==e.rd && d.get_observation$$retire$$bits$$floating$$data()==e.value,
                                "CPU vector independent f0/IEEE oracle"+at);
            need(d.get_observation$$retire$$bits$$floating$$flags()==e.flags,"CPU vector independent flags oracle"+at);
            if(!e.trap)need(d.get_observation$$retire$$bits$$nextPc()==e.next,"CPU vector precise next-PC oracle"+at);
            ++checked;
        }
        need(checked==p.expected.size(),"CPU vector bounded completion index="+std::to_string(checked));
        need(offered==p.offers.size()&&done==offered,"CPU vector native offer/done ledger");
        need(memory.load(BASE+0x2020)==0x3f8000013f800001ULL && memory.load(BASE+0x2028)==0x3f8000013f800001ULL,
             "CPU vector final independent RAM oracle");
        need(memory.load(BASE+0x2180)==1,"CPU scalar completion sentinel oracle");
        std::cout<<"I1_SPINOR_CPU_PASS latency="<<latency<<" cycles="<<cycle<<" retire="<<checked
                 <<" vector_commands="<<offered<<" traps=2 token80_VS_FCSR_f0_cache_LRSC=PASS\n";
    }
    return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}

#endif
