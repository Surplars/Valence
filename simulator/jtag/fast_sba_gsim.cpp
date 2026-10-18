// Reuse the immutable independent byte-array bus driver, not a second RTL oracle.
#define main old_jtag_timing_main
#include "five_stage_jtag_timing.cpp"
#undef main

int main(int argc,char **argv) try {
    const bool wrong=argc>1 && std::string(argv[1])=="--wrong-word";
    unsigned cases=0,totalRequests=0;
    constexpr uint32_t plain=2U<<17, increment=plain|(1U<<16);
    for(unsigned words:{1U,2U,17U,1024U}) for(unsigned chunk:{1U,17U,256U})
        for(unsigned delay:{4U,20U}) for(bool atEnd:{false,true}) {
            Rig r; r.delay=delay; r.open();
            const uint32_t address=atEnd?end-words*4:base;
            const auto pattern=[](unsigned i) { return 0x89abcdefU^(i*0x9e3779b9U); };
            r.wr(0x38,increment|(1U<<20)|(1U<<15));
            check((r.rd(0x38)&0x1f8000)==(increment|(1U<<20)|(1U<<15)),"streaming controls not retained");
            r.wr(0x38,increment);
            for(unsigned i=0;i<words;++i) {
                if(i%chunk==0) r.wr(0x39,address+i*4);
                r.wr(0x3c,pattern(i)); r.idle();
                check(r.err()==0,"streamed RTL write failed");
            }
            for(unsigned first=0;first<words;first+=chunk) {
                const unsigned count=std::min(chunk,words-first);
                r.wr(0x38,increment|(1U<<20)|(count>1?1U<<15:0));
                r.wr(0x39,address+first*4);
                for(unsigned i=0;i<count;++i) {
                    r.idle();check(r.err()==0,"streamed RTL read failed");
                    if(i+1==count) r.wr(0x38,increment);
                    const auto actual=r.rd(0x3c),expected=pattern(first+i)^(wrong?1:0);
                    check(actual==expected,"independent streamed RTL readback oracle");
                }
                check(!(r.rd(0x38)&(1U<<21)),"chunk left a speculative read in flight");
            }
            check(r.requests==words*2&&r.writes==words,"extra/replayed RTL bus transaction");
            check(r.rd(0x39)==address+words*4,"final RTL increment mismatch");
            for(unsigned i=0;i<words;++i) {
                uint32_t observed=0;
                for(unsigned b=0;b<4;++b) observed|=uint32_t(r.ram[address-base+i*4+b])<<(8*b);
                check(observed==pattern(i),"independent final RTL bytes mismatch");
            }
            totalRequests+=r.requests; ++cases;
        }
    std::cout<<"I1_FAST_SBA_GSIM_PASS cases="<<cases<<" requests="<<totalRequests
        <<" autoincrement_readondata_final_chunk_and_aperture_no_extra_read=PASS\n";
    return 0;
} catch(const std::exception &e) { std::cerr<<"FAIL: "<<e.what()<<'\n'; return 1; }
