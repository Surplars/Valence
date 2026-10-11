// Same real coherent DMA model and byte/ownership ledger; only the external
// service law differs. R starts after 32 cycles, B after 40 cycles for EVERY
// accepted transaction, independent of the DUT's chosen AXI ID.
#define main historical_dma_main
#include "dma_overlap.cpp"
#undef main

static void fixedCase(unsigned id, unsigned bytes) {
    diagnosticMode=0; profile=0; oracleLatency=1;
    Test t; t.ddr.idSkew=false;
    t.arm(base,base+0x40000,bytes); while(t.cycles%385) t.tick();
    const uint64_t begin=t.cycles;
    t.metrics.measure=true; t.ddr.corruptWrite=mutation=="corrupt-write"; t.ddr.dropWrite=mutation=="drop-write";
    t.control(24,true,7); t.until([&]{return t.d.get_io$$irq();},"fixed-law DMA IRQ timeout");
    const uint64_t done=t.cycles; t.completion(false); t.metrics.measure=false;
    check(t.control(32)==2,"fixed-law completion status mismatch");
    check(t.metrics.ops.size()==bytes/32,"fixed-law line operation count mismatch");
    for (auto& o:t.metrics.ops) {
        check(o.event[15]>=o.event[1] && o.event[2]==o.event[1],"fixed-law unfinished or split owner");
        const bool packet=!o.write && t.d.get_io$$lineReadEnabled();
        check(o.aBeats==(o.write?8U:packet?0U:1U) && o.dBeats==(o.write?1U:packet?0U:8U),"fixed-law TL beat mismatch");
        check(o.rBeats==(o.write?0U:8U) && o.wBeats==(o.write?8U:0U),"fixed-law AXI beat mismatch");
        if(packet) check(o.event[17]>=o.event[2] && o.event[18]>o.event[10],"fixed-law incomplete packet result");
        if(o.write) check(o.event[11]<=o.event[15],"fixed-law completion before backing B");
        // The transport cannot influence these external service intervals.
        check(o.write ? o.event[11]-o.event[8]>=40 : o.event[9]-o.event[5]>=32,
            "fixed-law independent service interval changed");
    }
    check(t.ddr.memory==t.oracle,"fixed-law independent full byte oracle mismatch");
    std::cout<<"PIPE_CASE case="<<id<<" bytes="<<bytes<<" entries="<<DMA_LINE_ENTRIES
        <<" mode=0 profile=0 oracle_latency=1 line_channel="<<bool(t.d.get_io$$lineReadEnabled())
        <<" cycles="<<done-begin<<" begin="<<begin<<" done="<<done<<" payload_MiBps="<<std::fixed<<std::setprecision(9)
        <<double(bytes)*100000000.0/double(done-begin)/1048576.0
        <<" axi_read_bytes="<<t.ddr.rBytes<<" axi_write_bytes="<<t.ddr.wBytes
        <<" axi_ar="<<t.ddr.arCount<<" axi_aw="<<t.ddr.awCount<<" axi_b="<<t.ddr.bCount
        <<" completion_after_actual_b="<<done-t.ddr.lastDestinationB<<"\n";
    t.metrics.print(id);
}
int main(int argc,char** argv) { try {
    if(argc>1) { std::string a=argv[1]; check(a.rfind("--mutate=",0)==0,"unknown fixed-law argument"); mutation=a.substr(9); }
    if(!mutation.empty()) { fixedCase(0,512); throw std::runtime_error("fixed-law negative did not reject"); }
    fixedCase(0,4096); fixedCase(1,131072);
    std::cout<<"DMA_FIXED_LATENCY_PASS R_delay=32 B_delay=40 ID_dependent_delay=0\n";
    return 0;
} catch(const std::exception& e) { std::cerr<<"DMA_FIXED_LATENCY_FAIL "<<e.what()<<"\n";return 1; } }
