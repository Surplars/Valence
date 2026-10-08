// Reuse precisely the board model and independent memory implementation. This
// executable requires the explicit multi-ID memory flag; legacy board tests do not.
#ifndef DDR_MULTI_ID_MODEL
#error "board_dma_window requires explicit DDR_MULTI_ID_MODEL"
#endif
#define main board_boot_regression_main
#include "board_boot.cpp"
#undef main
int main(int argc,char**argv) {
    try {
        check(argc==2||argc==3,"usage: run board_dma_window.bin [--inject-mismatch]");
        const auto rom=readFile(argv[1]);Test t(rom);
        constexpr uint32_t source=0x10000,destination=0x20000;
        constexpr unsigned words=64;
        auto expected=[](unsigned n){return 0x9234567800000000ULL^(0x100100101ULL*n);};
        for(unsigned n=0;n<words;++n){t.ddr.memory[source+n*8]=expected(n);t.ddr.memory[destination+n*8]=~expected(n);}
        uint64_t begin=0,end=0;
        bool started=false,finished=false;
        const auto deadline=t.cycles+100000;
        while(t.cycles<deadline) {
            t.tick();
            if(!started&&t.ddr.reads){started=true;begin=t.cycles;}
            if(!finished&&t.ddr.writes==words&&!t.ddr.writing&&!t.ddr.responding){finished=true;end=t.cycles;}
            check(t.received.empty()||t.received.front()!='F',"DMA firmware status error");
            if(!t.received.empty()&&t.received.front()=='D')break;
        }
        check(started&&finished&&!t.received.empty()&&t.received.front()=='D',"DMA board stimulus did not finish");
        check(t.ddr.reads==words&&t.ddr.writes==words,"DMA board transaction loss/duplication");
        for(unsigned n=0;n<words;++n) {
            check(t.ddr.memory[destination+n*8]==(expected(n)^((argc==3&&n==0)?1ULL:0ULL)),"DMA independent destination oracle mismatch");
            check(t.ddr.memory[source+n*8]==expected(n),"DMA changed source backing");
        }
        std::cout<<"BOARD_DMA_WINDOW_PASS bytes="<<words*8<<" cycles="<<end-begin+1
            <<" peak_read_ids="<<t.ddr.peakReadIds<<" reads="<<t.ddr.reads<<" writes="<<t.ddr.writes
            <<" reordered_beats="<<t.ddr.reorderedBeats<<" latency="<<DDR_READ_LATENCY
            <<" read_gap="<<DDR_READ_BEAT_GAP<<" model_credits="<<DDR_READ_CREDITS<<"\n";
        return 0;
    }catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}
}
