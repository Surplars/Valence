// Reuse the production-independent byte, MMIO, credit and stalled-offer oracle.
#define main retained_packet_dma_oracle_main
#include "ethernet_packet_dma.cpp"
#undef main
#ifndef DMA_MAX_FRAME
#define DMA_MAX_FRAME 2048
#endif
#include <string>

static unsigned cases=0;
static bool corrupt=false;
static std::string mutation;
static void report(const std::string&name,const Test&t) {
    check(t.requests==t.responses,"focused accepted request/response leak");
    std::cout<<"TX_WORD_COUNT_METRICS case="<<name<<" cycles="<<t.cycle
        <<" requests="<<t.requests<<" responses="<<t.responses<<" reads="<<t.reads
        <<" writes="<<t.writes<<" peak="<<t.peak<<" stalls="<<t.txStalls+t.memoryStalls<<'\n';
    ++cases;
}
static void bytes(const Test&t,uint64_t address,unsigned n) {
    std::vector<uint8_t> expected(t.memory.begin()+(address-ram),t.memory.begin()+(address-ram)+n);
    if(corrupt)expected.at(0)^=1;
    check(t.dataOut==expected,"TX word count independent byte oracle mismatch");
}
static void legacy(unsigned n,bool upper) {
    Test t(109+n);const uint64_t a=upper?ram+DMA_RAM_BYTES-((uint64_t(n)+7)&~7ULL):ram+128;
    auto before=t.memory;t.startTx(a,n);t.finish(false,false,true,false);
    bytes(t,a,n);check(t.reads==(n+7)/8&&t.writes==0&&t.memory==before,"legacy count or memory side effect");
    report(std::string(upper?"upper-":"legacy-")+std::to_string(n),t);
}
static void invalid(uint64_t address,uint64_t length,unsigned id) {
    Test t(880+id);auto before=t.memory;
    t.access(16,true,address);t.access(24,true,length);
    check(t.access(16)==address&&t.access(24)==length,"full64 MMIO descriptor truncated");
    t.access(32,true,3);t.finish(true,false,true,false);
    for(unsigned i=0;i<24;++i)t.tick();
    check(!t.requests&&!t.responses&&t.dataOut.empty()&&t.controls.empty()&&t.memory==before,
        "illegal legacy descriptor had memory or stream side effects");
    report("invalid-"+std::to_string(id),t);
}
#if TX_POSTED_SLOTS > 0
static void post(Test&t,uint64_t address,uint64_t length,bool error=false) {
    t.access(224,true,address);t.access(232,true,length);t.access(240,true,4,error);
}
static void posted() {
    Test t(778);t.multiTx=true;t.access(240,true,1);
    const std::vector<unsigned> lengths={1,2,3,4,5,6,7,8,9,DMA_MAX_FRAME-1,DMA_MAX_FRAME};
    std::vector<uint8_t> expected;unsigned words=0,frames=0,frameBytes=0;
    for(unsigned batch=0;batch<lengths.size();batch+=TX_POSTED_SLOTS) {
        unsigned count=std::min<unsigned>(TX_POSTED_SLOTS,lengths.size()-batch);
        for(unsigned i=0;i<count;++i) {
            unsigned n=lengths[batch+i],offset=DMA_MAX_FRAME*i;
            expected.insert(expected.end(),t.memory.begin()+offset,t.memory.begin()+offset+n);
            words+=(n+7)/8;post(t,ram+offset,n);
        }
        unsigned limit=t.cycle+100000;
        while(((t.access(248)>>8)&255)!=count)check(t.cycle<limit,"posted focused completion timeout");
        check(t.dataOut==expected&&t.reads==words,"posted varied-length byte/count mismatch");
        for(unsigned i=0;i<count;++i) {
            unsigned n=lengths[batch+i],offset=DMA_MAX_FRAME*i;
            check(t.access(224)==ram+offset&&t.access(232)==n,"posted exact owner/length mismatch");
            ++frames;frameBytes+=n;
            check(t.txFrameEnds.size()>=frames,"posted frame boundary missing");
            unsigned observed=t.txFrameEnds.at(frames-1);
            if(mutation=="boundary"&&frames==1)++observed;
            check(observed==frameBytes,"posted exact TLAST byte offset mismatch");
            t.access(240,true,8);
        }
    }
    check(t.txFrameEnds.size()==lengths.size(),"posted extra/missing frames");
    t.access(240,true,2);t.multiTx=false;t.controls.clear();t.dataOut.clear();
    unsigned before=t.reads;t.startTx(ram+64,9);t.finish(false,false,true,false);bytes(t,ram+64,9);
    check(t.reads-before==2,"posted to legacy restart count");report("posted-varied-legacy-restart",t);
    Test e(901);e.multiTx=true;e.failRead=0;e.access(240,true,1);
    post(e,ram+128,std::min<unsigned>(DMA_MAX_FRAME,129));unsigned limit=e.cycle+50000;
    while(!((e.access(248)>>8)&255))check(e.cycle<limit,"posted fault timeout");
    check(e.dataOut.empty()&&e.controls.empty()&&e.access(232)==65536,"posted fault emitted partial stream");
    e.access(240,true,8);e.failRead=-1;unsigned prior=e.reads;
    post(e,ram+64,9);limit=e.cycle+50000;
    while(!((e.access(248)>>8)&255))check(e.cycle<limit,"posted error restart timeout");
    check(e.access(232)==9&&e.reads-prior==2,"posted error restart length/count");bytes(e,ram+64,9);
    e.access(240,true,8);e.access(240,true,2);report("posted-error-restart",e);
    Test bad(991);auto initial=bad.memory;bad.access(240,true,1);
    unsigned id=0;
    for(auto [a,n]:std::vector<std::pair<uint64_t,uint64_t>>{{ram,0},{ram,DMA_MAX_FRAME+1ULL},
        {ram,1ULL<<63},{ram,~0ULL},{ram+1,8},{ram+DMA_RAM_BYTES-8,9},
        {0xfffffffffffffff8ULL,16},{ram-8,8},{ram+DMA_RAM_BYTES,1}}) {
        post(bad,a,n,true);for(unsigned i=0;i<9;++i)bad.tick();++id;
    }
    if(mutation=="controls")bad.controls.push_back({0xa0000000U,15,false});
    check(id==9&&bad.requests==0&&bad.memory==initial&&bad.dataOut.empty()&&bad.controls.empty(),"illegal posted descriptor side effects");
    bad.access(240,true,2);report("posted-invalid-nine",bad);
}
#endif
static void busyWrites() {
    for(bool stream:{false,true})for(unsigned offset:{16U,24U,32U}) {
        Test t(501+offset+stream);const uint64_t a=ram+128;const unsigned n=17;
        auto initial=t.memory;t.holdMemoryRequest=!stream;t.holdTxData=stream;
        t.startTx(a,n);
        if(stream) {
            unsigned limit=t.cycle+50000;
            while(!t.G(txData$$valid)){t.tick();check(t.cycle<limit,"active stream witness timeout");}
        }
        check(t.access(40)&1,"legacy active-write witness not busy");
        t.access(offset,true,offset==16?ram+512:offset==24?9:3,true);
        auto address=t.access(16),length=t.access(24),status=t.access(40);
        if(mutation=="busy-address"&&offset==16)address^=8;
        if(mutation=="busy-length"&&offset==24)length^=1;
        if(mutation=="busy-start"&&offset==32)status=2;
        check(address==a&&length==n&&(status&1),"busy legacy descriptor/status changed");
        check(t.dataOut.empty()&&t.reads==(stream?3:0),"busy legacy read/stream count changed");
        t.holdMemoryRequest=false;t.holdTxData=false;t.finish(false,false,true,false);bytes(t,a,n);
        check(t.reads==3&&t.requests==3&&t.responses==3&&t.memory==initial,"busy legacy descriptor transfer changed");
        t.controls.clear();t.dataOut.clear();
        t.startTx(ram+512,9);t.finish(false,false,true,false);bytes(t,ram+512,9);
        check(t.reads==5&&t.responses==5&&t.memory==initial,"busy legacy changed-length restart mismatch");
        report(std::string("busy-")+(stream?"stream-":"fill-")+std::to_string(offset),t);
    }
}
int main(int argc,char**argv)try {
    bool review=false;
    for(int i=1;i<argc;++i) {
        std::string arg=argv[i];
        if(arg=="--review-gaps")review=true;
        else if(arg=="--corrupt-expected")corrupt=true;
        else if(arg.rfind("--mutate=",0)==0)mutation=arg.substr(9);
        else throw std::runtime_error("unknown focused argument");
    }
    if(review) {
        busyWrites();
#if TX_POSTED_SLOTS > 0
        posted();
#endif
        std::cout<<"TX_WORD_COUNT_REVIEW_GAPS_PASS cases="<<cases<<'\n';return 0;
    }
    for(unsigned n:{1U,2U,3U,4U,5U,6U,7U,8U,9U,unsigned(DMA_MAX_FRAME-1),unsigned(DMA_MAX_FRAME)})legacy(n,false);
    legacy(DMA_MAX_FRAME,true);legacy(9,true);
    unsigned id=0;
    for(auto [a,n]:std::vector<std::pair<uint64_t,uint64_t>>{{ram,0},{ram,DMA_MAX_FRAME+1ULL},
        {ram,1ULL<<63},{ram,~0ULL},{ram+1,8},{ram+DMA_RAM_BYTES-8,9},
        {0xfffffffffffffff8ULL,16},{ram-8,8},{ram+DMA_RAM_BYTES,1}})invalid(a,n,id++);
    Test seq(171);unsigned total=0;
    for(unsigned n:{unsigned(DMA_MAX_FRAME),1U,9U,unsigned(DMA_MAX_FRAME-1),8U}) {
        seq.controls.clear();seq.dataOut.clear();seq.startTx(ram+128,n);seq.finish(false,false,true,false);
        bytes(seq,ram+128,n);total+=(n+7)/8;check(seq.reads==total,"consecutive legacy stale count");
    }
    report("legacy-consecutive",seq);
    Test tail(202);tail.holdTxData=true;tail.startTx(ram+64,1);unsigned limit=tail.cycle+50000;
    while(!tail.G(txData$$valid)){tail.tick();check(tail.cycle<limit,"final beat absent");}
    check(tail.G(txData$$bits$$last),"single-byte final beat witness");
    for(unsigned i=0;i<17;++i)tail.tick();
    check(tail.dataOut.empty()&&(tail.access(40)&1),"final stalled beat completed early");
    tail.holdTxData=false;tail.finish(false,false,true,false);bytes(tail,ram+64,1);report("final-backpressure",tail);
    Test fault(333);fault.failRead=0;fault.startTx(ram+128,std::min<unsigned>(DMA_MAX_FRAME,129));
    fault.finish(true,false,true,false);check(fault.dataOut.empty()&&fault.controls.empty(),"legacy fault partial stream");
    fault.failRead=-1;unsigned prior=fault.reads;fault.startTx(ram+64,9);fault.finish(false,false,true,false);
    check(fault.reads-prior==2,"legacy fault restart count");bytes(fault,ram+64,9);report("legacy-error-restart",fault);
#if TX_POSTED_SLOTS > 0
    posted();
#endif
    std::cout<<"TX_WORD_COUNT_FOCUSED_PASS cases="<<cases<<" M="<<DMA_MAX_FRAME
        <<" posted="<<TX_POSTED_SLOTS<<" base="<<ram<<" final_backpressure=1 invalid_side_effects=0\n";
    return 0;
}catch(const std::exception&e){std::cerr<<"TX_WORD_COUNT_FOCUSED_FAIL "<<e.what()<<'\n';return 1;}
