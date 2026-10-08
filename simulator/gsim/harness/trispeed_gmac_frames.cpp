#include "TriSpeedFramesGsim.h"
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
static void check(bool ok,const char*msg){if(!ok)throw std::runtime_error(msg);}
struct Test {
    STriSpeedFramesGsim d;
    std::mt19937 random{0x31987};
    unsigned speed=2,cycles=0,txDone=0,txReject=0,txAbort=0,rxAccepted=0,rxDropped=0,badFcs=0,odd=0;
    unsigned txComplete=0,rxComplete=0,rxStalls=0,rateWait=0,halfTime=0,lastEdge=0,wireStart=0,lastEnd=0;
    unsigned observedRise=0,periodChecks=0,phaseChecks=0,byteSteps=0,inputBeats=0,inputOverlap=0,inputStalled=0;
    std::vector<unsigned> wireStarts,wireEnds,inputEnds;
    std::array<unsigned,8> reasons{};
    bool clock=false,clockKnown=false,checkClock=false,wireActive=false,riseEnable=false,lowHalf=false;
    bool ready=true,randomReady=true,allowAborted=false;
    unsigned low=0,nibble=0,clockRate=2;
    std::vector<uint8_t> wire,received;
    std::deque<std::vector<uint8_t>> expectedTx,expectedRx;
    std::optional<std::tuple<uint32_t,unsigned,bool,bool>> held;
    Test(){
        S(txFrame$$valid,0);S(txFrame$$bits$$data,0);S(txFrame$$bits$$keep,15);S(txFrame$$bits$$last,0);S(txFrame$$bits$$bad,0);
        S(txRate$$valid,0);S(txRate$$bits,2);S(rxRate$$valid,0);S(rxRate$$bits,2);
        S(txAbort,0);S(rxAbort,0);S(rxStop,0);S(rxRise,0);S(rxFall,0);S(rxFrame$$ready,1);
        d.set_reset(1);d.step();d.step();d.set_reset(0);idle(8);checkClock=true;
    }
    unsigned factor()const{return speed==2?1:speed==1?10:100;}
    unsigned period()const{return speed==2?2:speed==1?10:100;}
    void edge(bool value,unsigned data){
        ++halfTime;
        if(!clockKnown){clock=value;clockKnown=true;lastEdge=halfTime;return;}
        if(value==clock)return;
        if(checkClock){check(halfTime-lastEdge==(clockRate==2?1U:clockRate==1?5U:50U),"RGMII forwarded clock half-period mismatch");++periodChecks;}
        lastEdge=halfTime;clock=value;
        if(value){
            clockRate=G(txAppliedSpeed);
            ++observedRise;riseEnable=(data>>4)&1;nibble=data&15;
            if(riseEnable&&!wireActive){
                if(lastEnd)check(halfTime-lastEnd>=12*2*factor(),"RGMII scaled IFG mismatch");
                wireActive=true;wire.clear();lowHalf=false;wireStart=halfTime;wireStarts.push_back(halfTime);
            }
            if(!riseEnable&&wireActive){
                check(!lowHalf || allowAborted,"RGMII odd transmit nibble count");
                if(!allowAborted){
                    check(!expectedTx.empty(),"unexpected RGMII transmitted frame");
                    check(wire==expectedTx.front(),"tri-speed TX independent wire oracle mismatch");
                    check(halfTime-wireStart==wire.size()*2*factor(),"RGMII line-rate frame cycle budget mismatch");
                    expectedTx.pop_front();++txComplete;
                }
                wireActive=false;wire.clear();lastEnd=halfTime;wireEnds.push_back(halfTime);lowHalf=false;
            }
        }else if(riseEnable){
            check(((data>>4)&1)==riseEnable,"unexpected RGMII TX_ER");
            if(speed==2)wire.push_back(nibble|((data&15)<<4));
            else{
                check((data&15)==nibble,"RGMII low-speed nibble was not duplicated");++phaseChecks;
                if(!lowHalf){low=nibble;lowHalf=true;}else{wire.push_back(low|(nibble<<4));lowHalf=false;}
            }
        }
    }
    void tick(){
        const bool take=ready&&(!randomReady||random()%4!=0);S(rxFrame$$ready,take);d.step();++cycles;
        edge(G(txClockRise),G(txRise));edge(G(txClockFall),G(txFall));
        inputBeats+=G(txInputAccepted);inputOverlap+=G(txInputOverlap);inputStalled+=G(txInputStalled);if(G(txInputLast))inputEnds.push_back(cycles);
        txDone+=G(txDone);txReject+=G(txRejected);txAbort+=G(txAborted);rxAccepted+=G(rxAccepted);rxDropped+=G(rxDropped);badFcs+=G(rxBadFcs);odd+=G(rxOddNibble);byteSteps+=G(txByteStep);
        const unsigned mask=G(rxDropReasons);check(!mask || (mask&(mask-1))==0,"RX drop reason not exclusive");
        check(bool(mask)==bool(G(rxDropped)),"RX dropped frame missing exact diagnostic cause");
        for(unsigned i=0;i<8;++i)reasons[i]+=(mask>>i)&1;
        if(G(rxFrame$$valid)){
            const auto word=std::make_tuple(uint32_t(G(rxFrame$$bits$$data)),unsigned(G(rxFrame$$bits$$keep)),bool(G(rxFrame$$bits$$last)),bool(G(rxFrame$$bits$$bad)));
            if(held)check(*held==word,"tri-speed RX output changed under backpressure");
            held=take?std::nullopt:std::optional{word};rxStalls+=!take;
            if(take){auto [data,keep,last,bad]=word;check(!expectedRx.empty()&&!bad,"unexpected tri-speed RX frame");
                check(keep==1||keep==3||keep==7||keep==15,"tri-speed RX illegal keep");check(last||keep==15,"tri-speed RX short nonfinal beat");
                for(unsigned i=0;i<4;++i)if(keep&(1U<<i))received.push_back(data>>(8*i));
                if(last){check(received==expectedRx.front(),"tri-speed RX independent byte oracle mismatch");received.clear();expectedRx.pop_front();++rxComplete;}
            }
        }else{check(!held,"tri-speed RX withdrew a stalled beat");held.reset();}
    }
    void idle(unsigned count=16){S(rxRise,0);S(rxFall,0);while(count--)tick();}
    void drain(){for(unsigned n=0;n<500000&&(G(txBusy)||G(rxBusy)||wireActive||!expectedRx.empty()||!expectedTx.empty());++n)tick();
        check(!G(txBusy)&&!G(rxBusy)&&!wireActive&&expectedRx.empty()&&expectedTx.empty(),"tri-speed frame engines failed to drain");idle(16);}
    void setRate(unsigned next){
        S(txRate$$bits,next);S(txRate$$valid,1);S(rxRate$$bits,next);S(rxRate$$valid,1);S(rxStop,1);
        bool tx=false,rx=false;
        for(unsigned n=0;n<2000&&(!tx||!rx);++n){tick();if(G(txRate$$ready)){tx=true;S(txRate$$valid,0);}if(G(rxRate$$ready)){rx=true;S(rxRate$$valid,0);}}
        check(tx&&rx,"tri-speed rate command did not complete");speed=next;idle(16*factor()+8);S(rxStop,0);
        check(G(txAppliedSpeed)==next&&G(rxAppliedSpeed)==next,"tri-speed rate was not atomically applied");
        lastEnd=0;checkClock=true;const unsigned first=byteSteps;idle(10*factor());check(byteSteps-first==10,"tri-speed byte-enable duty mismatch");
    }
    void transmit(const std::vector<uint8_t>&body,unsigned mode=0){
        const bool valid=mode==0&&body.size()>=14&&body.size()<=2048;const unsigned before=txComplete,reject=txReject;
        if(valid)expectedTx.push_back(ethernetWire(body));
        for(unsigned i=0;i<body.size();i+=4){const unsigned count=std::min(4U,unsigned(body.size()-i));uint32_t word=0;
            for(unsigned n=0;n<count;++n)word|=uint32_t(body[i+n])<<(8*n);
            S(txFrame$$bits$$data,word);S(txFrame$$bits$$keep,mode==1&&i==0?5:(1U<<count)-1);S(txFrame$$bits$$last,i+count==body.size());S(txFrame$$bits$$bad,mode==2&&i+count==body.size());S(txFrame$$valid,1);
            unsigned n=0;do{tick();check(++n<500000,"tri-speed TX input timeout");}while(!G(txFrame$$ready));S(txFrame$$valid,0);
            if(i+count<body.size())check(!wireActive,"tri-speed TX emitted an incomplete native frame");
            idle(random()%3);
        }
        drain();check(txComplete==before+valid&&txReject==reject+!valid,"tri-speed TX complete/reject accounting mismatch");
    }
    void symbol(uint8_t byte,bool error=false,bool unusedNoise=false){
        if(speed==2){S(rxRise,16|(byte&15));S(rxFall,(error?0:16)|(byte>>4));tick();}
        else for(unsigned n=0;n<2;++n){unsigned nib=(byte>>(4*n))&15;S(rxRise,16|nib);S(rxFall,((error&&n==0)?0:16)|(unusedNoise?((nib+7)&15):nib));tick();}
    }
    void receive(std::vector<uint8_t> body,unsigned mode=0,bool good=true,unsigned cause=0){
        if(body.size()<60&&mode!=3)body.resize(60,0);auto bytes=ethernetWire(body,false);if(mode==1)bytes.back()^=1;if(mode==4)bytes[0]=0x54;
        const unsigned accepted=rxAccepted,dropped=rxDropped,diagnostic=reasons[cause];if(good)expectedRx.push_back(body);
        for(unsigned i=0;i<bytes.size();++i)symbol(bytes[i],mode==2&&i==19,mode==5);
        idle(3);drain();check(rxAccepted==accepted+good&&rxDropped==dropped+!good,"tri-speed RX whole-frame verdict mismatch");
        if(!good)check(reasons[cause]==diagnostic+1,"tri-speed RX diagnostic classification mismatch");
    }
    void overflow(){ready=false;randomReady=false;const unsigned accepted=rxAccepted,dropped=rxDropped,full=reasons[0];
        for(unsigned n=0;n<6;++n){auto body=ethernetBody(127+7*n,500+n);if(n<4)expectedRx.push_back(body);auto bytes=ethernetWire(body);
            for(unsigned i=0;i<bytes.size();++i){symbol(bytes[i]);if(n==5&&i==30)ready=true;}idle(speed==2?12:24);}
        ready=true;drain();check(rxAccepted==accepted+4&&rxDropped==dropped+2&&reasons[0]==full+2,"tri-speed exhausted-bank atomic ownership mismatch");randomReady=true;
    }
    void abortRx(){auto bytes=ethernetWire(ethernetBody(320,918));const unsigned dropped=rxDropped,abort=reasons[7];
        for(unsigned i=0;i<bytes.size();++i){if(i==37){S(rxAbort,1);S(rxStop,1);}symbol(bytes[i]);}
        idle(4);S(rxAbort,0);S(rxStop,0);drain();check(rxDropped==dropped+1&&reasons[7]==abort+1,"tri-speed link-aborted RX ownership mismatch");
    }
    void submit(const std::vector<uint8_t>&body){
        for(unsigned i=0;i<body.size();i+=4){unsigned count=std::min(4U,unsigned(body.size()-i));uint32_t word=0;
            for(unsigned n=0;n<count;++n)word|=uint32_t(body[i+n])<<(8*n);
            S(txFrame$$bits$$data,word);S(txFrame$$bits$$keep,(1U<<count)-1);S(txFrame$$bits$$last,i+count==body.size());S(txFrame$$bits$$bad,0);S(txFrame$$valid,1);
            unsigned n=0;do{tick();check(++n<500000,"TX submit timeout");}while(!G(txFrame$$ready));
        }S(txFrame$$valid,0);
    }
    void abortTx(){
        for(unsigned offset:{1U,7U,30U,266U}){const unsigned rejects=txReject,aborts=txAbort,dones=txDone;allowAborted=true;
            submit(ethernetBody(256,1300+offset));unsigned n=0;
            while((!wireActive||wire.size()<offset)&&n++<500000)tick();check(wireActive,"TX abort setup did not reach wire");
            S(txAbort,1);for(unsigned i=0;i<2*factor()+4;++i)tick();S(txAbort,0);drain();allowAborted=false;
            check(txReject==rejects+1&&txAbort==aborts+1&&txDone==dones,"TX on-wire abort event/owner mismatch");
        }
        const unsigned rejects=txReject,aborts=txAbort,done=txDone;S(txFrame$$valid,1);S(txFrame$$bits$$data,0x33221102);S(txFrame$$bits$$keep,15);S(txFrame$$bits$$last,0);S(txFrame$$bits$$bad,0);
        do{tick();}while(!G(txFrame$$ready));S(txAbort,1);
        auto tail=ethernetBody(60,1430);submit(tail);S(txAbort,0);drain();
        check(txReject==rejects+1&&txAbort==aborts+1&&txDone==done,"TX partial-collect abort did not drain LAST exactly once");
    }
    void heldRate(unsigned next){
        auto body=ethernetBody(256,1510+next);expectedTx.push_back(ethernetWire(body));submit(body);
        unsigned n=0;while(!wireActive&&n++<500000)tick();check(wireActive,"rate hold setup lacked active frame");
        S(txRate$$bits,next);S(txRate$$valid,1);bool accepted=false;
        for(n=0;n<500000&&!accepted;++n){tick();if(G(txBusy)){check(!G(txRate$$ready),"rate changed before TX frame/IFG drain");++rateWait;}
            if(G(txRate$$ready)){accepted=true;S(txRate$$valid,0);}}
        check(accepted&&!wireActive&&expectedTx.empty(),"held rate offer lost TX frame ownership");speed=next;
        // Submit immediately; the codec must provide a complete new-rate IFG.
        transmit(ethernetBody(60,1560+next));setRate(next);
    }
    void oddRx(){if(speed==2)return;auto bytes=ethernetWire(ethernetBody(67,334));const unsigned drops=rxDropped,odds=odd,phy=reasons[6];
        for(unsigned i=0;i+1<bytes.size();++i)symbol(bytes[i]);const unsigned nib=bytes.back()&15;S(rxRise,16|nib);S(rxFall,16|nib);tick();idle(3);drain();
        check(rxDropped==drops+1&&odd==odds+1&&reasons[6]==phy+1,"tri-speed odd-nibble RX was not rejected");
    }
};
#ifndef TRI_SPEED_NO_MAIN
int main(int argc,char**argv){try{
    bool inject=argc==2&&std::string_view(argv[1])=="--inject-mismatch";Test t;unsigned cases=0;
    check(ethernetReferenceCrc({'1','2','3','4','5','6','7','8','9'})==0xcbf43926,"CRC golden vector mismatch");
    for(unsigned rate:{2U,1U,0U}){
        t.setRate(rate);
        for(unsigned length:{14U,15U,59U,60U,61U,62U,63U,64U,127U,1514U,1518U,2047U,2048U}){auto body=ethernetBody(length,1000+cases);
            if(inject){t.expectedTx.push_back(ethernetWire(body));t.expectedTx.back().back()^=1;t.transmit(body);}
            t.transmit(body);t.receive(body);cases+=2;}
        for(unsigned n=0;n<12;++n){auto body=ethernetBody(60+t.random()%1989,2300+n);t.transmit(body);t.receive(body,rate==2?0:5);cases+=2;}
        t.transmit(ethernetBody(13));t.transmit(ethernetBody(2049));t.transmit(ethernetBody(64),1);t.transmit(ethernetBody(64),2);cases+=4;
        t.receive(ethernetBody(64),1,false,3);t.receive(ethernetBody(64),2,false,6);t.receive(ethernetBody(14),3,false,4);
        t.receive(ethernetBody(64),4,false,2);t.receive(ethernetBody(2049),0,false,4);cases+=5;
        auto foreign=ethernetBody(100);foreign[0]=0x44;t.receive(foreign,0,false,5);
        auto lt=ethernetBody(60);lt[12]=0;lt[13]=80;t.receive(lt,0,false,4);cases+=2;
        t.S(rxStop,1);t.receive(ethernetBody(64),0,false,1);t.S(rxStop,0);++cases;
        t.overflow();cases+=6;t.abortRx();++cases;t.abortTx();cases+=5;t.oddRx();cases+=rate!=2;t.receive(ethernetBody(77,809));++cases;
        std::cout<<"TRISPEED_RATE_PASS mbps="<<(rate==2?1000:rate==1?100:10)<<" cases_total="<<cases<<" cycles="<<t.cycles<<" tx_frames="<<t.txComplete<<" rx_frames="<<t.rxComplete<<" drops="<<t.rxDropped<<"\n";
    }
    for(auto [from,to]:std::array<std::pair<unsigned,unsigned>,6>{{{2,1},{1,2},{2,0},{0,2},{1,0},{0,1}}}){t.setRate(from);t.heldRate(to);cases+=2;}
    t.setRate(0);
    // Reserved rates are never acknowledged, and the current mode survives.
    t.S(txRate$$bits,3);t.S(txRate$$valid,1);t.S(rxRate$$bits,3);t.S(rxRate$$valid,1);t.S(rxStop,1);
    for(unsigned n=0;n<200;++n){t.tick();check(!t.G(txRate$$ready)&&!t.G(rxRate$$ready),"reserved Ethernet rate acknowledged");}
    t.S(txRate$$valid,0);t.S(rxRate$$valid,0);t.S(rxStop,0);check(t.G(txAppliedSpeed)==0&&t.G(rxAppliedSpeed)==0,"reserved rate changed active mode");
    check(t.periodChecks>10000&&t.phaseChecks>1000&&t.rxStalls>1000,"tri-speed test lacked timing/backpressure witnesses");
    std::cout<<"TRISPEED_FRAMES_PASS cases="<<cases<<" cycles="<<t.cycles<<" tx_frames="<<t.txComplete<<" rx_frames="<<t.rxComplete<<" rx_drops="<<t.rxDropped<<" rx_stalls="<<t.rxStalls<<" clock_half_periods="<<t.periodChecks<<" duplicate_nibbles="<<t.phaseChecks<<" tx_aborts="<<t.txAbort<<" held_rate_cycles="<<t.rateWait<<" directed_rate_changes=6 transition_clock_checks=1 drop_causes=";
    for(auto n:t.reasons)std::cout<<n<<",";std::cout<<"\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}

#endif
