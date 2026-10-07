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
#define S(n,v) d.set_io$$##n(v)
#define G(n) d.get_io$$##n()
static void check(bool v, const char *m) { if (!v) throw std::runtime_error(m); }
static constexpr uint64_t ram = 0x80200000ULL, regs = 0x10002000ULL;
struct Beat { uint32_t data; unsigned keep; bool last; };
struct Reply { unsigned due; uint64_t address, data; unsigned mask; bool write, error; };
struct Test {
    DmaModel d;
    std::array<uint8_t,8192> memory{};
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
    bool inject=false, requireCompleteRx=true;
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
        bool ready=rng()%4!=0, valid=!replies.empty() && replies.front().due<=cycle;
        S(memory$$request$$ready,ready); S(memory$$response$$valid,valid);
        S(memory$$response$$bits$$data,valid?replies.front().data:0);
        S(memory$$response$$bits$$error,valid?replies.front().error:0);
        bool txReady=cycle%23>=7 && rng()%3!=0, ctrlReady=cycle%17>=5 && rng()%3!=0;
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
            check(replies.size()<=4,"DMA credit overflow");
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
#ifdef COHERENT_DMA
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
        {ram+8184,9},{0xfffffffffffffff8ULL,16},{0x80010000ULL,64}}) {
        Test t(83); t.startTx(descriptor[0],descriptor[1]); t.finish(true,false,true,false);
        t.armRx(descriptor[0],descriptor[1]); t.finish(false,true,false,true);
        check(t.requests==0,"invalid descriptor had memory side effects"); ++cases;
    }
    Test t(113); check(t.access(0)==0x56444d4100010001ULL&&t.access(136)==2048,"DMA version/capability mismatch");
    t.access(40,true,0,true); t.access(160,false,0,true); t.access(16,true,0,true,2); t.access(16,true,0,true,3,15);
    t.armRx(ram+256,64); t.access(48,true,ram,true); t.access(64,true,3,true); t.supply(64); t.finish(false,false,false,true);
    t.access(64,true,1,true); // cannot overwrite unacknowledged completion
    unsigned stopped=0;
    for(unsigned scenario:{0U,1U,2U,3U}) {
        Test s(170+scenario); auto before=s.memory;
        check(s.access(152)==1,"RX stop capability missing");
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
    check(peak==4&&stalls>0,"missing outstanding/backpressure coverage");
    std::cout<<"ETHERNET_PACKET_DMA_PASS cases="<<cases<<" maxOutstanding="<<peak<<" stalls="<<stalls<<" safe_rx_stop="<<stopped<<"\n";
#endif
} catch(const std::exception &e) { std::cerr<<"ETHERNET_PACKET_DMA_FAIL "<<e.what()<<"\n"; return 1; } }
