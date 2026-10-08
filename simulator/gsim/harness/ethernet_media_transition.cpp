#include "EthernetMediaTransition.h"
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>
#include <string_view>
#define S(n,v) d.set_io$$##n(v)
#define G(n) d.get_io$$##n()
static void check(bool good,const char*why){if(!good)throw std::runtime_error(why);}
struct Test{
    SEthernetMediaTransition d;std::mt19937 random{0xa1eed};
    struct Mail{unsigned speed,delay;};std::optional<Mail> tx,rx;
    unsigned request=2,txApplied=2,rxApplied=2,ticks=0,txCommands=0,rxCommands=0,commits=0,closed=0;
    bool link=false,txDrain=true,rxDrain=true,txClock=true,rxClock=true,inject=false,epochReady=false;
    unsigned epochDelay=0;
    Test(){S(requestedLink,0);S(requestedSpeed,2);S(txDrained,1);S(rxDrained,1);S(txRate$$ready,1);S(rxRate$$ready,1);S(txRateIdle,1);S(rxRateIdle,1);S(ingressReady,0);
        d.set_reset(1);d.step();d.step();d.set_reset(0);}
    void tick(){
        const bool tReady=!tx&&random()%3!=0,rReady=!rx&&random()%3!=0;
        S(requestedLink,link);S(requestedSpeed,request);S(txDrained,txDrain);S(rxDrained,rxDrain);
        S(txRate$$ready,tReady);S(rxRate$$ready,rReady);S(txRateIdle,!tx);S(rxRateIdle,!rx);S(ingressReady,epochReady);d.step();++ticks;
        if(G(txRate$$valid)&&tReady){check(!tx,"TX rate mailbox ownership overwritten");tx=Mail{unsigned(G(txRate$$bits)),unsigned(2+random()%13)};++txCommands;}
        if(G(rxRate$$valid)&&rReady){check(!rx,"RX rate mailbox ownership overwritten");rx=Mail{unsigned(G(rxRate$$bits)),unsigned(2+random()%13)};++rxCommands;}
        if(G(ingressReset)){epochReady=false;epochDelay=0;}else if(rxClock&&!epochReady){if(++epochDelay==4)epochReady=true;}
        if(tx&&txClock){if(tx->delay)--tx->delay;else{txApplied=tx->speed;tx.reset();}}
        if(rx&&rxClock){if(rx->delay)--rx->delay;else{rxApplied=rx->speed;rx.reset();}}
        if(G(linkUp)){
            check(link&&request<3&&G(appliedSpeed)==request,"media committed stale PHY request");
            check(!G(pending)&&!G(stopNewTraffic)&&!G(abortTraffic),"media open/closed contradiction");
            check(epochReady&&txApplied==request&&rxApplied==request&&!tx&&!rx,"media opened before both consumed-image ACKs");
            if(inject)check(false,"media independent ownership oracle mismatch");++commits;
        }else{check(G(stopNewTraffic)&&G(abortTraffic),"media failed to close admission");++closed;}
    }
    void cycles(unsigned count){while(count--)tick();}
    template<class F>void until(F done,unsigned budget=4000){unsigned n=0;do{tick();++n;}while(!done()&&n<budget);check(done(),"media transition did not converge");}
    void settle(unsigned rate){request=rate;link=true;until([&]{return G(linkUp)&&G(appliedSpeed)==rate;});}
};
int main(int argc,char**argv){try{
    Test t;t.inject=argc==2&&std::string_view(argv[1])=="--inject-mismatch";
    t.until([&]{return !t.G(pending);});t.txDrain=false;t.rxDrain=false;t.link=true;t.request=1;
    const auto before=t.txCommands;t.cycles(100);check(t.txCommands==before&&!t.G(linkUp)&&t.G(timedOut)&&t.G(timeoutCount)==1,"media drain barrier or timeout mismatch");
    t.txDrain=true;t.cycles(10);check(t.txCommands==before,"media ignored RX ownership");t.rxDrain=true;t.settle(1);
    t.cycles(5);check(!t.G(timedOut),"media timeout did not clear after convergence");
    // A stopped RX clock cannot be fabricated as an ACK. Recovery preserves the
    // exact held rate image, and a newer request cannot open the stale epoch.
    t.rxClock=false;t.request=0;t.until([&]{return bool(t.rx);});t.request=2;t.cycles(160);
    check(!t.G(linkUp)&&t.G(pending)&&t.G(timedOut)&&t.G(timeoutCount)==2,"stopped RX clock incorrectly completed rate change");
    t.rxClock=true;t.settle(2);check(t.txApplied==2&&t.rxApplied==2,"coalesced rate lost latest image");
    t.rxClock=false;t.request=0;t.until([&]{return bool(t.rx)&&bool(t.tx);});
    t.link=false;t.until([&]{return !t.G(pending);});check(!t.G(linkUp)&&t.G(stopNewTraffic)&&t.rx.has_value(),"link-down waited for a dead raw-clock ACK or reopened traffic");
    t.rxClock=true;t.settle(1);
    // Independent random service schedules and rapid/coalesced requests.
    for(unsigned trial=0;trial<180;++trial){t.request=t.random()%4;t.link=t.random()%5!=0;t.txDrain=false;t.rxDrain=false;
        const unsigned oldTx=t.txCommands;t.cycles(3+t.random()%11);check(t.txCommands==oldTx,"random transition sent rate before drain");
        t.txDrain=true;t.rxDrain=true;t.cycles(1+t.random()%7);
        if(trial%3==0){t.request=t.random()%3;t.link=true;}
        t.until([&]{return !t.G(pending);});
        check(bool(t.G(linkUp))==(t.link&&t.request<3),"random final link decision mismatch");
    }
    check(t.txCommands>100&&t.rxCommands>100&&t.commits>100&&t.closed>500,"media transition coverage incomplete");
    std::cout<<"MEDIA_TRANSITION_PASS trials=180 cycles="<<t.ticks<<" tx_rate_images="<<t.txCommands<<" rx_rate_images="<<t.rxCommands<<" ready_cycles="<<t.commits<<" closed_cycles="<<t.closed<<" timeouts="<<t.G(timeoutCount)<<" stopped_rx_clock=1 down_drain_without_raw_ack=1 returned_epoch_ack=1 coalesced_changes=1\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
