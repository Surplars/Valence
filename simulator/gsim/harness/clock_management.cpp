#if defined(CMU_TL)
#include "ClockManagementTlGsim.h"
using Model = SClockManagementTlGsim;
#elif defined(CMU_ROUTER)
#include "ClockManagementRouterGsim.h"
using Model = SClockManagementRouterGsim;
#else
#include "ClockManagementGsim.h"
using Model = SClockManagementGsim;
#endif
#include <cstdint>
#include <deque>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

static void check(bool ok, const char *reason) { if (!ok) throw std::runtime_error(reason); }
struct Request {
    uint64_t address, data=0; unsigned size=3, mask=255, source=0;
    bool write=false, atomic=false; unsigned opcode=4, param=0; bool corrupt=false;
};
struct Reply { uint64_t data; bool error; unsigned source=0, size=0, opcode=0; };
struct Harness {
    Model d; unsigned wake=0, noAck=0, forceAck=0, lastQ=0, accesses=0;
    std::deque<uint64_t> memory;
    Request offer{0}; bool valid=false;
    Harness() { drive({0},false); ready(false); reset(); }
    void drive(Request r, bool v) {
        offer=r; valid=v;
#if defined(CMU_TL)
        d.set_io$$tl$$a$$valid(v); d.set_io$$tl$$a$$bits$$address(r.address);
        d.set_io$$tl$$a$$bits$$data(r.data << ((r.address&7)*8));
        d.set_io$$tl$$a$$bits$$mask(r.mask << (r.address&7));
        d.set_io$$tl$$a$$bits$$size(r.size); d.set_io$$tl$$a$$bits$$source(r.source);
        d.set_io$$tl$$a$$bits$$opcode(r.opcode); d.set_io$$tl$$a$$bits$$param(r.param);
        d.set_io$$tl$$a$$bits$$corrupt(r.corrupt);
        d.set_io$$tl$$b$$ready(0); d.set_io$$tl$$c$$valid(0); d.set_io$$tl$$e$$valid(0);
#elif defined(CMU_ROUTER)
        d.set_io$$upstream$$request$$valid(v); d.set_io$$upstream$$request$$bits$$address(r.address);
        d.set_io$$upstream$$request$$bits$$data(r.data << ((r.address&7)*8));
        d.set_io$$upstream$$request$$bits$$mask(r.mask << (r.address&7));
        d.set_io$$upstream$$request$$bits$$size(r.size); d.set_io$$upstream$$request$$bits$$write(r.write);
        d.set_io$$upstream$$request$$bits$$atomic(r.atomic); d.set_io$$upstream$$request$$bits$$atomicOp(2);
        d.set_io$$upstream$$request$$bits$$virtualized(0); d.set_io$$upstream$$request$$bits$$uncached(1);
#else
        d.set_io$$control$$request$$valid(v); d.set_io$$control$$request$$bits$$address(r.address);
        d.set_io$$control$$request$$bits$$data(r.data); d.set_io$$control$$request$$bits$$byteEnable(r.mask);
        d.set_io$$control$$request$$bits$$size(r.size); d.set_io$$control$$request$$bits$$write(r.write);
#endif
    }
    void ready(bool v) {
#if defined(CMU_TL)
        d.set_io$$tl$$d$$ready(v);
#elif defined(CMU_ROUTER)
        d.set_io$$upstream$$response$$ready(v);
#else
        d.set_io$$control$$response$$ready(v);
#endif
    }
    bool requestReady() {
#if defined(CMU_TL)
        return d.get_io$$tl$$a$$ready();
#elif defined(CMU_ROUTER)
        return d.get_io$$upstream$$request$$ready();
#else
        return d.get_io$$control$$request$$ready();
#endif
    }
    bool replyValid() {
#if defined(CMU_TL)
        return d.get_io$$tl$$d$$valid();
#elif defined(CMU_ROUTER)
        return d.get_io$$upstream$$response$$valid();
#else
        return d.get_io$$control$$response$$valid();
#endif
    }
    Reply reply() {
#if defined(CMU_TL)
        check(bool(d.get_io$$tl$$d$$bits$$corrupt()) ==
            (bool(d.get_io$$tl$$d$$bits$$denied()) && d.get_io$$tl$$d$$bits$$opcode()==1),
            "CMU TL denied/corrupt mismatch");
        return {d.get_io$$tl$$d$$bits$$data(),bool(d.get_io$$tl$$d$$bits$$denied()),
            unsigned(d.get_io$$tl$$d$$bits$$source()),unsigned(d.get_io$$tl$$d$$bits$$size()),
            unsigned(d.get_io$$tl$$d$$bits$$opcode())};
#elif defined(CMU_ROUTER)
        check(!d.get_io$$upstream$$response$$bits$$pageFault(),"CMU router invented page fault");
        return {d.get_io$$upstream$$response$$bits$$data(),bool(d.get_io$$upstream$$response$$bits$$error())};
#else
        return {d.get_io$$control$$response$$bits$$data(),bool(d.get_io$$control$$response$$bits$$error())};
#endif
    }
    void tick() {
        d.set_io$$signals$$ack((lastQ & ~noAck) | forceAck); d.set_io$$signals$$wake(wake);
#if defined(CMU_ROUTER)
        bool have=!memory.empty(); uint64_t value=have?memory.front():0;
        d.set_io$$memory$$request$$ready(1); d.set_io$$memory$$response$$valid(have);
        d.set_io$$memory$$response$$bits$$data(value); d.set_io$$memory$$response$$bits$$error(0);
        d.set_io$$memory$$response$$bits$$pageFault(0);
#endif
        d.step(); lastQ=d.get_io$$signals$$quiesce();
#if defined(CMU_ROUTER)
        if (have && d.get_io$$memory$$response$$ready()) memory.pop_front();
        if (d.get_io$$memory$$request$$valid()) {
            check(valid && (offer.atomic || offer.address<0x10080000 || offer.address>=0x10081000),
                "CMU router forwarded a CSR access");
            check(d.get_io$$memory$$request$$bits$$address()==offer.address &&
                d.get_io$$memory$$request$$bits$$atomic()==offer.atomic &&
                d.get_io$$memory$$request$$bits$$atomicOp()==2 &&
                d.get_io$$memory$$request$$bits$$data()==(offer.data<<((offer.address&7)*8)) &&
                d.get_io$$memory$$request$$bits$$mask()==(offer.mask<<(offer.address&7)) &&
                d.get_io$$memory$$request$$bits$$uncached() &&
                !d.get_io$$memory$$request$$bits$$virtualized(),"CMU router memory/atomic changed");
            memory.push_back(offer.address ^ offer.data ^ 0x1122334455667788ULL);
        }
#endif
    }
    void wait(unsigned n) { drive({0},false); ready(true); while(n--)tick(); }
    void reset() { wake=noAck=forceAck=lastQ=0; memory.clear();
        d.set_reset(1); tick(); tick(); d.set_reset(0); wait(6); }
    Reply access(Request r) {
        r.source=(accesses++)%16;
        bool sent=false,held=false; Reply prev{};
        for(unsigned n=0;n<200;++n) {
            bool consume=n>=8 && n%3!=1;
            drive(r,!sent); ready(consume); tick();
            if(!sent && requestReady())sent=true;
            if(replyValid()) {
                Reply now=reply();
                if(held) check(now.data==prev.data && now.error==prev.error && now.source==prev.source &&
                    now.size==prev.size && now.opcode==prev.opcode,"CMU response changed while stalled");
                held=true; prev=now;
                if(consume) {
                    check(sent,"CMU response without request");
#if defined(CMU_TL)
                    check(now.source==r.source && now.size==r.size &&
                        now.opcode==((r.opcode==4 || r.opcode==2 || r.opcode==3)?1:0),
                        "CMU TL response owner mismatch");
#endif
                    drive({0},false); return now;
                }
            }
        }
        throw std::runtime_error("CMU access timed out");
    }
    uint64_t read(unsigned offset,unsigned size=3) {
        auto r=access({0x10080000ULL+offset,0,size,unsigned((1U<<(1U<<size))-1)});
        check(!r.error,"CMU valid read denied");
#if defined(CMU_TL) || defined(CMU_ROUTER)
        return r.data >> ((offset&7)*8);
#else
        return r.data;
#endif
    }
    void write(unsigned offset,uint64_t data,bool error=false,unsigned size=3,unsigned mask=255) {
        Request q{0x10080000ULL+offset,data,size,mask}; q.write=true; q.opcode=(mask==255?0:1);
        auto r=access(q); check(r.error==error && r.data==0,"CMU write status/side-effect contract mismatch");
    }
};

