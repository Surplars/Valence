#include "MachineCoreGsim.h"
#include <array>
#include <cstdint>
#include <deque>
#include <dlfcn.h>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <memory>
#include <random>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>
#ifndef REGISTERED_FETCH_PACKET
#define REGISTERED_FETCH_PACKET 0
#endif
#ifndef BRANCH_ENTRIES
#define BRANCH_ENTRIES 64
#endif
static constexpr uint64_t base=0x80000000, dataBase=0x80010000;
#ifdef SYNCHRONOUS_MACHINE
static constexpr uint64_t vectorPc=base+0x1000;
static std::vector<uint32_t> firmware;
static uint64_t firmwareStop=0,firmwareTrigger=0;
static bool atomicBoot=false,serialBoot=true,dmaBoot=false,timerBoot=false,sstcBoot=false;
static bool injectSerialMismatch=false;
#else
static constexpr uint64_t vectorPc=base+0xc000;
#endif
static bool privilegeBoot=false;
static bool pmpAvailable=false;
using Memory=std::array<uint8_t,4096>;
static void check(bool ok,const std::string& msg){if(!ok)throw std::runtime_error(msg);}
#include "isa_model.h"
#include "reference.h"
struct SystemModel {
    std::array<uint64_t,32> regs{};
    uint64_t pc=base,status=0xa00000000,mtvec=0,scratch=0,epc=0,cause=0,tval=0,select=0;
    uint64_t medeleg=0,mideleg=0,stvec=0,sscratch=0,sepc=0,scause=0,stval=0,sselect=0;
    uint64_t interruptEnable=0,stimecmp=~UINT64_C(0),timerTime=0;
    bool timerPending=false,softwarePending=false,supervisorTimerSoftwarePending=false;
    bool supervisorTimerHardwarePending=false,stce=false,mcounterenTm=false,scounterenTm=false;
    bool supervisorTimerPending()const{return stce?supervisorTimerHardwarePending:supervisorTimerSoftwarePending;}
    unsigned irqCause()const{
        bool machineEnabled=mode<3||(status&8);
        if(machineEnabled&&delivery&&top()&&(interruptEnable&2048))return 11;
        if(machineEnabled&&timerPending&&(interruptEnable&128))return 7;
        bool supervisorEnabled=(mideleg&512)?mode==0||(mode==1&&(status&2)):machineEnabled;
        if(supervisorEnabled&&deliveryS&&topS()&&(interruptEnable&512))return 9;
        bool softwareEnabled=(mideleg&2)?mode==0||(mode==1&&(status&2)):machineEnabled;
        if(softwareEnabled&&softwarePending&&(interruptEnable&2))return 1;
        bool supervisorTimerEnabled=(mideleg&32)?mode==0||(mode==1&&(status&2)):machineEnabled;
        if(supervisorTimerEnabled&&supervisorTimerPending()&&(interruptEnable&32))return 5;
        return 0;
    }
    bool irq()const{return irqCause()!=0;}
    bool reserved=false;uint64_t reservation=0;unsigned reservationBytes=0,atomicCount=0;
    unsigned mode=3;
    std::array<uint8_t,16> pmpCfg{};
    std::array<uint64_t,16> pmpAddr{};
    bool pmpDenied(uint64_t address,unsigned size,unsigned access,bool instruction)const {
        if(!pmpAvailable)return false;
        unsigned effectiveMode=instruction?mode:(mode==3 && (status&(UINT64_C(1)<<17)))?((status>>11)&3):mode;
        unsigned __int128 start=address,end=start+((unsigned __int128)1<<size)-1;
        for(unsigned i=0;i<16;++i){
            unsigned cfg=pmpCfg[i],matching=(cfg>>3)&3;
            unsigned __int128 low=0,high=0;
            if(matching==1){
                low=i?((unsigned __int128)pmpAddr[i-1]<<2):0;
                auto top=(unsigned __int128)pmpAddr[i]<<2;
                if(top<=low)continue;
                high=top-1;
            }else if(matching==2){low=(unsigned __int128)pmpAddr[i]<<2;high=low+3;}
            else if(matching==3){
                uint64_t mask=(((pmpAddr[i]^(pmpAddr[i]+1))<<2)|3)&((UINT64_C(1)<<56)-1);
                low=(pmpAddr[i]<<2)&~mask;high=low|mask;
            }else continue;
            if(start>high||end<low)continue;
            bool covered=start>=low&&end<=high;
            bool permission=access==0?(cfg&1):access==1?(cfg&2):access==2?(cfg&4):((cfg&3)==3);
            return !covered || (effectiveMode!=3 || (cfg&128)) && !permission;
        }
        return effectiveMode!=3;
    }
#ifdef MAPPED_APLIC
    uint32_t aplicDomain=0,aplicSource=0,aplicTarget=0,aplicEnable=0;
    unsigned mmioReads=0,mmioWrites=0;
#endif
#ifdef SYNCHRONOUS_MACHINE
    uint64_t dmaSource=0,dmaDestination=0,dmaLength=0,dmaControl=0,dmaStatus=0;
    unsigned dmaStarts=0;
    uint64_t timerCompare=~UINT64_C(0);
    unsigned timerWrites=0;
    unsigned uartLcr=3,uartDivisor=1,uartIer=0,uartScratch=0;
    bool uartReceived=false;
    std::string uartWrites;
#endif
    std::array<bool,128> pending{},enabled{},pendingS{},enabledS{};
    unsigned threshold=0,thresholdS=0; bool delivery=false,deliveryS=false;
    unsigned top()const {for(unsigned i=1;i<128;++i)if(pending[i]&&enabled[i]&&(!threshold||i<threshold))return i;return 0;}
    unsigned topS()const {for(unsigned i=1;i<128;++i)if(pendingS[i]&&enabledS[i]&&(!thresholdS||i<thresholdS))return i;return 0;}
    struct Result {uint64_t value=0,next=0,cause=0,tval=0;unsigned rd=0;bool fault=false;};
    Result step(uint32_t inst,Memory& mem) {
        Result r; r.next=pc+4;r.rd=(inst>>7)&31;
        if(pmpDenied(pc,2,2,true)){r.fault=true;r.cause=1;r.tval=pc;return r;}
        if((inst&0x707f)==0x0f || (inst&0x707f)==0x100f){r.rd=0;return r;}
#ifdef SYNCHRONOUS_MACHINE
        if((inst&127)==0x2f) {
            unsigned op=inst>>27,f=(inst>>12)&7,rs=(inst>>20)&31;uint64_t addr=regs[(inst>>15)&31],v=regs[rs];
            bool known=op==0||op==1||op==2||op==3||op==4||op==8||op==12||op==16||op==20||op==24||op==28;
            if(!known||(f!=2&&f!=3)||(op==2&&rs)){r.fault=true;r.cause=2;r.tval=inst;return r;}
            unsigned bytes=1U<<f;bool misaligned=addr&(bytes-1);
            if(misaligned||addr<dataBase||addr-dataBase>mem.size()-bytes){r.fault=true;r.cause=(op==2?4:6)+!misaligned;r.tval=addr;return r;}
            if(pmpDenied(addr,f,op==2?0:op==3?1:3,false)){
                r.fault=true;r.cause=op==2?5:7;r.tval=addr;return r;
            }
            uint64_t old=0;for(unsigned i=0;i<bytes;++i)old|=uint64_t(mem[addr-dataBase+i])<<(8*i);
            bool success=reserved&&reservation==addr&&reservationBytes==bytes;
            if(op==2||op==3||(addr>>6)==(reservation>>6))reserved=false;
            r.value=bytes==4?extend(old,32):old;
            if(op==2){reserved=true;reservation=addr;reservationBytes=bytes;}
            else if(op==3){r.value=success?0:1;}
            else {
                if(bytes==4)v=uint32_t(v);
                auto signedOld=bytes==4?extend(old,32):old,signedV=bytes==4?extend(v,32):v;
                bool less=(signedOld^(UINT64_C(1)<<63))<(signedV^(UINT64_C(1)<<63));
                switch(op){case 0:v=old+v;break;case 1:break;case 4:v=old^v;break;case 8:v=old|v;break;case 12:v=old&v;break;
                case 16:v=less?old:v;break;case 20:v=less?v:old;break;case 24:v=old<v?old:v;break;case 28:v=old>v?old:v;break;}
            }
            if(op!=2&&(op!=3||success))for(unsigned i=0;i<bytes;++i)mem[addr-dataBase+i]=v>>(8*i);
            ++atomicCount;return r;
        }
#endif
        if((inst&127)!=0x73) {
            auto e=decode(inst);
            if(!e) {r.fault=true;r.cause=2;r.tval=inst;return r;}
            if(e->memory){
                auto addr=regs[(inst>>15)&31]+immediate(*e,inst);
                bool store=e->memory==2;
                if(pmpDenied(addr,(inst>>12)&3,store?1:0,false)){
                    r.fault=true;r.cause=store?7:5;r.tval=addr;return r;
                }
            }
#ifdef MAPPED_APLIC
            if(e->memory) {
                uint64_t addr=regs[(inst>>15)&31]+immediate(*e,inst);
                if(addr>=0x0c000000 && addr<0x0c004000) {
                    bool store=e->memory==2;unsigned bytes=1U<<((inst>>12)&3);if(store)r.rd=0;
                    if((addr&(bytes-1)) || bytes!=4){r.fault=true;r.cause=(store?6:4)+!(addr&(bytes-1));r.tval=addr;return r;}
                    unsigned a=addr-0x0c000000;uint32_t value=0;
                    unsigned source=3;
#ifdef SYNCHRONOUS_MACHINE
                    if(dmaBoot)source=4;
#endif
                    if(a==0)value=0x80000004U|aplicDomain;
                    if(a==source*4)value=aplicSource;
                    if(a==0x3000+source*4)value=aplicTarget;
                    if(a==0x1e00)value=aplicEnable;
                    if(store){uint32_t v=regs[(inst>>20)&31];++mmioWrites;
                        if(a==0)aplicDomain=v&256;
                        if(a==source*4){aplicSource=v&7;if(!aplicSource)aplicTarget=aplicEnable=0;}
                        if(a==0x3000+source*4 && aplicSource)aplicTarget=v&127;
                        if(a==0x1edc && v==source && aplicSource)aplicEnable|=1U<<source;
                        if(a==0x1fdc && v==source)aplicEnable&=~(1U<<source);
                    }else {++mmioReads;r.value=(inst&0x4000)?uint64_t(value):extend(value,32);}
                    return r;
                }
            }
#endif
#ifdef SYNCHRONOUS_MACHINE
            if(e->memory) {
                uint64_t addr=regs[(inst>>15)&31]+immediate(*e,inst);
                if(addr>=0x02000000 && addr<0x02010000) {
                    bool store=e->memory==2;unsigned bytes=1U<<((inst>>12)&3);if(store)r.rd=0;
                    bool time=addr==0x0200bff8||addr==0x0200bffc,compare=addr==0x02004000||addr==0x02004004;
                    if(!(time||compare)||(bytes!=4&&bytes!=8)||(addr&(bytes-1))){r.fault=true;r.cause=store?7:5;r.tval=addr;return r;}
                    auto before=time?timerTime:timerCompare;
                    if(store){auto v=regs[(inst>>20)&31];auto after=bytes==8?v:(addr&4)?((v&0xffffffff)<<32)|(before&0xffffffff):(before&0xffffffff00000000ULL)|(v&0xffffffff);
                        if(time)timerTime=after;else timerCompare=after;++timerWrites;
                    }else {auto value=bytes==8?before:(addr&4)?before>>32:before&0xffffffff;
                        check(!time||timerTime==0,"time reads while ticking require a bus-time oracle");
                        r.value=bytes==8||(inst&0x4000)?value:extend(value,32);
                    }
                    return r;
                }
                if(addr>=0x10001000 && addr<0x10001028) {
                    check(dmaBoot,"unexpected DMA access");bool store=e->memory==2;unsigned offset=addr-0x10001000;
                    check(((inst>>12)&7)==3 && offset%8==0,"DMA access shape");
                    if(store){r.rd=0;auto v=regs[(inst>>20)&31];
                        if(offset==0)dmaSource=v;if(offset==8)dmaDestination=v;if(offset==16)dmaLength=v;
                        if(offset==24){dmaControl=v&4;if(v&2)dmaStatus=0;
                            if(v&1){
                                check(dmaSource==dataBase+256&&dmaDestination==dataBase+2048&&dmaLength==1024,"DMA firmware descriptor");
                                check(aplicDomain==256&&aplicSource==6&&aplicTarget==4&&aplicEnable==16,"DMA interrupt configuration");
                                // Architectural oracle copies from independently committed CPU stores. Firmware
                                // accesses destination only after IRQ; precise completion timing is tested by dma.cpp.
                                for(unsigned i=0;i<dmaLength;++i)mem[dmaDestination-dataBase+i]=mem[dmaSource-dataBase+i];
                                reserved=false;dmaStatus=2;pending[4]=true;++dmaStarts;
                            }
                        }
                    }else r.value=offset==0?dmaSource:offset==8?dmaDestination:offset==16?dmaLength:offset==24?dmaControl:dmaStatus;
                    return r;
                }
                if(addr>=0x10000000 && addr<0x10000008) {
                    bool store=e->memory==2;unsigned a=addr-0x10000000;if(store)r.rd=0;
                    if(((inst>>12)&3)!=0){r.fault=true;r.cause=store?7:5;r.tval=addr;return r;}
                    unsigned value=0;bool dlab=uartLcr&128;
                    if(store){unsigned v=regs[(inst>>20)&31]&255;
                        if(a==0){if(dlab)uartDivisor=(uartDivisor&0xff00)|v;else uartWrites+=char(v);}
                        if(a==1){if(dlab)uartDivisor=(uartDivisor&255)|(v<<8);else uartIer=v&7;}
                        if(a==3)uartLcr=v;if(a==7)uartScratch=v;
                    }else{
                        if(a==0){value=dlab?uartDivisor&255:uartReceived?0x5a:0;if(!dlab)uartReceived=false;}
                        if(a==1)value=dlab?uartDivisor>>8:uartIer;
                        if(a==2)value=(uartReceived&&(uartIer&1))?4:1;
                        if(a==3)value=uartLcr;if(a==7)value=uartScratch;
                        check(a!=5,"time-dependent LSR requires a bus-time oracle");
                        r.value=(inst&0x4000)?value:extend(value,8);
                    }
                    return r;
                }
            }
#endif
            auto x=interpret(*e,inst,pc,regs,mem);
            r.value=x.result;r.next=x.nextPc;r.rd=x.rd;r.fault=x.fault;r.cause=x.cause;
            r.tval=x.target;return r;
        }
        unsigned funct=(inst>>12)&7,csr=inst>>20,src=(inst>>15)&31;
        if(!funct) {
            r.rd=0;
            if(inst==0x30200073&&mode==3) {
                r.next=epc;mode=(status>>11)&3;
                status=(status&~UINT64_C(0x1888))|((status&128)>>4)|128;
                if(mode!=3)status&=~(UINT64_C(1)<<17);
            } else if(inst==0x10200073&&mode>=1) {
                r.next=sepc;mode=(status>>8)&1;
                status=(status&~UINT64_C(0x122))|((status&32)>>4)|32;
            } else {r.fault=true;r.cause=inst==0x73?8+mode:inst==0x100073?3:2;r.tval=inst==0x100073?pc:inst==0x73?0:inst;}
            return r;
        }
        if(funct==4) {r.fault=true;r.cause=2;r.tval=inst;return r;}
        unsigned op=funct&3;
        bool write=op==1||src!=0,read=op!=1||r.rd!=0;
        uint64_t data=funct&4?src:regs[src],before=0;
        bool exists=true;
        switch(csr) {
        case 0x100:before=(status&0x122)|UINT64_C(0x200000000);break;
        case 0x104:before=interruptEnable&mideleg&546;break;
        case 0x106:before=scounterenTm?2:0;break;
        case 0x105:before=stvec;break;
        case 0x140:before=sscratch;break;case 0x141:before=sepc;break;
        case 0x142:before=scause;break;case 0x143:before=stval;break;
        case 0x144:before=((mideleg&512)&&deliveryS&&topS()?512:0)|
            ((mideleg&32)&&supervisorTimerPending()?32:0)|((mideleg&2)&&softwarePending?2:0);break;
        case 0x14d:before=stimecmp;break;
        case 0x150:before=sselect;break;
        case 0x15c:before=uint64_t(topS())*0x10001;break;
        case 0x151:
            if(sselect<0x70||sselect>255||(sselect>=0x80&&(sselect&1)))exists=false;
            else if(sselect==0x70)before=deliveryS;
            else if(sselect==0x72)before=thresholdS;
            else if(sselect>=0x80) {
                unsigned start=(sselect%64)*32;
                for(unsigned b=0;b<64&&start+b<128;++b)if((sselect<0xc0?pendingS[start+b]:enabledS[start+b]))before|=UINT64_C(1)<<b;
            }
            break;
        case 0x304:before=interruptEnable;break;
        case 0x344:before=(delivery&&top()?2048:0)|(deliveryS&&topS()?512:0)|(timerPending?128:0)|
            (supervisorTimerPending()?32:0)|(softwarePending?2:0);break;
        case 0x300:before=status;break;case 0x301:break;case 0x302:before=medeleg;break;
        case 0x3a0:case 0x3a2:
            if(!pmpAvailable)exists=false;
            else for(unsigned i=0;i<8;++i)before|=uint64_t(pmpCfg[i+(csr==0x3a2?8:0)])<<(8*i);
            break;
        case 0x303:before=mideleg;break;case 0x305:before=mtvec;break;
        case 0x306:before=mcounterenTm?2:0;break;case 0x30a:before=stce?UINT64_C(1)<<63:0;break;
        case 0xc01:before=timerTime;break;
        case 0x340:before=scratch;break;case 0x341:before=epc;break;case 0x342:before=cause;break;
        case 0x343:before=tval;break;case 0x350:before=select;break;
        case 0x35c:before=uint64_t(top())*0x10001;break;
        case 0x351:
            if(select<0x70||select>255||(select>=0x80&&(select&1)))exists=false;
            else if(select==0x70)before=delivery;
            else if(select==0x72)before=threshold;
            else if(select>=0x80) {
                unsigned start=(select%64)*32;
                for(unsigned b=0;b<64&&start+b<128;++b)if((select<0xc0?pending[start+b]:enabled[start+b]))before|=UINT64_C(1)<<b;
            }
            break;
        case 0xf11:case 0xf12:case 0xf13:case 0xf14:break;
        default:if(pmpAvailable&&csr>=0x3b0&&csr<0x3c0)before=pmpAddr[csr-0x3b0];
            else exists=false;
        }
        bool timeAccess=mode==3||(mcounterenTm&&(mode==1||scounterenTm));
        bool compareAccess=mode==3||(stce&&mcounterenTm);
        if(!exists||mode<((csr>>8)&3)||(write&&(csr>>10)==3)||
            (csr==0xc01&&!timeAccess)||(csr==0x14d&&!compareAccess)) {
            r.fault=true;r.cause=2;r.tval=inst;return r;
        }
        r.value=read?before:0;
        if(write) {
            uint64_t after=op==1?data:op==2?before|data:before&~data;
            switch(csr) {
            case 0x100:status=(status&~UINT64_C(0x122))|(after&0x122);break;
            case 0x104:interruptEnable=(interruptEnable&~(mideleg&UINT64_C(546)))|(after&mideleg&546);break;
            case 0x106:scounterenTm=after&2;break;
            case 0x144:if(mideleg&2)softwarePending=after&2;break;
            case 0x14d:stimecmp=after;break;
            case 0x105:stvec=(after&~UINT64_C(3))|((after&3)==1);break;
            case 0x140:sscratch=after;break;case 0x141:sepc=after&~UINT64_C(3);break;
            case 0x142:scause=after;break;case 0x143:stval=after;break;
            case 0x150:sselect=after&4095;break;
            case 0x15c:pendingS[topS()]=false;break;
            case 0x151:
                if(sselect==0x70)deliveryS=after&1;
                else if(sselect==0x72) {if(after<128)thresholdS=after;}
                else if(sselect>=0x80) {
                    unsigned start=(sselect%64)*32;
                    for(unsigned b=0;b<64&&start+b<128;++b)if(start+b)(sselect<0xc0?pendingS[start+b]:enabledS[start+b])=bool((after>>b)&1);
                }
                break;
            case 0x304:interruptEnable=after&2722;break;
            case 0x344:softwarePending=after&2;if(!stce)supervisorTimerSoftwarePending=after&32;break;
            case 0x306:mcounterenTm=after&2;break;
            case 0x30a:stce=after>>63;break;
            case 0x300:status=0xa00000000|(after&0x219aa);if(((status>>11)&3)==2)status|=0x1800;break;
            case 0x3a0:case 0x3a2:
                for(unsigned i=0;i<8;++i){unsigned j=i+(csr==0x3a2?8:0);
                    if(!(pmpCfg[j]&128)){
                        unsigned v=(after>>(8*i))&0x9f;
                        if((v&3)==2)v&=~2U;
                        pmpCfg[j]=v;
                    }
                }
                break;
            case 0x302:medeleg=after&0xb3ff;break;
            case 0x303:mideleg=after&546;break;
            case 0x305:mtvec=(after&~UINT64_C(3))|((after&3)==1);break;
            case 0x340:scratch=after;break;case 0x341:epc=after&~UINT64_C(3);break;
            case 0x342:cause=after;break;case 0x343:tval=after;break;case 0x350:select=after&4095;break;
            case 0x35c:pending[top()]=false;break;
            case 0x351:
                if(select==0x70)delivery=after&1;
                else if(select==0x72) {if(after<128)threshold=after;}
                else if(select>=0x80) {
                    unsigned start=(select%64)*32;
                    for(unsigned b=0;b<64&&start+b<128;++b)if(start+b)(select<0xc0?pending[start+b]:enabled[start+b])=bool((after>>b)&1);
                }
                break;
            default:
                if(csr>=0x3b0&&csr<0x3c0){unsigned i=csr-0x3b0;
                    bool nextLocked=i<15&&(pmpCfg[i+1]&128)&&((pmpCfg[i+1]>>3)&3)==1;
                    if(!(pmpCfg[i]&128)&&!nextLocked)pmpAddr[i]=after&((UINT64_C(1)<<54)-1);
                }
                break;
            }
        }
        return r;
    }
    void trap(const Result&r) {
        reserved=false;
        bool delegated=(r.cause>>63)?(((r.cause&~(UINT64_C(1)<<63))==9 && (mideleg&512))||
            ((r.cause&~(UINT64_C(1)<<63))==1 && (mideleg&2))||
            ((r.cause&~(UINT64_C(1)<<63))==5 && (mideleg&32))):
            (r.cause<64 && (medeleg&(UINT64_C(1)<<r.cause)));
        if(mode!=3 && delegated) {
            sepc=pc;scause=r.cause;stval=r.tval;
            status=(status&~UINT64_C(0x122))|((status&2)<<4)|(mode==1?0x100:0);
            mode=1;pc=(stvec&~UINT64_C(3))+((r.cause>>63)&&(stvec&1)?4*(r.cause&63):0);return;
        }
        epc=pc;cause=r.cause;tval=r.tval;
        status=(status&~UINT64_C(0x1888))|((status&8)<<4)|(uint64_t(mode)<<11);
        mode=3;pc=(mtvec&~UINT64_C(3))+((r.cause>>63)&&(mtvec&1)?4*(r.cause&63):0);
    }
};
static uint32_t addi(unsigned rd,unsigned rs,int n){return (uint32_t(n)&4095)<<20|rs<<15|rd<<7|0x13;}
static uint32_t csr(unsigned address,unsigned funct,unsigned rd,unsigned src){return address<<20|src<<15|funct<<12|rd<<7|0x73;}
static uint32_t branch(unsigned rs,int offset){unsigned x=offset;return ((x>>12)&1)<<31|((x>>5)&63)<<25|rs<<20|rs<<15|((x>>1)&15)<<8|((x>>11)&1)<<7|0x63;}
static void constant(std::vector<uint32_t>&p,unsigned rd,uint64_t value) {
    p.push_back(addi(rd,0,value>>56));for(int n=48;n>=0;n-=8){p.push_back(8U<<20|rd<<15|1<<12|rd<<7|0x13);p.push_back(addi(rd,rd,(value>>n)&255));}
}
static std::vector<uint32_t> setup() {
    std::vector<uint32_t> p;constant(p,1,vectorPc);p.push_back(csr(0x305,1,0,1));return p;
}
static bool injectMismatch=false,injectInterruptMismatch=false,injectMmioMismatch=false;
static bool headTrapShortMode=false,headTrapNegativeAttempted=false;
static bool authorizationShortMode=false,authorizationNegative=false;
static unsigned authorizationFenceDelay=0;
static uint64_t authorizationFencePc=0;
struct Counts {
    unsigned programs=0,commits=0,traps=0,mret=0,sret=0,csrOps=0,held=0,redirects=0;
    unsigned interrupts=0,emptyInterrupts=0,memoryInterrupts=0,storeInterrupts=0,priorityTraps=0;
    unsigned fastHeadTraps=0,emptyTrapEvents=0;
    unsigned systemOffers=0,systemBlocked=0,systemLsuCollisions=0,systemMCollisions=0;
    unsigned systemAcks=0,systemRepeatedRollback=0,systemProtectedCommitHolds=0,systemProtectedReleases=0;
    uint64_t cycles=0;
};
#ifdef SYNCHRONOUS_MACHINE
struct CacheStallCounts {
    unsigned full=0,exclusive=0,serialized=0,sameBeat=0,fill=0,lowerCapacity=0,lowerReady=0,ramRequest=0,ramResponse=0;
    void sample(SMachineCoreGsim& d) {
        full+=d.get_io$$cacheStalls$$full();exclusive+=d.get_io$$cacheStalls$$exclusive();
        serialized+=d.get_io$$cacheStalls$$serialized();sameBeat+=d.get_io$$cacheStalls$$sameBeat();
        fill+=d.get_io$$cacheStalls$$fill();lowerCapacity+=d.get_io$$cacheStalls$$lowerCapacity();
        lowerReady+=d.get_io$$cacheStalls$$lowerReady();ramRequest+=d.get_io$$ramRequestStall();
        ramResponse+=d.get_io$$ramResponseStall();
    }
    void print(const char* scope,unsigned seed) const {
        std::cout<<"CACHE_STALL scope="<<scope<<" seed="<<seed<<" full="<<full<<" exclusive="<<exclusive
          <<" serialized="<<serialized<<" sameBeat="<<sameBeat<<" fill="<<fill
          <<" lowerCapacity="<<lowerCapacity<<" lowerReady="<<lowerReady
          <<" ramRequest="<<ramRequest<<" ramResponse="<<ramResponse<<"\n";
    }
};
struct FetchWaitCounts {
    unsigned total=0,duringDma=0,enabled=0,enabledDuringDma=0;
    void sample(SMachineCoreGsim& d,bool commitEnabled) {
        if(!d.get_io$$fetchWait())return;
        ++total;
        if(d.get_io$$dmaActive())++duringDma;
        if(commitEnabled){++enabled;if(d.get_io$$dmaActive())++enabledDuringDma;}
    }
    void print(unsigned seed) const {
        std::cout<<"FETCH_WAIT seed="<<seed<<" total="<<total<<" duringDma="<<duringDma
          <<" enabled="<<enabled<<" enabledDuringDma="<<enabledDuringDma<<"\n";
    }
};
#endif
static void program(const char*library,std::vector<uint32_t> code,unsigned seed,bool useNemu,Counts&counts,const std::vector<uint32_t>& customHandler={},unsigned irqScenario=0,uint64_t triggerPc=0,bool fenceScenario=false,bool timerScenario=false) {
    unsigned cpuDuringDma=0,dmaRequests=0,dmaCycles=0,releaseDataBeats=0,probeAckDataBeats=0;
    unsigned lineFillsLow=0,lineFillsHigh=0;
    unsigned irqCount=0,emptyWait=0,holdFault=0,busWrites=0,committedStores=0;bool injected=false,sawMemory=false;
#ifdef SYSTEM_AUTHORIZATION_FIXTURE
    bool expectedSystemProtected=false,systemOfferHeld=false,systemBoundaryAcknowledged=false;
    unsigned expectedSystemIndex=0,heldSystemIndex=0,authorizationFenceCycles=0;
    uint64_t expectedSystemTag=0,heldSystemTag=0;
#endif
#ifdef SYNCHRONOUS_MACHINE
    uint64_t stop=firmwareStop;
#else
    uint64_t stop=base+4*code.size();
    code.resize((vectorPc-base)/4,0);
    std::vector<uint32_t> handler{csr(0x342,2,26,0),csr(0x343,2,27,0),csr(0x341,2,28,0),
        csr(0x300,2,29,0),addi(28,28,4),csr(0x341,1,0,28),0x30200073};
    if(!customHandler.empty())handler=customHandler;
    code.insert(code.end(),handler.begin(),handler.end());
#endif
    SMachineCoreGsim d;
#ifdef SYSTEM_AUTHORIZATION_FIXTURE
    d.set_systemFenceHold(0);
#endif
    d.set_io$$programHold(0);d.set_io$$programWrite(0);d.set_io$$programIndex(0);d.set_io$$programData(0);
    d.set_io$$timerInterrupt(0);d.set_io$$timerTick(0);d.set_io$$timeValue(0);
    d.set_io$$sources(0);d.set_io$$uartRx(1);
    d.set_io$$instruction0$$valid(0);d.set_io$$instruction0$$bits(0);d.set_io$$instruction1$$valid(0);d.set_io$$instruction1$$bits(0);
    d.set_io$$commitEnable(0);d.set_io$$inspectRegister(0);
    d.set_io$$memory$$request$$ready(0);d.set_io$$memory$$response$$valid(0);
    d.set_io$$memory$$response$$bits$$data(0);d.set_io$$memory$$response$$bits$$error(0);
    d.set_io$$msi$$request$$valid(0);d.set_io$$msi$$request$$bits$$address(0x24000000);
    d.set_io$$msi$$request$$bits$$data(0);d.set_io$$msi$$request$$bits$$size(2);
    d.set_io$$msi$$request$$bits$$byteEnable(15);d.set_io$$msi$$request$$bits$$write(1);d.set_io$$msi$$response$$ready(1);
    d.set_reset(1);d.step();d.step();d.set_reset(0);
#ifdef SYNCHRONOUS_MACHINE
    d.set_io$$programHold(1);d.step();d.step();
    check(code.size()<=2048,"ROM image overflow");
    for(unsigned i=0;i<2048;++i){d.set_io$$programWrite(1);d.set_io$$programIndex(i);d.set_io$$programData(i<code.size()?code[i]:0);d.step();}
    d.set_io$$programWrite(0);d.step();d.set_io$$programHold(0);
#endif
    SystemModel m;Memory mem{},busMem{};
#ifdef WIRED_APLIC
    auto configure=[&](unsigned offset,unsigned value) {
        d.set_io$$msi$$request$$valid(1);d.set_io$$msi$$request$$bits$$address(0x0c000000+offset);
        d.set_io$$msi$$request$$bits$$data(value);
        for(unsigned n=0;;++n){d.step();if(d.get_io$$msi$$request$$ready())break;check(n<100,"APLIC configure timeout");}
        d.set_io$$msi$$request$$valid(0);
        for(unsigned n=0;;++n){d.step();if(d.get_io$$msi$$response$$valid()){check(!d.get_io$$msi$$response$$bits$$error(),"APLIC configuration error");break;}check(n<100,"APLIC response timeout");}
    };
    for(unsigned id:{3U,5U,7U}){configure(id*4,4);configure(0x3000+id*4,id);configure(0x1edc,id);}
    configure(0,256);
#endif
    if(!privilegeBoot && !useNemu &&
        ((irqScenario<4 && !fenceScenario && !timerScenario)||irqScenario==9||irqScenario==11)) {
        #ifdef WIRED_APLIC
        d.set_io$$sources((1U<<2)|(1U<<4)|(1U<<6));for(unsigned i=0;i<20;++i)d.step();
        for(unsigned id:{3U,5U,7U})m.pending[id]=true;
        d.set_io$$sources(0);d.step();d.step();
#else
        if(irqScenario==11) {
            for(auto [address,id]:{std::pair<uint64_t,unsigned>{0x24000000,3}, {0x28000000,5}}) {
                d.set_io$$msi$$request$$valid(1);d.set_io$$msi$$request$$bits$$address(address);
                d.set_io$$msi$$request$$bits$$data(id);d.step();check(d.get_io$$msi$$request$$ready(),"MSI preload backpressure");
                if(address==0x28000000)m.pendingS[id]=true;else m.pending[id]=true;
            }
        } else for(unsigned id:{3U,5U,7U}) {d.set_io$$msi$$request$$valid(1);d.set_io$$msi$$request$$bits$$data(id);d.step();check(d.get_io$$msi$$request$$ready(),"MSI preload backpressure");m.pending[id]=true;}
        d.set_io$$msi$$request$$valid(0);d.step();d.step();
#endif
    }
    std::unique_ptr<Reference> ref;
    if(useNemu){ref=std::make_unique<Reference>(library);ref->machineReset();ref->load(code);ref->initializeMemory(mem);}
    struct MemoryReply {uint64_t data;bool error;unsigned due;bool write;};
    std::deque<MemoryReply> replies;
    std::mt19937_64 rng(seed);
    uint64_t fetch=base;
    uint64_t lastTrapPc=0,lastTrapCause=0,lastTrapValue=0;
    unsigned protectedFetchGets=0,protectedNarrowGets=0;
    std::array<unsigned,BRANCH_ENTRIES> direction;direction.fill(1);
    bool finished=false;
#ifdef SYNCHRONOUS_MACHINE
    int serialStart=-1,timerStart=-1;
    CacheStallCounts allStalls,dmaStalls;
    FetchWaitCounts fetchWaits;
    bool timerIrq=false;unsigned timerPulses=0;
    unsigned txPhase=0,txTimer=0,txByte=0;
    std::string serialOutput;
#endif
    for(unsigned cycle=0;cycle<200000;++cycle) {
        bool supply=seed==0||rng()%5!=0,allow=seed==0||rng()%4!=0;
#ifdef SYSTEM_AUTHORIZATION_FIXTURE
        bool fenceHold=false;
        if(authorizationShortMode && m.pc==authorizationFencePc) {
            const unsigned phase=authorizationFenceCycles++;
            fenceHold=phase<authorizationFenceDelay;
            // Start remains authorized under the original commitEnable/drain
            // rules. A later, bounded commit stall tests protection release.
            if(phase>=authorizationFenceDelay+2 && phase<authorizationFenceDelay+7)allow=false;
        }
        d.set_systemFenceHold(fenceHold);
#endif
        bool pause=irqScenario==4 && fetch>=triggerPc && fetch<vectorPc && irqCount==0;
        if(pause)supply=false;
        if(pause && m.pc==triggerPc)++emptyWait;
        if(irqScenario==7 && m.pc==triggerPc && irqCount==0 && holdFault<40){++holdFault;allow=false;}
        bool sendMsi=!injected && ((irqScenario==4 && emptyWait>=20) ||
            ((irqScenario==5 || irqScenario==6) && sawMemory) || (irqScenario==7 && holdFault>=20) ||
            ((irqScenario==8 || irqScenario==10) && m.pc>=triggerPc && m.pc<vectorPc));
#ifdef SYNCHRONOUS_MACHINE
        sendMsi = !dmaBoot && !timerBoot && !sstcBoot && !privilegeBoot && !injected &&
            m.pc >= triggerPc && m.pc < firmwareStop;
#endif
#if defined(WIRED_APLIC) || defined(MAPPED_APLIC)
        d.set_io$$msi$$request$$valid(0);d.set_io$$sources(sendMsi?4:0);
#ifdef SYNCHRONOUS_MACHINE
        if(serialBoot && !privilegeBoot){
            d.set_io$$sources(0);
            if(sendMsi)serialStart=cycle;
            int elapsed=serialStart<0?-1:int(cycle)-serialStart;
            unsigned bit=elapsed<0?10:unsigned(elapsed)/16;
            d.set_io$$uartRx(bit==0?0:bit>=9?1:(0x5a>>(bit-1))&1);
            // The wire stop-bit midpoint is the earliest valid completion. DUT adds RX synchronizer latency.
            if(elapsed==152){m.uartReceived=true;m.pending[3]=true;}
        }
#endif
#else
        d.set_io$$msi$$request$$valid(sendMsi);
        d.set_io$$msi$$request$$bits$$address(irqScenario==10?0x28000000:0x24000000);
        d.set_io$$msi$$request$$bits$$data(irqScenario==10?5:3);
#endif
        for(unsigned lane=0;lane<2;++lane) {
            uint64_t pc=fetch+4*lane;bool valid=supply&&pc>=base&&(pc-base)/4<code.size()&&pc!=stop && !(irqScenario==4 && pc==triggerPc && irqCount==0);
            uint32_t inst=valid?code[(pc-base)/4]:0;
            if(lane==0){d.set_io$$instruction0$$valid(valid);d.set_io$$instruction0$$bits(inst);}
            else{d.set_io$$instruction1$$valid(valid);d.set_io$$instruction1$$bits(inst);}
            if(!valid)supply=false;
        }
#ifdef SYNCHRONOUS_MACHINE
        bool timerPulse=false;
        if(timerBoot || sstcBoot){
            if(timerStart<0 && m.pc>=triggerPc && m.pc<firmwareStop)timerStart=cycle;
            timerPulse=timerStart>=0 && (cycle-unsigned(timerStart))%4==0 && (!sstcBoot || m.timerTime<5);
            d.set_io$$timerTick(timerPulse);
            if(timerBoot)m.timerPending=timerIrq;
        }
#endif
        if(timerScenario){
            if(sendMsi||irqScenario==9||irqScenario==3){m.timerPending=true;injected=true;}
            d.set_io$$timerInterrupt(m.timerPending);
            d.set_io$$msi$$request$$valid(0);d.set_io$$sources(0);sendMsi=false;
        }
#ifndef SYNCHRONOUS_MACHINE
        if(irqScenario==14 && m.pc>=triggerPc && m.pc<vectorPc)m.timerTime=5;
        d.set_io$$timeValue(m.timerTime);
#endif
        bool nextSupervisorTimerHardwarePending=m.timerTime>=m.stimecmp;
        d.set_io$$commitEnable(allow);d.set_io$$inspectRegister(cycle%32);
        bool ready=seed==0||rng()%3!=0;
        bool response=!replies.empty()&&replies.front().due<=cycle;
        d.set_io$$memory$$request$$ready(ready);d.set_io$$memory$$response$$valid(response);
        d.set_io$$memory$$response$$bits$$data(response?replies.front().data:0);
        d.set_io$$memory$$response$$bits$$error(response&&replies.front().error);
        d.step();
#if REGISTERED_FETCH_PACKET
        const bool headAccepted=d.get_headTrapAccepted(),emptyAccepted=d.get_emptyTrapAccepted();
        check(!(headAccepted&&emptyAccepted),"nonempty/empty trap boundaries must be exclusive");
        check(!(headAccepted||emptyAccepted)||d.get_io$$trap$$valid(),"trap recovery witness without architectural trap");
        counts.fastHeadTraps+=headAccepted;
        counts.emptyTrapEvents+=emptyAccepted;
#endif
#ifdef SYSTEM_AUTHORIZATION_FIXTURE
        const bool systemValid=d.get_systemOfferValid(),systemReady=d.get_systemOfferReady();
        const bool systemRedirect=systemValid&&d.get_systemOfferRedirect();
        const bool systemAck=systemRedirect&&d.get_systemRecoveryAck();
        const bool systemMatch=d.get_systemRedirectMatch();
        check(bool(d.get_systemProtectedSeen())==expectedSystemProtected,"system protection lifetime oracle");
        if(expectedSystemProtected)
            check(d.get_systemOwnerIndex()==expectedSystemIndex && d.get_systemOwnerTag()==expectedSystemTag,
                "protected system owner changed before precise release");
        if(systemOfferHeld)
            check(systemValid && d.get_systemOfferIndex()==heldSystemIndex &&
                d.get_systemOfferTag()==heldSystemTag,"system completion token changed under backpressure");
        if(systemValid) {
            check(expectedSystemProtected && d.get_systemOfferIndex()==expectedSystemIndex &&
                d.get_systemOfferTag()==expectedSystemTag,"completion does not own protected system transaction");
            ++counts.systemOffers;
            if(!systemReady) {
                ++counts.systemBlocked;
                counts.systemLsuCollisions+=d.get_systemLsuComplete();
                counts.systemMCollisions+=d.get_systemMComplete();
            }
        }
        check(bool(d.get_systemInvalidated())==
            (bool(d.get_systemInvalidateRequested())&&systemMatch),"system invalidate bypassed redirect token match");
        if(systemRedirect && !systemMatch)
            check(!systemReady,"unmatched system redirect consumed completion");
        if(systemBoundaryAcknowledged && d.get_io$$recovering() && systemRedirect) {
            check(!systemAck && !systemReady,"duplicate retain-one recovery acknowledged or consumed completion");
            ++counts.systemRepeatedRollback;
        }
        if(systemAck) {
            auto expected=m;auto expectedMemory=mem;
            const auto result=expected.step(code[(m.pc-base)/4],expectedMemory);
            uint64_t target=result.next;
            if(authorizationNegative){target^=4;authorizationNegative=false;}
            check(!result.fault && d.get_io$$redirect$$valid() && systemMatch &&
                d.get_io$$redirect$$bits$$pc()==m.pc && d.get_io$$redirect$$bits$$target()==target,
                "system redirect architectural oracle mismatch");
            check(!d.get_io$$commit0$$valid()&&!d.get_io$$commit1$$valid(),
                "system redirect retired through recovery");
            ++counts.systemAcks;systemBoundaryAcknowledged=true;
        }
        counts.systemProtectedCommitHolds+=expectedSystemProtected&&!allow;
        systemOfferHeld=systemValid&&!systemReady;
        heldSystemIndex=d.get_systemOfferIndex();heldSystemTag=d.get_systemOfferTag();
        if(systemValid&&systemReady&&d.get_systemOfferException()) {
            expectedSystemProtected=false;++counts.systemProtectedReleases;
        }
        if(systemValid&&systemReady)systemBoundaryAcknowledged=false;
        if(d.get_systemStartSeen()) {
            check(!expectedSystemProtected && d.get_systemStartPc()==m.pc,
                "system start must be at the independent architectural head");
            expectedSystemProtected=true;
            expectedSystemIndex=d.get_systemStartIndex();expectedSystemTag=d.get_systemStartTag();
        }
#endif
#ifdef SYNCHRONOUS_MACHINE
        if(privilegeBoot && d.get_io$$fetchGetFire()) {
            ++protectedFetchGets;
            const uint64_t address=d.get_io$$fetchGetAddress();
            const unsigned size=d.get_io$$fetchGetSize();
            check(size==2||size==3,"instruction TileLink Get size");
            if(m.pmpCfg[0]&128) {
                const uint64_t forbidden=m.pmpAddr[0]<<2;
                check(address+(UINT64_C(1)<<size)<=forbidden || address>=forbidden+4,
                    "PMP-denied instruction word reached TileLink A");
                if(address==forbidden-4) {
                    check(size==2,"PMP boundary fetched an oversized beat");
                    ++protectedNarrowGets;
                }
            }
        }
        if(serialBoot){
            bool tx=d.get_io$$uartTx();
            if(!txPhase){if(!tx){txPhase=1;txTimer=23;txByte=0;}}
            else if(txTimer)--txTimer;
            else if(txPhase<=8){txByte|=unsigned(tx)<<(txPhase-1);++txPhase;txTimer=15;}
            else {check(tx,"boot UART stop bit");serialOutput+=char(txByte);txPhase=0;}
        }
#endif
#ifdef SYNCHRONOUS_MACHINE
        if(timerBoot || sstcBoot){
            if(timerBoot)timerIrq=m.timerTime>=m.timerCompare;
            if(timerPulse){++m.timerTime;++timerPulses;}
        }
#endif
        check(!d.get_io$$msiError(),"APLIC MSI transport error");
        check(d.get_io$$committedValue()==m.regs[cycle%32],"architectural register inspection");
        if(d.get_io$$redirect$$valid())++counts.redirects;
#ifdef SYNCHRONOUS_MACHINE
        allStalls.sample(d);
        fetchWaits.sample(d,allow);
        if(d.get_io$$dmaActive())dmaStalls.sample(d);
        if(d.get_io$$dmaActive()){++dmaCycles;if(d.get_io$$cpuMemoryFire())++cpuDuringDma;}
        if(d.get_io$$dmaMemoryFire())++dmaRequests;
        if(d.get_io$$coherentReleaseData())++releaseDataBeats;
        if(d.get_io$$coherentProbeAckData())++probeAckDataBeats;
        if(d.get_io$$lineFillGetFire()){
            const uint64_t address=d.get_io$$lineFillGetAddress();
            if(address>=UINT64_C(0x80010000)&&address<UINT64_C(0x80010800))++lineFillsLow;
            else if(address>=UINT64_C(0x80010800)&&address<UINT64_C(0x80011000))++lineFillsHigh;
            else throw std::runtime_error("cache line fill outside split RAM");
        }
#endif
        if(!allow)++counts.held;
        if(response&&d.get_io$$memory$$response$$ready())replies.pop_front();
        if(d.get_io$$memory$$request$$valid()&&ready) {
            auto addr=d.get_io$$memory$$request$$bits$$address();
#ifdef MAPPED_APLIC
            check(addr<0x0c000000 || addr>=0x0c004000,"APLIC request escaped to RAM");
#endif
            bool write=d.get_io$$memory$$request$$bits$$write();
            bool error=addr<dataBase||addr>=dataBase+mem.size();uint64_t data=0;
            check(!write || irqScenario==6 || irqScenario==8 || fenceScenario,"unexpected or wrong-path store reached bus");
            if(write) {
                check(!error,"bad test store address");++busWrites;
                auto data=d.get_io$$memory$$request$$bits$$data();auto mask=d.get_io$$memory$$request$$bits$$mask();
                for(unsigned i=0;i<8;++i)if(mask&(1U<<i))busMem[((addr-dataBase)&~7U)+i]=data>>(8*i);
            }
            if(fenceScenario&&!write)for(const auto& prior:replies)check(!prior.write,"load crossed FENCE before store response");
            sawMemory=true;
            if(!error)for(unsigned i=0;i<8;++i)data|=uint64_t(busMem[((addr-dataBase)&~7U)+i])<<(8*i);
            replies.push_back({data,error,cycle+((irqScenario==5 || irqScenario==6 ||
                (fenceScenario&&!authorizationShortMode))?80:3)+unsigned(rng()%5),write});
        }
        uint64_t predictedFetch=fetch+4*(d.get_io$$accepted0()+d.get_io$$accepted1());
#if !defined(SYNCHRONOUS_MACHINE) && !REGISTERED_FETCH_PACKET
        for(unsigned lane=0;lane<2;++lane)if(lane==0?d.get_io$$accepted0():d.get_io$$accepted1()) {
            uint64_t pc=fetch+4*lane;auto inst=code[(pc-base)/4];
            if((inst&127)==0x63 && direction[(pc/4)%direction.size()]>=2) {
                auto e=decode(inst);predictedFetch=pc+immediate(*e,inst);break;
            }
        }
#endif
        auto commit=[&](bool valid,uint64_t pc,uint32_t inst,unsigned rd,uint64_t value,uint64_t next) {
            if(!valid)return;
            check(allow,"commit under backpressure");check(pc==m.pc,"commit PC mismatch: "+std::to_string(pc)+" vs "+std::to_string(m.pc));
            check(inst==code[(pc-base)/4],"commit instruction mismatch");
            if((irqScenario>=1 && irqScenario<=4)||irqScenario==10||irqScenario==11)check(!m.irq(),"younger retirement before eligible interrupt");
            if(irqScenario==10 && inst==csr(0x100,6,0,2))check(m.pendingS[5],"S interrupt did not wait behind SIE mask");
            if(irqScenario==10 && inst==0x10200073 && irqCount==0)check(m.pendingS[5],"S interrupt not pending at U-mode handoff");
            if(fenceScenario && ((inst&0x707f)==0x0f || (inst&0x707f)==0x100f))
                for(const auto& prior:replies)check(!prior.write,"FENCE retired before store response");
            auto x=m.step(inst,mem);check(!x.fault,"faulting instruction retired");
#ifdef MAPPED_APLIC
            if(injectMmioMismatch && (inst&127)==3 && m.regs[(inst>>15)&31]==0x0c000000){x.value^=1;injectMmioMismatch=false;}
#endif
            if(injectMismatch && (inst&127)==0x73 && x.rd) {x.value^=1;injectMismatch=false;}
            check(rd==x.rd&&next==x.next&&(rd==0||value==x.value),"commit data/nextPC at "+std::to_string(pc)+" inst="+std::to_string(inst));
            if((inst&127)==0x23) {
                auto e=decode(inst);auto value=m.regs[(inst>>20)&31];
                auto address=m.regs[(inst>>15)&31]+immediate(*e,inst);
                if(address>=dataBase && address<dataBase+mem.size()){
                    for(unsigned i=0;i<(1U<<((inst>>12)&7));++i)mem[address-dataBase+i]=value>>(8*i);
                    if((address>>6)==(m.reservation>>6))m.reserved=false;
                    ++committedStores;
                }
            }
            if(rd)m.regs[rd]=x.value;m.pc=x.next;++counts.commits;
            if((inst&127)==0x73&&((inst>>12)&7))++counts.csrOps;
            if(inst==0x30200073)++counts.mret;
            if(inst==0x10200073)++counts.sret;
            if((inst&127)==0x63){auto& c=direction[(pc/4)%direction.size()];if(next!=pc+4){if(c<3)++c;}else if(c)--c;}
            if(ref) {
                ref->compare(m.regs,m.pc);auto s=ref->inspectState();
                check(s.mepc==m.epc&&s.mcause==m.cause&&s.mtval==m.tval&&s.mtvec==m.mtvec&&s.mscratch==m.scratch,
                    "NEMU CSR state mismatch");
                check(s.mstatus==m.status&&s.mode==m.mode,"NEMU status/privilege mismatch");
            }
        };
#define COMMIT(N) commit(d.get_io$$commit##N##$$valid(),d.get_io$$commit##N##$$bits$$pc(),d.get_io$$commit##N##$$bits$$instruction(),d.get_io$$commit##N##$$bits$$rd(),d.get_io$$commit##N##$$bits$$data(),d.get_io$$commit##N##$$bits$$nextPc())
        COMMIT(0);COMMIT(1);
#undef COMMIT
#ifdef SYSTEM_AUTHORIZATION_FIXTURE
        auto systemRetired=[&](bool valid,unsigned index,uint64_t tag) {
            if(valid&&expectedSystemProtected&&index==expectedSystemIndex&&tag==expectedSystemTag) {
                expectedSystemProtected=false;++counts.systemProtectedReleases;
            }
        };
        systemRetired(d.get_io$$commit0$$valid(),d.get_io$$commit0$$bits$$token$$index(),
            d.get_io$$commit0$$bits$$token$$tag());
        systemRetired(d.get_io$$commit1$$valid(),d.get_io$$commit1$$bits$$token$$index(),
            d.get_io$$commit1$$bits$$token$$tag());
#endif
        if(d.get_io$$trap$$valid()) {
            check(!d.get_io$$commit0$$valid()&&!d.get_io$$commit1$$valid()&&allow,"trap/retirement ordering");
            SystemModel::Result fault;
            if(d.get_io$$trap$$bits$$cause()>>63) {
                check(irqScenario && m.irq(),"masked or unsolicited interrupt");
                check(replies.empty(),"interrupt before memory drain");
                fault.cause=UINT64_C(0x8000000000000000)|m.irqCause();fault.fault=true;
                if(injectInterruptMismatch){
                    fault.cause^=1;injectInterruptMismatch=false;
                    headTrapNegativeAttempted=headTrapShortMode;
                }
                ++irqCount;++counts.interrupts;
                if(irqScenario==10)check(d.get_io$$externalPending()&2,"S IMSIC signal missing at trap");
                if(irqScenario==11)check((fault.cause&63)==(irqCount==1?11U:9U),"M/S interrupt priority");
                if(irqScenario==13)check(m.mode==0 && (fault.cause&63)==1,"U-mode SSIP delivery");
#ifdef SYNCHRONOUS_MACHINE
                if(sstcBoot)check(m.mode==1 && (fault.cause&63)==5 && m.timerTime==5,
                    "platform Sstc interrupt timing and privilege");
#endif
                if(irqScenario==4){check(emptyWait>=20 && m.pc==triggerPc,"empty ROB interrupt PC");++counts.emptyInterrupts;}
                if(irqScenario==5){check(sawMemory,"memory interrupt not exercised");++counts.memoryInterrupts;}
                if(irqScenario==6){check(busWrites && busWrites==committedStores && busMem==mem,"store drain/retirement mismatch");++counts.storeInterrupts;}
                if(irqScenario==7)check(counts.priorityTraps>0 && m.pc==triggerPc+4,"synchronous trap priority");
            } else {
                fault=m.step(code[(m.pc-base)/4],mem);check(fault.fault,"unexpected synchronous trap");
                if(irqScenario==7){check(irqCount==0 && m.irq() && holdFault==40,"simultaneous exception/IRQ not covered");++counts.priorityTraps;}
            }
            check(d.get_io$$trap$$bits$$pc()==m.pc&&d.get_io$$trap$$bits$$cause()==fault.cause&&d.get_io$$trap$$bits$$tval()==fault.tval,"trap metadata");
            lastTrapPc=m.pc;lastTrapCause=fault.cause;lastTrapValue=fault.tval;
            m.trap(fault);++counts.traps;
            check(d.get_io$$redirect$$valid()&&d.get_io$$redirect$$bits$$target()==m.pc,"trap redirect");
            if(ref)ref->compare(m.regs,m.pc);
        }
#if !defined(SYNCHRONOUS_MACHINE) && !REGISTERED_FETCH_PACKET
        check(d.get_io$$fetchPc()==fetch,"fetch prediction model mismatch scenario="+std::to_string(irqScenario)+" seed="+std::to_string(seed)+" cycle="+std::to_string(cycle)+" expected="+std::to_string(fetch)+" actual="+std::to_string(d.get_io$$fetchPc()));
#endif
        // Outputs are pre-edge; compute next fetch PC using acceptance and the authoritative redirect.
        fetch=d.get_io$$redirect$$valid()?d.get_io$$redirect$$bits$$target():predictedFetch;
#if REGISTERED_FETCH_PACKET
        // The FIFO's raw supply cursor is NOT the architectural admission PC.
        // Only drive the external instruction device from the next cursor;
        // retirement/trap PCs still come exclusively from SystemModel above.
        fetch=d.get_nextFetchPc();
        check((fetch&3)==0,"unaligned raw instruction fetch cursor");
#endif
#if defined(WIRED_APLIC) || defined(MAPPED_APLIC)
        if(sendMsi){
#ifdef MAPPED_APLIC
            check(m.aplicDomain==256 && m.aplicTarget==3 && m.aplicEnable==8,"firmware failed APLIC configuration");
#ifdef SYNCHRONOUS_MACHINE
            check(m.aplicSource==(serialBoot?6U:4U),"firmware source mode");
            if(serialBoot)check(m.uartIer==1&&m.uartDivisor==1&&m.uartLcr==3,"firmware UART configuration");
#else
            check(m.aplicSource==4,"firmware source mode");
#endif
#endif
            injected=true;
#ifdef SYNCHRONOUS_MACHINE
            if(!serialBoot)m.pending[3]=true;
#else
            m.pending[3]=true;
#endif
        }
#else
        if(sendMsi&&d.get_io$$msi$$request$$ready()) {
            if(irqScenario==10)m.pendingS[5]=true;else m.pending[3]=true;
            injected=true;
        }
#endif
        m.supervisorTimerHardwarePending=nextSupervisorTimerHardwarePending;
        if(m.pc==stop){
#ifdef SYNCHRONOUS_MACHINE
            if(sstcBoot){
                check(m.regs[10]==42 && mem[0]==1 && mem[8]==5 && mem[15]==0x80 &&
                    mem[16]==5 && mem[24]==0 && m.timerTime==5 && m.stimecmp==100 && m.mode==1,
                    "Sstc platform completion signature");
            }else if(privilegeBoot){
                check(m.mode==1 && m.regs[10]==42 && mem[0]==6 && mem[8]==42 && mem[16]==1,
                    "privilege UART completion signature");
                if(protectedFetchGets)
                    check(protectedNarrowGets>0,"PMP fetch boundary lacked a narrow TileLink Get");
            }else check(m.regs[10]==376 && mem[0]==(timerBoot?2:1) && mem[8]==0x78 && mem[9]==1,
                "boot completion signature");
            if(serialBoot){
                if(injectSerialMismatch)serialOutput[0]^=1;
                check(serialOutput==(privilegeBoot?"SU!\n":"OK\n") && serialOutput==m.uartWrites,
                    "boot serial output mismatch: decoded="+std::to_string(serialOutput.size())+
                    " model="+std::to_string(m.uartWrites.size()));
                if(!privilegeBoot)check(mem[16]==0x5a&&!m.uartReceived,"boot UART receive signature");
            }
            if(dmaBoot){
                check(m.dmaStarts==1&&m.dmaStatus==0&&mem[32]==1,"DMA boot completion signature");
                check(cpuDuringDma>0&&dmaRequests==256,"CPU/DMA overlap coverage");
                std::cout<<"DMA activeCycles="<<dmaCycles<<" requests="<<dmaRequests<<" cpuRequestsWhileActive="<<cpuDuringDma<<"\n";
            }
            if(timerBoot){check(m.timerWrites==6&&timerPulses>=200&&m.timerCompare==~UINT64_C(0),"timer boot coverage");
                std::cout<<"timer pulses="<<timerPulses<<" reloads=2\n";}
            if(sstcBoot)check(timerPulses==5 && irqCount==1,"Sstc platform tick/interrupt coverage");
            if(atomicBoot)check(m.atomicCount>=70,"atomic boot coverage");
            allStalls.print("boot",seed);
            if(dmaBoot)dmaStalls.print("dma",seed);
            fetchWaits.print(seed);
            std::cout<<"COHERENCE releaseDataBeats="<<releaseDataBeats
                <<" probeAckDataBeats="<<probeAckDataBeats<<"\n";
            std::cout<<"LINE_FILL low="<<lineFillsLow<<" high="<<lineFillsHigh<<"\n";
#if SPLIT_COHERENT
            if(!dmaBoot)check(lineFillsLow>0&&lineFillsHigh>0,
                "CPU did not issue 64-byte line fills to both TileLink RAM banks");
#endif
            std::cout<<(privilegeBoot?"privilege-uart ":sstcBoot?"sstc ":atomicBoot?"atomic ":
                timerBoot?"timer ":dmaBoot?"dma ":serialBoot?"uart ":"ram ")
                <<"boot seed="<<seed<<" cycles="<<cycle+1<<" result="<<m.regs[10]
                <<(privilegeBoot?" trap_counter=":" irq_counter=")<<unsigned(mem[0])<<"\n";
#endif
            check(d.get_io$$externalPending()==(unsigned(m.delivery&&m.top()!=0)|
                (unsigned(m.deliveryS&&m.topS()!=0)<<1)),"IMSIC external pending routing");
            counts.cycles+=cycle+1;
            finished=true;break;
        }
    }
    check(finished,"program timeout scenario="+std::to_string(irqScenario)+
        " pc="+std::to_string(m.pc)+" fetch="+std::to_string(fetch)+
        " commits="+std::to_string(counts.commits)+" traps="+std::to_string(counts.traps)+
        " counter="+std::to_string(unsigned(mem[0]))+
        " lastTrapPc="+std::to_string(lastTrapPc)+" lastTrapCause="+std::to_string(lastTrapCause)+
        " lastTrapValue="+std::to_string(lastTrapValue)+" a3="+std::to_string(m.regs[13]));
    bool twoInterrupts=irqScenario==9 || irqScenario==11;
#ifdef SYNCHRONOUS_MACHINE
    twoInterrupts|=timerBoot;
#endif
    if(irqScenario)check(irqCount==(twoInterrupts?2U:(timerScenario||irqScenario>=4)?1U:3U),
        "interrupt claim/retrigger coverage scenario="+std::to_string(irqScenario)+" seed="+std::to_string(seed)+
        " count="+std::to_string(irqCount)+" pending="+std::to_string(m.softwarePending)+
        " mode="+std::to_string(m.mode));
#ifdef MAPPED_APLIC
#ifdef SYNCHRONOUS_MACHINE
    if(!timerBoot && !sstcBoot && !privilegeBoot)
#endif
    check(m.mmioReads>=5 && m.mmioWrites>=5,"mapped MMIO coverage");
#endif
    ++counts.programs;
}
// One shared construction for the existing full IRQ route and the focused
// head-trap route. Keep the instructions, handler and independent oracle intact.
static void machineInterruptProgram(const char*library,unsigned scenario,unsigned seed,
    bool timerScenario,Counts&counts) {
    auto p=setup();
    if(scenario==2 || (timerScenario && scenario==4)){constant(p,1,vectorPc|1);p.push_back(csr(0x305,1,0,1));}
    p.push_back(addi(1,0,0xc0));p.push_back(csr(0x350,1,0,1));
    p.push_back(addi(2,0,-1));p.push_back(csr(0x351,1,0,2));
    p.push_back(addi(1,0,0x70));p.push_back(csr(0x350,1,0,1));p.push_back(csr(0x351,5,0,1));
    p.push_back(csr(0x344,1,4,0)); // MEIP is read-only even under CSR write.
    p.push_back(csr(0x344,2,5,0));
    p.push_back(csr(0x304,1,6,2)); // Unsupported enable bits must read zero.
    p.push_back(csr(0x304,2,7,0));
    p.push_back(csr(0x304,1,0,0));
    p.push_back(csr(0x300,6,0,8)); // Global enable alone must not deliver.
    for(unsigned i=0;i<8;++i)p.push_back(addi(8,8,1));
    p.push_back(csr(0x300,7,0,8));
    p.push_back(csr(0x304,1,0,2)); // Individual enable alone must not deliver in M.
    for(unsigned i=0;i<8;++i)p.push_back(addi(8,8,1));
    if(scenario==3) {
        // Return to U with MIE=0; M interrupts must still preempt it.
        p.push_back(csr(0x300,1,0,0));
        p.push_back(0x00000097);p.push_back(addi(1,1,16));p.push_back(csr(0x341,1,0,1));p.push_back(0x30200073);
    } else p.push_back(csr(0x300,6,0,8));
    uint64_t trigger=base+4*p.size();
    if(scenario==5 || scenario==6) {
        constant(p,1,dataBase);
        if(scenario==6) {
            p.push_back(addi(11,0,42));
            for(unsigned i=0;i<8;++i){p.push_back(0x00b0b023|((i*8U)&31)<<7|((i*8U)>>5)<<25);p.push_back(addi(11,11,1));}
        }
        for(unsigned i=0;i<12;++i)p.push_back(0x0000b183); // LD, delayed responses overlap MSI.
        p.push_back(0x0200c133);p.push_back(branch(2,8));p.push_back(csr(0x340,5,0,31));
    }
    if(scenario==7)p.push_back(0xffffffff);
    for(unsigned i=0;i<64;++i)p.push_back(addi(10,10,1));
    std::vector<uint32_t> h;
    if(timerScenario && scenario==4)h.resize(7,0xffffffff);
    if(scenario==2)h.resize(11,0xffffffff); // Only BASE+44 is a legal handler entry.
    const std::vector<uint32_t> body{csr(0x342,2,26,0),csr(0x343,2,27,0),csr(0x341,2,28,0),
        csr(0x300,2,29,0),csr(0x35c,1,30,0),addi(31,31,1),0x30200073};
    h.insert(h.end(),body.begin(),body.end());
    if(scenario==7)h={csr(0x342,2,26,0),0x000d4a63, // blt x26,x0,+20
        csr(0x341,2,28,0),addi(28,28,4),csr(0x341,1,0,28),branch(0,8),csr(0x35c,1,30,0),0x30200073};
    if(timerScenario)for(auto& inst:h)if(inst==csr(0x35c,1,30,0))inst=csr(0x304,1,0,0);
    program(library,p,seed,false,counts,h,scenario,trigger,false,timerScenario);
}
#ifndef SYNCHRONOUS_MACHINE
static void headTrapShort(const char*library) {
#if defined(WIRED_APLIC) || defined(MAPPED_APLIC)
    check(false,"--head-trap-short supports only the DIRECT-IRQ instruction/data/MSI fixture");
#endif
    check(REGISTERED_FETCH_PACKET==1 && BRANCH_ENTRIES==32,
        "--head-trap-short requires the throughput raw-fetch fixture and BRANCH_ENTRIES=32");
    Counts externalCounts,timerCounts;
    for(unsigned timerMode=0;timerMode<2;++timerMode) {
        auto& counts=timerMode?timerCounts:externalCounts;
        for(unsigned scenario=4;scenario<=7;++scenario) {
            const Counts before=counts;
            machineInterruptProgram(library,scenario,0,timerMode,counts);
            check(counts.programs==before.programs+1 && counts.interrupts==before.interrupts+1 &&
                counts.traps==before.traps+(scenario==7?2U:1U) &&
                counts.mret==before.mret+(scenario==7?2U:1U),"head-trap case interrupt/return witnesses");
            check(counts.commits>before.commits && counts.csrOps>before.csrOps &&
                counts.cycles>before.cycles,"head-trap case execution/CSR witnesses");
            check(counts.emptyInterrupts==before.emptyInterrupts+(scenario==4) &&
                counts.memoryInterrupts==before.memoryInterrupts+(scenario==5) &&
                counts.storeInterrupts==before.storeInterrupts+(scenario==6) &&
                counts.priorityTraps==before.priorityTraps+(scenario==7),"head-trap case boundary witnesses");
            if(scenario==4)check(counts.emptyTrapEvents>before.emptyTrapEvents,"empty-head trap fast boundary not observed");
            if(scenario==7)check(counts.fastHeadTraps>before.fastHeadTraps && counts.held>=before.held+40,
                "nonempty synchronous head-trap fast boundary/backpressure not observed");
            std::cout<<"HEAD_TRAP_CASE irq="<<(timerMode?"timer":"external")<<" scenario="<<scenario
                <<" seed=0 cycles="<<counts.cycles-before.cycles<<" commits="<<counts.commits-before.commits
                <<" traps="<<counts.traps-before.traps<<" interrupts="<<counts.interrupts-before.interrupts
                <<" empty="<<counts.emptyInterrupts-before.emptyInterrupts
                <<" memoryIrq="<<counts.memoryInterrupts-before.memoryInterrupts
                <<" storeIrq="<<counts.storeInterrupts-before.storeInterrupts
                <<" priority="<<counts.priorityTraps-before.priorityTraps<<" mret="<<counts.mret-before.mret
                <<" csr="<<counts.csrOps-before.csrOps<<" held="<<counts.held-before.held
                <<" fastHeadTraps="<<counts.fastHeadTraps-before.fastHeadTraps
                <<" emptyTrapEvents="<<counts.emptyTrapEvents-before.emptyTrapEvents<<"\n";
        }
        check(counts.programs==4 && counts.interrupts==4 && counts.traps==5 && counts.mret==5 &&
            counts.emptyInterrupts==1 && counts.memoryInterrupts==1 && counts.storeInterrupts==1 &&
            counts.priorityTraps==1 && counts.fastHeadTraps>0 && counts.emptyTrapEvents>0 &&
            counts.csrOps>0 && counts.held>=40,"head-trap short coverage");
    }
    check(!headTrapNegativeAttempted && !injectInterruptMismatch,"head-trap negative control was not rejected");
    std::cout<<"GSIM head trap short: PASS programs=8 interrupts=8 traps=10 empty=2 memoryIrq=2 storeIrq=2 priority=2 mret=10"
        <<" csr="<<externalCounts.csrOps+timerCounts.csrOps<<" held="<<externalCounts.held+timerCounts.held
        <<" fastHeadTraps="<<externalCounts.fastHeadTraps+timerCounts.fastHeadTraps
        <<" emptyTrapEvents="<<externalCounts.emptyTrapEvents+timerCounts.emptyTrapEvents
        <<" cycles="<<externalCounts.cycles+timerCounts.cycles
        <<" irqBoundary=DIRECT-IRQ oracle=SystemModel registeredFetchPacket="<<REGISTERED_FETCH_PACKET<<"\n";
}
#endif
#ifndef SYNCHRONOUS_MACHINE
static void authorizationShort(const char*library) {
#ifndef SYSTEM_AUTHORIZATION_FIXTURE
    check(false,"authorization short requires its observational direct-machine fixture");
#else
    check(REGISTERED_FETCH_PACKET==1 && BRANCH_ENTRIES==32,"authorization fixture geometry");
    Counts counts;
    // Legal external FENCE.I flush response phases, not an internal forced
    // completion or an oracle derived from the DUT head. Younger RAM/M traffic
    // can run after the irrevocable head's pending bit has been consumed.
    for(unsigned memory=0;memory<2;++memory)for(unsigned delay=1;delay<=12;++delay) {
        auto code=setup();
        constant(code,1,dataBase);
        code.push_back(addi(2,0,7));code.push_back(addi(3,0,13));
        authorizationFencePc=base+4*code.size();
        code.push_back(0x0000100fU);
        for(unsigned n=0;n<10;++n) {
            const unsigned rd=4+n;
            if(memory && n%2==0)code.push_back((8*n)<<20|1U<<15|3U<<12|rd<<7|0x03U);
            else code.push_back(1U<<25|3U<<20|2U<<15|rd<<7|0x33U);
        }
        code.push_back(csr(0x340,1,20,2));code.push_back(csr(0x340,2,21,0));
        code.push_back(addi(22,21,1));
        authorizationFenceDelay=delay;
        const Counts before=counts;
        program(library,code,0,false,counts,{},0,0,true);
        check(counts.systemAcks>before.systemAcks && counts.systemProtectedReleases>before.systemProtectedReleases,
            "authorization case did not execute system recovery and precise release");
        std::cout<<"AUTHORIZATION_CASE memory="<<memory<<" delay="<<delay
            <<" cycles="<<counts.cycles-before.cycles<<" blocked="<<counts.systemBlocked-before.systemBlocked
            <<" lsu="<<counts.systemLsuCollisions-before.systemLsuCollisions
            <<" mul="<<counts.systemMCollisions-before.systemMCollisions
            <<" rollback="<<counts.systemRepeatedRollback-before.systemRepeatedRollback<<"\n";
    }
    check(counts.programs==24 && counts.systemBlocked>0 && counts.systemLsuCollisions>0 &&
        counts.systemMCollisions>0 && counts.systemRepeatedRollback>0 &&
        counts.systemProtectedCommitHolds>0 && !authorizationNegative,
        "authorization machine coverage incomplete; stimulus is not a collision witness");
    std::cout<<"GSIM authorization machine: PASS programs="<<counts.programs
        <<" offers="<<counts.systemOffers<<" blocked="<<counts.systemBlocked
        <<" lsuCollision="<<counts.systemLsuCollisions<<" mulCollision="<<counts.systemMCollisions
        <<" repeatRollback="<<counts.systemRepeatedRollback<<" commitHolds="<<counts.systemProtectedCommitHolds
        <<" protectedReleases="<<counts.systemProtectedReleases<<" acks="<<counts.systemAcks
        <<" cycles="<<counts.cycles<<" oracle=SystemModel irqBoundary=DIRECT-IRQ\n";
#endif
}
#endif
#ifdef SYNCHRONOUS_MACHINE
static void prepareInstructionProgram(SMachineCoreGsim& d,const std::vector<uint32_t>& code) {
    check(code.size()<=2048,"instruction test ROM overflow");
    d.set_io$$programHold(0);d.set_io$$programWrite(0);d.set_io$$programIndex(0);d.set_io$$programData(0);
    d.set_io$$timerInterrupt(0);d.set_io$$timerTick(0);d.set_io$$timeValue(0);
    d.set_io$$sources(0);d.set_io$$uartRx(1);d.set_io$$commitEnable(1);d.set_io$$inspectRegister(0);
    d.set_io$$instruction0$$valid(0);d.set_io$$instruction0$$bits(0);
    d.set_io$$instruction1$$valid(0);d.set_io$$instruction1$$bits(0);
    d.set_io$$memory$$request$$ready(0);d.set_io$$memory$$response$$valid(0);
    d.set_io$$memory$$response$$bits$$data(0);d.set_io$$memory$$response$$bits$$error(0);
    d.set_io$$msi$$request$$valid(0);d.set_io$$msi$$request$$bits$$address(0);
    d.set_io$$msi$$request$$bits$$data(0);d.set_io$$msi$$request$$bits$$size(0);
    d.set_io$$msi$$request$$bits$$byteEnable(0);d.set_io$$msi$$request$$bits$$write(0);
    d.set_io$$msi$$response$$ready(1);
    d.set_reset(1);d.step();d.step();d.set_reset(0);
    d.set_io$$programHold(1);d.step();d.step();
    for(unsigned i=0;i<2048;++i){
        d.set_io$$programWrite(1);d.set_io$$programIndex(i);
        d.set_io$$programData(i<code.size()?code[i]:0U);
        d.step();
    }
    d.set_io$$programWrite(0);d.step();d.set_io$$programHold(0);
}
static void fetchFaultProgram(bool lowerBoundary) {
    SMachineCoreGsim d;
    const uint32_t jump=lowerBoundary?0xffdff06fU:0x0000206fU;
    prepareInstructionProgram(d,{jump});
    unsigned commits=0;
    const uint64_t faultPc=lowerBoundary?base-4:base+8192;
    for(unsigned cycle=0;cycle<2000;++cycle){
        d.step();
        if(d.get_io$$commit0$$valid()){
            check(commits==0 && d.get_io$$commit0$$bits$$pc()==base &&
                d.get_io$$commit0$$bits$$instruction()==jump &&
                d.get_io$$commit0$$bits$$nextPc()==faultPc,
                "fetch fault program committed an unexpected instruction");
            ++commits;
        }
        check(!d.get_io$$commit1$$valid(),"fetch fault program committed a younger instruction");
        if(d.get_io$$trap$$valid()){
            check(commits==1 && d.get_io$$trap$$bits$$pc()==faultPc &&
                d.get_io$$trap$$bits$$cause()==1 && d.get_io$$trap$$bits$$tval()==faultPc,
                "TileLink denied fetch did not produce a precise instruction access fault");
            std::cout<<"GSIM TileLink instruction access fault: PASS committedPrefix="<<commits
                <<" boundary="<<(lowerBoundary?"low":"high")<<"\n";
            return;
        }
    }
    throw std::runtime_error("TileLink instruction access fault timeout");
}
static void ramExecProgram() {
    // The stores form a complete 64-bit RAM fetch beat. FENCE.I drains them before the jump.
    const std::vector<uint32_t> code{
        0x00010097U, // auipc x1, 0x10 -> dataBase
        0x02a00137U, // lui x2, 0x02a00
        addi(2,2,0x513), // x2 = addi x10, x0, 42
        addi(3,0,0x73), // x3 = ecall
        0x0020a023U, // sw x2, 0(x1)
        0x0030a223U, // sw x3, 4(x1)
        0x0000100fU, // fence.i
        0x00008067U // jalr x0, 0(x1)
    };
    SMachineCoreGsim d;
    prepareInstructionProgram(d,code);
    d.set_io$$inspectRegister(10);
    unsigned commits=0;
    unsigned releaseBeats=0;
    unsigned instructionLineFills=0;
    for(unsigned cycle=0;cycle<4000;++cycle){
        d.step();
#ifdef COHERENT_FENCEI
        releaseBeats += d.get_io$$coherentReleaseData();
        instructionLineFills += d.get_io$$fetchGetFire() && d.get_io$$fetchGetSize()==6;
#endif
        auto commit=[&](bool valid,uint64_t pc,uint32_t instruction,uint64_t nextPc,uint64_t value){
            if(!valid)return;
            check(commits<=code.size(),"RAM execution committed past its end");
            const uint64_t expectedPc=commits<code.size()?base+4*commits:dataBase;
            const uint32_t expectedInstruction=commits<code.size()?code[commits]:addi(10,0,42);
            const uint64_t expectedNext=commits==code.size()-1?dataBase:expectedPc+4;
            check(pc==expectedPc && instruction==expectedInstruction && nextPc==expectedNext &&
                (commits!=code.size() || value==42),"RAM execution commit mismatch");
            ++commits;
        };
        commit(d.get_io$$commit0$$valid(),d.get_io$$commit0$$bits$$pc(),
            d.get_io$$commit0$$bits$$instruction(),d.get_io$$commit0$$bits$$nextPc(),
            d.get_io$$commit0$$bits$$data());
        commit(d.get_io$$commit1$$valid(),d.get_io$$commit1$$bits$$pc(),
            d.get_io$$commit1$$bits$$instruction(),d.get_io$$commit1$$bits$$nextPc(),
            d.get_io$$commit1$$bits$$data());
        if(d.get_io$$trap$$valid()){
#ifdef COHERENT_FENCEI
            check(releaseBeats>=8,"FENCE.I did not write back the dirty code line");
            check(instructionLineFills>=1,"RAM execution did not use the 64-byte instruction line fill");
#endif
            check(commits==code.size()+1 && d.get_io$$trap$$bits$$pc()==dataBase+4 &&
                d.get_io$$trap$$bits$$cause()==11 && d.get_io$$trap$$bits$$tval()==0 &&
                d.get_io$$committedValue()==42,
                "RAM code did not execute after FENCE.I");
            std::cout<<"GSIM TileLink RAM execution after FENCE.I: PASS commits="<<commits
                <<" cycles="<<cycle+1<<"\n";
            return;
        }
    }
    throw std::runtime_error("TileLink RAM execution timeout");
}
static uint32_t storeWord(unsigned rs2,unsigned offset,unsigned rs1=1) {
    return ((offset>>5)&127)<<25 | rs2<<20 | rs1<<15 | 2<<12 | (offset&31)<<7 | 0x23;
}
static uint32_t branchNotEqual(unsigned rs1,unsigned rs2,int offset) {
    unsigned x=unsigned(offset)&8191;
    return ((x>>12)&1)<<31 | ((x>>5)&63)<<25 | rs2<<20 | rs1<<15 | 1<<12 |
        ((x>>1)&15)<<8 | ((x>>11)&1)<<7 | 0x63;
}
static void instructionIpcProgram(unsigned issueWidth,unsigned cacheLines,unsigned frontendSets,bool packed,
    bool longBody=false) {
    const unsigned bodyWords=longBody?768:384;
    constexpr unsigned iterations=30;
    std::vector<uint32_t> body;
    for(unsigned i=0;i<bodyWords;++i){
        if(packed){
            const auto cAddi=[](unsigned reg){return reg<<7 | 1<<2 | 1;};
            body.push_back(cAddi(10+(2*i)%4) | cAddi(10+(2*i+1)%4)<<16);
        }else body.push_back(addi(10+i%4,10+i%4,1));
    }
    body.push_back(addi(20,20,-1));
    body.push_back(branchNotEqual(20,0,-int((bodyWords+1)*4)));
    body.push_back(0x00000073); // ecall terminates the RAM loop
    std::vector<uint32_t> code{0x00010097U}; // auipc x1, 0x10 -> dataBase
    auto loadWord=[&](unsigned reg,uint32_t value){
        const uint32_t upper=(value+0x800U)>>12;
        code.push_back(upper<<12 | reg<<7 | 0x37);
        code.push_back(addi(reg,reg,int(value-(upper<<12))));
    };
    for(unsigned reg=2;reg<6;++reg)loadWord(reg,body[reg-2]);
    loadWord(6,body[bodyWords]);
    loadWord(7,body[bodyWords+1]);
    loadWord(8,body[bodyWords+2]);
    if(longBody){code.push_back(addi(9,1,2047));code.push_back(addi(9,9,1));}
    for(unsigned i=0;i<body.size();++i){
        const unsigned reg=i<bodyWords?2+i%4:6+i-bodyWords;
        const unsigned offset=i*4;
        code.push_back(offset<2048?storeWord(reg,offset):storeWord(reg,offset-2048,9));
    }
    code.push_back(addi(20,0,iterations));
    code.push_back(0x0000100fU); // fence.i after executable RAM writes
    code.push_back(0x00008067U); // jalr x0, 0(x1)
    SMachineCoreGsim d;
    prepareInstructionProgram(d,code);
    d.set_io$$inspectRegister(10);
    const unsigned bodyInstructions=packed?bodyWords*2:bodyWords;
    unsigned ramCommits=0,ramIndex=0,loop=0,fetchGets=0,lineGets=0;
    unsigned firstRamCycle=0,firstLoopCycle=0,fetchGetsAtFirstLoop=0;
    for(unsigned cycle=1;cycle<=100000;++cycle){
        d.step();
        if(d.get_io$$fetchGetFire() && d.get_io$$fetchGetAddress()>=dataBase){
            ++fetchGets;
            lineGets+=d.get_io$$fetchGetSize()==6;
        }
        auto commit=[&](bool valid,uint64_t pc,uint32_t instruction){
            if(!valid || pc<dataBase)return;
            const bool inBody=ramIndex<bodyInstructions;
            const unsigned tailIndex=ramIndex-bodyInstructions;
            const uint64_t expectedPc=inBody?dataBase+ramIndex*(packed?2:4):
                dataBase+4*(bodyWords+tailIndex);
            const uint32_t expectedInstruction=inBody?(packed?
                (body[ramIndex/2]>>(16*(ramIndex%2)))&0xffff:body[ramIndex]):body[bodyWords+tailIndex];
            check(ramIndex<bodyInstructions+2 && pc==expectedPc && instruction==expectedInstruction,
                "RAM IPC instruction mismatch at retired="+std::to_string(ramCommits));
            if(!firstRamCycle)firstRamCycle=cycle;
            ++ramCommits;
            if(ramIndex==bodyInstructions+1){
                ++loop;
                if(loop==1){firstLoopCycle=cycle;fetchGetsAtFirstLoop=fetchGets;}
                ramIndex=loop==iterations?bodyInstructions+2:0;
            }else ++ramIndex;
        };
        commit(d.get_io$$commit0$$valid(),d.get_io$$commit0$$bits$$pc(),
            d.get_io$$commit0$$bits$$instruction());
        commit(d.get_io$$commit1$$valid(),d.get_io$$commit1$$bits$$pc(),
            d.get_io$$commit1$$bits$$instruction());
        if(issueWidth==4){
            commit(d.get_io$$commit2$$valid(),d.get_io$$commit2$$bits$$pc(),
                d.get_io$$commit2$$bits$$instruction());
            commit(d.get_io$$commit3$$valid(),d.get_io$$commit3$$bits$$pc(),
                d.get_io$$commit3$$bits$$instruction());
        }
        if(d.get_io$$trap$$valid()){
            check(loop==iterations && ramCommits==iterations*(bodyInstructions+2) &&
                d.get_io$$trap$$bits$$pc()==dataBase+(bodyWords+2)*4 &&
                d.get_io$$trap$$bits$$cause()==11 && d.get_io$$committedValue()==
                iterations*(packed?bodyWords/2:bodyWords/4),"RAM IPC result or trap mismatch");
            const unsigned measuredCycles=cycle-firstRamCycle+1;
            const unsigned warmCommits=(iterations-1)*(bodyInstructions+2);
            const unsigned warmCycles=cycle-firstLoopCycle;
            std::cout<<std::fixed<<std::setprecision(3)
                <<"ICACHE_IPC issue="<<issueWidth<<" lines="<<cacheLines
                <<" frontendSets="<<frontendSets<<" packed="<<packed
                <<" bodyWords="<<bodyWords
                <<" commits="<<ramCommits<<" cycles="<<measuredCycles
                <<" ipc="<<double(ramCommits)/measuredCycles
                <<" warmCommits="<<warmCommits<<" warmCycles="<<warmCycles
                <<" warmIpc="<<double(warmCommits)/warmCycles
                <<" fetchGets="<<fetchGets<<" warmGets="<<fetchGets-fetchGetsAtFirstLoop
                <<" lineGets="<<lineGets<<"\n";
            return;
        }
    }
    throw std::runtime_error("RAM IPC program timeout: commits=" + std::to_string(ramCommits) +
        " loop=" + std::to_string(loop) + " index=" + std::to_string(ramIndex) +
        " fetchGets=" + std::to_string(fetchGets) +
        " fetchPc=" + std::to_string(d.get_io$$fetchPc()));
}
#endif
int main(int argc,char**argv) {
    try {
#ifdef SYNCHRONOUS_MACHINE
        check(!(argc>=3 && std::string(argv[2])=="--authorization-short"),
            "authorization short requires the DIRECT-IRQ fixture, not a synchronous machine");
        if((argc==5 || argc==6) && std::string(argv[1])=="--instruction-ipc"){
            check(argc==5 || std::string(argv[5])=="packed" || std::string(argv[5])=="long",
                "instruction IPC body mode");
            instructionIpcProgram(std::stoul(argv[2]),std::stoul(argv[3]),std::stoul(argv[4]),
                argc==6 && std::string(argv[5])=="packed",argc==6 && std::string(argv[5])=="long");return 0;
        }
        if(argc==2 && std::string(argv[1])=="--ram-exec"){
            ramExecProgram();return 0;
        }
        if(argc==2 && (std::string(argv[1])=="--fetch-fault" ||
            std::string(argv[1])=="--fetch-fault-low")){
            fetchFaultProgram(std::string(argv[1])=="--fetch-fault-low");return 0;
        }
        pmpAvailable=true;
        check(argc==5 || argc==6 || (argc==7 && std::string(argv[5])=="--privilege-uart" &&
            std::string(argv[6])=="--inject-serial"),
            "usage: boot NEMU.so image.bin stop trigger [--sstc|--timer|--dma|--atomic|--external-irq|--privilege-uart]");
        std::ifstream input(argv[2],std::ios::binary);check(bool(input),"boot image open");
        std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(input)),{});
        check(bytes.size()%4==0,"boot image alignment");
        for(size_t i=0;i<bytes.size();i+=4)firmware.push_back(uint32_t(bytes[i])|uint32_t(bytes[i+1])<<8|uint32_t(bytes[i+2])<<16|uint32_t(bytes[i+3])<<24);
        firmwareStop=std::stoull(argv[3],nullptr,16);firmwareTrigger=std::stoull(argv[4],nullptr,16);
        atomicBoot=argc==6 && std::string(argv[5])=="--atomic";
        dmaBoot=atomicBoot || (argc==6 && std::string(argv[5])=="--dma");
        timerBoot=argc==6 && std::string(argv[5])=="--timer";
        sstcBoot=argc==6 && std::string(argv[5])=="--sstc";
        privilegeBoot=argc>=6 && std::string(argv[5])=="--privilege-uart";
        serialBoot=!timerBoot && !sstcBoot && !dmaBoot && (argc!=6 || std::string(argv[5])!="--external-irq");
        injectMmioMismatch=argc==6 && std::string(argv[5])=="--inject-mmio";
        injectSerialMismatch=(argc==6 && std::string(argv[5])=="--inject-serial") ||
            (argc==7 && std::string(argv[6])=="--inject-serial");Counts counts;
