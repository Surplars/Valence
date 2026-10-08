#include "SelfGmacFramesGsim.h"
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
static void check(bool ok,const char*msg){if(!ok)throw std::runtime_error(msg);}
struct Test {
    SSelfGmacFramesGsim d;
    std::mt19937 random{0x10467};
    std::vector<uint8_t> burst,received;
    std::vector<std::vector<uint8_t>> wires;
    std::deque<std::vector<uint8_t>> expectedRx;
    std::optional<std::tuple<uint32_t,unsigned,bool,bool>> held;
    unsigned ticks=0,txDone=0,txRejected=0,rxAccepted=0,rxDropped=0,badFcs=0,rxComplete=0;
    unsigned txStalls=0,rxStalls=0,concurrent=0,idles=100,lastWireEnd=0;
    bool ready=true,randomReady=true,hadFrame=false,rxDriving=false;
    Test(){
        S(txFrame$$valid,0);S(txFrame$$bits$$data,0);S(txFrame$$bits$$keep,15);
        S(txFrame$$bits$$last,0);S(txFrame$$bits$$bad,0);
        S(txEnable,1);S(rxEnable,1);S(promiscuous,0);S(broadcastEnable,1);S(macAddress,0x021122334455ULL);
        S(gmiiRxValid,0);S(gmiiRxError,0);S(gmiiRxData,0);S(rxFrame$$ready,1);
        d.set_reset(1);d.step();d.step();d.set_reset(0);tick();
    }
    void tick(){
        const bool take=ready && (!randomReady || random()%4!=0);
        S(rxFrame$$ready,take);d.step();++ticks;
        check(!G(gmiiTxError),"unexpected GMII TX_ER");
        if(G(gmiiTxEnable)){
            if(burst.empty())check(idles>=12,"GMII IFG independent oracle mismatch");
            burst.push_back(G(gmiiTxData));idles=0;hadFrame=true;
            concurrent+=rxDriving;
        }else{
            if(!burst.empty()){wires.push_back(burst);burst.clear();lastWireEnd=ticks;}
            ++idles;
        }
        txDone+=G(txDone);txRejected+=G(txRejected);rxAccepted+=G(rxAccepted);
        rxDropped+=G(rxDropped);badFcs+=G(rxBadFcs);
        if(G(txDone))check(G(txBytes)>=60 && G(txBytes)<=2048,"TX event byte count invalid");
        if(G(rxAccepted))check(!expectedRx.empty() && G(rxBytes)==expectedRx.back().size(),
            "RX accepted byte count mismatch");
        if(G(rxFrame$$valid)){
            const auto actual=std::make_tuple(uint32_t(G(rxFrame$$bits$$data)),unsigned(G(rxFrame$$bits$$keep)),
                bool(G(rxFrame$$bits$$last)),bool(G(rxFrame$$bits$$bad)));
            if(held)check(actual==*held,"RX frame changed under backpressure");
            held=take?std::nullopt:std::optional{actual};rxStalls+=!take;
            if(take){
                auto [data,keep,last,bad]=actual;
                check(!expectedRx.empty()&&!bad,"bad/unexpected frame escaped RX buffer");
                check(keep==1||keep==3||keep==7||keep==15,"RX sparse keep");
                check(last||keep==15,"RX non-final partial keep");
                for(unsigned b=0;b<4;++b)if(keep&(1U<<b))received.push_back(data>>(8*b));
                if(last){
                    check(received==expectedRx.front(),"GMII RX independent byte oracle mismatch");
                    expectedRx.pop_front();received.clear();++rxComplete;
                }
            }
        }else{check(!held,"RX withdrew a stalled frame");held.reset();}
    }
    void rxValid(bool value){rxDriving=value;S(gmiiRxValid,value);}
    void idle(unsigned n=20){rxValid(false);S(gmiiRxError,0);for(unsigned i=0;i<n;++i)tick();}
    void drain(){
        for(unsigned n=0;n<10000&&(G(txBusy)||G(rxBusy)||!expectedRx.empty()||!burst.empty());++n)tick();
        check(!G(txBusy)&&!G(rxBusy)&&expectedRx.empty()&&burst.empty(),"frame engines failed to drain");idle();
    }
    void transmit(const std::vector<uint8_t>&body,unsigned mode=0){
        const unsigned before=wires.size(),reject=txRejected;
        for(unsigned i=0;i<body.size();i+=4){
            const unsigned count=std::min(4U,unsigned(body.size()-i));uint32_t word=0;
            for(unsigned n=0;n<count;++n)word|=uint32_t(body[i+n])<<(8*n);
            S(txFrame$$bits$$data,word);S(txFrame$$bits$$keep,mode==1&&i==0?5:(1U<<count)-1);
            S(txFrame$$bits$$last,i+count==body.size());S(txFrame$$bits$$bad,mode==2&&i+count==body.size());
            S(txFrame$$valid,1);unsigned n=0;
            do{tick();check(++n<10000,"TX native input timeout");}while(!G(txFrame$$ready));
            if(i+count<body.size())check(wires.size()==before&&burst.empty(),"TX emitted before complete frame");
            S(txFrame$$valid,0);idle(random()%5);
        }
        drain();
        if(mode||body.size()<14||body.size()>2048){
            check(wires.size()==before && txRejected==reject+1,"TX malformed frame was not atomically rejected");
        }else check(wires.size()==before+1 && wires.back()==ethernetWire(body),"GMII TX independent wire oracle mismatch");
    }
    void receive(std::vector<uint8_t> body,unsigned mode=0,bool good=true){
        if(body.size()<60 && mode!=3)body.resize(60,0);
        auto wire=ethernetWire(body,false);
        if(mode==1)wire.back()^=1;
        if(mode==4)wire[0]=0x54;
        const unsigned accepted=rxAccepted,dropped=rxDropped;
        if(good)expectedRx.push_back(body);
        for(unsigned i=0;i<wire.size();++i){
            rxValid(true);S(gmiiRxData,wire[i]);S(gmiiRxError,mode==2&&i==19);tick();
        }
        idle(2);drain();
        check(rxAccepted==accepted+good && rxDropped==dropped+!good,"RX whole-frame verdict mismatch");
    }
};
#ifndef RX_FRAME_SLOTS
#define RX_FRAME_SLOTS 4
#endif
int main(int argc,char**argv){try{
    bool inject=argc==2&&std::string_view(argv[1])=="--inject-mismatch";
    Test t;unsigned cases=0;
    check(ethernetReferenceCrc({'1','2','3','4','5','6','7','8','9'})==0xcbf43926,"independent CRC golden vector wrong");
    for(unsigned length:{14U,15U,16U,59U,60U,61U,62U,63U,64U,65U,127U,1514U,1518U,2047U,2048U}){
        auto body=ethernetBody(length,cases);t.transmit(body);++cases;
        if(inject){auto expected=ethernetWire(body);expected.back()^=1;
            check(t.wires.back()==expected,"GMII TX independent wire oracle mismatch");}
        t.receive(body);++cases;
    }
    for(unsigned n=0;n<96;++n){auto b=ethernetBody(60+t.random()%1989,n);t.transmit(b);t.receive(b);cases+=2;}
    t.transmit(ethernetBody(13));t.transmit(ethernetBody(2049));
    t.transmit(ethernetBody(64),1);t.transmit(ethernetBody(64),2);cases+=4;
    t.receive(ethernetBody(64),1,false);t.receive(ethernetBody(64),2,false);
    t.receive(ethernetBody(14),3,false);t.receive(ethernetBody(64),4,false);
    t.receive(ethernetBody(2049),0,false);cases+=5;
    auto other=ethernetBody(100);other[0]=0x22;t.receive(other,0,false);
    t.S(promiscuous,1);t.receive(other);t.S(promiscuous,0);cases+=2;
    auto bc=ethernetBody(128);std::fill_n(bc.begin(),6,255);t.receive(bc);
    t.S(broadcastEnable,0);t.receive(bc,0,false);t.S(broadcastEnable,1);cases+=2;
    t.S(rxEnable,0);t.receive(ethernetBody(64),0,false);t.S(rxEnable,1);++cases;
    auto lengthFrame=ethernetBody(60);lengthFrame[12]=0;lengthFrame[13]=8;t.receive(lengthFrame);
    lengthFrame[13]=80;t.receive(lengthFrame,0,false);lengthFrame[12]=5;lengthFrame[13]=255;
    t.receive(lengthFrame,0,false);cases+=3;
    // Selected retained banks tolerate a bounded burst; the next two
    // frames are wholly discarded without changing any of the retained bytes.
    t.ready=false;t.randomReady=false;
    const unsigned dropped=t.rxDropped,accepted=t.rxAccepted;
    for(unsigned n=0;n<RX_FRAME_SLOTS+2;++n){auto body=ethernetBody(127+n*7,777+n);
        if(n<RX_FRAME_SLOTS)t.expectedRx.push_back(body);
        auto next=ethernetWire(body);
        for(unsigned i=0;i<next.size();++i){t.rxValid(true);t.S(gmiiRxData,next[i]);
            if(n==RX_FRAME_SLOTS+1 && i==20)t.ready=true; // freed bank must not re-admit this physical tail
            t.tick();}t.idle(12);}
    check(t.rxAccepted==accepted+RX_FRAME_SLOTS&&t.rxDropped==dropped+2,"bounded RX bank admission mismatch");
    t.ready=true;t.drain();cases+=RX_FRAME_SLOTS+2;
    // Reuse wrapped banks after retirement; no old payload may reappear.
    for(unsigned n=0;n<6;++n){t.receive(ethernetBody(65+n,991+n));++cases;}
    std::vector<uint8_t> wire;
    t.randomReady=true;
    // Simultaneous TX packet input and uninterrupted PHY RX.
    auto both=ethernetBody(512,888);wire=ethernetWire(both);t.expectedRx.push_back(both);
    unsigned wi=0,ti=0;const unsigned before=t.wires.size();
    for(unsigned n=0;n<10000&&(wi<wire.size()||ti<both.size());++n){
        t.rxValid(wi<wire.size());t.S(gmiiRxData,wi<wire.size()?wire[wi]:0);
        uint32_t word=0;for(unsigned b=0;b<4&&ti+b<both.size();++b)word|=uint32_t(both[ti+b])<<(8*b);
        t.S(txFrame$$valid,ti<both.size());t.S(txFrame$$bits$$data,word);t.S(txFrame$$bits$$keep,15);
        t.S(txFrame$$bits$$last,ti+4==both.size());t.S(txFrame$$bits$$bad,0);t.tick();
        if(wi<wire.size())++wi;if(ti<both.size()&&t.G(txFrame$$ready))ti+=4;
    }
    t.S(txFrame$$valid,0);t.rxValid(false);t.drain();
    check(t.wires.size()==before+1&&t.wires.back()==wire&&t.concurrent>0,"full-duplex independent oracle mismatch");++cases;
    // Reset cancels partially collected TX and mid-wire RX; held DV on release
    // must be discarded until EOF, then the next clean frame must work.
    auto canceled=ethernetWire(ethernetBody(256));
    for(unsigned i=0;i<60;++i){t.rxValid(true);t.S(gmiiRxData,canceled[i]);t.tick();}
    t.S(txFrame$$valid,1);t.S(txFrame$$bits$$last,0);t.tick();t.S(txFrame$$valid,0);
    t.d.set_reset(1);t.d.step();t.d.step();t.d.set_reset(0);
    t.held.reset();t.received.clear();t.expectedRx.clear();t.burst.clear();t.idles=100;
    const unsigned a=t.rxAccepted,drop=t.rxDropped;
    for(unsigned i=60;i<canceled.size();++i){t.rxValid(true);t.S(gmiiRxData,canceled[i]);t.tick();}
    t.idle();check(t.rxAccepted==a&&t.rxDropped==drop,"reset-canceled RX leaked data/event");
    t.transmit(ethernetBody(65));t.receive(ethernetBody(65));cases+=3;
    check(t.rxStalls>0&&t.txDone==t.wires.size()&&t.badFcs>0,"missing frame coverage");
    std::cout<<"SELF_GMAC_FRAMES_PASS cases="<<cases<<" tx_wire_frames="<<t.wires.size()
        <<" rx_frames="<<t.rxComplete<<" rx_drops="<<t.rxDropped<<" rx_stalls="<<t.rxStalls
        <<" simultaneous_byte_cycles="<<t.concurrent<<" reset_cancel=1\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
