#include "Rtl8211fPhyManager.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <map>
#include <optional>
#include <random>
#include <stdexcept>
#include <string_view>
#include <tuple>
#define S(n,v) d.set_io$$##n(v)
#define G(n) d.get_io$$##n()
static void check(bool good,const char*why){if(!good)throw std::runtime_error(why);}
struct Test {
    SRtl8211fPhyManager d;std::mt19937 random{0x8211f};
    std::map<unsigned,uint16_t> regs;
    unsigned page=0,mmdControl=0,mmdAddress=0,bmsrReads=0,commands=0,polls=0,cycles=0,configurations=0;
    unsigned wireSpeed=2;bool wireLink=true,full=true,anComplete=true,remoteFault=false;
    bool held=false,pendingAck=false,injectNoAck=false,injectVerify=false,injectOracle=false,txReadback=false;
    uint16_t pendingData=0;unsigned delay=0;
    bool previousLink=false;unsigned rises=0,falls=0;
    Test(){regs[0]=0x1140;regs[2]=0x001c;regs[3]=0xc916;regs[4]=0x01e1;regs[9]=0x0700;
        regs[(0xd08<<5)|17]=0xf377;regs[(0xd08<<5)|21]=0x7890;
        S(command$$ready,0);S(response$$valid,0);S(response$$bits$$data,0);S(response$$bits$$noAck,0);S(restart,0);
        d.set_reset(1);d.step();d.step();d.set_reset(0);
    }
    uint16_t access(unsigned phy,unsigned reg,bool write,uint16_t data){
        check(phy==1,"PHY manager addressed wrong PHY");++commands;
        if(reg==31){if(write)page=data;return page;}
        if(write){
            if(page==0){
                if(reg==13)mmdControl=data;
                else if(reg==14){if((mmdControl&0xc000)==0)mmdAddress=data;else regs[0x100000|(mmdControl&31)<<16|mmdAddress]=data;}
                else if(reg==4){check(data==0x0141,"PHY manager advertised half duplex or pause");++configurations;regs[reg]=data;}
                else if(reg==9){check((data&0x0300)==0x0200,"PHY manager gigabit advertisement mismatch");regs[reg]=data;}
                else if(reg==0){check(data==0x1340,"PHY manager restart control mismatch");regs[reg]=data&~0x0200;}
                else throw std::runtime_error("PHY manager wrote unexpected base register");
            }else if(page==0xd08&&(reg==17||reg==21)){
                check(data==(reg==17?0xf277:0x7898),"PHY delay RMW did not preserve unrelated bits");regs[(page<<5)|reg]=data;if(reg==17)txReadback=true;
            }else throw std::runtime_error("PHY manager wrote unexpected vendor register");
            return data;
        }
        if(page==0){
            if(reg==1){++bmsrReads;return (anComplete?0x20:0)|(remoteFault?0x10:0)|((bmsrReads%2==0&&wireLink)?4:0);}
            if(reg==5)return 0x4141;
            if(reg==10)return 0x7800;
            if(reg==14)return regs[0x100000|(mmdControl&31)<<16|mmdAddress];
            return regs[reg];
        }
        if(page==0xa43&&reg==26){++polls;return 0x1000|(wireSpeed<<4)|(full?8:0)|(wireLink?4:0);}
        if(page==0xd08&&(reg==17||reg==21)){
            auto result=regs[(page<<5)|reg];
            if(reg==17&&txReadback){txReadback=false;if(injectVerify){injectVerify=false;return result^1;}}
            return result;
        }
        throw std::runtime_error("PHY manager read unexpected vendor register");
    }
    void tick(){
        bool response=held&&delay==0;const bool ready=!held&&random()%4!=0;
        S(command$$ready,ready);S(response$$valid,response);S(response$$bits$$data,pendingData);S(response$$bits$$noAck,pendingAck);
        d.step();++cycles;
        if(response&&G(response$$ready)){held=false;S(response$$valid,0);}
        if(G(command$$valid)&&ready){
            check(!held&&G(lock),"PHY manager command escaped page-sequence owner");
            const unsigned reg=G(command$$bits$$register);const bool write=G(command$$bits$$write);
            pendingData=access(G(command$$bits$$phy),reg,write,G(command$$bits$$data));
            if(injectOracle){check(pendingData==uint16_t(pendingData^1),"PHY independent register oracle mismatch");}
            pendingAck=injectNoAck&&!write;if(pendingAck)injectNoAck=false;held=true;delay=1+random()%7;
        }
        if(held&&delay)--delay;
        if(G(linkUp)&&!previousLink){++rises;check(G(initialized)&&full&&wireLink&&anComplete&&!remoteFault,"PHY asserted link without resolved full-duplex negotiation");}
        if(!G(linkUp)&&previousLink)++falls;previousLink=G(linkUp);
        if(!G(lock)&&G(initialized))check(page==0,"PHY released page lock before restoring default page");
    }
    template<class F>void until(F done,unsigned budget=10000){unsigned n=0;while(!done()&&n++<budget)tick();check(done(),"PHY state machine failed to reach requested condition");}
    void settleRate(unsigned rate){wireSpeed=rate;until([&]{return G(linkUp)&&G(requestedSpeed)==rate;});}
};
int main(int argc,char**argv){try{
    Test t;t.injectOracle=argc==2&&std::string_view(argv[1])=="--inject-mismatch";
    t.until([&]{return t.G(linkUp);});check(t.G(pollCount)>=2,"PHY link rose before debounce polls");check(t.G(requestedSpeed)==2,"PHY initial gigabit rate mismatch");
    check(t.regs[4]==0x0141&&(t.regs[9]&0x300)==0x200,"PHY advertised unsupported rates/duplex");
    check(t.regs[0x100000|(7<<16)|60]==0,"PHY did not disable EEE advertisement");
    for(unsigned speed:{1U,0U,2U,0U,1U,2U}){const unsigned before=t.falls;t.settleRate(speed);check(t.falls==before+1,"PHY changed active rate without dropping link during debounce");}
    t.full=false;t.until([&]{return !t.G(linkUp)&&t.G(unsupportedCount)>0;});const unsigned unsupported=t.G(unsupportedCount);
    t.full=true;t.settleRate(0);t.wireSpeed=3;t.until([&]{return !t.G(linkUp)&&t.G(unsupportedCount)>unsupported;});t.settleRate(2);
    t.wireLink=false;t.until([&]{return !t.G(linkUp);});t.wireLink=true;t.settleRate(1);
    t.anComplete=false;t.until([&]{return !t.G(linkUp);});t.anComplete=true;t.settleRate(0);
    t.remoteFault=true;t.until([&]{return !t.G(linkUp);});t.remoteFault=false;t.settleRate(2);
    const unsigned noack=t.G(noAckCount);t.injectNoAck=true;t.until([&]{return t.G(noAckCount)==noack+1;});check(!t.G(linkUp)&&!t.G(initialized)&&t.G(fault)==1,"PHY no-ACK did not invalidate stale state");t.settleRate(1);
    const unsigned errors=t.G(verifyErrorCount),configs=t.configurations;t.injectVerify=true;t.S(restart,1);t.tick();t.S(restart,0);
    t.until([&]{return t.G(verifyErrorCount)==errors+1;});check(!t.G(linkUp)&&!t.G(initialized)&&t.G(fault)==4,"PHY delay readback failure did not fail closed");t.settleRate(2);check(t.configurations>configs,"PHY restart did not restore all policy registers");
    check(t.rises>=14&&t.falls>=13,"PHY test missed transition witnesses");
    std::cout<<"RTL8211F_MANAGER_PASS commands="<<t.commands<<" cycles="<<t.cycles<<" polls="<<t.G(pollCount)<<" link_rises="<<t.rises<<" link_falls="<<t.falls<<" no_ack="<<t.G(noAckCount)<<" verify_errors="<<t.G(verifyErrorCount)<<" unsupported="<<t.G(unsupportedCount)<<" page_restore=1 latched_low_bmsr=1\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
