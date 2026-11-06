#include "GsimClockContract.h"
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <stdexcept>
#include <string>
using Wide = unsigned _BitInt(128);
static void need(bool v, const std::string &message) { if(!v)throw std::runtime_error(message); }
static Wide payload(uint64_t n) {return (Wide(0x8000|(n&0x7fff))<<64) | (n*0x9e3779b97f4a7c15ULL);}
int main(int argc,char**argv){try{
    const bool inject=argc>1;
    uint64_t checks=0, transfers=0;
    for(auto periods:{std::array<unsigned,2>{10,6},{6,10},{14,10}}){
        SGsimClockContract d;bool oldA=false,oldB=false;
        uint8_t a=0x39,b=0,aa=0,bb=0;
        std::array<uint64_t,16> ramA{},ramB{};std::array<bool,16> initA{},initB{};
        std::deque<Wide> queue;unsigned sent=0,received=0;
        d.set_clockA(0);d.set_clockB(0);d.set_resetA(1);d.set_resetB(1);d.set_coldReset(1);
        d.set_enableA(0);d.set_enableB(0);d.set_deltaA(0);d.set_deltaB(0);
        d.set_writeA(0);d.set_writeB(0);d.set_readA(0);d.set_readB(0);
        d.set_addressA(0);d.set_addressB(0);d.set_dataA(0);d.set_dataB(0);
        d.set_mailboxIn$$valid(0);d.set_mailboxIn$$bits(0);d.set_mailboxOut$$ready(0);d.step();
        need(d.get_countA()==0x39 && d.get_countB()==0,"async nonzero reset / synchronous no-edge oracle");
        for(unsigned t=0;t<30000;++t){
            const bool cold=t<80 || (t>=14000&&t<14080);
            bool ca=(t%periods[0])>=periods[0]/2,cb=((t+1)%periods[1])>=periods[1]/2;
            if(t>=11000&&t<11200)ca=oldA; // A stopped while B keeps running.
            const bool ea=ca&&!oldA,eb=cb&&!oldB;
            const bool ra=t<40 || t%307==0,rb=t<40 || t%101<4;
            const bool ena=t%7>=2,enb=t%11>=4;
            const uint8_t da=(t*37)&255,db=(t*59)&255;
            const unsigned adrA=(t/periods[0])%16,adrB=(t/periods[1])%16;
            const bool wa=t<500 || t%3==0,wb=t<500 || t%5==0;
            const bool rdA=t%4!=0,rdB=t%6!=0;
            const uint64_t dataA=0x1234567800000000ULL+t*19,dataB=0xfedcba9800000000ULL+t*23;
            d.set_clockA(oldA);d.set_clockB(oldB);d.set_resetA(ra);d.set_resetB(rb);d.set_coldReset(cold);
            d.set_enableA(ena);d.set_enableB(enb);d.set_deltaA(da);d.set_deltaB(db);
            d.set_addressA(adrA);d.set_addressB(adrB);d.set_dataA(dataA);d.set_dataB(dataB);
            d.set_writeA(wa);d.set_writeB(wb);d.set_readA(rdA);d.set_readB(rdB);
            if(cold){queue.clear();sent=received=0;}
            d.set_mailboxIn$$valid(!cold&&sent<2000);d.set_mailboxIn$$bits(payload(sent));
            d.set_mailboxOut$$ready(!cold&&t%13>=5);d.step(); // settle changed inputs with NO edge
            if(ra){a=0x39;aa=0;}
            need(d.get_countA()==a&&d.get_countB()==b&&d.get_seenA()==aa&&d.get_seenB()==bb,
                 "no-edge register/reset oracle t="+std::to_string(t));
            const bool push=ea&&!cold&&d.get_mailboxIn$$ready()&&sent<2000;
            const bool pop=eb&&!cold&&d.get_mailboxOut$$valid()&&t%13>=5;
            Wide got=d.get_mailboxOut$$bits();if(inject&&pop)got^=Wide(1)<<79;
            const uint8_t preA=a,preB=b;
            if(ea){if(ra){a=0x39;aa=0;}else if(ena){a+=da;aa=preB;}}
            if(eb){if(rb){b=0xa7;bb=0;}else if(enb){b+=db;bb=preA;}}
            const bool checkA=ea&&rdA&&!wa&&initA[adrA],checkB=eb&&rdB&&!wb&&initB[adrB];
            const uint64_t expectedA=ramA[adrA],expectedB=ramB[adrB];
            if(ea&&wa){ramA[adrA]=dataA;initA[adrA]=true;}
            if(eb&&wb){ramB[adrB]=dataB;initB[adrB]=true;}
            d.set_clockA(ca);d.set_clockB(cb);d.step();oldA=ca;oldB=cb;
            need(d.get_countA()==a&&d.get_countB()==b&&d.get_seenA()==aa&&d.get_seenB()==bb,
                 "rising/simultaneous old-state oracle t="+std::to_string(t));
            if(initA[adrA])need(d.get_asyncA()==ramA[adrA],"A RAM write edge oracle");
            if(initB[adrB])need(d.get_asyncB()==ramB[adrB],"B RAM write edge oracle");
            if(checkA)need(d.get_syncA()==expectedA,"A synchronous RAM edge oracle");
            if(checkB)need(d.get_syncB()==expectedB,"B synchronous RAM edge oracle");
            if(push){queue.push_back(payload(sent++));}
            if(pop){need(!queue.empty()&&got==queue.front(),"independent mailbox 80-bit order oracle");queue.pop_front();++received;++transfers;}
            ++checks;
        }
        need(received>20,"mailbox bounded progress");
    }
    std::cout<<"GSIM_EXPLICIT_CLOCK_CONTRACT_PASS eval_pairs="<<checks<<" mailbox80_transfers="<<transfers
             <<" simultaneous_old_state_sync_async_reset_RAM_backpressure_stop=PASS\n";
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
