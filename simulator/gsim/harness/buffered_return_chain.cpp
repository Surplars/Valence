#include "BufferedReturnChainGsim.h"
#include "gsim_model_storage.h"
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <memory>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

static void need(bool b, const char *s) { if (!b) throw std::runtime_error(s); }
struct Op {
    unsigned index, size = 3;
    uint64_t tag, address, data = 0, pc = 0x80000000;
    bool store = false, unsign = true, error = false, page = false, cancel = false, local = false;
    unsigned delay = 7;
    bool cancelOnReply = false;
};
static uint64_t beat(uint64_t address) { return 0x81fedcba98765432ULL ^ (address * 0x0101010101010101ULL); }
// Standalone ISA byte extraction, not copied from a DUT formatter/helper.
static uint64_t expectedLoad(const Op &o, uint64_t raw) {
    const unsigned bits = 8U << o.size;
    uint64_t v = raw >> (8U * unsigned(o.address & 7));
    if (bits < 64) {
        const uint64_t mask = (uint64_t(1) << bits) - 1;
        v &= mask;
        if (!o.unsign && (v & (uint64_t(1) << (bits - 1)))) v |= ~mask;
    }
    return v;
}
struct State { bool started=false, requested=false, replied=false, consumed=false, complete=false, canceled=false; unsigned slot=0; uint64_t start=0; };
struct Pending { unsigned owner; uint64_t due; };
class Test {
    std::unique_ptr<GsimModelStorage<SBufferedReturnChainGsim>> storage;
    SBufferedReturnChainGsim &d;
    std::string injection;
    bool injected=false;
public:
    explicit Test(std::string fault="") : storage(std::make_unique<GsimModelStorage<SBufferedReturnChainGsim>>()), d(storage->get()), injection(fault) {
        defaults(); d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    }
    void defaults() {
        d.set_io$$start$$valid(0); drive(Op{0,3,0,0});
        d.set_io$$parallel(1); d.set_io$$cancel(0); d.set_io$$complete$$ready(1);
        d.set_io$$fastStore$$valid(0);
#define ZERO_REQUEST(F) d.set_io$$fastStore$$bits$$##F(0)
        ZERO_REQUEST(address); ZERO_REQUEST(data); ZERO_REQUEST(write); ZERO_REQUEST(size); ZERO_REQUEST(mask);
        ZERO_REQUEST(atomic); ZERO_REQUEST(atomicOp); ZERO_REQUEST(virtualized); ZERO_REQUEST(precheckedLoad);
        ZERO_REQUEST(translationEpoch); ZERO_REQUEST(prefetchNextAllowed); ZERO_REQUEST(uncached);
#undef ZERO_REQUEST
        d.set_io$$fpMode(0); d.set_io$$fpValid(0); d.set_io$$fpToken$$index(0); d.set_io$$fpToken$$tag(0);
        d.set_io$$fpInstruction(0x00003007); d.set_io$$fpAddress(0); d.set_io$$fpData(0); d.set_io$$fpPc(0);
        d.set_io$$fpComplete$$ready(1); d.set_io$$memory$$request$$ready(1);
        d.set_io$$memory$$response$$valid(0); d.set_io$$memory$$response$$bits$$data(0);
        d.set_io$$memory$$response$$bits$$error(0); d.set_io$$memory$$response$$bits$$pageFault(0);
    }
    void drive(const Op&o) {
#define SET(F,V) d.set_io$$start$$bits$$##F(V)
        SET(token$$index,o.index); SET(token$$tag,o.tag); SET(pc,o.pc); SET(address,o.address); SET(data,o.data);
        SET(size,o.size); SET(store,o.store); SET(unsigned,o.unsign); SET(atomic,0); SET(atomicOp,0);
        SET(accessDenied,0); SET(virtualized,0); SET(precheckedLoad,0); SET(physicalAddress,0); SET(translationEpoch,0);
        SET(forward$$valid,0); SET(forward$$bits,0);
#undef SET
    }
    void run(const std::string &name, const std::vector<Op>& ops, bool fp=false, unsigned completionHold=0, bool localForward=false) {
        std::vector<State> state(ops.size()); std::deque<Pending> pending; std::deque<unsigned> integerOwners;
        std::array<std::optional<unsigned>,4> slots{};
        unsigned next=0, requests=0, replies=0, completions=0, discards=0, quiet=0, heldChecks=0;
        bool sawBusyHold=false, sawLocalBeforeDrain=false;
        std::optional<std::array<uint64_t,6>> held;
        std::map<unsigned,std::array<uint64_t,6>> heldOwners;
        for(uint64_t cycle=0;cycle<1000;++cycle) {
            // Admission and cancellation derive only from accepted host operations and time.
            bool valid=next<ops.size() && (!fp || cycle>0);
            if(localForward && next==1) valid=state[0].complete;
            unsigned cancelMask=0;
            for(unsigned i=0;i<ops.size();++i) if(state[i].started && ops[i].cancel && !state[i].canceled && (ops[i].cancelOnReply ? (!pending.empty() && pending.front().owner==i && cycle>=pending.front().due) : cycle>=state[i].start+2)) {
                cancelMask|=1U<<state[i].slot; state[i].canceled=true;
            }
            const bool consumerReady=cycle>=completionHold && cycle%11!=7;
            const bool parallel = valid && !fp && !localForward && !ops[next].store;
            d.set_io$$fpMode(fp); d.set_io$$cancel(cancelMask); d.set_io$$parallel(parallel);
            d.set_io$$complete$$ready(consumerReady); d.set_io$$fpComplete$$ready(consumerReady);
            d.set_io$$start$$valid(!fp && valid);
            d.set_io$$fpValid(fp && valid);
            if(valid) {
                const auto&o=ops[next]; drive(o);
                d.set_io$$fpToken$$index(o.index); d.set_io$$fpToken$$tag(o.tag);
                d.set_io$$fpAddress(o.address); d.set_io$$fpData(o.data); d.set_io$$fpPc(o.pc);
                // zero offset FLW/FLD/FSW/FSD, no DUT instruction decoder used by oracle.
                d.set_io$$fpInstruction((o.store?0x27U:0x07U)|(o.size<<12));
            }
            const bool offer=!pending.empty() && cycle>=pending.front().due;
            const unsigned responseOwner=offer?pending.front().owner:0;
            const bool requestReady = cycle%7!=4;
            d.set_io$$memory$$request$$ready(requestReady);
            d.set_io$$memory$$response$$valid(offer);
            d.set_io$$memory$$response$$bits$$data(offer?beat(ops[responseOwner].address):0xbad0bad0deadbeefULL);
            d.set_io$$memory$$response$$bits$$error(offer&&ops[responseOwner].error);
            d.set_io$$memory$$response$$bits$$pageFault(offer&&ops[responseOwner].page);
            d.step();
            for(unsigned i=0;i<ops.size();++i) if(ops[i].cancelOnReply && state[i].started &&
                (cancelMask&(1U<<state[i].slot)))
                need(offer && responseOwner==i && d.get_io$$memory$$response$$ready(),
                     "chain intended same-edge cancel did not coincide with source response fire");
            const bool accept=valid&&(fp?d.get_io$$fpReady():d.get_io$$start$$ready());
            // Completion is checked while VALID, including every stalled cycle.
            bool cv=fp?d.get_io$$fpComplete$$valid():d.get_io$$complete$$valid();
#define COMPLETE(F) uint64_t(fp?d.get_io$$fpComplete$$bits$$##F():d.get_io$$complete$$bits$$##F())
            if(cv) {
                uint64_t index=COMPLETE(token$$index),tag=COMPLETE(token$$tag),data=COMPLETE(data);
                uint64_t exception=COMPLETE(exception),cause=COMPLETE(cause),tval=COMPLETE(tval),nextPc=COMPLETE(nextPc);
                const bool wasInjected=injected;
                if(!injected && !injection.empty()) {
                    if(injection=="tag") { tag^=1ULL<<63; injected=true; }
                    if(injection=="data") { data^=1ULL<<35; injected=true; }
                    if(injection=="cause" && exception) { cause^=1; injected=true; }
                    if(injection=="tval" && exception) { tval^=8; injected=true; }
                }
                if(injected && !wasInjected) std::cout<<"CHAIN_INJECTION_REACHED kind="<<injection<<"\n";
                unsigned owner=unsigned(ops.size());
                for(unsigned i=0;i<ops.size();++i) if(state[i].started&&ops[i].index==index&&ops[i].tag==tag) owner=i;
                need(owner<ops.size(),"chain full64 completion owner");
                const auto&o=ops[owner]; const auto&s=state[owner];
                need(!s.canceled,"chain canceled completion leaked"); need(!s.complete,"chain duplicate completion");
                need(exception==unsigned(o.error||o.page),"chain exception mismatch");
                if(exception) { need(cause==(o.page?(o.store?15:13):(o.store?7:5)),"chain independent cause mismatch"); need(tval==o.address,"chain independent tval mismatch"); }
                uint64_t raw=(localForward && owner==1)?ops[0].data:beat(o.address);
                const uint64_t expected=o.store?0:expectedLoad(o,raw);
                need(data==expected,"chain independent data mismatch"); need(nextPc==o.pc+4,"chain nextPC mismatch");
                need(fp ? s.replied : s.consumed,"chain completion before consumer response ownership");
                std::array<uint64_t,6> payload{index,tag,data,exception,cause,tval};
                // The integer ResetDefinedRRArbiter is explicitly Decoupled,
                // not irrevocable: another slot may win while output is held.
                // Compare every offered owner's complete payload independently.
                if(heldOwners.count(owner)) { need(heldOwners.at(owner)==payload,"chain held owner payload changed"); ++heldChecks; }
                if(fp && held) need(*held==payload,"chain FP held completion changed");
                if(!consumerReady) heldOwners[owner]=payload;
                else heldOwners.erase(owner);
                held=consumerReady?std::nullopt:std::optional(payload);
                if(consumerReady) { state[owner].complete=true; ++completions; if(!fp) slots[s.slot].reset(); }
                if(o.local&&!s.replied) sawLocalBeforeDrain=true;
            } else { if(fp) need(!held,"chain FP held completion lost valid"); held.reset(); }
#undef COMPLETE
            if(!fp) {
                const unsigned live=d.get_io$$live();
                for(unsigned s=0;s<4;++s) if(slots[s] && !(live&(1U<<s))) {
                    const unsigned owner=*slots[s]; need(state[owner].canceled&&state[owner].consumed,"chain slot reused before canceled drain"); slots[s].reset();
                }
                discards+=bool(d.get_io$$discarded());
            }
            if(accept) {
                need(!state[next].started,"chain duplicate accepted start");
                state[next].started=true; state[next].start=cycle;
                if(!fp) { unsigned mask=d.get_io$$startSlots(); need(mask && !(mask&(mask-1)),"chain accepted start unique slot"); unsigned slot=0; while(!(mask&(1U<<slot)))++slot; need(!slots[slot],"chain overwrite live owner"); slots[slot]=next; state[next].slot=slot; }
                ++next;
            }
            if(d.get_io$$memory$$request$$valid() && requestReady) {
                const uint64_t address=d.get_io$$memory$$request$$bits$$address(); const bool write=d.get_io$$memory$$request$$bits$$write();
                unsigned owner=unsigned(ops.size());
                for(unsigned i=0;i<ops.size();++i) if(state[i].started&&!state[i].requested&&ops[i].address==address&&ops[i].store==write) {owner=i;break;}
                need(owner<ops.size(),"chain external request has no accepted owner"); const auto&o=ops[owner];
                need(d.get_io$$memory$$request$$bits$$size()==o.size,"chain request size");
                const uint64_t mask=((1U<<(1U<<o.size))-1U)<<(o.address&7);
                need(d.get_io$$memory$$request$$bits$$mask()==mask,"chain request byte mask");
                if(write)need(d.get_io$$memory$$request$$bits$$data()==(o.data<<(8*(o.address&7))),"chain store independent data");
                state[owner].requested=true; pending.push_back({owner,cycle+o.delay}); ++requests;
            }
            if(offer&&d.get_io$$memory$$response$$ready()) { need(!state[responseOwner].replied,"chain duplicate external reply"); state[responseOwner].replied=true;pending.pop_front();++replies; }
            if(!fp && d.get_io$$requestOwned()) {
                const uint64_t index=d.get_io$$requestToken$$index(),tag=d.get_io$$requestToken$$tag();
                unsigned owner=unsigned(ops.size());
                for(unsigned i=0;i<ops.size();++i) if(state[i].started&&ops[i].index==index&&ops[i].tag==tag) owner=i;
                need(owner<ops.size(),"chain request flow owner lacks accepted full token");
                integerOwners.push_back(owner);
            }
            if(!fp && d.get_io$$integerReply()) {
                need(!integerOwners.empty(),"chain consumer reply without ordered request owner");
                const unsigned owner=integerOwners.front();integerOwners.pop_front();
                need(!state[owner].consumed,"chain duplicate consumer reply");
                need(state[owner].replied || ops[owner].local || (localForward&&owner==1),
                     "chain consumer reply before independent source or local authorization");
                state[owner].consumed=true;
            }
            if(!pending.empty()) need(!d.get_io$$allIdle(),"chain aggregate idle with outstanding physical owner");
            if(!consumerReady && (fp?d.get_io$$fpBusy():d.get_io$$integerBusy())) sawBusyHold=true;
            if(next==ops.size()&&pending.empty()&&d.get_io$$allIdle()) {
                if(++quiet==4) {
                    for(unsigned i=0;i<ops.size();++i) need(state[i].started && (ops[i].cancel?state[i].canceled&&state[i].replied&&state[i].consumed:state[i].complete),"chain incomplete terminal owner");
                    need(requests==replies && integerOwners.empty(),"chain external and consumer owner conservation");
                    if(completionHold) need(sawBusyHold&&heldChecks,"chain missing held-completion coverage");
                    if(localForward) need(sawLocalBeforeDrain&&requests==1,"chain local ACK/forward and delayed drain coverage");
                    if(!injection.empty()) need(injected,"chain requested negative did not trigger");
                    std::cout<<"BUFFERED_RETURN_CHAIN_CASE name="<<name<<" cycles="<<cycle<<" starts="<<next<<" requests="<<requests<<" replies="<<replies<<" completions="<<completions<<" discards="<<discards<<" held_checks="<<heldChecks<<"\n";return;
                }
            } else quiet=0;
        }
        throw std::runtime_error("chain terminal drain timeout");
    }
};
int main(int argc,char**argv) { try {
    const std::string injection=argc==2?argv[1]:"";
    std::vector<Op> loads;
    for(unsigned i=0;i<12;++i) { Op o{i%16,i%4,0x8000000000000000ULL+i,0x80202000ULL+8*i};o.address+=(i*3+7)&(7U&~((1U<<o.size)-1U));o.unsign=(i&1);o.error=i%4==1;o.page=i%4==2;loads.push_back(o); }
    Test(injection).run("integer_payload_faults_stall",loads,false,70);
    Op canceled{7,3,0xfffffffffffffff0ULL,0x80204000};canceled.cancel=true;canceled.error=true;canceled.delay=20;
    Test().run("cancel_before_reply_drains",{canceled});
    canceled.cancelOnReply=true;canceled.tag++;canceled.error=false;canceled.page=true;
    Test().run("cancel_on_physical_reply_drains",{canceled});
    Op store{3,3,0x8000000100000003ULL,0x10001000,0xfedcba9876543210ULL};store.store=true;store.error=true;
    Test().run("direct_write_error_ack",{store});store.page=true;store.error=false;store.index=4;store.tag++;
    Test().run("direct_write_pagefault_ack",{store});
    Op local{5,3,0x8000000200000005ULL,0x80201000,0x81abcdef01234567ULL};local.store=true;local.local=true;local.delay=60;
    Op forwarded{6,3,0x8000000200000006ULL,local.address};
    Test().run("local_store_ack_forward_late_drain",{local,forwarded},false,0,true);
    std::vector<Op> fps;
    for(unsigned i=0;i<5;++i){Op o{i,3,0x8000000300000000ULL+i,0x80206000ULL+8*i};o.error=i==1;o.page=i==2;o.store=i==3;o.data=0x123456789abcdef0ULL;fps.push_back(o);}
    Test().run("fp_load_store_fault_completion_drain",fps,true,80);
    std::cout<<"BUFFERED_RETURN_CHAIN_PASS actual_modules=1 full_cpu=0\n";return 0;
} catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;} }