#else
#ifndef SYNCHRONOUS_MACHINE
        authorizationShortMode=argc>=3 && std::string(argv[2])=="--authorization-short";
        if(authorizationShortMode) {
            check(argc==3 || (argc==4&&std::string(argv[3])=="--inject-system-redirect"),
                "usage: machine NEMU.so --authorization-short [--inject-system-redirect]");
            authorizationNegative=argc==4;
            authorizationShort(argv[1]);return 0;
        }
#endif
        headTrapShortMode=argc>=3 && std::string(argv[2])=="--head-trap-short";
        const bool shortInterruptNegative=headTrapShortMode && argc==4 && std::string(argv[3])=="--inject-interrupt";
        check(argc==2 || (argc==3 && (std::string(argv[2])=="--inject-mismatch" ||
            std::string(argv[2])=="--inject-interrupt" || std::string(argv[2])=="--inject-mmio")) ||
            (headTrapShortMode && (argc==3 || shortInterruptNegative)),
            "usage: machine NEMU.so [--inject-mismatch|--inject-interrupt|--inject-mmio|--head-trap-short [--inject-interrupt]]");
        injectMismatch=argc==3 && std::string(argv[2])=="--inject-mismatch";
        injectInterruptMismatch=(argc==3 && std::string(argv[2])=="--inject-interrupt") || shortInterruptNegative;
        if(headTrapShortMode){headTrapShort(argv[1]);return 0;}
        Counts counts;

