#include "GmacShutdownGsim.h"
#include "gmii_reference.h"
#include <array>
#include <deque>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>
#include <string>
#include <string_view>
#include <tuple>
#define S(n,v) d.set_io$$##n(v)
#define G(n) d.get_io$$##n()
static void check(bool ok,const char*why){if(!ok)throw std::runtime_error(why);}
static constexpr uint64_t ram=0x80200000ULL,macRegs=0x10040000ULL,dmaRegs=0x10002000ULL;
struct Reply{unsigned due;uint64_t address,data;unsigned mask;};
struct MmioReply{uint64_t data;bool error;bool operator==(const MmioReply&)const=default;};
using Beat=std::tuple<uint32_t,unsigned,bool>;
using Request=std::tuple<uint64_t,uint64_t,unsigned,unsigned,bool>;
struct Test{
    SGmacShutdownGsim d;
    std::mt19937 random;
    std::array<uint8_t,8192> memory{},expectedMemory{};
    std::deque<Reply> replies;
    std::deque<int> incoming;
    std::deque<std::vector<uint8_t>> expectedFrames;
    std::deque<unsigned> expectedStatus;
    std::vector<uint8_t> received,storeBody;
    std::optional<Beat> heldData,heldStatus;
    std::optional<Request> heldRequest;
    unsigned cycles=0,dataFrames=0,statusFrames=0,statusIndex=0,dataStalls=0,statusStalls=0;
    unsigned writes=0,completed=0,peak=0,mmio=0,requestStalls=0,storeOffset=0,storeNext=0;
    bool holdData=false,holdLastData=false,holdStatus=false,holdLastStatus=false,holdReplies=false,holdRequests=false;
    bool clockSleep=false;unsigned wakeCycles=0;
    std::string inject;
    explicit Test(unsigned seed,std::string injection={}):random(seed),inject(std::move(injection)){
        for(auto&byte:memory)byte=random();expectedMemory=memory;
        bus(0,0,false,0,false);bus(1,0,false,0,false);
        ready(0,false);ready(1,false);
        S(rxClockEnable,1);S(rxQuiesce,0);S(rxIsolate,0);
        S(gmiiRxValid,0);S(gmiiRxData,0);S(gmiiRxError,0);S(holdData,0);S(holdStatus,0);
        S(memory$$request$$ready,0);S(memory$$response$$valid,0);
        S(memory$$response$$bits$$data,0);S(memory$$response$$bits$$error,0);
        d.set_reset(1);d.step();d.step();d.set_reset(0);idle(100);
        check((access(0,8)&256)!=0,"managed GMAC does not advertise RX_STOP capability");
        check(access(0,0x90)==0,"RX_STOP reset state is not released");
        check((access(1,0x98)&1)==1,"DMA does not advertise safe RX_STOP");
        access(0,0x18,true,0x021122334455ULL);idle(100);
        access(0,0x10,true,11);idle(100);
    }
    void bus(unsigned p,unsigned off,bool write,uint64_t value,bool valid,unsigned size=3,unsigned mask=255){
#define BUS(ID,NAME,BASE) case ID: \
        S(NAME##$$request$$valid,valid);S(NAME##$$request$$bits$$address,BASE+off); \
        S(NAME##$$request$$bits$$write,write);S(NAME##$$request$$bits$$data,value); \
        S(NAME##$$request$$bits$$size,size);S(NAME##$$request$$bits$$byteEnable,mask);break;
        switch(p){BUS(0,gmac,macRegs);BUS(1,dma,dmaRegs);}
#undef BUS
    }
    void ready(unsigned p,bool value){if(p==0){S(gmac$$response$$ready,value);}else{S(dma$$response$$ready,value);}}
    bool requestReady(unsigned p){return p==0?G(gmac$$request$$ready):G(dma$$request$$ready);}
    bool responseValid(unsigned p){return p==0?G(gmac$$response$$valid):G(dma$$response$$valid);}
    MmioReply response(unsigned p){return p==0?MmioReply{G(gmac$$response$$bits$$data),bool(G(gmac$$response$$bits$$error))}:
        MmioReply{G(dma$$response$$bits$$data),bool(G(dma$$response$$bits$$error))};}
    void tick(){
        bool requestReady=!holdRequests&&random()%4!=0;
        bool responseValid=!holdReplies&&!replies.empty()&&replies.front().due<=cycles;
        S(memory$$request$$ready,requestReady);S(memory$$response$$valid,responseValid);
        S(memory$$response$$bits$$data,0);S(memory$$response$$bits$$error,0);
        bool lastData=holdLastData&&!expectedFrames.empty()&&received.size()+4>=expectedFrames.front().size();
        S(holdData,holdData||lastData);S(holdStatus,holdStatus||(holdLastStatus&&statusIndex==5));
        S(rxClockEnable,!clockSleep);S(rxQuiesce,clockSleep);S(rxIsolate,clockSleep);
        int byte=incoming.empty()?-1:incoming.front();
        S(gmiiRxValid,byte>=0);S(gmiiRxData,byte<0?0:byte);S(gmiiRxError,0);
        d.step();++cycles;wakeCycles+=G(rxWake);
        if(!incoming.empty())incoming.pop_front();
        check(!G(gmiiTxEnable)&&!G(gmiiTxError),"RX shutdown unexpectedly drove TX");
        if(responseValid&&G(memory$$response$$ready)){
            auto r=replies.front();replies.pop_front();++completed;
            for(unsigned n=0;n<8;++n)if(r.mask&(1U<<n))memory.at(r.address-ram+n)=r.data>>(8*n);
        }
        Request request{G(memory$$request$$bits$$address),G(memory$$request$$bits$$data),
            unsigned(G(memory$$request$$bits$$byteEnable)),unsigned(G(memory$$request$$bits$$size)),
            bool(G(memory$$request$$bits$$write))};
        if(heldRequest)check(G(memory$$request$$valid)&&request==*heldRequest,
            "RX_STOP cancelled or changed an offered DDR request");
        heldRequest=G(memory$$request$$valid)&&!requestReady?std::optional{request}:std::nullopt;
        requestStalls+=bool(heldRequest);
        if(G(memory$$request$$valid)&&requestReady){
            auto[address,data,mask,size,write]=request;
            check(write&&size==3&&address==ram+storeOffset+storeNext&&storeNext<storeBody.size(),
                "RX shutdown independent DDR address/order oracle mismatch");
            unsigned count=std::min(8U,unsigned(storeBody.size()-storeNext));
            check(mask==((1U<<count)-1),"RX shutdown independent DDR tail-mask oracle mismatch");
            for(unsigned n=0;n<count;++n){
                check(uint8_t(data>>(8*n))==storeBody.at(storeNext+n),
                    "RX shutdown independent DDR payload oracle mismatch");
                expectedMemory.at(storeOffset+storeNext+n)=storeBody.at(storeNext+n);
            }
            storeNext+=count;++writes;
            replies.push_back({cycles+7+unsigned(random()%11),address,data,mask});
            peak=std::max(peak,unsigned(replies.size()));
            check(replies.size()<=4,"RX shutdown exceeded four accepted DDR credits");
        }
        if(G(rxDataValid)){
            Beat value{uint32_t(G(rxData$$data)),unsigned(G(rxData$$keep)),bool(G(rxData$$last))};
            if(heldData)check(value==*heldData,"RX_STOP changed a stalled RX data beat");
            heldData=G(rxDataReady)?std::nullopt:std::optional{value};dataStalls+=!G(rxDataReady);
            if(G(rxDataReady)){
                auto[word,keep,last]=value;
                check(!expectedFrames.empty()&&(keep==1||keep==3||keep==7||keep==15)&&(last||keep==15),
                    "RX shutdown admitted unexpected frame or malformed keep");
                for(unsigned n=0;n<4;++n)if(keep&(1U<<n))received.push_back(word>>(8*n));
                if(last){
                    auto expected=expectedFrames.front();
                    if(inject=="payload"&&dataFrames==0)expected.at(17)^=1;
                    check(received==expected,"RX shutdown independent frame payload oracle mismatch");
                    expectedStatus.push_back(expected.size());expectedFrames.pop_front();
                    received.clear();++dataFrames;
                }
            }
        }else check(!heldData,"RX_STOP withdrew a stalled RX data beat");
        if(G(rxStatusValid)){
            Beat value{uint32_t(G(rxStatus$$data)),unsigned(G(rxStatus$$keep)),bool(G(rxStatus$$last))};
            if(heldStatus)check(value==*heldStatus,"RX_STOP changed a stalled RX status beat");
            heldStatus=G(rxStatusReady)?std::nullopt:std::optional{value};statusStalls+=!G(rxStatusReady);
            if(G(rxStatusReady)){
                check(!expectedStatus.empty(),"RX shutdown status has no complete frame");
                uint32_t expected=statusIndex==0?0x50000000:statusIndex==3?64:statusIndex==5?expectedStatus.front():0;
                if(inject=="status"&&statusFrames==0&&statusIndex==5)expected^=1;
                auto[word,keep,last]=value;
                check(word==expected&&keep==15&&last==(statusIndex==5),
                    "RX shutdown independent status-tail oracle mismatch");
                if(++statusIndex==6){statusIndex=0;expectedStatus.pop_front();++statusFrames;}
            }
        }else check(!heldStatus,"RX_STOP withdrew a stalled RX status beat");
    }
    void idle(unsigned n){while(n--)tick();}
    uint64_t access(unsigned p,unsigned off,bool write=false,uint64_t value=0,bool error=false,
        unsigned size=3,unsigned mask=255,unsigned minHold=5){
        bool sent=false;std::optional<MmioReply> held;
        for(unsigned n=0;n<2000;++n){
            bus(p,off,write,value,!sent,size,mask);bool take=n>=minHold&&(minHold==0||n%3!=0);ready(p,take);tick();
            if(!sent&&requestReady(p))sent=true;
            if(responseValid(p)){
                auto result=response(p);if(held)check(result==*held,"RX shutdown MMIO response changed while held");
                held=result;
                if(take){
                    if(!sent||result.error!=error)throw std::runtime_error("RX shutdown MMIO result mismatch: port="+
                        std::to_string(p)+" offset="+std::to_string(off)+" error="+std::to_string(result.error));
                    bus(p,off,write,value,false,size,mask);ready(p,false);++mmio;return result.data;
                }
            }
        }
        throw std::runtime_error("RX shutdown MMIO hung");
    }
    void startRx(unsigned offset,const std::vector<uint8_t>&body){
        check(replies.empty()&&!heldRequest,"test rearmed DMA before previous DDR completion");
        storeOffset=offset;storeBody=body;storeNext=0;
        access(1,0x30,true,ram+offset);access(1,0x38,true,2048);access(1,0x40,true,3);
    }
    void supply(const std::vector<uint8_t>&body,bool expected=true,unsigned gap=12){
        if(expected)expectedFrames.push_back(body);
        for(auto byte:ethernetWire(body))incoming.push_back(byte);
        while(gap--)incoming.push_back(-1);
    }
    void stop(){access(0,0x90,true,1);}
    void notDrained(){
        auto value=access(0,0x90);if(inject=="drain")value|=2;
        check(value==1,"RX shutdown independent premature-drain oracle mismatch");
    }
    void waitDrained(){
        unsigned limit=cycles+20000;while(access(0,0x90)!=3){check(cycles<limit,"GMAC RX_STOP did not drain");}
    }
    void waitDma(){
        unsigned limit=cycles+20000;while(access(1,0x48)&1){check(cycles<limit,"DMA RX_STOP did not retire");}
        check(replies.empty()&&!heldRequest,"DMA completed while accepted/offered DDR ownership remained");
    }
    void verifyMemory(){
        auto expected=expectedMemory;if(inject=="memory")expected.at(storeOffset)^=1;
        check(memory==expected,"RX shutdown independent memory/canary oracle mismatch");
    }
    void release(){
        access(0,0x90,true,0);idle(160);
        check(access(0,0x90)==0,"RX_STOP release did not settle");
    }
};

static void queuedAndDdrCase(unsigned seed,unsigned length,const std::string&inject){
    Test t(seed,inject);auto body=ethernetBody(length,seed);auto initial=t.memory;
    // The original failure order: software disarms an empty DMA first, then a
    // long already-admitted wire frame fills the CDC queue and strands the MAC.
    t.startRx(256,body);t.access(1,0x90,true,1);t.waitDma();
    check(t.access(1,0x48)==6,"empty DMA stop did not disarm the descriptor");
    t.supply(body);t.idle(length+600);
    check(t.G(rxDataValid)&&!t.G(rxDataReady)&&(t.access(0,0x28)&4),
        "historical disarm-before-long-frame busy condition was not reproduced");
    t.access(0,0x10,true,0,true);t.stop();t.notDrained();
    t.stop();t.notDrained();
    // First stop cannot be acknowledged while this admitted frame is blocked.
    // Reverse desired level twice while that mailbox is still owned.
    t.access(0,0x90,true,0);check(t.access(0,0x90)==0,"release level was not recorded while stop pending");
    t.stop();t.notDrained();
    t.access(0,0x90,true,2,true);t.access(0,0x90,true,1,true,2,15);
    t.access(0,0x90,true,1,true,3,15);t.notDrained();
    t.access(0,0x10,true,0,true);
    // Stop must remain pending with a source-owned frame, FIFO and CPU prefetch.
    // All later traffic is unrelated, and must not replace that admitted frame.
    for(unsigned n=0;n<8;++n)t.supply(ethernetBody(64,n+91),false);
    t.idle(160);t.notDrained();check(t.memory==initial&&!t.writes,"stopped DMA leaked a DDR write");
    // Firmware may rearm a scratch descriptor WHILE stop is pending to consume
    // its admitted tail. Deliberately hold the sixth status word independently.
    t.holdReplies=true;t.holdLastData=true;t.holdLastStatus=true;t.startRx(256,body);
    unsigned limit=t.cycles+10000;
    while(!t.G(rxDataValid)||!t.G(rxData$$last)||t.G(rxDataReady)){
        t.tick();check(t.cycles<limit,"last RX data hold was not reached");
    }
    t.idle(80);t.notDrained();t.holdLastData=false;
    while(t.dataFrames!=1||t.statusIndex!=5){t.tick();check(t.cycles<limit,"scratch rearm failed to drain RX payload");}
    t.idle(100);t.notDrained();
    check(t.G(rxStatusValid)&&!t.G(rxStatusReady)&&!t.writes&&t.memory==initial,
        "RX status tail was lost or DMA stored before complete status");
    t.holdLastStatus=false;t.waitDrained();
    limit=t.cycles+1000;while(t.replies.size()<4){t.tick();check(t.cycles<limit,"DDR hold failed to fill four credits");}
    check(t.statusFrames==1&&(t.access(1,0x48)&1)&&t.memory==initial,
        "GMAC drain incorrectly claimed DMA DDR completion");
    // Even an active background wire frame cannot keep configuration busy once
    // stop has closed admission and all admitted media/CPU ownership is gone.
    while(!t.incoming.empty())t.tick();
    t.supply(ethernetBody(2048,77),false);t.idle(160);
    check(!t.incoming.empty()&&t.access(0,0x90)==3,"stopped background frame revoked drain");
    t.access(0,0x10,true,0);t.idle(100);
    check(t.access(0,0x10)==0,"CONTROL=0 was not accepted under stopped background traffic");
    // No accepted DDR transaction is forcibly cancelled by either stop command.
    unsigned pending=t.replies.size(),completed=t.completed;
    t.access(1,0x90,true,1);t.idle(100);
    check((t.access(1,0x48)&1)&&t.replies.size()==pending&&t.completed==completed,
        "DMA RX_STOP completed/cancelled accepted DDR requests before their replies");
    t.holdReplies=false;t.waitDma();t.verifyMemory();
    check(t.completed==t.writes&&t.peak==4,"accepted DDR requests were not all retired");
    t.stop();check(t.access(0,0x90)==3,"repeated drained stop is not idempotent");
    while(!t.incoming.empty())t.tick();t.idle(100);
    // Reconfigure while stopped, release, and use a different buffer/odd tail.
    t.access(0,0x10,true,11);t.idle(100);t.release();
    auto resumed=ethernetBody(61,seed+1);t.startRx(4096,resumed);t.supply(resumed);
    t.waitDma();t.verifyMemory();
    check(t.storeNext==resumed.size()&&t.access(1,0x48)==2&&t.dataFrames==2&&t.statusFrames==2,
        "released GMAC did not receive the second attempt exactly once");
    t.stop();t.waitDrained();t.access(1,0x90,true,1);t.access(0,0x10,true,0);
    check(t.access(0,0x48)==2,"background frames escaped admission stop");
    check(t.dataStalls&&t.statusStalls&&t.requestStalls,"shutdown backpressure coverage missing");
    std::cout<<"queued_case seed="<<seed<<" length="<<length<<" writes="<<t.writes
        <<" data_stalls="<<t.dataStalls<<" status_stalls="<<t.statusStalls<<" cycles="<<t.cycles<<'\n';
}

static void inFlightCase(unsigned seed,unsigned length,bool preamble=false){
    Test t(seed);auto body=ethernetBody(length,seed);t.startRx(512,body);t.holdData=true;
    if(preamble)for(unsigned n=0;n<96;++n)t.incoming.push_back(0x55);
    t.supply(body);t.idle(preamble?160:400);
    check(!t.incoming.empty()&&(t.access(0,0x28)&4),"in-flight stop did not reach an admitted preamble/body");
    t.stop();t.notDrained();
    for(unsigned n=0;n<6;++n)t.supply(ethernetBody(127,n+33),false);
    while(!t.G(rxDataValid)){t.tick();check(t.cycles<20000,"admitted in-flight frame vanished on RX_STOP");}
    t.idle(160);t.notDrained();t.stop();t.notDrained();
    t.holdData=false;t.waitDrained();t.waitDma();t.verifyMemory();
    check(t.storeNext==body.size()&&t.access(1,0x48)==2&&t.dataFrames==1&&t.statusFrames==1,
        "busy-safe RX_STOP truncated the already-admitted frame");
    while(!t.incoming.empty())t.tick();t.idle(100);
    check(t.access(0,0x48)==1,"in-flight shutdown admitted a background frame");
    t.access(0,0x10,true,0);t.release();
    check(t.access(0,0x10)==0,"release unexpectedly enabled RX");
    std::cout<<"inflight_case seed="<<seed<<" preamble="<<preamble<<" length="<<length<<" writes="<<t.writes<<" cycles="<<t.cycles<<'\n';
}

static void managedWakeCase(){
    Test t(101);t.clockSleep=true;t.idle(180);
    check(t.G(rxAck),"aliased managed RX failed to acknowledge quiesce before command");
    unsigned wake=t.wakeCycles;t.stop();t.waitDrained();
    check(t.wakeCycles>wake,"queued RX_STOP did not assert managed RX wake");
    t.clockSleep=false;t.idle(160);
    // Back-to-back one-credit MMIO: release has actually been sent through the
    // mailbox when stop supersedes it. An older stop ack must not mean drained.
    t.access(0,0x90,true,0,false,3,255,0);
    t.access(0,0x90,true,1,false,3,255,0);
    check(t.access(0,0x90,false,0,false,3,255,0)==1,
        "RX_STOP reused an old acknowledgement while release was still in flight");
    t.waitDrained();t.release();
    check(!t.G(rxAck),"managed quiesce acknowledgement survived resume");
    std::cout<<"managed_wake_case control_stop_simulated=1 actual_clock_halted=0\n";
}

int main(int argc,char**argv){try{
    std::string inject;
    if(argc==2){std::string_view flag=argv[1];check(flag.starts_with("--inject-"),"unknown failure injection");inject=flag.substr(9);}
    queuedAndDdrCase(3,1518,inject);queuedAndDdrCase(919,2048,{});
    inFlightCase(17,1514);inFlightCase(71,2047,true);managedWakeCase();
    std::cout<<"GMAC_SHUTDOWN_PASS cases=5 historical_busy=1 scratch_rearm=1 status_tail=1"
        <<" accepted_ddr_retained=1 background_admission_closed=1 release_resume=1"
        <<" independent_memory=1 single_clock_only=1 multiclock_verified=0 board_verified=0\n";
    return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
