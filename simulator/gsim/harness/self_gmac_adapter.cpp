#include "EthernetDmaFrameAdapter.h"
#include <algorithm>
#include <cstdint>
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
struct Beat{uint32_t data;unsigned keep;bool last,bad=false;};
int main(int argc,char**argv){try{
    bool inject=argc==2&&std::string_view(argv[1])=="--inject-mismatch";
    unsigned cases=0,stalls=0,beats=0;
    std::mt19937 random(0x104ada);
    for(unsigned length:{1U,2U,3U,4U,5U,14U,60U,61U,64U,1514U,2047U,2048U})
    for(unsigned mode=0;mode<8;++mode){
        SEthernetDmaFrameAdapter d;
        S(txControl$$valid,0);S(txData$$valid,0);S(rxFrame$$valid,0);
        S(txFrame$$ready,0);S(rxData$$ready,0);S(rxStatus$$ready,0);
        d.set_reset(1);d.step();d.step();d.set_reset(0);
        std::deque<Beat> control,tx,rx;
        std::vector<Beat> expectedTx,expectedRx;
        bool badControl=mode>=1&&mode<=4;
        const unsigned controlWords=mode==2?3:mode==3?7:6;
        for(unsigned n=0;n<controlWords;++n){
            uint32_t data=n==0?0xa0000000:0;
            if(mode==1&&n==0)data^=0x10000000;
            if(mode==4&&n==2)data=1;
            control.push_back({data,15,n+1==controlWords});
        }
        unsigned byteCount=0;
        for(unsigned n=0;n<length;n+=4){
            const unsigned count=std::min(4U,length-n);uint32_t data=0;
            for(unsigned b=0;b<count;++b)data|=uint32_t(uint8_t(n+b+17))<<(8*b);
            Beat t{data,(1U<<count)-1,n+count==length};tx.push_back(t);
            t.bad=t.last&&badControl;expectedTx.push_back(t);
            Beat r{data,(1U<<count)-1,n+count==length};
            if(mode==5&&n==0)r.keep=5;
            if(mode==6&&r.last)r.bad=true;
            if(mode==7&&n==0)r.keep=1;
            byteCount+=__builtin_popcount(r.keep);rx.push_back(r);expectedRx.push_back(r);
        }
        bool rxBad=mode==5||mode==6||(mode==7&&length>4);
        const std::vector<uint32_t> status{0x50000000,0,0,rxBad?128U:64U,0,byteCount};
        unsigned txIndex=0,rxIndex=0,statusIndex=0,ctrlConsumed=0;
        bool ctrlOffer=false,txOffer=false,rxOffer=false;
        std::optional<std::tuple<uint32_t,unsigned,bool,bool>> txHeld;
        std::optional<std::tuple<uint32_t,unsigned,bool>> dataHeld,statusHeld;
        for(unsigned cycle=0;cycle<30000&&(txIndex<expectedTx.size()||rxIndex<expectedRx.size()||statusIndex<6);++cycle){
            ctrlOffer=ctrlOffer||(!control.empty()&&random()%3!=0);
            txOffer=txOffer||(!tx.empty()&&random()%3!=0);
            rxOffer=rxOffer||(!rx.empty()&&random()%3!=0);
            Beat c=control.empty()?Beat{}:control.front(),t=tx.empty()?Beat{}:tx.front(),r=rx.empty()?Beat{}:rx.front();
            S(txControl$$valid,ctrlOffer);S(txControl$$bits$$data,c.data);S(txControl$$bits$$keep,c.keep);
            S(txControl$$bits$$last,c.last);S(txData$$valid,txOffer);S(txData$$bits$$data,t.data);
            S(txData$$bits$$keep,t.keep);S(txData$$bits$$last,t.last);
            S(rxFrame$$valid,rxOffer);S(rxFrame$$bits$$data,r.data);S(rxFrame$$bits$$keep,r.keep);
            S(rxFrame$$bits$$last,r.last);S(rxFrame$$bits$$bad,r.bad);
            const bool tr=cycle%29>=13&&random()%3!=0,rr=cycle%31>=15&&random()%3!=0,sr=cycle%47>=21&&random()%3!=0;
            S(txFrame$$ready,tr);S(rxData$$ready,rr);S(rxStatus$$ready,sr);d.step();
            if(ctrlOffer&&G(txControl$$ready)){control.pop_front();ctrlOffer=false;++ctrlConsumed;}
            if(txOffer&&G(txData$$ready)){tx.pop_front();txOffer=false;}
            if(rxOffer&&G(rxFrame$$ready)){rx.pop_front();rxOffer=false;}
            if(G(txFrame$$valid)){
                auto a=std::make_tuple(uint32_t(G(txFrame$$bits$$data)),unsigned(G(txFrame$$bits$$keep)),
                    bool(G(txFrame$$bits$$last)),bool(G(txFrame$$bits$$bad)));
                check(ctrlConsumed==controlWords,"adapter emitted data before TX control completed");
                if(txHeld)check(a==*txHeld,"adapter changed stalled native TX");
                txHeld=tr?std::nullopt:std::optional{a};stalls+=!tr;
                if(tr){const Beat e=expectedTx.at(txIndex++);
                    check(a==std::make_tuple(e.data,e.keep,e.last,e.bad),"DMA adapter independent TX oracle mismatch");++beats;}
            }else check(!txHeld,"adapter withdrew stalled TX");
            if(G(rxData$$valid)){
                auto a=std::make_tuple(uint32_t(G(rxData$$bits$$data)),unsigned(G(rxData$$bits$$keep)),bool(G(rxData$$bits$$last)));
                if(dataHeld)check(a==*dataHeld,"adapter changed stalled RX data");
                dataHeld=rr?std::nullopt:std::optional{a};stalls+=!rr;
                if(rr){const Beat e=expectedRx.at(rxIndex++);
                    check(a==std::make_tuple(e.data,e.keep,e.last),"DMA adapter independent RX oracle mismatch");++beats;}
            }else check(!dataHeld,"adapter withdrew stalled RX data");
            if(G(rxStatus$$valid)){
                check(rxIndex==expectedRx.size()&&!G(rxFrame$$ready),"adapter status/native ownership mismatch");
                auto a=std::make_tuple(uint32_t(G(rxStatus$$bits$$data)),unsigned(G(rxStatus$$bits$$keep)),bool(G(rxStatus$$bits$$last)));
                if(statusHeld)check(a==*statusHeld,"adapter changed stalled RX status");
                statusHeld=sr?std::nullopt:std::optional{a};stalls+=!sr;
                uint32_t e=status.at(statusIndex)^(inject&&cases==0&&statusIndex==5?1U:0U);
                check(a==std::make_tuple(e,15U,statusIndex==5),"DMA adapter independent status oracle mismatch");
                if(sr){++statusIndex;++beats;}
            }else check(!statusHeld,"adapter withdrew stalled RX status");
        }
        check(txIndex==expectedTx.size()&&rxIndex==expectedRx.size()&&statusIndex==6&&control.empty(),
            "adapter test did not drain all channels");
        ++cases;
    }
    std::cout<<"SELF_GMAC_ADAPTER_PASS cases="<<cases<<" beats="<<beats<<" stalls="<<stalls
        <<" invalid_control=1 malformed_rx=1\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
