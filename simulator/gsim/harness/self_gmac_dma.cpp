#include "SelfGmacDmaGsim.h"
#include "gmii_reference.h"
#include <array>
#include <deque>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>
#include <string_view>
#include <tuple>
#define S(n,v) d.set_io$$##n(v)
#define G(n) d.get_io$$##n()
static void check(bool ok,const char*why){if(!ok)throw std::runtime_error(why);}
static constexpr uint64_t ram=0x80200000,regs=0x10002000;
struct Reply{unsigned due;uint64_t address,data;unsigned mask;bool write,error;};
struct Test{
    SSelfGmacDmaGsim d;
    std::array<uint8_t,8192> memory{};
    std::deque<Reply> replies;
    std::deque<uint8_t> incoming;
    std::vector<uint8_t> burst;
    std::vector<std::vector<uint8_t>> wires;
    std::optional<std::tuple<uint64_t,uint64_t,unsigned,unsigned,bool>> held;
    std::mt19937 random;
    unsigned cycles=0,reads=0,writes=0,peak=0,stalls=0,drops=0,accepted=0,rejected=0,simultaneous=0;
    int failRead=-1,failWrite=-1;
    Test(unsigned seed):random(seed){
        for(auto&b:memory)b=random();
        S(control$$request$$valid,0);S(control$$response$$ready,0);
        S(control$$request$$bits$$address,regs);S(control$$request$$bits$$data,0);
        S(control$$request$$bits$$write,0);S(control$$request$$bits$$size,3);
        S(control$$request$$bits$$byteEnable,255);
        S(gmiiRxValid,0);S(gmiiRxError,0);S(gmiiRxData,0);
        S(memory$$request$$ready,0);S(memory$$response$$valid,0);
        S(memory$$response$$bits$$data,0);S(memory$$response$$bits$$error,0);
        d.set_reset(1);d.step();d.step();d.set_reset(0);tick();
    }
    void tick(){
        const bool ready=random()%4!=0,valid=!replies.empty()&&replies.front().due<=cycles;
        S(memory$$request$$ready,ready);S(memory$$response$$valid,valid);
        S(memory$$response$$bits$$data,valid?replies.front().data:0);
        S(memory$$response$$bits$$error,valid?replies.front().error:false);
        S(gmiiRxValid,!incoming.empty());S(gmiiRxData,incoming.empty()?0:incoming.front());
        d.step();++cycles;
        if(valid&&G(memory$$response$$ready)){
            Reply r=replies.front();replies.pop_front();
            if(r.write&&!r.error)for(unsigned n=0;n<8;++n)if(r.mask&(1U<<n))memory.at(r.address-ram+n)=r.data>>(8*n);
        }
        auto offer=std::make_tuple(uint64_t(G(memory$$request$$bits$$address)),uint64_t(G(memory$$request$$bits$$data)),
            unsigned(G(memory$$request$$bits$$byteEnable)),unsigned(G(memory$$request$$bits$$size)),bool(G(memory$$request$$bits$$write)));
        if(held)check(G(memory$$request$$valid)&&offer==*held,"GMAC DMA changed stalled memory request");
        held=G(memory$$request$$valid)&&!ready?std::optional{offer}:std::nullopt;stalls+=bool(held);
        if(G(memory$$request$$valid)&&ready){
            auto [address,data,mask,size,write]=offer;
            check(size==3&&address>=ram&&address+8<=ram+8192&&!(address&7)&&mask<=255,
                "GMAC DMA address/mask outside independent memory model");
            uint64_t value=0;if(!write)for(unsigned n=0;n<8;++n)value|=uint64_t(memory[address-ram+n])<<(8*n);
            const bool error=write?int(writes)==failWrite:int(reads)==failRead;
            if(write)check(incoming.empty(),"GMAC DMA wrote before physical EOF/FCS validation");
            if(!write)check(mask==255,"GMAC TX used partial memory read");
            write?++writes:++reads;
            replies.push_back({cycles+7+unsigned(random()%6),address,write?data:value,mask,write,error});
            peak=std::max(peak,unsigned(replies.size()));check(peak<=4,"GMAC DMA exceeded four memory credits");
        }
        if(G(gmiiTxEnable)){burst.push_back(G(gmiiTxData));simultaneous+=!incoming.empty();}
        else if(!burst.empty()){wires.push_back(burst);burst.clear();}
        check(!G(gmiiTxError),"GMAC DMA unexpectedly emitted TX_ER");
        drops+=G(rxDropped);accepted+=G(rxAccepted);rejected+=G(txRejected);
        if(!incoming.empty())incoming.pop_front();
    }
    uint64_t access(unsigned off,bool write=false,uint64_t value=0){
        S(control$$request$$bits$$address,regs+off);S(control$$request$$bits$$write,write);
        S(control$$request$$bits$$data,value);S(control$$request$$valid,1);
        unsigned limit=cycles+10000;
        do{tick();check(cycles<limit,"GMAC DMA MMIO request timeout");}while(!G(control$$request$$ready));
        S(control$$request$$valid,0);
        do{tick();check(cycles<limit,"GMAC DMA MMIO response timeout");}while(!G(control$$response$$valid));
        check(!G(control$$response$$bits$$error),"GMAC DMA unexpected MMIO error");
        const uint64_t result=G(control$$response$$bits$$data);
        for(unsigned n=0;n<3;++n){tick();check(G(control$$response$$valid)&&G(control$$response$$bits$$data)==result,
            "GMAC DMA MMIO response changed under backpressure");}
        S(control$$response$$ready,1);tick();S(control$$response$$ready,0);return result;
    }
    void startTx(unsigned length){access(16,true,ram+4096);access(24,true,length);access(32,true,3);}
    void startRx(unsigned capacity){access(48,true,ram+256);access(56,true,capacity);access(64,true,3);}
    void supply(const std::vector<uint8_t>&wire){check(incoming.empty(),"overlapping reference RX");incoming.insert(incoming.end(),wire.begin(),wire.end());}
    void finish(bool tx=true,bool rx=true,bool txError=false,bool rxError=false){
        unsigned limit=cycles+50000;
        while((tx&&(access(40)&1))||(rx&&(access(72)&1))||G(txBusy)||!incoming.empty()||!burst.empty())
            {tick();check(cycles<limit,"GMAC DMA completion timeout");}
        if(tx)check(access(40)==(txError?6:2),"GMAC TX DMA completion mismatch");
        if(rx)check(access(72)==(rxError?6:2),"GMAC RX DMA completion mismatch");
        check(replies.empty()&&!held,"GMAC DMA completed before memory drain");
    }
};
int main(int argc,char**argv){try{
    const bool inject=argc==2&&std::string_view(argv[1])=="--inject-mismatch";
    unsigned cases=0,peak=0,stalls=0,simultaneous=0;
    for(unsigned seed:{3U,17U,919U})for(unsigned length:{14U,15U,16U,59U,60U,61U,62U,63U,64U,65U,127U,1514U,1518U,2047U,2048U}){
        Test t(seed);auto body=ethernetBody(length,seed);std::copy(body.begin(),body.end(),t.memory.begin()+4096);
        auto expected=t.memory;auto rxBody=ethernetBody(length,seed+7);rxBody.resize(std::max(60U,length),0);
        std::copy(rxBody.begin(),rxBody.end(),expected.begin()+256);
        t.access(8,true,3);t.startRx(rxBody.size());t.startTx(length);t.supply(ethernetWire(rxBody));t.finish();
        auto wire=ethernetWire(body);if(inject&&cases==0)wire.back()^=1;
        check(t.wires.size()==1&&t.wires.front()==wire,"GMAC DMA independent TX wire oracle mismatch");
        check(t.memory==expected,"GMAC DMA independent RX memory oracle mismatch");
        check(t.reads==(length+7)/8&&t.writes==(rxBody.size()+7)/8&&t.accepted==1&&!t.drops,
            "GMAC DMA beat count/receive verdict mismatch");
        check(t.access(80)==rxBody.size()&&t.access(128)==rxBody.size(),"GMAC adapter APP4 length mismatch");
        check(t.G(irq),"GMAC DMA IRQ missing");t.access(32,true,2);check(t.G(irq),"GMAC RX IRQ lost");
        t.access(64,true,2);check(!t.G(irq),"GMAC DMA IRQ did not clear");
        peak=std::max(peak,t.peak);stalls+=t.stalls;simultaneous+=t.simultaneous;++cases;
    }
    // Corrupt physical frame must not write memory or finish the armed DMA;
    // the following good frame must work without rearming/resetting.
    Test bad(31);auto before=bad.memory;bad.startRx(128);auto body=ethernetBody(63);auto wire=ethernetWire(body);
    wire.back()^=1;bad.supply(wire);while(!bad.incoming.empty())bad.tick();for(unsigned n=0;n<100;++n)bad.tick();
    check(bad.memory==before&&bad.writes==0&&bad.access(72)==1&&bad.drops==1,
        "GMAC bad FCS escaped into armed DMA");
    bad.supply(ethernetWire(body));bad.finish(false,true);++cases;
    for(unsigned fault:{0U,2U,7U}){
        Test tx(43);tx.failRead=fault;auto b=ethernetBody(128);std::copy(b.begin(),b.end(),tx.memory.begin()+4096);
        tx.startTx(128);tx.finish(true,false,true,false);check(tx.wires.empty()&&!tx.rejected,"GMAC read fault emitted a frame");
        tx.failRead=-1;tx.startTx(128);tx.finish(true,false);
        check(tx.wires.size()==1&&tx.wires.front()==ethernetWire(b),"GMAC DMA read-fault restart mismatch");++cases;
        Test rx(71);rx.failWrite=fault;rx.startRx(128);rx.supply(ethernetWire(ethernetBody(128)));rx.finish(false,true,false,true);++cases;
    }
    Test small(53);before=small.memory;small.startRx(32);small.supply(ethernetWire(ethernetBody(64)));
    small.finish(false,true,false,true);check(small.memory==before&&!small.writes,"RX capacity error wrote memory");++cases;
    Test shortTx(61);shortTx.startTx(13);shortTx.finish(true,false);
    check(shortTx.wires.empty()&&shortTx.rejected==1,"short header did not reach MAC rejection event");++cases;
    check(peak==4&&stalls&&simultaneous,"GMAC DMA outstanding/backpressure/full-duplex coverage incomplete");
    std::cout<<"SELF_GMAC_DMA_PASS cases="<<cases<<" maxOutstanding="<<peak<<" memory_stalls="<<stalls
        <<" simultaneous_byte_cycles="<<simultaneous<<" bad_fcs_no_write=1 tail_masks=1\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