#endif
#ifdef MAPPED_APLIC
#ifndef SYNCHRONOUS_MACHINE
        injectMmioMismatch=argc==3 && std::string(argv[2])=="--inject-mmio";
#endif
        for(unsigned seed:{0U,17U,8191U}) {
#ifdef SYNCHRONOUS_MACHINE
            if(sstcBoot && seed==8191)continue;
            program(argv[1],firmware,seed,false,counts,{},privilegeBoot?0:sstcBoot?16:8,firmwareTrigger);
#else
            auto p=setup();constant(p,12,0x0c000000);
            auto sw=[&](unsigned a,unsigned v){constant(p,13,v);constant(p,14,0x0c000000+a);p.push_back(0x00d72023);};
            sw(12,4);sw(0x300c,3);sw(0x1edc,3);sw(0,256);
            p.push_back(0x00062783); // lw x15,0(x12): sign-extended domaincfg
            p.push_back(0x00066803); // lwu x16,0(x12)
            p.push_back(0x00c62883); // lw x17,12(x12): upper word lanes
            constant(p,14,0x0c00300c);p.push_back(0x00072903);
            constant(p,14,0x0c001e00);p.push_back(0x00072983);
            // Speculative bad path must not disable the APLIC.
            p.push_back(0x0200c133);p.push_back(branch(2,8));p.push_back(0x00062023);
            p.push_back(0x00062783);
            // Unsupported local byte/doubleword accesses must fault without writing the device.
            p.push_back(0x00060883);p.push_back(0x00063883);p.push_back(0x00060023);
            constant(p,1,dataBase);p.push_back(addi(11,0,42));p.push_back(0x00b0b023);p.push_back(0x0000b903);
            p.push_back(addi(1,0,0xc0));p.push_back(csr(0x350,1,0,1));p.push_back(addi(2,0,8));p.push_back(csr(0x351,1,0,2));
            p.push_back(addi(1,0,0x70));p.push_back(csr(0x350,1,0,1));p.push_back(csr(0x351,5,0,1));
            constant(p,2,2048);p.push_back(csr(0x304,1,0,2));p.push_back(csr(0x300,6,0,8));
            auto trigger=base+4*p.size();for(unsigned i=0;i<96;++i)p.push_back(addi(10,10,1));
            std::vector<uint32_t> handler{csr(0x342,2,26,0),0x000d4a63, // blt cause,x0,+20
                csr(0x341,2,28,0),addi(28,28,4),csr(0x341,1,0,28),branch(0,16),
                0x00062f83, // lw x31,0(x12), firmware reads controller in IRQ handler
                0x00062023, // sw x0,0(x12), mask delivery
                csr(0x35c,1,30,0),0x30200073};
            program(argv[1],p,seed,false,counts,handler,8,trigger);
#endif
        }
