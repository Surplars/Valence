#pragma once
#include <array>
#include <map>
// Independent tagged-owner observers. Expected memory bytes remain host-owned.
struct PipelineMetrics {
    struct Op {
        bool write; uint64_t address; unsigned tag;
        std::array<int64_t,17> event;
        unsigned aBeats=0,dBeats=0,rBeats=0,wBeats=0,source=0;
        Op(bool w,uint64_t a,unsigned t):write(w),address(a),tag(t){event.fill(-1);}
    };
    std::vector<Op> ops;
    bool measure=false;
    uint64_t lineBlocked=0,homeBlocked=0,tlABlocked=0,tlDBlocked=0,arBlocked=0,awBlocked=0,wBlocked=0,rBlocked=0,bBlocked=0;
    uint64_t tlA=0,tlD=0,lineArea=0,homeArea=0,bridgeArea=0,bridgeRArea=0,bridgeWArea=0,axiRArea=0,axiWArea=0;
    uint64_t linePeak=0,homePeak=0,bridgePeak=0,bridgeRPeak=0,bridgeWPeak=0,axiRPeak=0,axiWPeak=0;
    std::map<unsigned,unsigned> lineOwners,homeOwners,bridgeR,bridgeW,axiR,axiW;
    std::optional<unsigned> offered;
    unsigned _BitInt(512) offeredData=0;
    std::array<uint64_t,5> bridgeHistogram{},axiHistogram{};
    void mark(unsigned index,unsigned event,uint64_t cycle){check(ops.at(index).event[event]<0,"duplicate tagged event");ops.at(index).event[event]=cycle;}
    unsigned byAddress(uint64_t address,bool write,unsigned notYetEvent){
        std::optional<unsigned> found;
        for(auto[tag,index]:homeOwners){auto&o=ops.at(index);if(o.address==address&&o.write==write&&o.event[notYetEvent]<0){check(!found,"ambiguous address event owner");found=index;}}
        check(bool(found),"address event lost independent owner");return *found;
    }
    template<class Dut> void sample(Dut& d,uint64_t c,PipelineDdr& memory,bool oracleResponseValid,unsigned oracleTag){
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
        if(d.get_io$$lineRequestOffer()){
            if(!offered){offered=ops.size();ops.emplace_back(bool(d.get_io$$lineRequestWrite()),d.get_io$$lineRequestAddress(),d.get_io$$lineRequestTag());mark(*offered,0,c);offeredData=d.get_io$$lineRequestData();}
            auto&o=ops.at(*offered);check(o.write==bool(d.get_io$$lineRequestWrite())&&o.address==d.get_io$$lineRequestAddress()&&o.tag==d.get_io$$lineRequestTag()&&offeredData==d.get_io$$lineRequestData(),"held tagged line request changed");
        }else check(!offered,"held tagged line request withdrawn");
        if(d.get_io$$lineRequestFire()){
            check(bool(offered),"line acceptance without offer");auto i=*offered;auto tag=ops.at(i).tag;
            check(!lineOwners.count(tag),"line tag reused before reply");lineOwners[tag]=i;mark(i,1,c);offered.reset();
        }
        if(d.get_io$$homeLineFire()){
            auto tag=unsigned(d.get_io$$homeLineRequestTag());check(lineOwners.count(tag)&&!homeOwners.count(tag),"home admission tag lost/reused");
            auto i=lineOwners.at(tag);homeOwners[tag]=i;mark(i,2,c);
        }
        if(d.get_io$$tlAValid()&&d.get_io$$tlAReady()){
            ++tlA;auto id=unsigned(d.get_io$$tlASource());bool write=d.get_io$$tlAOpcode()!=4;auto&q=write?bridgeW:bridgeR;
            unsigned i;
            if(q.count(id)){i=q.at(id);check(write&&ops.at(i).aBeats<8,"TL source reused before reply");}
            else{check(!bridgeR.count(id)&&!bridgeW.count(id),"TL source aliases another owner");i=byAddress(d.get_io$$tlAAddress(),write,3);q[id]=i;mark(i,3,c);ops.at(i).source=id;}
            auto&o=ops.at(i);check(o.address==d.get_io$$tlAAddress(),"TL burst address changed");
            ++o.aBeats;if(o.aBeats==(write?8U:1U))mark(i,4,c);
        }
        if(d.get_io$$ddrAxi$$ar$$valid()&&memory.arReady){auto id=unsigned(d.get_io$$ddrAxi$$ar$$bits$$id());check(!axiR.count(id)&&!axiW.count(id),"AXI ID reused");auto i=byAddress(base+d.get_io$$ddrAxi$$ar$$bits$$addr(),false,5);axiR[id]=i;mark(i,5,c);}
        if(d.get_io$$ddrAxi$$aw$$valid()&&memory.awReady){auto id=unsigned(d.get_io$$ddrAxi$$aw$$bits$$id());check(!axiR.count(id)&&!axiW.count(id),"AXI ID reused");auto i=byAddress(base+d.get_io$$ddrAxi$$aw$$bits$$addr(),true,6);axiW[id]=i;mark(i,6,c);}
        if(d.get_io$$ddrAxi$$w$$valid()&&memory.wReady){
            check(!memory.writes.empty(),"W lacks host address owner");auto id=memory.writes.front().id;check(axiW.count(id),"W lacks observed owner");auto i=axiW.at(id);auto&o=ops.at(i);
            if(!o.wBeats)mark(i,7,c);++o.wBeats;if(d.get_io$$ddrAxi$$w$$bits$$last())mark(i,8,c);
        }
        if(memory.rValid&&d.get_io$$ddrAxi$$r$$ready()){
            auto r=PipelineDdr::selected(memory.reads,memory.heldR);check(r!=memory.reads.end()&&axiR.count(r->id),"R lacks observed owner");auto i=axiR.at(r->id);auto&o=ops.at(i);
            if(!o.rBeats)mark(i,9,c);++o.rBeats;if(r->beat+1==r->count){mark(i,10,c);axiR.erase(r->id);}
        }
        if(memory.bValid&&d.get_io$$ddrAxi$$b$$ready()){
            auto b=PipelineDdr::selected(memory.replies,memory.heldB);check(b!=memory.replies.end()&&axiW.count(b->id),"B lacks observed owner");auto i=axiW.at(b->id);mark(i,11,c);axiW.erase(b->id);
        }
        if(d.get_io$$tlDValid()&&d.get_io$$tlDReady()){
            ++tlD;auto id=unsigned(d.get_io$$tlDSource());bool write=d.get_io$$tlDOpcode()==0;auto&q=write?bridgeW:bridgeR;check(q.count(id),"TL response owner missing");auto i=q.at(id);auto&o=ops.at(i);
            if(!o.dBeats)mark(i,12,c);++o.dBeats;if(o.dBeats==(write?1U:8U)){mark(i,13,c);q.erase(id);}
        }
        if(oracleResponseValid&&d.get_io$$oracle$$response$$ready()){check(lineOwners.count(oracleTag),"oracle response owner missing");mark(lineOwners.at(oracleTag),16,c);}
        if(d.get_io$$homeLineResponse()){auto tag=unsigned(d.get_io$$homeLineResponseTag());check(homeOwners.count(tag),"home response tag lost");mark(homeOwners.at(tag),14,c);homeOwners.erase(tag);}
        if(d.get_io$$lineResponseFire()){auto tag=unsigned(d.get_io$$lineResponseTag());check(lineOwners.count(tag),"DMA response tag lost");mark(lineOwners.at(tag),15,c);lineOwners.erase(tag);}
        auto track=[](uint64_t n,uint64_t&area,uint64_t&peak){area+=n;peak=std::max(peak,n);};
        track(lineOwners.size(),lineArea,linePeak);track(homeOwners.size(),homeArea,homePeak);
        track(bridgeR.size()+bridgeW.size(),bridgeArea,bridgePeak);track(bridgeR.size(),bridgeRArea,bridgeRPeak);track(bridgeW.size(),bridgeWArea,bridgeWPeak);
        track(axiR.size(),axiRArea,axiRPeak);track(axiW.size(),axiWArea,axiWPeak);
        ++bridgeHistogram.at(bridgeR.size()+bridgeW.size());++axiHistogram.at(axiR.size()+axiW.size());
    }
    void print(unsigned caseId){
        const char* names[]={"offer","dma_accept","home_accept","a_first","a_last","ar","aw","w_first","w_last","r_first","r_last","b","d_first","d_last","home_response","dma_response","oracle_response"};
        for(unsigned i=0;i<ops.size();++i){auto&o=ops[i];std::cout<<"PIPE_EVENT case="<<caseId<<" index="<<i<<" write="<<o.write<<" address="<<o.address<<" tag="<<o.tag;
            for(unsigned j=0;j<o.event.size();++j)std::cout<<" "<<names[j]<<"="<<o.event[j];
            std::cout<<" a_beats="<<o.aBeats<<" d_beats="<<o.dBeats<<" r_beats="<<o.rBeats<<" w_beats="<<o.wBeats<<"\n";}
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
