#include "TileLinkGmacControl.h"
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>
#include <string_view>
#include <tuple>
#include <vector>

static constexpr uint64_t base=0x10040000;
static void check(bool ok,const char *why){if(!ok)throw std::runtime_error(why);}
struct Request {unsigned opcode=4,size=3,source=0,mask=255,param=0;uint64_t address=base,data=0;bool corrupt=false;};
struct Reply {uint64_t data;unsigned opcode,size,source;bool denied,corrupt;};
// Independent end-to-end CSR -> wire -> result/IRQ check. The random register
// oracle below deliberately does not model serial timing or launch commands.
static void mdioThroughControl(bool inject) {
    STileLinkGmacControl d;
    d.set_io$$tl$$a$$valid(0);d.set_io$$tl$$d$$ready(0);
    d.set_io$$tl$$c$$valid(0);d.set_io$$tl$$e$$valid(0);
    d.set_io$$ports$$events(0);d.set_io$$ports$$txBytes(0);d.set_io$$ports$$rxBytes(0);
    d.set_io$$ports$$linkUp(0);d.set_io$$ports$$txBusy(0);d.set_io$$ports$$rxBusy(0);
    d.set_io$$ports$$mdioIn(1);d.set_reset(1);d.step();d.step();d.set_reset(0);
    struct Command {unsigned phy,reg;bool write;uint16_t data,rx;bool noAck;};
    std::optional<Command> serial;
    std::vector<bool> expectedBits;
    unsigned rises=0,falls=0,frames=0,stalls=0,transactions=0;
    bool previousMdc=false;
    std::deque<Reply> replies;
    auto tick=[&](const std::optional<Request>&request,bool dReady,uint64_t expectedData=0,
                  bool denied=false,std::optional<Command> launch=std::nullopt) {
        const Request r=request.value_or(Request{});
        bool in=true;
        if(serial && !serial->write) {
            if(falls==47)in=serial->noAck;
            if(falls>=48 && falls<64)in=(serial->rx>>(63-falls))&1;
        }
        d.set_io$$ports$$mdioIn(in);
        d.set_io$$tl$$a$$valid(bool(request));d.set_io$$tl$$d$$ready(dReady);
        d.set_io$$tl$$a$$bits$$opcode(r.opcode);d.set_io$$tl$$a$$bits$$param(r.param);
        d.set_io$$tl$$a$$bits$$size(r.size);d.set_io$$tl$$a$$bits$$source(r.source);
        d.set_io$$tl$$a$$bits$$address(r.address);d.set_io$$tl$$a$$bits$$mask(r.mask);
        d.set_io$$tl$$a$$bits$$data(r.data);d.set_io$$tl$$a$$bits$$corrupt(r.corrupt);
        d.step();
        const bool mdc=d.get_io$$ports$$mdc();
        if(mdc!=previousMdc) {
            check(bool(serial),"GMAC MDIO emitted clocks without accepted START");
            if(mdc) {
                const unsigned bit=rises++;
                check(bit<64,"GMAC MDIO excess frame clocks");
                const bool oe=serial->write || bit<46;
                check(bool(d.get_io$$ports$$mdioOe())==oe,"GMAC MDIO read turnaround ownership mismatch");
                if(oe)check(bool(d.get_io$$ports$$mdioOut())==
                    (expectedBits.at(bit)^(inject && frames==0 && bit==36)),
                    "TL GMAC MDIO independent wire oracle mismatch");
            } else if(++falls==64) {
                check(rises==64 && !d.get_io$$ports$$mdioOe(),"GMAC MDIO incomplete bus release");
                serial.reset();++frames;
            }
        }
        previousMdc=mdc;
        check(bool(d.get_io$$tl$$d$$valid())==!replies.empty(),"GMAC MDIO TL reply ordering mismatch");
        if(!replies.empty()) {
            const Reply e=replies.front();
            check(d.get_io$$tl$$d$$bits$$data()==e.data && d.get_io$$tl$$d$$bits$$opcode()==e.opcode &&
                d.get_io$$tl$$d$$bits$$size()==e.size && d.get_io$$tl$$d$$bits$$source()==e.source &&
                bool(d.get_io$$tl$$d$$bits$$denied())==e.denied &&
                bool(d.get_io$$tl$$d$$bits$$corrupt())==e.corrupt,
                "TL GMAC MDIO CSR result/IRQ oracle mismatch");
            if(dReady)replies.pop_front();
        }
        bool accepted=request && d.get_io$$tl$$a$$ready();
        if(request && !accepted)++stalls;
        if(accepted) {
            const bool get=r.opcode==4;
            replies.push_back({expectedData,get?1U:0U,r.size,r.source,denied,denied&&get});
            ++transactions;
            if(launch) {
                check(!serial,"GMAC accepted overlapping MDIO command");
                serial=launch;rises=0;falls=0;expectedBits.assign(32,true);
                auto append=[&](unsigned value,unsigned width){
                    for(unsigned n=width;n>0;--n)expectedBits.push_back((value>>(n-1))&1);
                };
                append(1,2);append(launch->write?1:2,2);append(launch->phy,5);append(launch->reg,5);
                append(2,2);append(launch->data,16);
            }
        }
        return accepted;
    };
    auto access=[&](Request r,uint64_t expected=0,bool denied=false,
                    std::optional<Command> launch=std::nullopt,bool dReady=true) {
        bool accepted=false;
        for(unsigned n=0;n<2000&&!accepted;++n)accepted=tick(r,dReady,expected,denied,launch);
        check(accepted,"GMAC MDIO CSR access timed out");
        if(dReady)tick(std::nullopt,true);
    };
    auto get=[&](unsigned off,uint64_t expected){Request r;r.address=base+off;access(r,expected);};
    auto put=[&](unsigned off,uint64_t value){Request r;r.opcode=0;r.address=base+off;r.data=value;access(r);};
    auto start=[&](Command c,bool ready=true){
        Request r;r.opcode=0;r.address=base+0x78;r.source=3;
        r.data=c.data|(uint64_t(c.write)<<16)|(1ULL<<17)|(uint64_t(c.phy)<<18)|(uint64_t(c.reg)<<23);
        access(r,0,false,c,ready);
    };
    auto finish=[&]{
        for(unsigned n=0;n<2000&&serial;++n)tick(std::nullopt,true);
        check(!serial,"GMAC MDIO wire transaction timed out");
        for(unsigned n=0;n<4;++n)tick(std::nullopt,true);
        get(0x80,2);get(0x30,64);check(d.get_io$$irq()==1,"GMAC MDIO completion IRQ missing");
    };
    get(0x80,0);get(0x88,0);put(0x38,64);
    start({1,0,true,0x1200,0,false},false);
    // Invalid partial START must be denied even while the serial engine is busy,
    // and held TL replies must not stop the ongoing wire transaction.
    Request partial;partial.opcode=1;partial.address=base+0x78;partial.mask=4;partial.data=1ULL<<17;
    access(partial,0,true,std::nullopt,false);
    for(unsigned n=0;n<50;++n)tick(std::nullopt,false);
    start({1,2,false,0,0x001c,false}); // Held legal START until the first command/reply completes.
    finish();get(0x88,0x001c);put(0x30,64);get(0x30,0);
    check(!d.get_io$$irq(),"GMAC MDIO W1C did not clear IRQ");
    start({7,17,false,0,0xdead,true});finish();get(0x88,0x1dead);
    start({31,31,true,0x55aa,0,false});finish();get(0x88,0x55aa);
    start({1,3,false,0,0xbeef,false});
    for(unsigned n=0;n<100;++n)tick(std::nullopt,true);
    d.set_io$$tl$$a$$valid(0);d.set_reset(1);d.step();d.step();d.set_reset(0);
    serial.reset();replies.clear();previousMdc=false;
    tick(std::nullopt,true);get(0x80,0);get(0x88,0);get(0x30,0);
    check(!d.get_io$$ports$$mdc() && !d.get_io$$ports$$mdioOe() && !d.get_io$$irq(),
        "GMAC control reset did not cancel serial state/IRQ");
    check(frames==4 && stalls>400 && replies.empty(),"GMAC MDIO integrated coverage incomplete");
    std::cout<<"TL_GMAC_MDIO_PASS frames="<<frames<<" requests="<<transactions<<" busy_stalls="<<stalls
        <<" noack=1 reset_cancel=1\n";
}
struct Oracle {
    uint64_t control=8,mac=0,enable=0,pending=0;
    std::array<uint64_t,6> counts{};
    static bool known(unsigned off){switch(off){
        case 0:case 8:case 0x10:case 0x18:case 0x20:case 0x28:case 0x30:case 0x38:
        case 0x40:case 0x48:case 0x50:case 0x58:case 0x60:case 0x68:case 0x70:case 0x78:case 0x80:case 0x88:return true;
        default:return false;}}
    static uint64_t allowed(unsigned off){switch(off){
        case 0x10:return 15;case 0x18:return 0xffffffffffffULL;case 0x30:case 0x38:return 127;
        case 0x70:return 1;case 0x78:return 0x0fffffff;default:return 0;}}
    uint64_t read(unsigned off,bool link,bool txBusy,bool rxBusy)const{switch(off){
        case 0:return 0x56474d4100010001ULL;case 8:return (2048ULL<<32)|(8ULL<<16)|1;
        case 0x10:return control;case 0x18:return mac;case 0x20:return 2048;
        case 0x28:return unsigned(link)|(unsigned(txBusy)<<1)|(unsigned(rxBusy)<<2);
        case 0x30:return pending;case 0x38:return enable;
        case 0x40:case 0x48:case 0x50:case 0x58:case 0x60:case 0x68:return counts.at((off-0x40)/8);
        default:return 0;}}
    Reply request(const Request&r,bool link,bool txBusy,bool rxBusy){
        const unsigned off=unsigned(r.address)&0xff8;
        const bool get=r.opcode==4,put=r.opcode<=1;
        uint64_t byteMask=0;for(unsigned n=0;n<8;++n)if(r.mask&(1U<<n))byteMask|=0xffULL<<(8*n);
        const uint64_t bits=r.data&byteMask;
        unsigned fullMask=0;if(r.size<=3)fullMask=((1U<<(1U<<r.size))-1)<<(r.address&7);
        const bool launch=put && off==0x78 && (bits&(1ULL<<17));
        bool legal=(get||put)&&r.size<=3&&!(r.address&((1ULL<<r.size)-1))&&
            (r.opcode==1?!(r.mask&~fullMask):r.mask==fullMask)&&!r.param&&!r.corrupt&&
            r.address>=base&&r.address<base+4096&&known(off);
        if(put)legal=legal&&allowed(off)&&!(bits&~allowed(off))&&
            (!launch||(r.size==3&&r.mask==255))&&
            !((off==0x10||off==0x18)&&r.mask&&(txBusy||rxBusy));
        // Serial launches are separately verified at the MDIO module; valid
        // launches are deliberately not issued by this CSR/credit oracle.
        check(!legal||!launch,"CSR oracle accidentally issued serial command");
        const bool dataResponse=get||r.opcode==2||r.opcode==3;
        Reply reply{legal&&get?read(off,link,txBusy,rxBusy):0,dataResponse?1U:0U,
            r.size,r.source,!legal,!legal&&dataResponse};
        if(legal&&put){
            if(off==0x10)control=(control&~byteMask)|bits;
            if(off==0x18)mac=(mac&~byteMask)|bits;
            if(off==0x38)enable=(enable&~byteMask)|bits;
            if(off==0x30)pending&=~bits;
            if(off==0x70&&(bits&1))counts.fill(0);
        }
        return reply;
    }
    void event(unsigned flags,unsigned tx,unsigned rx){
        pending|=flags;
        for(unsigned n=0;n<4;++n)counts[n]+=(flags>>n)&1;
        if(flags&1)counts[4]+=tx;if(flags&2)counts[5]+=rx;
    }
};
int main(int argc,char **argv){try{
    const bool inject=argc==2&&std::string_view(argv[1])=="--inject-mismatch";
    const bool injectMdio=argc==2&&std::string_view(argv[1])=="--inject-mdio-mismatch";
    STileLinkGmacControl d;Oracle oracle;std::deque<Reply> queue;
    d.set_io$$tl$$a$$valid(0);d.set_io$$tl$$d$$ready(0);d.set_io$$tl$$c$$valid(0);d.set_io$$tl$$e$$valid(0);
    d.set_io$$ports$$events(0);d.set_io$$ports$$txBytes(0);d.set_io$$ports$$rxBytes(0);
    d.set_io$$ports$$linkUp(0);d.set_io$$ports$$txBusy(0);d.set_io$$ports$$rxBusy(0);d.set_io$$ports$$mdioIn(1);
    d.set_reset(1);d.step();d.step();d.set_reset(0);
    std::mt19937_64 random(0x20261004c50ULL);
    unsigned accepted=0,returned=0,rejected=0,maxPending=0,stalls=0;
    std::optional<std::tuple<uint64_t,unsigned,unsigned,unsigned,bool,bool>> held;
    auto cycle=[&](const std::optional<Request>&req,bool ready,unsigned flags,unsigned tx,unsigned rx,
        bool link,bool txBusy,bool rxBusy){
        Request r=req.value_or(Request{});
        d.set_io$$tl$$a$$valid(bool(req));d.set_io$$tl$$a$$bits$$opcode(r.opcode);
        d.set_io$$tl$$a$$bits$$param(r.param);d.set_io$$tl$$a$$bits$$size(r.size);
        d.set_io$$tl$$a$$bits$$source(r.source);d.set_io$$tl$$a$$bits$$address(r.address);
        d.set_io$$tl$$a$$bits$$mask(r.mask);d.set_io$$tl$$a$$bits$$data(r.data);d.set_io$$tl$$a$$bits$$corrupt(r.corrupt);
        d.set_io$$tl$$d$$ready(ready);d.set_io$$ports$$events(flags);
        d.set_io$$ports$$txBytes(tx);d.set_io$$ports$$rxBytes(rx);
        d.set_io$$ports$$linkUp(link);d.set_io$$ports$$txBusy(txBusy);d.set_io$$ports$$rxBusy(rxBusy);
        d.step();
        check(bool(d.get_io$$irq())==bool(oracle.pending&oracle.enable),"GMAC IRQ sticky/event/W1C mismatch");
        check(d.get_io$$ports$$txEnable()==bool(oracle.control&1)&&d.get_io$$ports$$rxEnable()==bool(oracle.control&2)&&
            d.get_io$$ports$$promiscuous()==bool(oracle.control&4)&&d.get_io$$ports$$broadcastEnable()==bool(oracle.control&8)&&
            d.get_io$$ports$$macAddress()==oracle.mac,"GMAC rejected/partial write changed configuration");
        check(bool(d.get_io$$tl$$d$$valid())==!queue.empty(),"GMAC reply latency/capacity mismatch");
        const bool canAccept=queue.size()<4;
        check(bool(d.get_io$$tl$$a$$ready())==canAccept,"GMAC reply credits mismatch");
        if(!queue.empty()){
            auto actual=std::make_tuple(uint64_t(d.get_io$$tl$$d$$bits$$data()),unsigned(d.get_io$$tl$$d$$bits$$opcode()),
                unsigned(d.get_io$$tl$$d$$bits$$size()),unsigned(d.get_io$$tl$$d$$bits$$source()),
                bool(d.get_io$$tl$$d$$bits$$denied()),bool(d.get_io$$tl$$d$$bits$$corrupt()));
            const auto expected=queue.front();
            const auto target=std::make_tuple(expected.data^(inject&&returned==0?1ULL:0ULL),expected.opcode,
                expected.size,expected.source,expected.denied,expected.corrupt);
            check(actual==target&&d.get_io$$tl$$d$$bits$$param()==0&&d.get_io$$tl$$d$$bits$$sink()==0,
                "TL GMAC independent CSR oracle mismatch");
            if(held)check(actual==*held,"GMAC D payload changed under backpressure");
            held=ready?std::nullopt:std::optional{actual};
            if(ready){queue.pop_front();++returned;}
        }else held.reset();
        bool fired=req&&canAccept;
        if(fired){Reply reply=oracle.request(r,link,txBusy,rxBusy);rejected+=reply.denied;queue.push_back(reply);++accepted;}
        if(req&&!canAccept)++stalls;
        oracle.event(flags,tx,rx);if(queue.size()>maxPending)maxPending=queue.size();
        return fired;
    };
    std::vector<Request> requests;
    requests.push_back(Request{});
    Request enable;enable.opcode=0;enable.address=base+0x38;enable.data=63;requests.push_back(enable);
    static constexpr std::array<unsigned,18> offsets{0,8,0x10,0x18,0x20,0x28,0x30,0x38,
        0x40,0x48,0x50,0x58,0x60,0x68,0x70,0x78,0x80,0x88};
    for(unsigned n=0;n<3000;++n){
        Request r;r.opcode=n%3==0?4:(n%2);r.size=n%4;r.source=n%16;
        unsigned off=offsets[n%offsets.size()];
        unsigned lane=(n/4)%8;lane&=~((1U<<r.size)-1);r.address=base+off+lane;
        r.mask=((1U<<(1U<<r.size))-1)<<lane;
        if(r.opcode==1)r.mask&=unsigned(random()%256);
        r.data=random()&Oracle::allowed(off);
        if(off==0x78)r.data&=~(1ULL<<17);
        if(n%11==0)r.data=random();
        // Never accidentally start a legal serial request in this test.
        if(off==0x78)r.data&=~(1ULL<<17);
        if(n%13==0)r.address=base-8;
        if(n%17==0)r.address=base+4096;
        if(n%19==0)r.address=base+0x90;
        if(n%23==0)r.mask^=128;
        if(n%29==0)r.param=1;
        if(n%31==0)r.corrupt=true;
        if(n%37==0)r.opcode=2;
        requests.push_back(r);
    }
    for(unsigned size=0;size<4;++size)for(unsigned lane=0;lane<8;++lane){
        Request r;r.opcode=1;r.size=size;r.mask=0;r.address=base+0x18+lane;
        requests.push_back(r);
    }
    unsigned next=0;
    for(unsigned n=0;n<20000&&(next<requests.size()||!queue.empty());++n){
        std::optional<Request> req=next<requests.size()?std::optional{requests[next]}:std::nullopt;
        bool ready=n%41>=15&&random()%3!=0;
        unsigned events=n%7==0?unsigned(random()%64):0;
        if(cycle(req,ready,events,n%1515,(n*3)%1515,n%5!=0,n%11==0,n%17==0))++next;
    }
    check(next==requests.size()&&accepted==returned&&maxPending==4&&stalls&&rejected,
        "TL GMAC coverage/drain incomplete");
    // Snapshot every counter after stopping events, and exercise event-vs-clear.
    for(unsigned off: {0x40U,0x48U,0x50U,0x58U,0x60U,0x68U}){
        Request r;r.address=base+off;
        cycle(r,true,0,0,0,false,false,false);cycle(std::nullopt,true,0,0,0,false,false,false);
    }
    Request clear;clear.opcode=0;clear.address=base+0x70;clear.data=1;
    cycle(clear,true,15,77,88,false,false,false);cycle(std::nullopt,true,0,0,0,false,false,false);
    Request ack;ack.opcode=0;ack.address=base+0x30;ack.data=63;
    cycle(ack,true,8,0,0,false,false,false);cycle(std::nullopt,true,0,0,0,false,false,false);
    Request read;read.address=base+0x30;
    cycle(read,true,0,0,0,false,false,false);cycle(std::nullopt,true,0,0,0,false,false,false);
    // Reset with queued responses; all replies and configuration must be discarded.
    cycle(read,false,0,0,0,false,false,false);cycle(read,false,0,0,0,false,false,false);
    d.set_io$$tl$$a$$valid(0);d.set_io$$ports$$events(0);d.set_reset(1);d.step();d.step();d.set_reset(0);
    oracle=Oracle{};queue.clear();held.reset();
    cycle(std::nullopt,true,0,0,0,false,false,false);
    mdioThroughControl(injectMdio);
    std::cout<<"TILELINK_GMAC_CONTROL_PASS requests="<<accepted<<" denied="<<rejected
        <<" max_credits="<<maxPending<<" a_stalls="<<stalls<<" reset_cancel=1\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