#ifdef SYNCHRONOUS_MACHINE
        check(counts.traps==(privilegeBoot?21U:sstcBoot?2U:atomicBoot?21U:timerBoot?15U:12U) &&
            counts.interrupts==(privilegeBoot?0U:sstcBoot?2U:timerBoot?6U:3U) &&
            (!privilegeBoot || (counts.mret==6 && counts.sret==21)),"mapped firmware trap coverage");
#else
        check(counts.traps==12 && counts.interrupts==3,"mapped firmware trap coverage");
#endif
        std::cout<<
#ifdef SYNCHRONOUS_MACHINE
        "GSIM MachinePlatform: PASS programs="
#else
        "GSIM MappedMachineCore: PASS programs="
#endif
        <<counts.programs<<" commits="<<counts.commits<<" traps="<<counts.traps<<" interrupts="<<counts.interrupts<<"\n";
        return 0;
#endif
        for(unsigned seed:{0U,17U,8191U}) {
            auto f=setup();constant(f,1,dataBase);f.push_back(addi(11,0,42));
            for(unsigned i=0;i<4;++i)f.push_back(0x00b0b023|((i*8U)&31)<<7);
            f.push_back(0x0ff0000f);f.push_back(0x0000b183);
            f.push_back(0x8330000f); // FENCE.TSO conservatively drains everything.
            f.push_back(0x0ff5858f); // Reserved rs1/rd ignored: x11 must remain 42.
            f.push_back(0xfff5958f); // FENCE.I also ignores reserved rs1/rd/imm fields.
            f.push_back(addi(12,11,0));
            f.push_back(0x0000100f);
            program(argv[1],f,seed,false,counts,{},0,0,true);
        }
        for(unsigned seed:{0U,17U,8191U}) {
            auto p=setup();p.push_back(0x0ff0000f);
            for(unsigned op:{1U,2U,3U,5U,6U,7U})for(unsigned src:{0U,1U,2U})for(unsigned rd:{0U,1U,2U,3U}) {
                p.push_back(addi(1,0,0));p.push_back(addi(2,0,-1));p.push_back(csr(0x340,op,rd,src));
            }
            for(unsigned i=0;i<32;++i){p.push_back(csr(0x340,1,1,1));p.push_back(addi(1,1,1));}
            p.push_back(csr(0x300,6,0,8)); // MIE stack is exercised by each exception/return.
            p.push_back(0x00004073); // reserved SYSTEM funct3
            p.push_back(addi(1,0,0));p.push_back(csr(0xf14,2,0,1)); // nonzero register containing zero still writes
            p.push_back(0x73);p.push_back(0x100073);p.push_back(0xffffffff);
            p.push_back(csr(0x777,2,3,0));p.push_back(csr(0xf14,1,0,1));p.push_back(csr(0xf14,2,3,0));
            // Wrong-path CSR and store behind a long older divide/branch must never act.
            p.push_back(addi(1,0,1));p.push_back(0x0200c133);p.push_back(branch(2,12));
            p.push_back(csr(0x340,5,0,31));p.push_back(0x00103023);p.push_back(csr(0x340,2,4,0));
            std::mt19937_64 random(seed+19);
            for(unsigned i=0;i<128;++i) {
                constant(p,1,random());p.push_back(csr(0x340,1+unsigned(random()%3),2,1));
                p.push_back(csr(0x340,5+unsigned(random()%3),3,unsigned(random()%32)));
            }
            program(argv[1],p,seed,true,counts);
            auto a=setup();
            a.push_back(addi(1,0,-1));a.push_back(csr(0x350,1,0,1)); // invalid selector then restore
            a.push_back(csr(0x351,2,2,0));
            a.push_back(addi(1,0,0xc0));a.push_back(csr(0x350,1,0,1));a.push_back(addi(2,0,-1));a.push_back(csr(0x351,1,0,2));
            a.push_back(csr(0x35c,2,4,0));a.push_back(addi(2,0,0));
            a.push_back(csr(0x35c,2,5,2)); // nonzero rs1 encoding, value=0 still claims ID3
            a.push_back(csr(0x35c,6,6,0)); // zimm0 does not claim ID5
            a.push_back(csr(0x35c,1,7,0));a.push_back(csr(0x35c,6,8,0));a.push_back(csr(0x35c,2,9,0));
            a.push_back(addi(1,0,0x70));a.push_back(csr(0x350,1,0,1));a.push_back(csr(0x351,5,0,1));
            // Branch prevents an external CSR claim from reaching the independent IP.
            a.push_back(branch(0,8));a.push_back(csr(0x35c,1,0,0));a.push_back(csr(0x35c,2,10,0));
            program(argv[1],a,seed,false,counts);
        }
        // Both lower privilege labels reject M CSRs/MRET and produce the correct ECALL cause.
        for(unsigned mode:{0U,1U}) {
            auto p=setup();constant(p,2,mode<<11);p.push_back(csr(0x300,1,0,2));
            p.push_back(0x00000097);p.push_back(addi(1,1,16));p.push_back(csr(0x341,1,0,1));p.push_back(0x30200073);
            p.push_back(csr(0x340,2,5,0));p.push_back(0x30200073);p.push_back(0x73);p.push_back(addi(10,0,42));
            program(argv[1],p,mode+99,false,counts);
        }
        // Nested synchronous exception: handler explicitly saves/restores outer mepc and mstatus.
        auto nested=setup();nested.push_back(csr(0x340,1,0,0));nested.push_back(0x73);nested.push_back(addi(10,0,42));
        std::vector<uint32_t> handler{addi(25,0,1),csr(0x340,1,24,25),
            0x000c1e63, // bne x24,x0,+28: second entry skips the nested call/save/restore block
            csr(0x341,2,23,0),csr(0x300,2,22,0),0x73,
            csr(0x341,1,0,23),csr(0x300,1,0,22),addi(0,0,0),
            csr(0x341,2,28,0),addi(28,28,4),csr(0x341,1,0,28),0x30200073};
        // Branch at index2 targets index9, offset28.
        program(argv[1],nested,101,true,counts,handler);
        auto faults=setup();faults.push_back(addi(1,0,3));faults.push_back(0x0000b183); // misaligned LD
        faults.push_back(addi(1,0,0));faults.push_back(0x0000b183); // access-fault LD
        faults.push_back(addi(10,0,42));program(argv[1],faults,102,false,counts);
        check(counts.traps==34&&counts.mret==36&&counts.csrOps>1000&&counts.held>100,"system coverage");
        // M configures delegation, enters S with MRET, S enters U with SRET, then
        // U ECALL, a forbidden U read of sstatus and U-mode SRET must enter the
        // S handler, then return to the following U instruction.
        Counts supervisorCounts;
        for(unsigned seed:{0U,17U,8191U}) {
            auto p=setup();
            constant(p,1,vectorPc|(seed==17));p.push_back(csr(0x105,1,0,1));
            constant(p,2,0xffff);p.push_back(csr(0x302,1,0,2));
            p.push_back(csr(0x302,2,6,0)); // WARL mask excludes machine ECALL.
            constant(p,2,(1U<<11)|(1U<<5));p.push_back(csr(0x300,1,0,2));
            p.push_back(0x00000097);p.push_back(addi(1,1,32));p.push_back(csr(0x141,1,0,1));
            p.push_back(0x00000097);p.push_back(addi(1,1,16));p.push_back(csr(0x341,1,0,1));
            p.push_back(0x30200073);p.push_back(0x10200073);p.push_back(0x00000073);
            p.push_back(csr(0x100,2,5,0));
            p.push_back(0x10200073);
            p.push_back(addi(10,0,42));
            std::vector<uint32_t> supervisorHandler{csr(0x142,2,26,0),csr(0x143,2,27,0),
                csr(0x141,2,28,0),csr(0x100,2,29,0),addi(28,28,4),
                csr(0x141,1,0,28),0x10200073};
            program(argv[1],p,seed,false,supervisorCounts,supervisorHandler);
        }
        check(supervisorCounts.programs==3 && supervisorCounts.traps==9 &&
            supervisorCounts.mret==3 && supervisorCounts.sret==12,"supervisor trap/return coverage");
        std::cout<<"GSIM supervisor trap: PASS programs="<<supervisorCounts.programs
            <<" traps="<<supervisorCounts.traps<<" sret="<<supervisorCounts.sret<<"\n";
