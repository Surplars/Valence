#ifdef COHERENT_DMA
#include "EthernetDmaCoherenceGsim.h"
using DmaModel = SEthernetDmaCoherenceGsim;
#else
#include "EthernetPacketDma.h"
using DmaModel = SEthernetPacketDma;
#endif
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdlib>
#include <deque>
#include <iostream>
#include <random>
#include <stdexcept>
#include <tuple>
#include <vector>
#ifndef TX_POSTED_SLOTS
#define TX_POSTED_SLOTS 0
#endif
#ifndef RX_POSTED_SLOTS
#define RX_POSTED_SLOTS 4
#endif
#ifndef DMA_MEMORY_CREDITS
#define DMA_MEMORY_CREDITS 4
#endif
#ifndef DMA_RAM_BYTES
#ifdef DCACHE_CAPACITY
#define DMA_RAM_BYTES ((DCACHE_CAPACITY * 128ULL) > 8192ULL ? (DCACHE_CAPACITY * 128ULL) : 8192ULL)
#else
#define DMA_RAM_BYTES 8192ULL
#endif
#endif
#define S(n,v) d.set_io$$##n(v)
#define G(n) d.get_io$$##n()
static void check(bool v, const char *m) { if (!v) throw std::runtime_error(m); }
static constexpr uint64_t ram = 0x80200000ULL, regs = 0x10002000ULL;
struct Beat { uint32_t data; unsigned keep; bool last; };
struct Reply { unsigned due; uint64_t address, data; unsigned mask; bool write, error; };
struct Test {
    DmaModel d;
    #ifdef DCACHE_CAPACITY
    static constexpr size_t memoryBytes = std::max(8192, DCACHE_CAPACITY * 128);
#else
    static constexpr size_t memoryBytes = 8192;
#endif
    std::array<uint8_t,memoryBytes> memory{};
    std::deque<Reply> replies;
    std::deque<Beat> dataIn, statusIn;
    std::vector<uint8_t> dataOut;
    std::vector<Beat> controls;
    std::mt19937 rng;
    unsigned cycle=0, requests=0, reads=0, writes=0, peak=0, latency=9;
    unsigned dataDelay=0, statusDelay=0, dataAccepted=0, statusAccepted=0;
    unsigned txStalls=0, memoryStalls=0;
    int failRead=-1, failWrite=-1;
    bool dataOffered=false, statusOffered=false, held=false, txHeld=false, ctrlHeld=false;
    std::tuple<uint64_t,uint64_t,unsigned,bool> offer;
    std::tuple<uint32_t,unsigned,bool> txOffer, ctrlOffer;
    bool inject=false, requireCompleteRx=true, holdMemoryRequest=false, multiTx=false, holdTxData=false;
    std::vector<unsigned> txFrameEnds;
    bool trace=std::getenv("DMA_TRACE")!=nullptr;
    Test(unsigned seed, bool negative=false):rng(seed),inject(negative) {
        for(auto &b:memory) b=rng();
        S(control$$request$$valid,0); S(control$$response$$ready,0);
        S(control$$request$$bits$$address,regs); S(control$$request$$bits$$write,0);
        S(control$$request$$bits$$data,0); S(control$$request$$bits$$size,3);
        S(control$$request$$bits$$byteEnable,255);
        S(rxData$$valid,0); S(rxStatus$$valid,0);
#ifdef COHERENT_DMA
        S(cpu$$request$$valid,0); S(cpu$$response$$ready,0);
        S(cpu$$request$$bits$$address,ram); S(cpu$$request$$bits$$write,0);
        S(cpu$$request$$bits$$data,0); S(cpu$$request$$bits$$size,3); S(cpu$$request$$bits$$mask,255);
        S(cpu$$request$$bits$$atomic,0); S(cpu$$request$$bits$$atomicOp,0);
        S(cpu$$request$$bits$$virtualized,0); S(cpu$$request$$bits$$uncached,0);
#endif
        d.set_reset(1); tick(); tick(); d.set_reset(0);
    }
    void tick() {
        bool ready=!holdMemoryRequest && rng()%4!=0, valid=!replies.empty() && replies.front().due<=cycle;
        S(memory$$request$$ready,ready); S(memory$$response$$valid,valid);
        S(memory$$response$$bits$$data,valid?replies.front().data:0);
        S(memory$$response$$bits$$error,valid?replies.front().error:0);
        bool txReady=!holdTxData && cycle%23>=7 && rng()%3!=0, ctrlReady=cycle%17>=5 && rng()%3!=0;
        S(txData$$ready,txReady); S(txControl$$ready,ctrlReady);
        if(!dataOffered && !dataIn.empty() && cycle>=dataDelay && rng()%3!=0) dataOffered=true;
        if(!statusOffered && !statusIn.empty() && cycle>=statusDelay && rng()%3!=0) statusOffered=true;
        S(rxData$$valid,dataOffered); S(rxStatus$$valid,statusOffered);
        Beat db=dataIn.empty()?Beat{}:dataIn.front(), sb=statusIn.empty()?Beat{}:statusIn.front();
        S(rxData$$bits$$data,db.data); S(rxData$$bits$$keep,db.keep); S(rxData$$bits$$last,db.last);
        S(rxStatus$$bits$$data,sb.data); S(rxStatus$$bits$$keep,sb.keep); S(rxStatus$$bits$$last,sb.last);
        d.step(); ++cycle;
        if(valid && G(memory$$response$$ready)) {
            auto r=replies.front(); replies.pop_front();
            if(r.write && !r.error) for(unsigned b=0;b<8;++b)
                if(r.mask&(1U<<b)) memory.at(r.address-ram+b)=r.data>>(8*b);
        }
        auto next=std::make_tuple(G(memory$$request$$bits$$address),G(memory$$request$$bits$$data),
            unsigned(G(memory$$request$$bits$$byteEnable)),bool(G(memory$$request$$bits$$write)));
        if(held) check(G(memory$$request$$valid) && next==offer,"memory stalled offer changed");
        held=G(memory$$request$$valid) && !ready; offer=next; memoryStalls+=held;
        if(G(memory$$request$$valid) && ready) {
            auto [a,v,m,w]=next;
            unsigned bytes=1U<<G(memory$$request$$bits$$size);
            check(bytes<=8 && a>=ram && a+bytes<=ram+memory.size() && a%bytes==0,"DMA address outside board RAM");
            check((m&~((1U<<bytes)-1))==0 && (w||m==((1U<<bytes)-1)),"DMA beat width/mask mismatch");
            uint64_t value=0; if(!w) for(unsigned b=0;b<8;++b) value|=uint64_t(memory[a-ram+b])<<(8*b);
            bool error=w?int(writes)==failWrite:int(reads)==failRead;
            if(trace && cycle<1000) std::cerr<<"MEM cycle="<<cycle<<" address="<<std::hex<<a<<" data="<<v
                <<" mask="<<m<<std::dec<<" write="<<w<<"\n";
            if(w && requireCompleteRx) check(dataIn.empty() && statusIn.empty(),"RX wrote before full frame/status");
            if(!w) check(m==255,"TX read mask mismatch");
            w?++writes:++reads; ++requests;
            replies.push_back({cycle+latency+unsigned(rng()%5),a,w?v:value,m,w,error});
            peak=std::max(peak,unsigned(replies.size()));
#ifndef COHERENT_DMA
            check(replies.size()<=DMA_MEMORY_CREDITS,"DMA credit overflow");
#endif
        }
        auto t=std::make_tuple(uint32_t(G(txData$$bits$$data)),unsigned(G(txData$$bits$$keep)),bool(G(txData$$bits$$last)));
        auto c=std::make_tuple(uint32_t(G(txControl$$bits$$data)),unsigned(G(txControl$$bits$$keep)),bool(G(txControl$$bits$$last)));
        if(txHeld) check(G(txData$$valid)&&t==txOffer,"TX data changed under backpressure");
        if(ctrlHeld) check(G(txControl$$valid)&&c==ctrlOffer,"TX control changed under backpressure");
        txHeld=G(txData$$valid)&&!txReady; txOffer=t; ctrlHeld=G(txControl$$valid)&&!ctrlReady; ctrlOffer=c;
        txStalls+=txHeld+ctrlHeld;
        if(G(txControl$$valid)&&ctrlReady) {
            auto [v,k,l]=c; check(controls.size()<6,"extra TX control words");
            check(v==(controls.empty()?0xa0000000U:0U)&&k==15&&l==(controls.size()==5),"PG138 TX control mismatch");
            controls.push_back({v,k,l});
        }
        if(G(txData$$valid)&&txReady) {
            auto [v,k,l]=t; check(controls.size()==6,"TX data preceded control completion");
            check(k==1||k==3||k==7||k==15,"invalid TX keep");
            check(l||k==15,"TX non-final partial word");
            for(unsigned b=0;b<4;++b) if(k&(1U<<b)) dataOut.push_back(v>>(8*b));
            if(l && multiTx) { txFrameEnds.push_back(dataOut.size()); controls.clear(); }
        }
        if(dataOffered&&G(rxData$$ready)) { dataIn.pop_front(); dataOffered=false; ++dataAccepted; }
        if(statusOffered&&G(rxStatus$$ready)) { statusIn.pop_front(); statusOffered=false; ++statusAccepted; }
    }
    uint64_t access(unsigned offset,bool write=false,uint64_t value=0,bool error=false,
        unsigned size=3,unsigned mask=255) {
        S(control$$request$$bits$$address,regs+offset); S(control$$request$$bits$$write,write);
        S(control$$request$$bits$$data,value); S(control$$request$$bits$$size,size);
        S(control$$request$$bits$$byteEnable,mask); S(control$$request$$valid,1);
        unsigned limit=cycle+20000;
        do { tick(); check(cycle<limit,"MMIO request timeout"); } while(!G(control$$request$$ready));
        S(control$$request$$valid,0);
        do { tick(); check(cycle<limit,"MMIO response timeout"); } while(!G(control$$response$$valid));
        uint64_t result=G(control$$response$$bits$$data);
        check(bool(G(control$$response$$bits$$error))==error,"MMIO independent error mismatch");
        for(unsigned i=0;i<4;++i) { tick(); check(G(control$$response$$valid) &&
            result==G(control$$response$$bits$$data) && bool(G(control$$response$$bits$$error))==error,
            "MMIO response changed under backpressure"); }
        S(control$$response$$ready,1); tick(); S(control$$response$$ready,0);
        return result;
    }
    void startTx(uint64_t address,unsigned length) {
        access(16,true,address); access(24,true,length); access(32,true,3);
    }
#ifdef COHERENT_DMA
    uint64_t cpuAccess(uint64_t address,bool write=false,uint64_t value=0) {
        S(cpu$$request$$bits$$address,address); S(cpu$$request$$bits$$write,write);
        S(cpu$$request$$bits$$data,value); S(cpu$$request$$valid,1);
        unsigned limit=cycle+10000;
        do { tick(); check(cycle<limit,"coherent CPU request timeout"); } while(!G(cpu$$request$$ready));
        S(cpu$$request$$valid,0);
        do { tick(); check(cycle<limit,"coherent CPU response timeout"); } while(!G(cpu$$response$$valid));
        check(!G(cpu$$response$$bits$$error),"coherent CPU response error");
        uint64_t result=G(cpu$$response$$bits$$data);
        S(cpu$$response$$ready,1); tick(); S(cpu$$response$$ready,0); return result;
    }
#endif
    void armRx(uint64_t address,unsigned capacity) {
        access(48,true,address); access(56,true,capacity); access(64,true,3);
    }
    void supply(unsigned length,unsigned mode=0) {
        for(unsigned i=0;i<length;i+=4) {
            uint32_t v=0; unsigned n=std::min(4U,length-i);
            for(unsigned b=0;b<n;++b) v|=uint32_t(uint8_t((i+b)*13+7))<<(8*b);
            unsigned k=(1U<<n)-1; if(mode==4&&i==0) k=5;
            dataIn.push_back({v,k,i+n==length});
        }
        for(unsigned i=0;i<6;++i) statusIn.push_back({i==0?(mode==1?0xa0000000U:0x50000000U):
            i==3?(mode==2?0x80U:0x40U):i==5?length+(mode==3):0U,15,i==5});
        if(mode==5) { statusIn[2].last=true; statusIn.resize(3); }
        if(mode==6) { statusIn.back().last=false; statusIn.push_back({0,15,true}); }
    }
    void finish(bool txError=false,bool rxError=false,bool withTx=true,bool withRx=true) {
        unsigned limit=cycle+50000;
        while((withTx&&(access(40)&1)) || (withRx&&(access(72)&1))) check(cycle<limit,"DMA completion timeout");
        if(withTx) check(access(40)==(txError?6:2),"TX completion status mismatch");
        if(withRx) check(access(72)==(rxError?6:2),"RX completion status mismatch");
        check(replies.empty()&&!held,"completion before memory drain");
    }
};
int main(int argc,char**) { try {
#if TX_POSTED_SLOTS > 0 && !defined(COHERENT_DMA)
    // Independent FIFO/byte oracle. No RTL queue state defines expected data.
    for(unsigned seed:{5U,331U}) {
        Test q(seed);q.multiTx=true;q.access(8,true,3);q.access(240,true,1);
        q.access(32,true,3,true);q.access(240,true,3,true);
        std::vector<uint8_t> expected;unsigned oldBytes=0;
        for(unsigned batch=0;batch<3;++batch) {
            for(unsigned i=0;i<TX_POSTED_SLOTS;++i) {
                unsigned n=65+i+batch,offset=4096+256*i;
                expected.insert(expected.end(),q.memory.begin()+offset,q.memory.begin()+offset+n);
                q.access(224,true,ram+offset);q.access(232,true,n);q.access(240,true,4);
            }
            q.access(240,true,4,true); // retained owners make the queue full
            unsigned limit=q.cycle+50000;
            while(((q.access(248)>>8)&255)!=TX_POSTED_SLOTS)check(q.cycle<limit,"TX queue completion timeout");
            check(q.G(irq),"TX completion IRQ missing");
            check(q.dataOut==expected,"posted TX independent byte mismatch");
            for(unsigned i=0;i<TX_POSTED_SLOTS;++i) {
                check(q.access(224)==ram+4096+256*i&&q.access(232)==65+i+batch,"TX owner/result FIFO mismatch");
                oldBytes+=65+i+batch;
                check(q.txFrameEnds.at(batch*TX_POSTED_SLOTS+i)==oldBytes,"TX packet boundary mismatch");
                q.access(240,true,8);
            }
            check(!q.G(irq),"TX completion IRQ survived final POP");
        }
        q.access(240,true,2);q.multiTx=false;q.controls.clear();q.dataOut.clear();
        q.startTx(ram+4096,23);q.finish(false,false,true,false);
        check(q.dataOut==std::vector<uint8_t>(q.memory.begin()+4096,q.memory.begin()+4119),"TX legacy restart bytes");
    }
    // STOP preserves a held active read, finishes its frame, and cancels pending owners.
    {
        Test q(773);q.multiTx=true;q.holdMemoryRequest=true;q.access(240,true,1);
        for(unsigned i=0;i<TX_POSTED_SLOTS;++i){q.access(224,true,ram+4096+256*i);q.access(232,true,97);q.access(240,true,4);}
        check(q.G(memory$$request$$valid),"TX held read witness absent");
        q.access(240,true,16);q.access(240,true,4,true);
        for(unsigned n=0;n<9;++n)q.tick();check(q.reads==0,"held TX read accepted too early");
        q.holdMemoryRequest=false;unsigned limit=q.cycle+50000;
        while(((q.access(248)>>8)&255)!=TX_POSTED_SLOTS)check(q.cycle<limit,"TX STOP drain timeout");
        check(q.txFrameEnds.size()==1 && q.dataOut==std::vector<uint8_t>(q.memory.begin()+4096,q.memory.begin()+4193),"TX STOP truncated/extra frame");
        for(unsigned i=0;i<TX_POSTED_SLOTS;++i){check(q.access(224)==ram+4096+256*i&&q.access(232)==(i?65536U:97U),"TX STOP FIFO result");q.access(240,true,8);}
        q.access(240,true,2);
    }
    // A stalled stream cannot be withdrawn by STOP or completion publication.
    {
        Test q(9191);q.multiTx=true;q.holdTxData=true;q.access(240,true,1);
        q.access(224,true,ram+4096);q.access(232,true,63);q.access(240,true,4);
        unsigned limit=q.cycle+10000;while(!q.G(txData$$valid)){q.tick();check(q.cycle<limit,"TX held stream absent");}
        q.access(240,true,16);for(unsigned n=0;n<9;++n)q.tick();
        check(!((q.access(248)>>8)&255),"TX completion before held stream accepted");
        q.holdTxData=false;limit=q.cycle+10000;while(!((q.access(248)>>8)&255))check(q.cycle<limit,"TX stream drain timeout");
        check(q.access(232)==63&&q.dataOut==std::vector<uint8_t>(q.memory.begin()+4096,q.memory.begin()+4159),"TX held stream bytes");q.access(240,true,8);q.access(240,true,2);
    }
    // Memory faults emit no partial packet; a subsequent posted frame succeeds.
    {
        Test q(810);q.multiTx=true;q.failRead=0;q.access(240,true,1);
        q.access(224,true,ram+4096);q.access(232,true,129);q.access(240,true,4);
        unsigned limit=q.cycle+10000;while(!((q.access(248)>>8)&255))check(q.cycle<limit,"TX fault drain timeout");
        check(q.dataOut.empty()&&q.controls.empty()&&q.access(232)==65536,"TX fault emitted partial packet");q.access(240,true,8);
        q.failRead=-1;q.access(240,true,4);limit=q.cycle+10000;while(!((q.access(248)>>8)&255))check(q.cycle<limit,"TX fault restart timeout");
        check(q.access(232)==129&&q.dataOut==std::vector<uint8_t>(q.memory.begin()+4096,q.memory.begin()+4225),"TX fault restart bytes");q.access(240,true,8);q.access(240,true,2);
    }
    // Independent simultaneous RX modifies only its own RAM slice.
    {
        Test q(441);q.multiTx=true;auto expected=q.memory;q.armRx(ram+256,63);q.supply(63);
        for(unsigned b=0;b<63;++b)expected[256+b]=b*13+7;
        q.access(240,true,1);q.access(224,true,ram+4096);q.access(232,true,131);q.access(240,true,4);
        unsigned limit=q.cycle+10000;while(!((q.access(248)>>8)&255)||!(q.access(72)&2))check(q.cycle<limit,"TX/RX simultaneous timeout");
        check(q.memory==expected&&q.dataOut==std::vector<uint8_t>(expected.begin()+4096,expected.begin()+4227),"TX/RX simultaneous bytes");q.access(240,true,8);q.access(240,true,2);
    }
    std::cout<<"ETHERNET_POSTED_TX_PASS slots="<<TX_POSTED_SLOTS<<" wrap_batches=6 held_read_stop=1 held_stream_stop=1 memory_fault=1 simultaneous_rx=1 fifo=1 legacy_restart=1\n";
#endif
#if TX_POSTED_SLOTS > 0 && defined(COHERENT_DMA)
    {
        Test q(661);q.multiTx=true;q.access(240,true,1);q.access(8,true,1);
        std::vector<uint8_t> expected;
        for(unsigned i=0;i<TX_POSTED_SLOTS;++i){
            unsigned offset=4096+256*i,n=64+i;uint64_t dirty=0x9182736455463728ULL+i;
            std::vector<uint8_t> frame(q.memory.begin()+offset,q.memory.begin()+offset+n);
            q.cpuAccess(ram+offset,true,dirty);
            for(unsigned b=0;b<8;++b)frame[b]=dirty>>(8*b);
            check(!std::equal(frame.begin(),frame.begin()+8,q.memory.begin()+offset),"posted coherent TX dirty witness missing");
            expected.insert(expected.end(),frame.begin(),frame.end());
            q.access(224,true,ram+offset);q.access(232,true,n);q.access(240,true,4);
        }
        unsigned limit=q.cycle+50000;while(((q.access(248)>>8)&255)!=TX_POSTED_SLOTS)check(q.cycle<limit,"posted coherent TX timeout");
        check(q.dataOut==expected&&q.txFrameEnds.size()==TX_POSTED_SLOTS&&q.G(irq),"posted coherent TX independent bytes/IRQ mismatch");
        for(unsigned i=0;i<TX_POSTED_SLOTS;++i){check(q.access(224)==ram+4096+256*i&&q.access(232)==64+i,"posted coherent TX owner mismatch");q.access(240,true,8);}
        q.access(240,true,2);
        std::cout<<"ETHERNET_POSTED_TX_COHERENCE_PASS slots="<<TX_POSTED_SLOTS<<" dirty_sources=1 fifo=1 retained_completion=1\n";
    }
#endif
    // Capacity-independent owner/address oracle. Source memory credits and
    // packet ownership are deliberately selected independently by the runner.
    {
        Test q(701);q.requireCompleteRx=false;q.access(184,true,1);auto expected=q.memory;
        check(q.access(152)==((uint64_t(TX_POSTED_SLOTS)<<24)|(DMA_MEMORY_CREDITS<<16)|(RX_POSTED_SLOTS<<8)|(TX_POSTED_SLOTS?7:3)),"parameter CAP mismatch");
        for(unsigned i=0;i<RX_POSTED_SLOTS;++i) {
            q.access(160,true,ram+512*i);q.access(168,true,256);q.access(176,true,1);
            q.supply(63+i);for(unsigned b=0;b<63+i;++b)expected[512*i+b]=b*13+7;
        }
        q.access(176,true,1,true);unsigned limit=q.cycle+50000;
        while(((q.access(192)>>8)&255)!=RX_POSTED_SLOTS)check(q.cycle<limit,"parameter batch timeout");
        check(q.memory==expected,"parameter packet bytes/canary mismatch");
        for(unsigned i=0;i<RX_POSTED_SLOTS;++i) {
            check(q.access(200)==ram+512*i&&q.access(208)==63+i,"parameter completion owner mismatch");q.access(216,true,1);
        }
        for(unsigned i=0;i<RX_POSTED_SLOTS;++i) {
            q.access(160,true,ram+512*i);q.access(176,true,1);
        }
        q.access(144,true,1);limit=q.cycle+10000;
        while(((q.access(192)>>8)&255)!=RX_POSTED_SLOTS)check(q.cycle<limit,"parameter stop timeout");
        for(unsigned i=0;i<RX_POSTED_SLOTS;++i) {
            check(q.access(200)==ram+512*i&&(q.access(208)&65536),"parameter cancelled owner mismatch");q.access(216,true,1);
        }
        q.access(184,true,0);q.armRx(ram,13);q.supply(13);q.finish(false,false,false,true);
    }
#ifndef COHERENT_DMA
    {
        Test q(811);q.latency=200;q.armRx(ram,2048);q.supply(2048);
        unsigned limit=q.cycle+20000;
        while(q.writes<DMA_MEMORY_CREDITS){q.tick();check(q.cycle<limit,"credit saturation missing");}
        for(unsigned n=0;n<5;++n)q.tick();
        check(!q.G(memory$$request$$valid),"expected unoffered credit-blocked RX request");
        unsigned accepted=q.writes;q.access(144,true,1);q.finish(false,true,false,true);
        check(q.writes==accepted,"RX_STOP issued a new credit-blocked write");
    }
#endif
#if DMA_RAM_BYTES > 0x80000000ULL - 0x200000ULL
    // Control-only cancelled owner above 4 GiB proves the compact descriptor
    // retains bit32 and the exact upper-bound address. No sparse RAM aliasing.
    {
        Test q(913);q.requireCompleteRx=false;q.access(184,true,1);
        uint64_t high=ram+DMA_RAM_BYTES-256;
        check(high>0xffffffffULL,"high-address fixture missing");
        q.access(160,true,high);q.access(168,true,256);q.access(176,true,1);
        q.access(144,true,1);unsigned limit=q.cycle+10000;
        while(((q.access(192)>>8)&255)!=1)check(q.cycle<limit,"high-address stop timeout");
        check(q.access(200)==high&&(q.access(208)&65536),"high-address owner truncated");
        check(q.requests==0,"cancelled high-address owner reached RAM");
        q.access(216,true,1);q.access(184,true,0);
    }
#endif
    std::cout<<"ETHERNET_DMA_CAPACITY_PASS slots="<<RX_POSTED_SLOTS<<" memory_credits="<<DMA_MEMORY_CREDITS
             <<" owner_fifo=1 cancel_wrap=1 legacy_restart=1\n";
#if RX_POSTED_SLOTS == 4
    // The oracle owns buffer contents/addresses independently of RTL counters.
    for(unsigned seed:{3U,17U,919U}) {
        Test q(seed); q.requireCompleteRx=false;
        check(q.access(152)==((uint64_t(TX_POSTED_SLOTS)<<24)|(DMA_MEMORY_CREDITS<<16)|(RX_POSTED_SLOTS<<8)|(TX_POSTED_SLOTS?7:3)),"posted queue capability/depth mismatch");
        q.access(184,true,1); q.access(8,true,2);
        auto expected=q.memory;
        const std::array<unsigned,4> lengths={63,5,128,1024};
        for(unsigned i=0;i<4;++i) {
            q.access(160,true,ram+i*1536); q.access(168,true,1152); q.access(176,true,1);
            if(i==0) q.access(176,true,1,true); // overlapping owned address
            for(unsigned b=0;b<lengths[i];++b) expected[i*1536+b]=b*13+7;
            q.supply(lengths[i]);
        }
        q.access(176,true,1,true); // completion retention consumes ownership too
        q.access(48,true,ram,true); q.access(64,true,3,true); // mode excludes V1 mutations
        unsigned limit=q.cycle+50000;
        while(((q.access(192)>>8)&255)!=4) check(q.cycle<limit,"posted batch completion timeout");
        check(q.memory==expected && q.replies.empty(),"posted batch byte/retirement oracle mismatch");
        check(q.G(irq),"posted completion IRQ missing");
        q.access(176,true,1,true); q.access(184,true,0,true);
        for(unsigned i=0;i<4;++i) {
            check(q.access(200)==ram+i*1536 && q.access(208)==lengths[i],"posted completion FIFO mismatch");
            q.access(216,true,1);
        }
        check(!q.G(irq),"posted completion IRQ not retired by POP");
        q.access(216,true,1,true); // cannot reclaim an uncompleted slot
        // Wrap all ring indices, reject invalid addresses without acquiring a slot.
        q.access(160,true,ram+1); q.access(176,true,1,true);
        q.access(160,true,ram); q.access(176,true,1); q.supply(13);
        limit=q.cycle+10000;
        while(!((q.access(192)>>8)&255)) check(q.cycle<limit,"posted wrap timeout");
        check(q.access(200)==ram && q.access(208)==13,"posted wrap metadata mismatch"); q.access(216,true,1);
        auto beforeOversize=q.memory;
        q.access(160,true,ram+1536); q.access(176,true,1); q.supply(1153);
        q.access(160,true,ram+3072); q.access(176,true,1); q.supply(5);
        limit=q.cycle+10000;
        while(((q.access(192)>>8)&255)!=2) check(q.cycle<limit,"posted oversize recovery timeout");
        check(q.access(200)==ram+1536 && q.access(208)==(65536|1153),"posted oversize metadata mismatch");
        check(std::equal(beforeOversize.begin()+1536,beforeOversize.begin()+2688,q.memory.begin()+1536),
            "posted oversized frame modified destination"); q.access(216,true,1);
        check(q.access(200)==ram+3072 && q.access(208)==5,"posted recovery owner mismatch"); q.access(216,true,1);
        q.access(184,true,0); check(!q.G(active),"posted disable left active ownership");
    }
    // Cancel with either stream half outstanding, plus an empty active wait.
    for(unsigned half:{0U,1U,2U,3U}) {
        Test q(90+half); q.requireCompleteRx=false; auto before=q.memory;
        q.access(184,true,1);
        for(unsigned i=0;i<4;++i) {
            q.access(160,true,ram+i*1536); q.access(168,true,1152); q.access(176,true,1);
        }
        if(half) {
            q.supply(128);
            if(half==1) q.statusDelay=q.cycle+400;
            if(half==2) q.dataDelay=q.cycle+400;
            if(half==3) {
                unsigned limit=q.cycle+10000;
                while(q.writes==0) { q.tick(); check(q.cycle<limit,"posted write phase missing"); }
                q.holdMemoryRequest=true;
                while(!q.held) { q.tick(); check(q.cycle<limit,"posted held write offer missing"); }
            } else while(q.dataAccepted+q.statusAccepted==0) q.tick();
        }
        q.access(144,true,1); q.access(176,true,1,true);
        if(half==3) {
            for(unsigned n=0;n<20;++n) { q.tick(); check(q.G(active),"posted stop abandoned held write"); }
            q.holdMemoryRequest=false;
        }
        unsigned limit=q.cycle+10000;
        while(((q.access(192)>>8)&255)!=4) check(q.cycle<limit,"posted cancel drain timeout");
        check(q.replies.empty(),"posted cancel published before accepted responses retired");
        if(half!=3) check(q.memory==before && q.writes==0,"cancel before capture wrote RAM");
        else for(unsigned n=0;n<q.memory.size();++n) {
            uint8_t expected=n<q.writes*8?uint8_t(n*13+7):before[n];
            check(q.memory[n]==expected,"posted cancel accepted-write prefix mismatch");
        }
        check(q.dataIn.empty()&&q.statusIn.empty(),"posted cancel abandoned stream tail");
        for(unsigned i=0;i<4;++i) {
            check(q.access(200)==ram+i*1536 && (q.access(208)&65536),"cancel completion owner/error missing");
            q.access(216,true,1);
        }
        q.access(184,true,0); q.armRx(ram,13); q.supply(13); q.finish(false,false,false,true);
    }
    {
        Test q(131); q.requireCompleteRx=false; q.failWrite=0;
        q.access(184,true,1);
        for(unsigned i=0;i<2;++i) {
            q.access(160,true,ram+i*1536); q.access(168,true,1152); q.access(176,true,1); q.supply(128);
        }
        unsigned limit=q.cycle+10000;
        while(((q.access(192)>>8)&255)!=2) check(q.cycle<limit,"posted memory fault recovery timeout");
        check(q.access(200)==ram && (q.access(208)&65536),"posted write fault lost error completion");
        q.access(216,true,1);
        check(q.access(200)==ram+1536 && q.access(208)==128,"posted fault poisoned following owner");
        for(unsigned n=0;n<128;++n) check(q.memory[1536+n]==uint8_t(n*13+7),"posted recovery payload mismatch");
        q.access(216,true,1); q.access(184,true,0);
    }
    std::cout<<"ETHERNET_POSTED_RX_PASS batches=3 wrap=1 retention=1 cancel_cases=4 held_write_stop=1 memory_fault=1 legacy_restart=1\n";
#endif
#ifdef COHERENT_DMA
#ifdef DCACHE_CAPACITY
    // Real cache + home directory + DMA. Three lines share one set. The second
    // owner remains in the upper way while the dirty first owner is evicted.
    // Fill every home slot, then verify resident upper/lower ways without
    // backing reads. Probe the last slot to expose truncated directory indices.
    {
        Test full(743U);
        for(unsigned i=0;i<DCACHE_CAPACITY;++i)
            full.cpuAccess(ram+64ULL*i,true,0xabcd000000000000ULL^i);
        auto reads=full.reads;
        for(unsigned i=0;i<DCACHE_CAPACITY;++i)
            check(full.cpuAccess(ram+64ULL*i)==(0xabcd000000000000ULL^i),"full directory data mismatch");
        check(full.reads==reads,"full directory residency failed");
        const uint64_t high=ram+64ULL*(DCACHE_CAPACITY-1);
        const uint64_t value=0xabcd000000000000ULL^(DCACHE_CAPACITY-1);
        full.startTx(high,8);full.finish(false,false,true,false);
        std::vector<uint8_t> expected;for(unsigned i=0;i<8;++i)expected.push_back(value>>(8*i));
        if(argc>1)expected[0]^=1;
        check(full.dataOut==expected,"TX independent byte oracle mismatch");
        reads=full.reads;
        check(full.cpuAccess(high)==value&&full.reads==reads+8,"high directory slot probe did not invalidate");
        std::cout<<"ETHERNET_DMA_FULL_DIRECTORY_PASS lines="<<DCACHE_CAPACITY
                 <<" cycles="<<full.cycle<<" high_slot_probe=1\n";
    }
    for(unsigned seed:{17U,31U,919U}) {
        Test conflict(seed);
        constexpr uint64_t stride=64ULL*DCACHE_CAPACITY/2;
        const uint64_t a=ram,b=ram+stride,c=ram+2*stride;
        const uint64_t av=0x13579bdf02468aceULL,bv=0xfedcba9876543210ULL;
        conflict.cpuAccess(a,true,av);conflict.cpuAccess(b,true,bv);
        check(conflict.cpuAccess(b)==bv,"directory MRU touch mismatch");
        conflict.cpuAccess(c);
        uint64_t backing=0;for(unsigned i=0;i<8;++i)backing|=uint64_t(conflict.memory[i])<<(8*i);
        check(backing==av,"directory dirty victim did not reach independent backing memory");
        auto reads=conflict.reads;
        check(conflict.cpuAccess(b)==bv&&conflict.reads==reads,"remaining upper-way owner should hit");
        check(conflict.cpuAccess(a)==av&&conflict.reads==reads+8,"actual evicted owner must reload eight beats");
        conflict.startTx(b,8);conflict.finish(false,false,true,false);
        std::vector<uint8_t> expected;for(unsigned i=0;i<8;++i)expected.push_back(bv>>(8*i));
        if(argc>1)expected[0]^=1;
        check(conflict.dataOut==expected,"TX independent byte oracle mismatch");
        reads=conflict.reads;
        check(conflict.cpuAccess(b)==bv&&conflict.reads==reads+8,"DMA probe must invalidate remaining upper-way owner");
        std::cout<<"ETHERNET_DMA_DIRECTORY_PASS lines="<<DCACHE_CAPACITY<<" stride="<<stride
                 <<" seed="<<seed<<" cycles="<<conflict.cycle<<" dirty_eviction=1 upper_way_probe=1 victim_reload=1\n";
    }
#endif
    for(unsigned seed:{17U,31U,919U}) {
        Test t(seed);
        std::array<uint8_t,8> stale{}; std::copy_n(t.memory.begin()+4096,8,stale.begin());
        uint64_t dirty=0x1029384756abcdefULL;
        t.cpuAccess(ram+4096,true,dirty);
        check(std::equal(stale.begin(),stale.end(),t.memory.begin()+4096),"missing dirty-cache witness");
        check(t.cpuAccess(ram+4096)==dirty,"CPU dirty store mismatch");
        t.startTx(ram+4096,8); t.finish(false,false,true,false);
        std::vector<uint8_t> expected; for(unsigned b=0;b<8;++b) expected.push_back(dirty>>(8*b));
        if(argc>1) expected[0]^=1;
        check(t.dataOut==expected,"TX independent byte oracle mismatch");
        t.cpuAccess(ram+256,true,0xffffffffffffffffULL); // RX must invalidate this dirty cached line
        t.cpuAccess(ram+264,true,0x8877665544332211ULL);
        t.armRx(ram+256,13); t.supply(13); t.finish(false,false,false,true);
        uint64_t low=0,high=0; for(unsigned b=0;b<8;++b) low|=uint64_t(uint8_t(b*13+7))<<(8*b);
        for(unsigned b=0;b<5;++b) high|=uint64_t(uint8_t((b+8)*13+7))<<(8*b);
        high|=0x8877660000000000ULL;
        check(t.cpuAccess(ram+256)==low&&t.cpuAccess(ram+264)==high,"RX coherent cache/tail oracle mismatch");
        std::cout<<"ETHERNET_DMA_COHERENCE_PASS seed="<<seed<<" cycles="<<t.cycle<<" dirty_tx_probe=1 dirty_rx_invalidate=1\n";
    }
#else
    unsigned cases=0,peak=0,stalls=0;
    for(unsigned seed:{3U,17U,919U}) for(unsigned order:{0U,1U,2U})
        for(unsigned length:{1U,2U,3U,4U,5U,6U,7U,8U,9U,60U,64U,1514U,1518U,2047U,2048U}) {
            Test t(seed,argc>1); t.latency=3+seed%19;
            auto expected=t.memory;
            std::vector<uint8_t> txExpected(expected.begin()+4096,expected.begin()+4096+length);
            if(t.inject) txExpected[0]^=1;
            for(unsigned i=0;i<length;++i) expected[256+i]=i*13+7;
            t.access(8,true,3); t.armRx(ram+256,length);
            t.dataDelay=t.cycle+(order==1?200:0); t.statusDelay=t.cycle+(order==2?300:0);
            t.supply(length); t.startTx(ram+4096,length); t.finish();
            if(t.memory!=expected) {
                std::cerr<<"CASE seed="<<seed<<" order="<<order<<" length="<<length<<"\n";
                for(unsigned i=0,n=0;i<expected.size()&&n<8;++i) if(t.memory[i]!=expected[i]) {
                    std::cerr<<"BYTE "<<i<<" got="<<unsigned(t.memory[i])<<" expected="<<unsigned(expected[i])<<"\n"; ++n;
                }
            }
            check(t.memory==expected,"RX independent byte oracle mismatch");
            check(t.dataOut==txExpected,"TX independent byte oracle mismatch");
            check(t.reads==(length+7)/8&&t.writes==(length+7)/8,
                "DMA memory beat count mismatch");
            check(t.access(80)==length&&t.access(128)==length,"RX status length mismatch");
            check(t.G(irq),"completion interrupt missing");
            t.access(32,true,2); check(t.G(irq),"RX interrupt lost when TX acknowledged");
            t.access(64,true,2); check(!t.G(irq),"completion interrupt did not clear");
            peak=std::max(peak,t.peak); stalls+=t.txStalls+t.memoryStalls; ++cases;
        }
    for(unsigned mode=1;mode<=7;++mode) {
        Test t(31); auto before=t.memory; t.armRx(ram+256,mode==7?32:128); t.supply(63,mode);
        t.finish(false,true,false,true);
        check(t.writes==0&&t.memory==before,"bad frame modified memory"); ++cases;
    }
    for(unsigned index:{0U,2U,7U}) {
        Test t(43); t.failRead=index; t.startTx(ram+4096,128); t.finish(true,false,true,false);
        check(t.dataOut.empty()&&t.controls.empty(),"TX read fault emitted partial frame");
        t.failRead=-1; t.startTx(ram+4096,128); t.finish(false,false,true,false);
        check(t.dataOut==std::vector<uint8_t>(t.memory.begin()+4096,t.memory.begin()+4224),"TX fault restart failed"); ++cases;
        Test r(71); r.failWrite=index; r.armRx(ram+256,128); r.supply(128); r.finish(false,true,false,true); ++cases;
    }
    for(auto descriptor:{std::array<uint64_t,2>{ram+1,64},{ram,0},{ram,2049},
        {ram+DMA_RAM_BYTES-8,9},{0xfffffffffffffff8ULL,16},{0x80010000ULL,64}}) {
        Test t(83); t.startTx(descriptor[0],descriptor[1]); t.finish(true,false,true,false);
        t.armRx(descriptor[0],descriptor[1]); t.finish(false,true,false,true);
        check(t.requests==0,"invalid descriptor had memory side effects"); ++cases;
    }
    Test t(113); check(t.access(0)==0x56444d4100010001ULL&&t.access(136)==2048,"DMA version/capability mismatch");
    t.access(40,true,0,true); t.access(TX_POSTED_SLOTS?248:224,TX_POSTED_SLOTS!=0,0,true); t.access(16,true,0,true,2); t.access(16,true,0,true,3,15);
    t.armRx(ram+256,64); t.access(48,true,ram,true); t.access(64,true,3,true); t.supply(64); t.finish(false,false,false,true);
    t.access(64,true,1,true); // cannot overwrite unacknowledged completion
    unsigned stopped=0;
    for(unsigned scenario:{0U,1U,2U,3U}) {
        Test s(170+scenario); auto before=s.memory;
        check((s.access(152)&1)==1,"RX stop capability missing");
        s.access(144,true,0,true); s.access(144,true,3,true);
        s.armRx(ram+256,128);
        if(scenario) {
            s.supply(128);
            if(scenario==1) s.statusDelay=s.cycle+200;
            if(scenario==2) s.dataDelay=s.cycle+200;
            if(scenario==3) { while(s.writes==0) s.tick(); }
            else { while(s.dataAccepted+s.statusAccepted==0) s.tick(); }
        }
        s.access(144,true,1); s.finish(false,true,false,true);
        if(scenario!=3) check(s.memory==before && s.writes==0,"RX stop before commit modified DDR");
        check(s.dataIn.empty()&&s.statusIn.empty(),"RX stop did not drain stream boundaries");
        s.access(64,true,2); check(!s.G(active),"RX stop left DMA active");
        s.armRx(ram+512,13); s.supply(13); s.finish(false,false,false,true);
        for(unsigned b=0;b<13;++b) check(s.memory[512+b]==uint8_t(b*13+7),"RX restart after stop mismatch");
        ++stopped;
    }
    check(peak==DMA_MEMORY_CREDITS&&stalls>0,"missing outstanding/backpressure coverage");
    std::cout<<"ETHERNET_PACKET_DMA_PASS cases="<<cases<<" maxOutstanding="<<peak<<" stalls="<<stalls<<" safe_rx_stop="<<stopped<<"\n";
#endif
} catch(const std::exception &e) { std::cerr<<"ETHERNET_PACKET_DMA_FAIL "<<e.what()<<"\n"; return 1; } }
