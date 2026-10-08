#define TRI_SPEED_NO_MAIN 1
#include "trispeed_gmac_frames.cpp"
#ifndef TX_FRAME_SLOTS
#define TX_FRAME_SLOTS 1
#endif
int main(int argc,char**argv){try{
    const bool inject=argc==2&&std::string_view(argv[1])=="--inject-mismatch";
    for(unsigned rate:{2U,1U,0U})for(unsigned length:{60U,1514U,2048U}){
        Test t;t.randomReady=false;t.setRate(rate);constexpr unsigned frames=16;
        std::vector<std::vector<uint8_t>> bodies;
        for(unsigned n=0;n<frames;++n){bodies.push_back(ethernetBody(length,0x900+n));t.expectedTx.push_back(ethernetWire(bodies.back()));}
        if(inject)t.expectedTx.front()[31]^=1;
        const unsigned begin=t.cycles;
        // Continuously asserted native input, across packet boundaries. Both
        // profiles see the same unlimited producer; only DUT ready throttles it.
        for(const auto&body:bodies)t.submit(body);t.drain();
        check(t.txComplete==frames&&t.txDone==frames&&!t.txReject,"TX bandwidth frame/completion accounting mismatch");
        check(t.wireStarts.size()==frames&&t.inputEnds.size()==frames,"TX bandwidth timing witness count mismatch");
        const unsigned ideal=(length+24)*t.factor();
        unsigned minGap=~0U,maxGap=0,sum=0;
        for(unsigned n=1;n<frames;++n){const unsigned gap=(t.wireStarts[n]-t.wireStarts[n-1])/2;minGap=std::min(minGap,gap);maxGap=std::max(maxGap,gap);sum+=gap;
            check(gap>=ideal,"TX bandwidth violated frame/FCS/scaled IFG budget");
#if TX_FRAME_SLOTS > 1
            check(gap==ideal,"double-buffer TX missed saturated line-rate initiation budget");
#endif
        }
#if TX_FRAME_SLOTS > 1
        check(t.inputOverlap>0,"double-buffer TX did not collect while serializing");
#else
        check(t.inputOverlap==0,"single-buffer baseline unexpectedly overlapped collection");
#endif
        std::cout<<"TX_BANDWIDTH slots="<<TX_FRAME_SLOTS<<" mbps="<<(rate==2?1000:rate==1?100:10)<<" body="<<length<<" frames="<<frames<<" steady_interval_min="<<minGap<<" steady_interval_max="<<maxGap<<" steady_interval_sum="<<sum<<" ideal_interval="<<ideal<<" accepted_input_beats="<<t.inputBeats<<" collection_wire_overlap="<<t.inputOverlap<<" producer_stall_cycles="<<t.inputStalled<<" total_cycles="<<t.cycles-begin<<"\n";
    }
    std::cout<<"TX_BANDWIDTH_PASS profiles=9 input_pacing=continuous frame_oracle=independent\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
