#include "DmaCoherentLineGsim.h"
#include <algorithm>
#include <cstdint>
#include <deque>
#include <functional>
#include <iomanip>
#include <iostream>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>
static void check(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
#define DMA_RAM_BYTES (2ULL*1024*1024*1024)
#include "dma_coherent_ddr.h"
#ifndef DMA_LINE_ENABLED
#define DMA_LINE_ENABLED 0
#endif
static constexpr uint64_t base=0x80200000ULL;
static std::string mutation;
struct Request {uint64_t address;bool write=false;uint64_t data=0;unsigned mask=255;bool atomic=false;unsigned operation=0;bool uncached=false;std::optional<uint64_t> expected;};
struct Reply {uint64_t data,accepted;bool atomic=false;unsigned operation=0;bool write=false;unsigned bytes=0;};
struct Test {
    SDmaCoherentLineGsim d;
    DmaDdr ddr;
    std::vector<uint8_t> oracle,highOracle;
    std::optional<Request> offered;
    std::deque<Reply> replies;
    std::optional<std::tuple<uint64_t,bool,bool>> heldCpu;
    std::vector<uint64_t> cpuLatencies;
    uint64_t cycles=0,cpuAccepted=0,cpuReturned=0,dmaRequests=0,dmaResponses=0,peakDma=0;
    uint64_t probes=0,dirtyBeats=0,homeRequests=0,homeResponses=0,homeOfferCycles=0,homeBusyCycles=0;
    uint64_t lineRequests=0,lineResponses=0,peakLine=0,lineBusyCycles=0,lastCpu=0;
    bool blockCpu=false,measure=false,earlyChecked=false,atomicExclusive=false;
    unsigned concurrent=0,concurrentIndex=0,concurrentLimit=0;
    uint64_t lastCpuRead=0,cpuReadPayload=0,cpuWritePayload=0,offerBlocked=0,worstOfferBlocked=0;
    static uint8_t initial(uint64_t i){return uint8_t(((i*0x9e3779b97f4a7c15ULL)^(i>>7)^0xa5)>>23);}
    uint8_t& oracleByte(uint64_t offset){if(offset<oracle.size())return oracle.at(offset);check(offset>=DMA_RAM_BYTES-highOracle.size()&&offset<DMA_RAM_BYTES,"oracle address outside sparse image");return highOracle.at(offset-(DMA_RAM_BYTES-highOracle.size()));}
    uint8_t oracleByte(uint64_t offset) const {if(offset<oracle.size())return oracle.at(offset);check(offset>=DMA_RAM_BYTES-highOracle.size()&&offset<DMA_RAM_BYTES,"oracle address outside sparse image");return highOracle.at(offset-(DMA_RAM_BYTES-highOracle.size()));}
    uint64_t word(uint64_t address) const {uint64_t v=0;for(unsigned b=0;b<8;++b)v|=uint64_t(oracleByte(address-base+b))<<(8*b);return v;}
    void store(uint64_t address,uint64_t value,unsigned mask){for(unsigned b=0;b<8;++b)if(mask&(1U<<b))oracleByte(address-base+b)=uint8_t(value>>(8*b));}
    Test():oracle(1024*1024),highOracle(4096) {
        for(uint64_t i=0;i<oracle.size();++i)ddr.memory[i]=oracle[i]=initial(i);
        for(uint64_t i=0;i<highOracle.size();++i)ddr.high[i]=highOracle[i]=initial(DMA_RAM_BYTES-4096+i);
        d.set_io$$control$$request$$valid(0);d.set_io$$control$$response$$ready(0);
        d.set_io$$control$$request$$bits$$address(0);d.set_io$$control$$request$$bits$$data(0);d.set_io$$control$$request$$bits$$write(0);
        d.set_io$$control$$request$$bits$$size(3);d.set_io$$control$$request$$bits$$byteEnable(255);
        d.set_io$$cpu$$request$$valid(0);d.set_io$$cpu$$response$$ready(0);d.set_io$$cpu$$request$$bits$$address(base);
        d.set_io$$cpu$$request$$bits$$data(0);d.set_io$$cpu$$request$$bits$$mask(255);d.set_io$$cpu$$request$$bits$$write(0);
        d.set_io$$cpu$$request$$bits$$size(3);d.set_io$$cpu$$request$$bits$$atomic(0);d.set_io$$cpu$$request$$bits$$atomicOp(0);
        d.set_io$$cpu$$request$$bits$$virtualized(0);d.set_io$$cpu$$request$$bits$$uncached(0);d.set_io$$cpu$$request$$bits$$prefetchNextAllowed(0);
        d.set_io$$flushRequest(0);d.set_io$$holdLineHome(0);d.set_reset(1);tick();tick();d.set_reset(0);tick();
    }
    void tick(){
        check(cycles<15000000,"integration cycle budget exceeded");
        bool ready=!blockCpu&&cycles%13!=4;
        if(concurrent&&(!concurrentLimit||concurrentIndex<concurrentLimit)&&!offered&&replies.empty()&&cycles%32==0){
            uint64_t a=base+0x80000+64ULL*((concurrentIndex/2)%1024);
            if(concurrent==1)offered=Request{a};
            else if(concurrent==2)offered=Request{a,true,0x1234567800000000ULL^concurrentIndex,0x55};
            else if(!(concurrentIndex&1)){lastCpuRead=word(a);offered=Request{a};}
            else offered=Request{a+0x20000,true,lastCpuRead};
            ++concurrentIndex;
        }
        d.set_io$$cpu$$request$$valid(bool(offered));d.set_io$$cpu$$response$$ready(ready);
        if(offered){auto&q=*offered;d.set_io$$cpu$$request$$bits$$address(q.address);d.set_io$$cpu$$request$$bits$$write(q.write);
            d.set_io$$cpu$$request$$bits$$data(q.data);d.set_io$$cpu$$request$$bits$$mask(q.mask);d.set_io$$cpu$$request$$bits$$atomic(q.atomic);
            d.set_io$$cpu$$request$$bits$$atomicOp(q.operation);d.set_io$$cpu$$request$$bits$$uncached(q.uncached);}
        ddr.drive(d,cycles);d.step();ddr.sample(d);++cycles;
        auto current=std::make_tuple(uint64_t(d.get_io$$cpu$$response$$bits$$data()),bool(d.get_io$$cpu$$response$$bits$$error()),bool(d.get_io$$cpu$$response$$bits$$pageFault()));
        if(heldCpu)check(d.get_io$$cpu$$response$$valid()&&current==*heldCpu,"held CPU response changed");
        heldCpu=d.get_io$$cpu$$response$$valid()&&!ready?std::optional{current}:std::nullopt;
        if(offered&&d.get_io$$cpu$$request$$ready()){
            auto q=*offered;uint64_t old=word(q.address),expected=q.expected.value_or(q.write&&!q.atomic?0:old);
            if(q.atomic&&q.operation==3)expected=q.expected.value_or(1);
            replies.push_back({expected,cycles,q.atomic,q.operation,q.write,unsigned(q.write?__builtin_popcount(q.mask):8)});
            if(measure)worstOfferBlocked=std::max(worstOfferBlocked,offerBlocked);offerBlocked=0;
            
            if(q.write&&!q.atomic)store(q.address,q.data,q.mask);
            if(q.atomic&&q.operation==0)store(q.address,old+q.data,255);
            if(q.atomic&&q.operation==3&&expected==0)store(q.address,q.data,255);
            offered.reset();++cpuAccepted;
        } else if(offered&&measure)++offerBlocked;
        if(d.get_io$$cpu$$response$$valid()&&ready){check(!replies.empty(),"CPU response without request owner");auto e=replies.front();replies.pop_front();
            check(!std::get<1>(current)&&!std::get<2>(current),"CPU response error");check(std::get<0>(current)==e.data,e.atomic&&e.operation==3?"LR DMA SC reservation oracle mismatch":"CPU independent byte oracle mismatch");
            
            ++cpuReturned;if(measure){cpuLatencies.push_back(cycles-e.accepted);if(e.write)cpuWritePayload+=e.bytes;else cpuReadPayload+=e.bytes;}lastCpu=cycles;
        }
        atomicExclusive=d.get_io$$atomicActive();
        if(atomicExclusive)check(!d.get_io$$dmaRequestFire(),"DMA ordinary request crossed active AMO");
        dmaRequests+=d.get_io$$dmaRequestFire();dmaResponses+=d.get_io$$dmaResponseFire();
#if DMA_LINE_ENABLED
        if(atomicExclusive)check(!d.get_io$$lineRequestFire(),"DMA line request crossed active AMO");
        lineRequests+=d.get_io$$lineRequestFire();lineResponses+=d.get_io$$lineResponseFire();
        check(lineResponses<=lineRequests,"DMA line response without owner");
        peakLine=std::max(peakLine,lineRequests-lineResponses);check(peakLine<=1,"DMA line owner overflow");
        lineBusyCycles+=lineRequests>lineResponses;
#endif
        check(dmaResponses<=dmaRequests,"DMA response without ordinary owner");peakDma=std::max(peakDma,dmaRequests-dmaResponses);check(peakDma<=4,"DMA ordinary credit overflow");
        probes+=d.get_io$$probeFire();dirtyBeats+=d.get_io$$probeReplyFire()&&d.get_io$$probeReplyData();
        homeRequests+=d.get_io$$homeRequestFire();homeResponses+=d.get_io$$homeResponseFire();
        check(homeResponses<=homeRequests,"home response without owner");homeOfferCycles+=d.get_io$$homeRequestOffer();homeBusyCycles+=homeRequests>homeResponses;
        if(mutation=="early-ack"&&!earlyChecked&&ddr.destinationBytes>=ddr.length&&ddr.length&&ddr.destinationPending()){
            earlyChecked=true;completion(false);
        }
    }
    void until(const std::function<bool()>& done,const char* message){uint64_t limit=cycles+5000000;while(!done()){tick();check(cycles<limit,message);}}
    uint64_t control(unsigned offset,bool write=false,uint64_t value=0,bool error=false){
        d.set_io$$control$$request$$bits$$address(0x10001000+offset);d.set_io$$control$$request$$bits$$write(write);d.set_io$$control$$request$$bits$$data(value);d.set_io$$control$$request$$valid(1);
        do{tick();}while(!d.get_io$$control$$request$$ready());d.set_io$$control$$request$$valid(0);
        until([&]{return d.get_io$$control$$response$$valid();},"control response timeout");
        uint64_t result=d.get_io$$control$$response$$bits$$data();check(bool(d.get_io$$control$$response$$bits$$error())==error,"DMA control error mismatch");
        d.set_io$$control$$response$$ready(1);tick();d.set_io$$control$$response$$ready(0);return result;
    }
    void cpu(Request q){check(!offered,"duplicate CPU offer");offered=q;until([&]{return !offered&&replies.empty();},"CPU request deadlock");}
    void flush(){
        check(!offered&&replies.empty(),"flush while CPU queue live");d.set_io$$flushRequest(1);
        until([&]{return d.get_io$$flushDone();},"cache/home drain deadlock");d.set_io$$flushRequest(0);tick();
        check(ddr.memory==oracle&&ddr.high==highOracle,"independent full-memory oracle mismatch after drain");
        check(ddr.reads.empty()&&ddr.writes.empty()&&ddr.replies.empty(),"coherent flush completed before all AXI responses drained");
    }
    void completion(bool error){
        check(!ddr.destinationPending(),"DMA completion before final AXI B");
        check(dmaRequests==dmaResponses,"DMA completion retained ordinary owner");
        check(lineRequests==lineResponses,"DMA completion retained line owner");
        if(!error){check(ddr.destinationBytes>=ddr.length,"DMA completion before all payload writes");
            for(uint64_t i=0;i<ddr.length;++i)check(ddr.byte(ddr.destination+i)==oracleByte(ddr.destination+i),"DMA independent destination byte oracle mismatch");}
    }
    void descriptor(uint64_t source,uint64_t destination,uint64_t bytes){control(0,true,source);control(8,true,destination);control(16,true,bytes);}
    void arm(uint64_t source,uint64_t destination,uint64_t bytes,bool expectSuccess=true){
        descriptor(source,destination,bytes);ddr.destination=destination-base;ddr.length=bytes;ddr.destinationBytes=0;ddr.lastDestinationB=0;
        if(expectSuccess){std::vector<uint8_t> copy(bytes);for(uint64_t i=0;i<bytes;++i)copy[i]=oracleByte(source-base+i);for(uint64_t i=0;i<bytes;++i)oracleByte(destination-base+i)=copy[i];}
    }
    uint64_t start(uint64_t source,uint64_t destination,uint64_t bytes,bool expectSuccess=true){arm(source,destination,bytes,expectSuccess);uint64_t begin=cycles;control(24,true,7);return begin;}
    uint64_t finish(bool error=false){until([&]{return d.get_io$$irq();},"DMA IRQ timeout");uint64_t done=cycles;completion(error);
        check(control(32)==(error?6:2),"DMA completion status mismatch");control(24,true,6);tick();check(!d.get_io$$irq(),"DMA IRQ clear failed");return done;}
};
static uint64_t percentile(std::vector<uint64_t> values,unsigned p){if(values.empty())return 0;std::sort(values.begin(),values.end());return values[(values.size()-1)*p/100];}
static void benchmark(unsigned bytes,unsigned warm,unsigned cpuMode,unsigned offset=0,unsigned delay=40){
    Test t;t.ddr.bDelay=delay;
    uint64_t source=base+offset,destination=base+0x40000+offset;
    if(warm){for(unsigned i=0;i<bytes;i+=64){t.cpu({source+i,warm==2,0x76543210abcdef00ULL^i,0x55});t.cpu({destination+i,warm==2,0xaabbccdd11223344ULL^i,0xaa});}}
    t.arm(source,destination,bytes);
    while(t.cycles%385)t.tick();
    auto ar=t.ddr.arCount,aw=t.ddr.awCount,rb=t.ddr.rBytes,wb=t.ddr.wBytes,bc=t.ddr.bCount,pr=t.probes,dp=t.dirtyBeats;
    auto hr=t.homeRequests,hs=t.homeBusyCycles,ho=t.homeOfferCycles,dr=t.dmaRequests,lr=t.lineRequests,ls=t.lineBusyCycles;
    t.measure=true;t.concurrent=cpuMode;t.ddr.corruptWrite=mutation=="corrupt-write";t.ddr.dropWrite=mutation=="drop-write";
    uint64_t begin=t.cycles;t.control(24,true,7);t.until([&]{return t.d.get_io$$irq();},"DMA IRQ timeout");uint64_t done=t.cycles;t.completion(false);t.concurrent=0;t.measure=false;
    uint64_t elapsed=done-begin,tail=done-t.ddr.lastDestinationB;auto count=t.cpuLatencies.size();
    auto finalAr=t.ddr.arCount,finalAw=t.ddr.awCount,finalRb=t.ddr.rBytes,finalWb=t.ddr.wBytes,finalBc=t.ddr.bCount;
    auto finalPr=t.probes,finalDp=t.dirtyBeats,finalHr=t.homeRequests,finalHs=t.homeBusyCycles,finalHo=t.homeOfferCycles;
    auto finalLr=t.lineRequests,finalLs=t.lineBusyCycles;
    auto finalWorst=std::max(t.worstOfferBlocked,t.offerBlocked),finalB=t.ddr.lastDestinationB;
    auto finalDmaPeak=t.peakDma,finalLinePeak=t.peakLine,finalReadPeak=t.ddr.peakR,finalWritePeak=t.ddr.peakW;
    check(t.control(32)==2,"DMA completion status mismatch");t.control(24,true,6);t.tick();check(!t.d.get_io$$irq(),"DMA IRQ clear failed");
    t.until([&]{return !t.offered&&t.replies.empty();},"concurrent CPU drain timeout");
    for(unsigned i=0;i<std::min(bytes,512U);i+=8)t.cpu({destination+i});
    t.flush();
    if(warm==2&&bytes<=4096&&cpuMode==0)check(t.dirtyBeats-dp>=16,"missing dirty source and destination probes");
    std::cout<<"DMA_BENCH line="<<DMA_LINE_ENABLED<<" bytes="<<bytes<<" warm="<<warm<<" cpu="<<cpuMode<<" offset="<<offset<<" b_delay="<<delay
        <<" cycles="<<elapsed<<" payload_MBps="<<std::fixed<<std::setprecision(6)<<(double(bytes)*100.0/double(elapsed))
        <<" payload_MiBps="<<(double(bytes)*100000000.0/double(elapsed)/1048576.0)
        <<" axi_ar="<<finalAr-ar<<" axi_aw="<<finalAw-aw<<" axi_read_bytes="<<finalRb-rb<<" axi_write_bytes="<<finalWb-wb
        <<" axi_b="<<finalBc-bc<<" probes="<<finalPr-pr<<" dirty_probe_beats="<<finalDp-dp
        <<" dma_requests="<<t.dmaRequests-dr<<" dma_peak="<<finalDmaPeak<<" axi_read_peak="<<finalReadPeak<<" axi_write_peak="<<finalWritePeak
        <<" line_requests="<<finalLr-lr<<" line_service_cycles="<<finalLs-ls<<" line_peak="<<finalLinePeak
        <<" scalar_home_requests="<<finalHr-hr<<" scalar_home_service_cycles="<<finalHs-hs<<" scalar_home_offer_cycles="<<finalHo-ho
        <<" final_b_cycle="<<finalB<<" completion_cycle="<<done<<" completion_tail="<<tail
        <<" cpu_completed="<<count<<" cpu_p50="<<percentile(t.cpuLatencies,50)<<" cpu_p95="<<percentile(t.cpuLatencies,95)<<" cpu_p99="<<percentile(t.cpuLatencies,99)<<" cpu_max="<<percentile(t.cpuLatencies,100)
        <<" cpu_worst_offer_blocked="<<finalWorst
        <<" cpu_read_payload_bytes="<<t.cpuReadPayload<<" cpu_write_payload_bytes="<<t.cpuWritePayload
        <<" cpu_useful_MiBps="<<(double(cpuMode==1?t.cpuReadPayload:t.cpuWritePayload)*100000000.0/double(elapsed)/1048576.0)<<"\n";
}
static void cpuOnly(unsigned mode){
    Test t;while(t.cycles%385)t.tick();const uint64_t begin=t.cycles,returned=t.cpuReturned;
    const auto rb=t.ddr.rBytes,wb=t.ddr.wBytes;t.measure=true;t.concurrent=mode;
    t.until([&]{return t.cpuReturned-returned==256;},"CPU-only fixed-work timeout");
    t.measure=false;t.concurrent=0;const auto elapsed=t.cycles-begin;
    check(!t.offered&&t.replies.empty(),"CPU-only fixed work retained request");
    const uint64_t payload=mode==1?t.cpuReadPayload:t.cpuWritePayload;
    std::cout<<"CPU_PORT_ONLY line="<<DMA_LINE_ENABLED<<" cpu="<<mode<<" operations=256 cycles="<<elapsed
        <<" useful_payload_bytes="<<payload<<" useful_MiBps="<<std::fixed<<std::setprecision(6)<<(double(payload)*100000000.0/double(elapsed)/1048576.0)
        <<" axi_read_bytes="<<t.ddr.rBytes-rb<<" axi_write_bytes="<<t.ddr.wBytes-wb
        <<" cpu_p50="<<percentile(t.cpuLatencies,50)<<" cpu_p95="<<percentile(t.cpuLatencies,95)
        <<" cpu_p99="<<percentile(t.cpuLatencies,99)<<" cpu_max="<<percentile(t.cpuLatencies,100)
        <<" cpu_worst_offer_blocked="<<std::max(t.worstOfferBlocked,t.offerBlocked)<<"\n";
    t.flush();
}
static void combined(unsigned bytes,unsigned warm,unsigned mode,unsigned operations=256){
    Test t;const uint64_t source=base,destination=base+0x40000;
    if(warm)for(unsigned i=0;i<bytes;i+=64){t.cpu({source+i,true,0x76543210abcdef00ULL^i,0x55});t.cpu({destination+i,true,0xaabbccdd11223344ULL^i,0xaa});}
    t.arm(source,destination,bytes);while(t.cycles%385)t.tick();
    const auto beforeCpu=t.cpuReturned,rb=t.ddr.rBytes,wb=t.ddr.wBytes;uint64_t dmaDone=0,cpuDone=0;
    t.concurrent=mode;t.concurrentLimit=operations;t.measure=true;const auto begin=t.cycles;t.control(24,true,7);
    t.until([&]{
        if(!dmaDone&&t.d.get_io$$irq()){dmaDone=t.cycles;t.completion(false);}
        if(!cpuDone&&t.cpuReturned-beforeCpu==operations)cpuDone=t.cycles;
        return dmaDone&&cpuDone;
    },"fixed-work CPU+DMA makespan timeout");
    t.concurrent=0;t.measure=false;const auto elapsed=t.cycles-begin;
    check(!t.offered&&t.replies.empty(),"fixed-work CPU target retained owner");
    const uint64_t payload=mode==1?t.cpuReadPayload:t.cpuWritePayload;
    std::ostringstream row;row<<"DMA_CPU_COMBINED line="<<DMA_LINE_ENABLED<<" bytes="<<bytes<<" warm="<<warm<<" cpu="<<mode<<" operations="<<operations<<" cycles="<<elapsed
        <<" dma_cycles="<<dmaDone-begin<<" cpu_cycles="<<cpuDone-begin
        <<" dma_MiBps="<<std::fixed<<std::setprecision(6)<<(double(bytes)*100000000.0/double(dmaDone-begin)/1048576.0)
        <<" cpu_payload_bytes="<<payload<<" cpu_useful_MiBps="<<(double(payload)*100000000.0/double(cpuDone-begin)/1048576.0)
        <<" aggregate_useful_MiBps="<<(double(bytes+payload)*100000000.0/double(elapsed)/1048576.0)
        <<" axi_read_bytes="<<t.ddr.rBytes-rb<<" axi_write_bytes="<<t.ddr.wBytes-wb
        <<" cpu_p50="<<percentile(t.cpuLatencies,50)<<" cpu_p95="<<percentile(t.cpuLatencies,95)<<" cpu_p99="<<percentile(t.cpuLatencies,99)
        <<" cpu_max="<<percentile(t.cpuLatencies,100)<<" cpu_worst_offer_blocked="<<std::max(t.worstOfferBlocked,t.offerBlocked);
    const auto kernelRead=t.ddr.rBytes,kernelWrite=t.ddr.wBytes;
    check(t.control(32)==2,"fixed-work DMA status mismatch");t.control(24,true,6);t.tick();const auto flushBegin=t.cycles;t.flush();
    row<<" completion_control_cycles="<<flushBegin-begin-elapsed<<" flush_tail_cycles="<<t.cycles-flushBegin
        <<" full_makespan_cycles="<<t.cycles-begin<<" full_aggregate_useful_MiBps="<<(double(bytes+payload)*100000000.0/double(t.cycles-begin)/1048576.0)
        <<" drain_axi_read_bytes="<<t.ddr.rBytes-kernelRead<<" drain_axi_write_bytes="<<t.ddr.wBytes-kernelWrite
        <<" full_axi_read_bytes="<<t.ddr.rBytes-rb<<" full_axi_write_bytes="<<t.ddr.wBytes-wb;
    std::cout<<row.str()<<"\n";
}
static void protocols(){
    // Whole descriptors spanning a 4 KiB boundary still use legal individual AXI bursts.
    benchmark(128,0,0,0xfc0);benchmark(512,0,0,8);benchmark(72,0,0,56);benchmark(64,0,0,0,240);
    for(auto desc:{std::vector<uint64_t>{base+8,base+0x40010,512},{base,base+DMA_RAM_BYTES-64,64},{base,base+DMA_RAM_BYTES-72,72},{base,base+0x40000,72}}){
        Test t;t.start(desc[0],desc[1],desc[2]);t.finish();t.flush();
    }
    Test high;const uint64_t highAddress=base+DMA_RAM_BYTES-64;
    high.cpu({highAddress,true,0x0123456789abcdefULL,0x55});high.start(highAddress,base+0x40000,64);high.finish();high.flush();
    high.cpu({highAddress,true,0xfedcba9876543210ULL,0xaa});high.start(base,highAddress,64);high.finish();high.cpu({highAddress});high.flush();
    Test held;held.d.set_io$$holdLineHome(1);held.start(base,base+0x40000,512);
#if DMA_LINE_ENABLED
    held.until([&]{return held.d.get_io$$lineRequestOffer();},"held line offer timeout");
    auto heldLines=held.lineRequests;for(unsigned i=0;i<20;++i){held.tick();check(held.lineRequests==heldLines,"line crossed forced home stall");}
#endif
    held.d.set_io$$flushRequest(1);held.until([&]{return held.d.get_io$$flushDone();},"fence blocked on unaccepted line offer");
    check(held.d.get_io$$active(),"held line unexpectedly completed before fence");held.d.set_io$$flushRequest(0);held.tick();held.d.set_io$$holdLineHome(0);held.finish();held.flush();
    Test busy;busy.ddr.bDelay=240;busy.start(base,base+0x40000,512);
    busy.until([&]{return busy.d.get_io$$active()&&(busy.dmaRequests||busy.lineRequests);},"busy descriptor setup timeout");
    busy.control(0,true,0,true);busy.control(24,true,0,true);busy.finish();busy.flush();
    Test two;two.offered=Request{base+0x90000};two.until([&]{return !two.offered;},"first concurrent miss not accepted");
    two.offered=Request{base+0x90040};two.until([&]{return !two.offered;},"second concurrent miss not accepted");
    check(two.replies.size()==2,"two independent CPU miss owners not resident");
    two.until([&]{return two.ddr.reads.size()==2;},"two independent home refills never coexisted");
    two.start(base,base+0x40000,512);two.finish();two.until([&]{return two.replies.empty();},"concurrent miss replies did not drain");two.flush();
    for(bool writeError:{false,true}){
        Test t;if(writeError)t.ddr.denyWrite=0x40000;else t.ddr.denyRead=0;
        t.start(base,base+0x40000,512,false);t.finish(true);t.ddr.denyRead.reset();t.ddr.denyWrite.reset();
        t.start(base,base+0x40000,512);t.finish();t.flush();
    }
    Test lr;lr.cpu({base+0x40000,false,0,255,true,2,true});lr.start(base,base+0x40000,64);lr.finish();
    lr.cpu({base+0x40000,true,0xfedcba9876543210ULL,255,true,3,true,uint64_t(1)});lr.flush();
    Test amo;amo.offered=Request{base+0x90000,true,17,255,true,0,true};
    amo.until([&]{return amo.atomicExclusive&&!amo.ddr.reads.empty();},"AMO read gap setup timeout");
    amo.start(base,base+0x40000,512);amo.finish();amo.until([&]{return !amo.atomicExclusive&&amo.replies.empty();},"AMO concurrent completion timeout");amo.flush();
    for(auto desc:{std::vector<uint64_t>{base,base+0x40000,0},{base+1,base+0x40000,64},{base,base+8,64},
        {base,base+DMA_RAM_BYTES-8,16},{0xfffffffffffffff8ULL,base,16},{0x10000000,base+0x40000,64}}){
        Test t;auto before=t.dmaRequests,lineBefore=t.lineRequests,ar=t.ddr.arCount,aw=t.ddr.awCount;t.descriptor(desc[0],desc[1],desc[2]);t.control(24,true,7);
        t.until([&]{return t.d.get_io$$irq();},"invalid descriptor failed to retire");check(t.control(32)==6&&t.dmaRequests==before&&t.lineRequests==lineBefore&&t.ddr.arCount==ar&&t.ddr.awCount==aw,"invalid descriptor produced memory traffic");
    }
    std::cout<<"DMA_PROTOCOL_PASS errors=2 restart=2 lr_sc=1 amo_gap=1 descriptor_rejects=6 boundary=1 fallback=5 aperture_high=4 above4GiB=1 delayed_b=1 held_line_fence=1 busy_write_reject=2 two_mshr=1\n";
}
int main(int argc,char** argv){try{
    bool smoke=false,oneLine=false,protocolOnly=false;for(int i=1;i<argc;++i){std::string a=argv[i];if(a=="--smoke")smoke=true;else if(a=="--one-line")oneLine=true;else if(a=="--protocol-only")protocolOnly=true;else if(a.rfind("--mutate=",0)==0)mutation=a.substr(9);else throw std::runtime_error("unknown argument");}
    if(protocolOnly){protocols();std::cout<<"DMA_COHERENT_LINE_PASS protocol_only=1 line="<<DMA_LINE_ENABLED<<"\n";return 0;}
    benchmark(oneLine?64:512,0,0);if(!mutation.empty())throw std::runtime_error("requested negative control did not reject");
    if(!smoke&&!oneLine){for(unsigned cpu:{1U,2U,3U})cpuOnly(cpu);benchmark(4096,0,0);benchmark(131072,0,0);for(unsigned warm:{1U,2U})for(unsigned n:{512U,4096U})benchmark(n,warm,0);
        for(unsigned cpu:{1U,2U,3U})benchmark(4096,2,cpu);for(unsigned cpu:{1U,2U,3U})benchmark(131072,0,cpu);
        for(unsigned cpu:{1U,2U,3U}){combined(4096,2,cpu);combined(131072,0,cpu);
            combined(4096,2,cpu,4096/(cpu==1?8:4));combined(131072,0,cpu,131072/(cpu==1?8:4));}protocols();}
    std::cout<<"DMA_COHERENT_LINE_PASS line="<<DMA_LINE_ENABLED<<" clock_MHz=100 scope=DMA+cache+home+AXI_host_model\n";
}catch(const std::exception&e){std::cerr<<"DMA_COHERENT_LINE_FAIL "<<e.what()<<"\n";return 1;}}
