#pragma once
#include <array>
#include <map>
// Observers use only public handshake signals. No DUT state supplies expected bytes.
struct PipelineMetrics {
    struct Op {
        bool write; uint64_t address;
        std::array<int64_t,17> event;
        unsigned aBeats=0,dBeats=0,rBeats=0,wBeats=0,source=0;
        Op(bool w,uint64_t a):write(w),address(a){event.fill(-1);}
    };
    std::vector<Op> ops;
    bool measure=false;
    uint64_t lineBlocked=0,homeBlocked=0,tlABlocked=0,tlDBlocked=0,arBlocked=0,awBlocked=0,wBlocked=0,rBlocked=0,bBlocked=0;
    uint64_t tlA=0,tlD=0,lineArea=0,homeArea=0,bridgeArea=0,bridgeRArea=0,bridgeWArea=0,axiRArea=0,axiWArea=0;
    uint64_t linePeak=0,homePeak=0,bridgePeak=0,bridgeRPeak=0,bridgeWPeak=0,axiRPeak=0,axiWPeak=0;
    std::map<unsigned,unsigned> bridgeR,bridgeW,axiR,axiW;
    bool lineLive=false,homeLive=false;
    std::array<uint64_t,5> bridgeHistogram{},axiHistogram{};
    template<class Dut> void sample(Dut& d,uint64_t c,PipelineDdr& memory,bool oracleResponseValid){
        if(!measure)return;
        lineBlocked+=d.get_io$$lineRequestOffer()&&!d.get_io$$lineRequestReady();
        homeBlocked+=d.get_io$$homeLineOffer()&&!d.get_io$$homeLineFire();
        tlABlocked+=d.get_io$$tlAValid()&&!d.get_io$$tlAReady();
        tlDBlocked+=d.get_io$$tlDValid()&&!d.get_io$$tlDReady();
        arBlocked+=d.get_io$$ddrAxi$$ar$$valid()&&!memory.arReady;
        awBlocked+=d.get_io$$ddrAxi$$aw$$valid()&&!memory.awReady;
        wBlocked+=d.get_io$$ddrAxi$$w$$valid()&&!memory.wReady;
        rBlocked+=memory.rValid&&!d.get_io$$ddrAxi$$r$$ready();
        bBlocked+=memory.bValid&&!d.get_io$$ddrAxi$$b$$ready();
        if(d.get_io$$lineRequestOffer()&&(ops.empty()||ops.back().event[15]>=0)){
            ops.emplace_back(bool(d.get_io$$lineRequestWrite()),d.get_io$$lineRequestAddress());ops.back().event[0]=c;
        }
        if(!ops.empty()){
            auto&o=ops.back();auto mark=[&](unsigned i){check(o.event[i]<0,"duplicate observed pipeline event");o.event[i]=c;};
            if(d.get_io$$lineRequestFire()){mark(1);check(!lineLive,"overlapped single DMA owner");lineLive=true;}
            if(d.get_io$$homeLineFire()){mark(2);check(!homeLive,"overlapped single home owner");homeLive=true;}
            if(d.get_io$$tlAValid()&&d.get_io$$tlAReady()){
                ++tlA;auto id=unsigned(d.get_io$$tlASource());unsigned opcode=d.get_io$$tlAOpcode();
                if(!o.aBeats){mark(3);o.source=id;check(!bridgeR.count(id)&&!bridgeW.count(id),"TL reused observed source");
                    (opcode==4?bridgeR:bridgeW)[id]=opcode==4?8:1;}
                ++o.aBeats;if((opcode==4&&o.aBeats==1)||(opcode==0&&o.aBeats==8))mark(4);
            }
            if(d.get_io$$ddrAxi$$ar$$valid()&&memory.arReady){
                mark(5);check(!axiR.count(d.get_io$$ddrAxi$$ar$$bits$$id()),"AXI read owner reused");axiR[d.get_io$$ddrAxi$$ar$$bits$$id()]=1;
            }
            if(d.get_io$$ddrAxi$$aw$$valid()&&memory.awReady){
                mark(6);check(!axiW.count(d.get_io$$ddrAxi$$aw$$bits$$id()),"AXI write owner reused");axiW[d.get_io$$ddrAxi$$aw$$bits$$id()]=1;
            }
            if(d.get_io$$ddrAxi$$w$$valid()&&memory.wReady){
                if(!o.wBeats)mark(7);++o.wBeats;if(d.get_io$$ddrAxi$$w$$bits$$last())mark(8);
            }
            if(memory.rValid&&d.get_io$$ddrAxi$$r$$ready()){
                auto r=PipelineDdr::selected(memory.reads,memory.heldR);check(r!=memory.reads.end(),"observed R missing host owner");
                if(!o.rBeats)mark(9);++o.rBeats;if((r->beat+1==r->count)){mark(10);check(axiR.erase(r->id)==1,"AXI read owner missing");}
            }
            if(memory.bValid&&d.get_io$$ddrAxi$$b$$ready()){
                auto b=PipelineDdr::selected(memory.replies,memory.heldB);check(b!=memory.replies.end(),"observed B missing host owner");
                mark(11);check(axiW.erase(b->id)==1,"AXI write owner missing");
            }
            if(d.get_io$$tlDValid()&&d.get_io$$tlDReady()){
                ++tlD;if(!o.dBeats)mark(12);++o.dBeats;auto id=unsigned(d.get_io$$tlDSource());auto&q=d.get_io$$tlDOpcode()==1?bridgeR:bridgeW;
                check(q.count(id),"TL response owner missing");if(--q.at(id)==0){mark(13);q.erase(id);}
            }
            if(d.get_io$$homeLineResponse()){mark(14);check(homeLive,"home response owner missing");homeLive=false;}
            if(d.get_io$$lineResponseFire()){mark(15);check(lineLive,"DMA response owner missing");lineLive=false;}
            if(oracleResponseValid&&d.get_io$$oracle$$response$$ready())mark(16);
        }
        auto track=[](uint64_t n,uint64_t&area,uint64_t&peak){area+=n;peak=std::max(peak,n);};
        track(lineLive,lineArea,linePeak);track(homeLive,homeArea,homePeak);
        track(bridgeR.size()+bridgeW.size(),bridgeArea,bridgePeak);track(bridgeR.size(),bridgeRArea,bridgeRPeak);track(bridgeW.size(),bridgeWArea,bridgeWPeak);
        track(axiR.size(),axiRArea,axiRPeak);track(axiW.size(),axiWArea,axiWPeak);
        ++bridgeHistogram.at(bridgeR.size()+bridgeW.size());++axiHistogram.at(axiR.size()+axiW.size());
    }
    void print(unsigned caseId){
        const char* names[]={"offer","dma_accept","home_accept","a_first","a_last","ar","aw","w_first","w_last","r_first","r_last","b","d_first","d_last","home_response","dma_response","oracle_response"};
        for(unsigned i=0;i<ops.size();++i){auto&o=ops[i];
            std::cout<<"PIPE_EVENT case="<<caseId<<" index="<<i<<" write="<<o.write<<" address="<<o.address;
            for(unsigned j=0;j<o.event.size();++j)std::cout<<" "<<names[j]<<"="<<o.event[j];
            std::cout<<" a_beats="<<o.aBeats<<" d_beats="<<o.dBeats<<" r_beats="<<o.rBeats<<" w_beats="<<o.wBeats<<"\n";
        }
#define P(x) std::cout<<" "#x"="<<x
        std::cout<<"PIPE_OCCUPANCY case="<<caseId;
        P(lineBlocked);P(homeBlocked);P(tlABlocked);P(tlDBlocked);P(arBlocked);P(awBlocked);P(wBlocked);P(rBlocked);P(bBlocked);
        P(tlA);P(tlD);P(lineArea);P(homeArea);P(bridgeArea);P(bridgeRArea);P(bridgeWArea);P(axiRArea);P(axiWArea);
        P(linePeak);P(homePeak);P(bridgePeak);P(bridgeRPeak);P(bridgeWPeak);P(axiRPeak);P(axiWPeak);
        for(unsigned i=0;i<5;++i)std::cout<<" bridge_hist_"<<i<<"="<<bridgeHistogram[i]<<" axi_hist_"<<i<<"="<<axiHistogram[i];
        std::cout<<"\n";
#undef P
    }
};
