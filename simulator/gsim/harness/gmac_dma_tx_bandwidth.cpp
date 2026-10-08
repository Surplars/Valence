#define SELF_GMAC_DMA_NO_MAIN 1
#define TX_POSTED_SLOTS 4
#include "self_gmac_dma.cpp"
#ifndef MAC_TX_FRAME_SLOTS
#define MAC_TX_FRAME_SLOTS 1
#endif
int main(int argc,char**argv){try{
    const bool inject=argc==2&&std::string_view(argv[1])=="--inject-mismatch";
    for(unsigned length:{60U,1514U,2048U}){
        Test t(0x32a8);t.deterministicMemory=true;constexpr unsigned frames=24,slots=4;
        std::deque<unsigned> owners;std::vector<std::vector<uint8_t>> expected;unsigned posted=0,retired=0;
        auto post=[&]{unsigned slot=posted%slots,address=slot*2048;auto body=ethernetBody(length,0x100+posted);std::copy(body.begin(),body.end(),t.memory.begin()+address);expected.push_back(ethernetWire(body));
            if(inject&&posted==0)expected.back()[21]^=1;
            t.access(224,true,ram+address);t.access(232,true,length);t.access(240,true,4);owners.push_back(posted++);};
        t.access(240,true,1);t.access(8,true,1);const unsigned begin=t.cycles;
        while(posted<slots)post();
        while(retired<frames){const uint64_t status=t.access(248);if((status>>8)&255){check(!owners.empty(),"DMA benchmark completed without a descriptor owner");unsigned owner=owners.front();
                check(t.access(224)==ram+(owner%slots)*2048&&t.access(232)==length,"DMA benchmark completion identity/result mismatch");
                t.access(240,true,8);owners.pop_front();++retired;if(posted<frames)post();
            }else t.tick();check(t.cycles-begin<300000,"DMA bandwidth benchmark timeout");}
        while(t.G(txBusy)||!t.burst.empty()||t.wires.size()<frames)t.tick();
        check(t.replies.empty()&&!t.held&&owners.empty()&&!t.rejected,"DMA bandwidth ownership failed to drain");
        check(t.wires==expected,"DMA bandwidth independent wire oracle mismatch");
        check(t.reads==frames*((length+7)/8)&&t.wireStarts.size()==frames,"DMA bandwidth beat/frame accounting mismatch");
        unsigned sum=0,min=~0U,max=0;
        for(unsigned n=4;n<frames;++n){unsigned delta=t.wireStarts[n]-t.wireStarts[n-1];sum+=delta;min=std::min(min,delta);max=std::max(max,delta);check(delta>=length+24,"DMA bandwidth IFG violation");}
#if MAC_TX_FRAME_SLOTS > 1
        check(t.dmaStreamOverlap>0,"banked MAC did not overlap actual DMA stream collection");
#else
        check(t.dmaStreamOverlap==0,"legacy MAC unexpectedly overlapped DMA stream collection");
#endif
        std::cout<<"GMAC_DMA_TX_BANDWIDTH mac_slots="<<MAC_TX_FRAME_SLOTS<<" posted_slots=4 body="<<length<<" frames="<<frames<<" measured_intervals="<<frames-4<<" interval_min="<<min<<" interval_max="<<max<<" interval_sum="<<sum<<" dma_stream_wire_overlap="<<t.dmaStreamOverlap<<" ddr_read_wire_overlap="<<t.ddrReadOverlap<<" reads="<<t.reads<<" peak_memory_credits="<<t.peak<<" total_cycles="<<t.cycles-begin<<"\n";
    }
    std::cout<<"GMAC_DMA_TX_BANDWIDTH_PASS profiles=3 complete_owner_retirement=1 fixed_memory_latency=1 independent_wire_fcs=1\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