#ifndef WIRED_APLIC
        Counts supervisorInterruptCounts;
        for(unsigned seed:{0U,17U,8191U}) {
            auto p=setup();
            constant(p,1,vectorPc|(seed==17));p.push_back(csr(0x105,1,0,1));
            constant(p,2,1U<<9);p.push_back(csr(0x303,1,0,2));
            constant(p,2,1U<<11);p.push_back(csr(0x300,1,0,2));
            p.push_back(0x00000097);p.push_back(addi(1,1,16));p.push_back(csr(0x341,1,0,1));p.push_back(0x30200073);
            p.push_back(addi(1,0,0x70));p.push_back(csr(0x150,1,0,1));
            p.push_back(addi(2,0,1));p.push_back(csr(0x151,1,0,2));
            p.push_back(addi(1,0,0xc0));p.push_back(csr(0x150,1,0,1));
            p.push_back(addi(2,0,1U<<5));p.push_back(csr(0x151,1,0,2));
            constant(p,2,1U<<9);p.push_back(csr(0x104,1,0,2));
            uint64_t trigger=base+4*p.size();
            for(unsigned i=0;i<16;++i)p.push_back(addi(10,10,1));
            p.push_back(csr(0x100,6,0,2)); // SIE=1; pending SEI must now become eligible.
            for(unsigned i=0;i<64;++i)p.push_back(addi(10,10,1));
            std::vector<uint32_t> supervisorInterruptHandler;
            if(seed==17)supervisorInterruptHandler.resize(9,addi(0,0,0));
            for(uint32_t inst:{csr(0x142,2,26,0),csr(0x141,2,28,0),csr(0x100,2,29,0),csr(0x104,2,24,0),
                    csr(0x144,2,27,0),csr(0x15c,1,30,0),csr(0x144,2,25,0),0x10200073U})
                supervisorInterruptHandler.push_back(inst);
            program(argv[1],p,seed,false,supervisorInterruptCounts,supervisorInterruptHandler,10,trigger);
        }
        check(supervisorInterruptCounts.programs==3 && supervisorInterruptCounts.interrupts==3 &&
            supervisorInterruptCounts.traps==3 && supervisorInterruptCounts.sret==3,
            "supervisor IMSIC interrupt coverage");
        std::cout<<"GSIM supervisor IMSIC: PASS programs="<<supervisorInterruptCounts.programs
            <<" interrupts="<<supervisorInterruptCounts.interrupts<<"\n";
        Counts undelegatedSupervisorCounts;
        for(unsigned seed:{0U,17U,8191U}) {
            auto p=setup();
            if(seed==17){constant(p,1,vectorPc|1);p.push_back(csr(0x305,1,0,1));}
            p.push_back(addi(1,0,0x70));p.push_back(csr(0x150,1,0,1));
            p.push_back(addi(2,0,1));p.push_back(csr(0x151,1,0,2));
            p.push_back(addi(1,0,0xc0));p.push_back(csr(0x150,1,0,1));
            p.push_back(addi(2,0,1U<<5));p.push_back(csr(0x151,1,0,2));
            constant(p,2,1U<<9);p.push_back(csr(0x304,1,0,2));
            constant(p,2,1U<<11);p.push_back(csr(0x300,1,0,2));
            p.push_back(0x00000097);p.push_back(addi(1,1,16));p.push_back(csr(0x341,1,0,1));p.push_back(0x30200073);
            uint64_t trigger=base+4*p.size();
            for(unsigned i=0;i<64;++i)p.push_back(addi(10,10,1));
            std::vector<uint32_t> machineHandler;
            if(seed==17)machineHandler.resize(9,addi(0,0,0));
            for(uint32_t inst:{csr(0x342,2,26,0),csr(0x341,2,28,0),csr(0x344,2,27,0),csr(0x104,2,24,0),
                    csr(0x15c,1,30,0),csr(0x344,2,25,0),0x30200073U})
                machineHandler.push_back(inst);
            program(argv[1],p,seed,false,undelegatedSupervisorCounts,machineHandler,10,trigger);
        }
        check(undelegatedSupervisorCounts.programs==3 && undelegatedSupervisorCounts.interrupts==3 &&
            undelegatedSupervisorCounts.traps==3 && undelegatedSupervisorCounts.mret==6,
            "undelegated supervisor IMSIC interrupt coverage");
        std::cout<<"GSIM undelegated S IMSIC: PASS programs="<<undelegatedSupervisorCounts.programs
            <<" interrupts="<<undelegatedSupervisorCounts.interrupts<<"\n";
        Counts interruptPriorityCounts;
        for(unsigned seed:{0U,17U,8191U}) {
            auto p=setup();
            constant(p,1,vectorPc+0x80);p.push_back(csr(0x105,1,0,1));
            p.push_back(addi(1,0,0x70));p.push_back(csr(0x350,1,0,1));
            p.push_back(addi(2,0,1));p.push_back(csr(0x351,1,0,2));
            p.push_back(addi(1,0,0xc0));p.push_back(csr(0x350,1,0,1));
            p.push_back(addi(2,0,1U<<3));p.push_back(csr(0x351,1,0,2));
            p.push_back(addi(1,0,0x70));p.push_back(csr(0x150,1,0,1));
            p.push_back(addi(2,0,1));p.push_back(csr(0x151,1,0,2));
            p.push_back(addi(1,0,0xc0));p.push_back(csr(0x150,1,0,1));
            p.push_back(addi(2,0,1U<<5));p.push_back(csr(0x151,1,0,2));
            constant(p,2,1U<<9);p.push_back(csr(0x303,1,0,2));
            constant(p,2,(1U<<11)|(1U<<9));p.push_back(csr(0x304,1,0,2));
            constant(p,2,(1U<<11)|2);p.push_back(csr(0x300,1,0,2));
            p.push_back(0x00000097);p.push_back(addi(1,1,16));p.push_back(csr(0x341,1,0,1));p.push_back(0x30200073);
            for(unsigned i=0;i<48;++i)p.push_back(addi(10,10,1));
            std::vector<uint32_t> priorityHandler{csr(0x342,2,26,0),csr(0x341,2,28,0),
                csr(0x35c,1,30,0),0x30200073};
            priorityHandler.resize(32,addi(0,0,0));
            for(uint32_t inst:{csr(0x142,2,27,0),csr(0x141,2,29,0),csr(0x15c,1,31,0),0x10200073U})
                priorityHandler.push_back(inst);
            program(argv[1],p,seed,false,interruptPriorityCounts,priorityHandler,11);
        }
        check(interruptPriorityCounts.programs==3 && interruptPriorityCounts.interrupts==6 &&
            interruptPriorityCounts.traps==6 && interruptPriorityCounts.mret==6 && interruptPriorityCounts.sret==3,
            "machine/supervisor interrupt priority coverage");
        std::cout<<"GSIM M/S IMSIC priority: PASS programs="<<interruptPriorityCounts.programs
            <<" interrupts="<<interruptPriorityCounts.interrupts<<"\n";
        Counts userSupervisorInterruptCounts;
        for(unsigned seed:{0U,17U,8191U}) {
            auto p=setup();
            constant(p,1,vectorPc);p.push_back(csr(0x105,1,0,1));
            p.push_back(addi(1,0,0x70));p.push_back(csr(0x150,1,0,1));
            p.push_back(addi(2,0,1));p.push_back(csr(0x151,1,0,2));
            p.push_back(addi(1,0,0xc0));p.push_back(csr(0x150,1,0,1));
            p.push_back(addi(2,0,1U<<5));p.push_back(csr(0x151,1,0,2));
            constant(p,2,1U<<9);p.push_back(csr(0x303,1,0,2));p.push_back(csr(0x304,1,0,2));
            constant(p,2,(1U<<11)|8);p.push_back(csr(0x300,1,0,2));
            uint64_t trigger=base+4*p.size();
            unsigned sepcAuipc=p.size();p.push_back(0x00000097);p.push_back(0);p.push_back(csr(0x141,1,0,1));
            unsigned mepcAuipc=p.size();p.push_back(0x00000097);p.push_back(0);p.push_back(csr(0x341,1,0,1));
            p.push_back(0x30200073);
            unsigned supervisorStart=p.size();
            for(unsigned i=0;i<16;++i)p.push_back(addi(10,10,1));
            p.push_back(0x10200073);
            unsigned userStart=p.size();
            for(unsigned i=0;i<64;++i)p.push_back(addi(10,10,1));
            p[sepcAuipc+1]=addi(1,1,4*(userStart-sepcAuipc));
            p[mepcAuipc+1]=addi(1,1,4*(supervisorStart-mepcAuipc));
            std::vector<uint32_t> userInterruptHandler{csr(0x142,2,26,0),csr(0x141,2,28,0),
                csr(0x100,2,29,0),csr(0x15c,1,30,0),0x10200073};
            program(argv[1],p,seed,false,userSupervisorInterruptCounts,userInterruptHandler,10,trigger);
        }
        check(userSupervisorInterruptCounts.programs==3 && userSupervisorInterruptCounts.interrupts==3 &&
            userSupervisorInterruptCounts.traps==3 && userSupervisorInterruptCounts.mret==3 &&
            userSupervisorInterruptCounts.sret==6,"U-mode supervisor interrupt coverage");
        std::cout<<"GSIM U-mode supervisor IMSIC: PASS programs="<<userSupervisorInterruptCounts.programs
            <<" interrupts="<<userSupervisorInterruptCounts.interrupts<<"\n";
        // SSIP is a writable pending bit shared by mip/sip; a delegated request
        // waits for SIE in S mode, but an undelegated request targets M mode.
        Counts softwareInterruptCounts;
        for(bool delegated:{true,false})for(unsigned seed:{0U,17U,8191U}) {
            auto p=setup();
            constant(p,1,vectorPc|(seed==17));p.push_back(csr(delegated?0x105:0x305,1,0,1));
            p.push_back(addi(2,0,delegated?2:0));p.push_back(csr(0x303,1,0,2));
            p.push_back(addi(2,0,2));p.push_back(csr(0x304,1,0,2));
            p.push_back(csr(0x344,1,0,2));
            constant(p,2,1U<<11);p.push_back(csr(0x300,1,0,2));
            p.push_back(0x00000097);p.push_back(addi(1,1,16));p.push_back(csr(0x341,1,0,1));p.push_back(0x30200073);
            if(delegated) {
                p.push_back(csr(0x144,2,24,0));p.push_back(csr(0x104,2,25,0));
                for(unsigned i=0;i<16;++i)p.push_back(addi(10,10,1));
                p.push_back(csr(0x100,6,0,2)); // SIE unmasks an already-pending SSIP.
            }
            for(unsigned i=0;i<64;++i)p.push_back(addi(10,10,1));
            std::vector<uint32_t> handler(seed==17?1:0,addi(0,0,0));
            if(delegated)for(uint32_t inst:{csr(0x142,2,26,0),csr(0x144,2,27,0),
                    csr(0x144,7,0,2),csr(0x144,2,28,0),0x10200073U})handler.push_back(inst);
            else for(uint32_t inst:{csr(0x342,2,26,0),csr(0x344,2,27,0),
                    csr(0x344,7,0,2),csr(0x344,2,28,0),0x30200073U})handler.push_back(inst);
            program(argv[1],p,seed,false,softwareInterruptCounts,handler,12);
        }
        {
            auto p=setup();
            constant(p,1,vectorPc);p.push_back(csr(0x105,1,0,1));
            p.push_back(addi(2,0,2));p.push_back(csr(0x303,1,0,2));p.push_back(csr(0x304,1,0,2));
            p.push_back(csr(0x344,1,0,2));
            constant(p,2,1U<<11);p.push_back(csr(0x300,1,0,2));
            unsigned sepcAuipc=p.size();p.push_back(0x00000097);p.push_back(0);p.push_back(csr(0x141,1,0,1));
            unsigned mepcAuipc=p.size();p.push_back(0x00000097);p.push_back(0);p.push_back(csr(0x341,1,0,1));
            p.push_back(0x30200073);
            unsigned supervisorStart=p.size();p.push_back(0x10200073);
            unsigned userStart=p.size();for(unsigned i=0;i<64;++i)p.push_back(addi(10,10,1));
            p[sepcAuipc+1]=addi(1,1,4*(userStart-sepcAuipc));
            p[mepcAuipc+1]=addi(1,1,4*(supervisorStart-mepcAuipc));
            std::vector<uint32_t> handler{csr(0x142,2,26,0),csr(0x144,2,27,0),
                csr(0x144,7,0,2),csr(0x144,2,28,0),0x10200073};
            program(argv[1],p,31,false,softwareInterruptCounts,handler,13);
        }
        check(softwareInterruptCounts.programs==7 && softwareInterruptCounts.interrupts==7 &&
            softwareInterruptCounts.traps==7 && softwareInterruptCounts.mret==10 && softwareInterruptCounts.sret==5,
            "supervisor software interrupt coverage");
        std::cout<<"GSIM supervisor software interrupt: PASS programs="<<softwareInterruptCounts.programs
            <<" interrupts="<<softwareInterruptCounts.interrupts<<"\n";
        Counts supervisorTimerAccessCounts;
        for(auto [enableCompare,enableTime]:{std::pair<bool,bool>{false,true},{true,false},{true,true}}) {
            auto p=setup();
            constant(p,1,vectorPc);p.push_back(csr(0x105,1,0,1));
            p.push_back(addi(2,0,4));p.push_back(csr(0x302,1,0,2)); // Delegate illegal CSR access to S.
            p.push_back(addi(2,0,100));p.push_back(csr(0x14d,1,0,2));
            if(enableCompare){constant(p,2,UINT64_C(1)<<63);p.push_back(csr(0x30a,1,0,2));}
            if(enableTime){p.push_back(addi(2,0,2));p.push_back(csr(0x306,1,0,2));}
            constant(p,2,1U<<11);p.push_back(csr(0x300,1,0,2));
            p.push_back(0x00000097);p.push_back(addi(1,1,16));p.push_back(csr(0x341,1,0,1));p.push_back(0x30200073);
            p.push_back(csr(0x14d,2,24,0));p.push_back(csr(0xc01,2,25,0));
            p.push_back(addi(10,0,42));
            std::vector<uint32_t> handler{csr(0x142,2,26,0),csr(0x141,2,28,0),
                addi(28,28,4),csr(0x141,1,0,28),0x10200073};
            program(argv[1],p,enableCompare?enableTime?17:31:0,false,supervisorTimerAccessCounts,handler);
        }
        check(supervisorTimerAccessCounts.programs==3 && supervisorTimerAccessCounts.traps==3 &&
            supervisorTimerAccessCounts.mret==3 && supervisorTimerAccessCounts.sret==3,
            "Sstc counter-enable and STCE access coverage");
        Counts userTimeAccessCounts;
        for(bool userTimeEnabled:{false,true}) {
            auto p=setup();
            constant(p,1,vectorPc);p.push_back(csr(0x105,1,0,1));
            p.push_back(addi(2,0,4));p.push_back(csr(0x302,1,0,2));
            p.push_back(addi(2,0,2));p.push_back(csr(0x306,1,0,2));
            if(userTimeEnabled)p.push_back(csr(0x106,1,0,2));
            constant(p,2,1U<<11);p.push_back(csr(0x300,1,0,2));
            unsigned sepcAuipc=p.size();p.push_back(0x00000097);p.push_back(0);p.push_back(csr(0x141,1,0,1));
            unsigned mepcAuipc=p.size();p.push_back(0x00000097);p.push_back(0);p.push_back(csr(0x341,1,0,1));
            p.push_back(0x30200073);
            unsigned supervisorStart=p.size();p.push_back(0x10200073);
            unsigned userStart=p.size();p.push_back(csr(0xc01,2,24,0));p.push_back(addi(10,0,42));
            p[sepcAuipc+1]=addi(1,1,4*(userStart-sepcAuipc));
            p[mepcAuipc+1]=addi(1,1,4*(supervisorStart-mepcAuipc));
            std::vector<uint32_t> handler{csr(0x142,2,26,0),csr(0x141,2,28,0),
                addi(28,28,4),csr(0x141,1,0,28),0x10200073};
            program(argv[1],p,userTimeEnabled?17:0,false,userTimeAccessCounts,handler);
        }
        check(userTimeAccessCounts.programs==2 && userTimeAccessCounts.traps==1 &&
            userTimeAccessCounts.mret==2 && userTimeAccessCounts.sret==3,
            "U-mode time CSR counter-enable coverage");
        Counts supervisorTimerInterruptCounts;
        for(unsigned seed:{0U,17U}) {
            auto p=setup();
            constant(p,1,vectorPc|(seed==17));p.push_back(csr(0x105,1,0,1));
            p.push_back(addi(2,0,32));p.push_back(csr(0x303,1,0,2));p.push_back(csr(0x304,1,0,2));
            p.push_back(addi(2,0,2));p.push_back(csr(0x306,1,0,2));
            constant(p,2,UINT64_C(1)<<63);p.push_back(csr(0x30a,1,0,2));
            p.push_back(addi(2,0,5));p.push_back(csr(0x14d,1,0,2));
            p.push_back(addi(2,0,32));p.push_back(csr(0x344,2,0,2));
            p.push_back(csr(0x344,2,24,0)); // mip.STIP is read-only while STCE=1.
            constant(p,2,1U<<11);p.push_back(csr(0x300,1,0,2));
            p.push_back(0x00000097);p.push_back(addi(1,1,16));p.push_back(csr(0x341,1,0,1));p.push_back(0x30200073);
            uint64_t trigger=base+4*p.size();
            for(unsigned i=0;i<16;++i)p.push_back(addi(10,10,1));
            p.push_back(csr(0x100,6,0,2)); // The expired timer is pending but masked in S.
            for(unsigned i=0;i<64;++i)p.push_back(addi(10,10,1));
            std::vector<uint32_t> handler(seed==17?5:0,addi(0,0,0));
            for(uint32_t inst:{csr(0x142,2,26,0),csr(0x144,2,27,0),csr(0xc01,2,25,0),
                    addi(2,0,100),csr(0x14d,1,0,2),addi(0,0,0),addi(0,0,0),
                    csr(0x144,2,28,0),0x10200073U})handler.push_back(inst);
            program(argv[1],p,seed,false,supervisorTimerInterruptCounts,handler,14,trigger);
        }
        check(supervisorTimerInterruptCounts.programs==2 && supervisorTimerInterruptCounts.interrupts==2 &&
            supervisorTimerInterruptCounts.traps==2 && supervisorTimerInterruptCounts.sret==2,
            "Sstc delegated timer coverage");
        Counts softwareTimerFallbackCounts;
        for(unsigned seed:{0U,17U}) {
            auto p=setup();
            if(seed==17){constant(p,1,vectorPc|1);p.push_back(csr(0x305,1,0,1));}
            p.push_back(addi(2,0,32));p.push_back(csr(0x344,1,0,2));p.push_back(csr(0x304,1,0,2));
            p.push_back(csr(0x300,6,0,8));
            for(unsigned i=0;i<64;++i)p.push_back(addi(10,10,1));
            std::vector<uint32_t> handler(seed==17?5:0,addi(0,0,0));
            for(uint32_t inst:{csr(0x342,2,26,0),csr(0x344,2,27,0),
                    addi(2,0,32),csr(0x344,3,0,2),csr(0x344,2,28,0),0x30200073U})handler.push_back(inst);
            program(argv[1],p,seed,false,softwareTimerFallbackCounts,handler,15);
        }
        check(softwareTimerFallbackCounts.programs==2 && softwareTimerFallbackCounts.interrupts==2 &&
            softwareTimerFallbackCounts.traps==2 && softwareTimerFallbackCounts.mret==2,
            "Sstc disabled software-STIP fallback coverage");
        std::cout<<"GSIM supervisor timer: PASS access="<<supervisorTimerAccessCounts.programs
            <<" userTime="<<userTimeAccessCounts.programs
            <<" delegated="<<supervisorTimerInterruptCounts.interrupts
            <<" fallback="<<softwareTimerFallbackCounts.interrupts<<"\n";