int main(int argc,char **argv) { try {
    bool inject=argc==2 && std::string_view(argv[1])=="--inject-mismatch";
    Harness h;
    check(h.read(0)==(0x56434d5500010001ULL ^ unsigned(inject)),"CMU independent register oracle mismatch");
    check(h.read(8)==((50000000ULL<<32)|(5<<16)|7) && h.read(16)==15 && h.read(24)==12,
        "CMU capability inventory mismatch");
    check(h.read(0x108)==50000000 && h.read(0x148)==100000000 && h.read(0x1d0)==3 &&
        h.read(0x210)==0 && h.read(0x128)==0x4e4f41,"CMU resource descriptor mismatch");
    for(unsigned size=0;size<4;++size) for(unsigned lane=0;lane<8;lane+=(1U<<size))
        check(h.read(lane,size)==(0x56434d5500010001ULL>>(8*lane)),"CMU subword lane mismatch");
    // Protected writes reject the WHOLE access, not just unsafe bits.
    h.write(0x20,13,true); check(h.read(0x20)==0,"CMU protected STOP partially applied");
    h.write(0x70,13,true); check(h.read(0x70)==0,"CMU protected IRQ partially applied");
    h.write(0,0,true); h.write(0x80,0,true); h.write(0x20,4,true,0,2);
    check(h.access({0x10080021,0,3,255}).error,"CMU unaligned read accepted");
#if !defined(CMU_ROUTER)
    check(h.access({0x10081000,0,3,255}).error,"CMU outside window accepted");
#endif
    // Partial byte strobes and randomized bounded RW mirror, independent of RTL.
    std::mt19937_64 rng(0x20261004c00ULL); unsigned mirror=0;
    for(unsigned n=0;n<128;++n) {
        unsigned size=n%4,mask=unsigned(rng())&((1U<<(1U<<size))-1),value=unsigned(rng())&12;
        h.write(0x70,value,false,size,mask); if(mask&1)mirror=value;
        check(h.read(0x70)==mirror,"CMU independent partial-write mirror mismatch");
    }
    h.write(0x71,0xff,true,0,1); check(h.read(0x70)==mirror,"CMU reserved-byte write had side effect");
    h.write(0x70,12); h.write(0x20,12); h.wait(20);
    check(h.read(0x30)==12 && h.read(0x28)==3 && h.read(0x40)==12 && h.read(0x48)==3,
        "CMU drain-to-stop state mismatch");
    h.wake=4; h.wait(12);
    check(h.read(0x20)==8 && h.read(0x50)==4 && h.d.get_io$$signals$$irq() &&
        (h.d.get_io$$signals$$enabled()&4) && !(h.d.get_io$$signals$$isolate()&4),
        "CMU wake did not reopen clock and release isolation");
    h.write(0x50,4); check(h.read(0x50)==4,"CMU wake event lost to concurrent W1C");
    h.wake=0; h.wait(5); h.write(0x50,4); check(h.read(0x50)==0,"CMU wake W1C failed");
    h.write(0x60,8); h.wait(12);
    check(h.read(0x20)==0 && h.read(0x50)==8 && h.read(0x28)==15,"CMU software wake failed");
    h.write(0x50,8); h.noAck=4; h.write(0x20,4); h.wait(48);
    check(h.read(0x68)==4 && h.read(0x28)==15 && h.d.get_io$$signals$$irq(),
        "CMU drain timeout did not fail open with IRQ");
    h.write(0x68,4); check(h.read(0x68)==0,"CMU fault W1C failed");
    h.write(0x20,0); h.noAck=0; h.wait(4); h.write(0x20,4); h.wait(16);
    check(h.read(0x30)==4,"CMU timeout retry did not rearm");
    h.forceAck=4; h.write(0x60,4); h.wait(48);
    check(h.read(0x68)==4 && (h.read(0x28)&4) && (h.read(0x40)&4) && !(h.read(0x48)&4),
        "CMU wake without destination progress released isolation");
    h.forceAck=0; h.wait(8); check(!(h.read(0x40)&4),"CMU wake recovery remained isolated");
    h.reset(); check(h.read(0x20)==0 && h.read(0x28)==15 && h.read(0x50)==0 && h.read(0x68)==0,
        "CMU coordinated cold reset failed");
    // Four reply credits: fifth request stalls and queued replies remain ordered.
    unsigned sent=0,received=0;
    for(unsigned n=0;n<12;++n) {
        Request r{0x10080000ULL}; r.source=sent;
        h.drive(r,true); h.ready(false); h.tick(); if(h.requestReady())++sent;
    }
    check(sent==4,"CMU ordered reply capacity is not four");
    for(unsigned n=0;n<30 && received<4;++n) {
        h.drive({0},false); h.ready(n%3!=0); h.tick();
        if(h.replyValid() && n%3!=0) {
            auto r=h.reply(); check(r.data==0x56434d5500010001ULL && !r.error,"CMU queued reply mismatch");
#if defined(CMU_TL)
            check(r.source==received,"CMU queued TL source order mismatch");
#endif
            ++received;
        }
    }
    check(received==4,"CMU queued replies lost");
#if defined(CMU_TL)
    for(unsigned op: {2U,3U,5U,6U,7U}) {
        Request r{0x10080020ULL,12}; r.opcode=op;
        check(h.access(r).error && h.read(0x20)==0,"CMU unsupported TL request modified control");
    }
    Request bad{0x10080020ULL,12}; bad.write=true; bad.opcode=0; bad.corrupt=true;
    check(h.access(bad).error && h.read(0x20)==0,"CMU corrupt TL write modified control");
    bad.corrupt=false;bad.param=1;check(h.access(bad).error,"CMU TL param accepted");
#endif
#if defined(CMU_ROUTER)
    for(bool atomic: {false,true}) {
        Request r{atomic?0x10080020ULL:0x80000200ULL,0x12345678}; r.atomic=atomic;
        auto response=h.access(r);
        check(!response.error && response.data==(r.address^r.data^0x1122334455667788ULL) &&
            h.read(0x20)==0,"CMU memory/atomic bypass oracle mismatch");
    }
#endif
    std::cout<<"CMU_REGISTER_POLICY_PASS accesses="<<h.accesses<<" reply_credits=4"
        <<" protected_domains=2 gateable_domains=2 timeout_cycles=32\n";return 0;
} catch(const std::exception &e) { std::cerr<<e.what()<<'\n';return 1; } }
