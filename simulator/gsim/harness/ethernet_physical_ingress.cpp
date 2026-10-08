#include "EthernetIngressGsim.h"
#include "gmii_reference.h"
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
struct Test{
    SEthernetIngressGsim d;std::mt19937 random{0xc1c2026};
    std::deque<std::vector<uint8_t>> expected;std::vector<uint8_t> received;
    std::optional<std::tuple<unsigned,unsigned,bool>> held;
    unsigned cycles=0,accepted=0,dropped=0,complete=0,overflow=0,skipped=0,stalls=0,erroredBytes=0;
    bool ready=true,randomReady=true;
    Test(){S(data,0);S(valid,0);S(error,0);S(byteStep,1);S(captureEnable,1);S(stall,0);S(epochReset,0);S(frame$$ready,1);d.set_reset(1);d.step();d.step();d.set_reset(0);idle(16);}
    void tick(){bool take=ready&&(!randomReady||random()%4!=0);S(frame$$ready,take);d.step();++cycles;accepted+=G(accepted);dropped+=G(dropped);overflow+=G(overflow);skipped+=G(skipped);erroredBytes+=G(outStep)&&G(outValid)&&G(outError);
        if(G(frame$$valid)){auto got=std::make_tuple(unsigned(G(frame$$bits$$data)),unsigned(G(frame$$bits$$keep)),bool(G(frame$$bits$$last)));
            if(held)check(got==*held,"physical ingress RX owner changed under backpressure");held=take?std::nullopt:std::optional{got};stalls+=!take;
            if(take){check(!expected.empty()&&!G(frame$$bits$$bad),"physical ingress leaked a discarded/old-epoch frame");auto [data,keep,last]=got;
                for(unsigned n=0;n<4;++n)if(keep&(1U<<n))received.push_back(data>>(8*n));
                if(last){check(received==expected.front(),"physical ingress independent frame oracle mismatch");received.clear();expected.pop_front();++complete;}
            }
        }else{check(!held,"physical ingress withdrew a stalled owner");held.reset();}
    }
    void idle(unsigned n=16){S(valid,0);S(error,0);S(byteStep,1);while(n--)tick();}
    void send(const std::vector<uint8_t>&bytes,unsigned factor=1,unsigned badIndex=0xffffffff){
        for(unsigned n=0;n<bytes.size();++n){S(data,bytes[n]);S(valid,1);S(error,n==badIndex);S(byteStep,1);tick();S(byteStep,0);for(unsigned i=1;i<factor;++i)tick();}
        idle(16);
    }
    void drain(){idle(64);for(unsigned n=0;n<30000&&(!expected.empty()||!G(idle));++n)tick();check(expected.empty()&&G(idle),"physical ingress failed to drain");idle(16);}
    void good(unsigned length,unsigned seed,unsigned factor=1){auto body=ethernetBody(length,seed);if(body.size()<60)body.resize(60,0);expected.push_back(body);send(ethernetWire(body),factor);drain();}
};
int main(int argc,char**argv){try{
    bool inject=argc==2&&std::string_view(argv[1])=="--inject-mismatch";Test t;unsigned cases=0;
    if(inject){auto body=ethernetBody(60);t.expected.push_back(body);t.expected.back()[17]^=1;t.send(ethernetWire(body));t.drain();}
    for(unsigned rate:{1U,2U,10U})for(unsigned length:{14U,60U,61U,62U,63U,64U,1518U,2047U,2048U}){t.good(length,++cases,rate);}
    for(unsigned n=0;n<64;++n){t.good(60+t.random()%1989,100+n,1+t.random()%3);++cases;}
    const unsigned before=t.complete,bad=t.dropped;
    auto crc=ethernetWire(ethernetBody(100));crc.back()^=1;t.send(crc);t.drain();
    t.send(ethernetWire(ethernetBody(100)),1,23);t.drain();
    t.send({0x55,0x55,0xd5,0,0,0,0});t.drain();
    check(t.complete==before&&t.dropped==bad+3,"physical ingress corrupted/truncated frame was accepted");cases+=3;
    // Full token channel: prefix must be poisoned, then an entirely skipped
    // second frame must not become the first frame's tail after service resumes.
    const unsigned ov=t.overflow,skip=t.skipped,drops=t.dropped;
    t.S(stall,1);t.send(ethernetWire(ethernetBody(2048,919)));t.send(ethernetWire(ethernetBody(127,920)));
    t.S(stall,0);t.drain();check(t.overflow==ov+2&&t.skipped==skip+1&&t.dropped==drops+1,"physical FIFO overflow whole-frame accounting mismatch");
    check(t.complete==before,"physical FIFO overflow leaked a frame");t.good(149,921);cases+=3;
    // Complete banks survive an ingress epoch reset and drain on the fixed
    // clock even while no new physical samples arrive. This is logical clock-
    // enable evidence; true independent-clock/reset proof is the native bench.
    t.ready=false;t.randomReady=false;const unsigned retained=t.complete;
    for(unsigned n=0;n<3;++n){auto body=ethernetBody(127+n*7,1100+n);t.expected.push_back(body);t.send(ethernetWire(body));}
    check(t.accepted>=retained+3,"retained-bank setup failed");
    auto partial=ethernetWire(ethernetBody(512,1188));
    for(unsigned n=0;n<50;++n){t.S(valid,1);t.S(data,partial[n]);t.S(byteStep,1);t.tick();}
    t.S(byteStep,0);t.S(epochReset,1);t.S(captureEnable,0);for(unsigned n=0;n<4;++n)t.tick();t.S(epochReset,0);
    t.ready=true;for(unsigned n=0;n<2000&&!t.expected.empty();++n)t.tick();
    check(t.expected.empty()&&t.complete==retained+3,"completed RX bank ownership depended on physical sample progress");
    // Re-enable inside an already-active wire frame containing an apparent
    // complete preamble/SFD/FCS. It must wait for real physical idle.
    t.S(captureEnable,1);auto falseSop=ethernetWire(ethernetBody(85,1200));const unsigned old=t.complete;
    for(auto byte:falseSop){t.S(valid,1);t.S(data,byte);t.S(byteStep,1);t.tick();}t.idle(30);t.drain();
    check(t.complete==old,"ingress reset accepted an embedded mid-frame SFD");
    t.good(81,1201);cases+=5;
    check(t.overflow>=2&&t.skipped>=1&&t.erroredBytes>0&&t.stalls>1000,"physical ingress tests lacked adverse witnesses");
    std::cout<<"PHYSICAL_INGRESS_FUNCTIONAL_PASS cases="<<cases<<" cycles="<<t.cycles<<" accepted="<<t.accepted<<" completed="<<t.complete<<" parser_drops="<<t.dropped<<" physical_overflow_frames="<<t.overflow<<" wholly_skipped="<<t.skipped<<" retained_banks=3 stalled_raw_samples=1 embedded_sfd_rejected=1 independent_clock_proof=0\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