#endif
        // Complete MSI -> M interrupt -> claim -> MRET, with independent architectural checks.
        Counts timerCounts;
        for(unsigned timerMode=0;timerMode<2;++timerMode)
        for(unsigned scenario=timerMode?3:1;scenario<=7;++scenario)for(unsigned seed:{0U,17U,8191U}) {
            machineInterruptProgram(argv[1],scenario,seed,timerMode,timerMode?timerCounts:counts);
        }
        for(unsigned seed:{0U,17U,8191U}) {
            auto p=setup();
            p.push_back(csr(0x344,1,4,0));p.push_back(csr(0x344,2,5,0)); // MTIP remains set with MTIE=0.
            p.push_back(csr(0x300,6,0,8)); // MIE alone cannot deliver.
            for(unsigned i=0;i<8;++i)p.push_back(addi(8,8,1));
            p.push_back(csr(0x300,7,0,8));
            p.push_back(addi(1,0,0xc0));p.push_back(csr(0x350,1,0,1));p.push_back(addi(2,0,8));p.push_back(csr(0x351,1,0,2));
            p.push_back(addi(1,0,0x70));p.push_back(csr(0x350,1,0,1));p.push_back(csr(0x351,5,0,1));
            constant(p,2,2176);p.push_back(csr(0x304,1,0,2)); // Both enabled while MIE=0.
            for(unsigned i=0;i<8;++i)p.push_back(addi(8,8,1));
            p.push_back(csr(0x300,6,0,8));
            for(unsigned i=0;i<64;++i)p.push_back(addi(10,10,1));
            std::vector<uint32_t> h{csr(0x342,2,26,0),0x00fd7d93,addi(28,0,1),0x01be1e33,
                csr(0x304,3,0,28),csr(0x35c,1,30,0),addi(31,31,1),0x30200073};
            program(argv[1],p,seed,false,timerCounts,h,9,0,false,true);
        }
        check(timerCounts.programs==18&&timerCounts.interrupts==21&&timerCounts.emptyInterrupts==3&&timerCounts.memoryInterrupts==3&&timerCounts.storeInterrupts==3&&timerCounts.priorityTraps==3,"timer IRQ coverage");
        std::cout<<"GSIM machine timer interrupts: PASS programs="<<timerCounts.programs<<" interrupts="<<timerCounts.interrupts<<" traps="<<timerCounts.traps<<"\n";
        check(counts.interrupts==39 && counts.emptyInterrupts==3 && counts.memoryInterrupts==3 && counts.storeInterrupts==3 && counts.priorityTraps==3,"IRQ coverage");
        std::cout<<"GSIM MachineCore: PASS programs="<<counts.programs<<" commits="<<counts.commits<<" traps="<<counts.traps
            <<" interrupts="<<counts.interrupts<<" empty="<<counts.emptyInterrupts<<" memoryIrq="<<counts.memoryInterrupts<<" storeIrq="<<counts.storeInterrupts<<" priority="<<counts.priorityTraps
            <<" mret="<<counts.mret<<" csr="<<counts.csrOps<<" held="<<counts.held<<" redirects="<<counts.redirects<<"\n";
    }catch(const std::exception&e){
        if(headTrapNegativeAttempted && std::string(e.what())=="trap metadata")
            std::cerr<<"GSIM head trap short negative: oracle rejected injected interrupt cause\n";
        std::cerr<<"GSIM MachineCore: FAIL "<<e.what()<<'\n';return 1;
    }
}
