#include "OrderedOwnerChainGsim.h"
#include "gsim_model_storage.h"
#include <array>
#include <algorithm>
#include <cstdlib>
#include <fstream>
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
struct State { bool started=false, requested=false, replied=false, consumed=false, complete=false, canceled=false, discarded=false; unsigned slot=0; uint64_t start=0; };
struct Pending { unsigned owner; uint64_t due; };
class Test {
    std::unique_ptr<GsimModelStorage<SOrderedOwnerChainGsim>> storage;
    SOrderedOwnerChainGsim &d;
    std::string injection;
    bool injected=false;
public:
    explicit Test(std::string fault="") : storage(std::make_unique<GsimModelStorage<SOrderedOwnerChainGsim>>()), d(storage->get()), injection(fault) {
        defaults(); d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    }
    void sample(bool backingResponse=false, bool pteResponse=false) {
        // Canonical little-endian u64 records; no hashes stand in for equality.
        // Input READY on requests is a shared host schedule. Invalid output payload,
        // invalid owner head and unowned slot ready are deliberately not compared.
        static std::unique_ptr<std::ofstream> stream;
        const char *path=std::getenv("ORDERED_OWNER_TRACE");if(!path)return;
        if(!stream){stream=std::make_unique<std::ofstream>(path,std::ios::binary|std::ios::trunc);need(bool(*stream),"open exact trace failed");}
        std::vector<uint64_t> row;
        auto add=[&](uint64_t value){row.push_back(value);};
        add(d.get_io$$startSlots());add(d.get_io$$phases());add(d.get_io$$live());add(d.get_io$$slotDiscard());
        add(d.get_io$$ownerCount());
        add(d.get_io$$ownerCount()?d.get_io$$ownerHead():0);
        const std::array<uint64_t,4> tags{d.get_io$$slotOwner0$$tag(),d.get_io$$slotOwner1$$tag(),d.get_io$$slotOwner2$$tag(),d.get_io$$slotOwner3$$tag()};
        const std::array<unsigned,4> indices{unsigned(d.get_io$$slotOwner0$$index()),unsigned(d.get_io$$slotOwner1$$index()),unsigned(d.get_io$$slotOwner2$$index()),unsigned(d.get_io$$slotOwner3$$index())};
        for(unsigned i=0;i<4;++i){bool live=(d.get_io$$phases()>>(2*i))&3;add(live?tags[i]:0);add(live?indices[i]:0);}
        bool rq=d.get_io$$requestOwned();add(rq);add(rq?d.get_io$$requestToken$$tag():0);add(rq?d.get_io$$requestToken$$index():0);add(rq?d.get_io$$requestSlot():0);
        add(d.get_io$$integerReply());add(d.get_io$$translatedRequest());add(d.get_io$$translatedResponse());
#define REQ(F) add(v?d.get_io$$memory$$request$$bits$$##F():0)
        bool v=d.get_io$$memory$$request$$valid();add(v);REQ(address);REQ(write);REQ(size);REQ(mask);
        add(v&&d.get_io$$memory$$request$$bits$$write()?d.get_io$$memory$$request$$bits$$data():0);
#undef REQ
        add(backingResponse);add(backingResponse?d.get_io$$memory$$response$$ready():0);
        bool t=d.get_io$$translatedRequest();
#define TRANS(F) add(t?d.get_io$$translated$$##F():0)
        TRANS(address);TRANS(write);TRANS(size);TRANS(mask);TRANS(atomic);
        add(t&&d.get_io$$translated$$atomic()?d.get_io$$translated$$atomicOp():0);
        add(t&&(d.get_io$$translated$$write()||d.get_io$$translated$$atomic())?d.get_io$$translated$$data():0);
#undef TRANS
        bool c=d.get_io$$complete$$valid();add(c);
#define COMPLETE_TRACE(F) add(c?d.get_io$$complete$$bits$$##F():0)
        COMPLETE_TRACE(token$$index);COMPLETE_TRACE(token$$tag);COMPLETE_TRACE(data);COMPLETE_TRACE(nextPc);COMPLETE_TRACE(exception);
        add(c&&d.get_io$$complete$$bits$$exception()?d.get_io$$complete$$bits$$cause():0);
        add(c&&d.get_io$$complete$$bits$$exception()?d.get_io$$complete$$bits$$tval():0);
#undef COMPLETE_TRACE
        bool f=d.get_io$$fpComplete$$valid();add(f);
#define FP_TRACE(F) add(f?d.get_io$$fpComplete$$bits$$##F():0)
        FP_TRACE(token$$index);FP_TRACE(token$$tag);FP_TRACE(data);FP_TRACE(nextPc);FP_TRACE(exception);
        add(f&&d.get_io$$fpComplete$$bits$$exception()?d.get_io$$fpComplete$$bits$$cause():0);
        add(f&&d.get_io$$fpComplete$$bits$$exception()?d.get_io$$fpComplete$$bits$$tval():0);
#undef FP_TRACE
        bool p=d.get_io$$pte$$request$$valid();add(p);add(p?d.get_io$$pte$$request$$bits():0);add(pteResponse);add(pteResponse?d.get_io$$pte$$response$$ready():0);
        add(d.get_io$$atomicPhase());add(d.get_io$$fpBusy());add(d.get_io$$integerBusy());add(d.get_io$$bufferIdle());add(d.get_io$$allIdle());add(d.get_io$$epoch());add(d.get_io$$stable());
        auto write=[&](uint64_t x){for(unsigned b=0;b<8;++b)stream->put(char((x>>(8*b))&255));};
        write(row.size());for(auto x:row)write(x);need(bool(*stream),"write exact trace failed");
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
        d.set_io$$vm$$satp(0); d.set_io$$vm$$sum(0); d.set_io$$vm$$mxr(0); d.set_io$$vm$$dataPrivilege(3);
        d.set_io$$pmpCfg(0); d.set_io$$pmpAddress(0); d.set_io$$flush(0); d.set_io$$clearReservation(0);
        d.set_io$$pte$$request$$ready(1); d.set_io$$pte$$response$$valid(0);
        d.set_io$$pte$$response$$bits$$data(0); d.set_io$$pte$$response$$bits$$error(0);
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
        uint64_t trace=1469598103934665603ULL;
        auto hash=[&](uint64_t x){for(unsigned b=0;b<8;++b){trace^=(x>>(8*b))&255;trace*=1099511628211ULL;}};
        unsigned maxOwners=0;
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
            d.step(); sample(offer);
            // Pre-edge obligation ledger. Check ALL owed slots, not just the selected head.
            if(!fp) {
                maxOwners=std::max(maxOwners,unsigned(d.get_io$$ownerCount()));
                if(d.get_io$$ownerCount()==4)need(!d.get_io$$requestOwned(),"full owner queue illegally borrowed pop credit");
                need(d.get_io$$ownerCount()==integerOwners.size(), "owner FIFO count differs from independent owed ledger");
                const std::array<uint64_t,4> tags{d.get_io$$slotOwner0$$tag(),d.get_io$$slotOwner1$$tag(),d.get_io$$slotOwner2$$tag(),d.get_io$$slotOwner3$$tag()};
                const std::array<unsigned,4> indices{unsigned(d.get_io$$slotOwner0$$index()),unsigned(d.get_io$$slotOwner1$$index()),unsigned(d.get_io$$slotOwner2$$index()),unsigned(d.get_io$$slotOwner3$$index())};
                unsigned owned=0;
                for(unsigned owner:integerOwners) {
                    unsigned sl=state[owner].slot, bit=1U<<sl;
                    need(!(owned&bit), "duplicate queued slot"); owned|=bit;
                    need(((d.get_io$$phases()>>(2*sl))&3)==2, "owed slot not in response phase");
                    need(tags[sl]==ops[owner].tag&&indices[sl]==ops[owner].index, "owed full token changed");
                    need(!((d.get_io$$slotRequestValid()|d.get_io$$slotStartReady()|d.get_io$$slotCompleteValid())&bit), "owed slot illegally requests starts or completes");
                    need(d.get_io$$slotResponseReady()&bit, "owed response phase not ready");
                }
                if(!integerOwners.empty()) need(d.get_io$$ownerHeadValid()&&d.get_io$$ownerHead()==state[integerOwners.front()].slot,"owner FIFO head mismatch");
                for(unsigned sl=0;sl<4;++sl) if(d.get_io$$slotDiscard()&(1U<<sl)) {
                    need(slots[sl].has_value(), "discard has no independently accepted owner");
                    auto &st=state[*slots[sl]];
                    need(st.canceled&&st.consumed&&!st.discarded,"discard without canceled drained obligation");
                    st.discarded=true;
                }
                hash(d.get_io$$phases()); hash(d.get_io$$live());
                hash(d.get_io$$requestOwned()); hash(d.get_io$$integerReply());
                if(d.get_io$$requestOwned()){hash(d.get_io$$requestToken$$index());hash(d.get_io$$requestToken$$tag());}
            }
            hash(valid&&(fp?d.get_io$$fpReady():d.get_io$$start$$ready()));
            hash(d.get_io$$memory$$request$$valid());
            if(d.get_io$$memory$$request$$valid()){hash(d.get_io$$memory$$request$$bits$$address());hash(d.get_io$$memory$$request$$bits$$write());hash(d.get_io$$memory$$request$$bits$$data());}
            hash(offer&&d.get_io$$memory$$response$$ready());
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
                hash(index);hash(tag);hash(data);hash(exception);hash(cause);hash(tval);hash(consumerReady);
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
                need(fp||d.get_io$$requestOwned(),"supp fixed ordinary topology admitted a delayed request");
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
                    for(unsigned i=0;i<ops.size();++i) need(state[i].started && (ops[i].cancel?state[i].canceled&&state[i].replied&&state[i].consumed&&state[i].discarded:state[i].complete),"chain incomplete terminal owner");
                    need(requests==replies && integerOwners.empty(),"chain external and consumer owner conservation");
                    if(completionHold) need(sawBusyHold&&heldChecks,"chain missing held-completion coverage");
                    if(name=="integer_payload_faults_stall")need(maxOwners==4,"full owner queue coverage not reached");
                    if(localForward) need(sawLocalBeforeDrain&&requests==1,"chain local ACK/forward and delayed drain coverage");
                    if(!injection.empty()) need(injected,"chain requested negative did not trigger");
                    std::cout<<"ORDERED_OWNER_CHAIN_CASE name="<<name<<" cycles="<<cycle<<" starts="<<next<<" requests="<<requests<<" replies="<<replies<<" completions="<<completions<<" discards="<<discards<<" held_checks="<<heldChecks<<" max_owners="<<maxOwners<<" trace="<<trace<<"\n";return;
                }
            } else quiet=0;
        }
        throw std::runtime_error("chain terminal drain timeout");
    }
    // A separate independently specified atomic transaction sequence: one LSU request
    // and completion per operation, versus zero, one or two subordinate beat transfers.
    void atomics(bool immediate=false) {
        struct A {unsigned opcode; bool readError=false,writeError=false;};
        const std::vector<A> program{{3},{2},{3},{3},{0},{4},{1,true,false},{1,false,true},{2,true,false}};
        unsigned cursor=0,slot=0,requests=0,replies=0,completed=0,physical=0,returned=0;
        bool started=false,owed=false,translated=false,reserved=false,scSuccess=false;
        unsigned beats=0,beatReplies=0,expectedBeats=0; uint64_t acceptedAt=0;
        struct B {bool write,error;uint64_t data,due;}; std::deque<B> pending;
        const uint64_t addr=0x80208000ULL,operand=0x1122334455667788ULL,old=beat(addr);
        uint64_t trace=1469598103934665603ULL;
        auto hash=[&](uint64_t x){trace^=x;trace*=1099511628211ULL;};
        for(uint64_t cycle=0;cycle<1600;++cycle) {
            const bool active=cursor<program.size();
            const A a=active?program[cursor]:A{0};
            const uint64_t tag=0x9000000000000000ULL+cursor;
            Op op{cursor%16,3,tag,addr,operand};
            drive(op); d.set_io$$parallel(0); d.set_io$$start$$bits$$atomic(1);
            d.set_io$$start$$bits$$atomicOp(a.opcode);
            d.set_io$$start$$valid(active&&!started);
            const bool completeReady=cycle%13!=8&&cycle%13!=9;
            d.set_io$$complete$$ready(completeReady);
            const bool ready=cycle%7!=3; d.set_io$$memory$$request$$ready(ready);
            // Atomic phase progression is predicted from accepted transfers, not read
            // from DUT phase to produce the service. Immediate replies are offered on
            // the next owed beat's issue cycle and held if the request is stalled.
            bool instant=immediate&&translated&&pending.empty()&&beats<expectedBeats&&
                beats==beatReplies&&cycle>acceptedAt;
            bool writeExpected=(a.opcode==3)||(beats==1);
            bool errExpected=writeExpected?a.writeError:a.readError;
            bool offer=!pending.empty()&&cycle>=pending.front().due;
            d.set_io$$memory$$response$$valid(offer||instant);
            d.set_io$$memory$$response$$bits$$data(old);
            d.set_io$$memory$$response$$bits$$error(offer?pending.front().error:instant&&errExpected);
            d.set_io$$memory$$response$$bits$$pageFault(0);
            d.step(); sample(offer||instant);
            need(d.get_io$$ownerCount()==unsigned(owed),"atomic LSU owner count mismatch");
            if(owed) {
                need(d.get_io$$ownerHeadValid()&&d.get_io$$ownerHead()==slot,"atomic queued owner mismatch");
                need(((d.get_io$$phases()>>(2*slot))&3)==2,"atomic owed slot phase");
                const std::array<uint64_t,4> tags{d.get_io$$slotOwner0$$tag(),d.get_io$$slotOwner1$$tag(),d.get_io$$slotOwner2$$tag(),d.get_io$$slotOwner3$$tag()};
                const std::array<unsigned,4> indices{unsigned(d.get_io$$slotOwner0$$index()),unsigned(d.get_io$$slotOwner1$$index()),unsigned(d.get_io$$slotOwner2$$index()),unsigned(d.get_io$$slotOwner3$$index())};
                need(tags[slot]==tag&&indices[slot]==cursor%16,"atomic owed full token changed");
                need(!((d.get_io$$slotRequestValid()|d.get_io$$slotStartReady()|d.get_io$$slotCompleteValid())&(1U<<slot)),"atomic owed slot illegally advances");
            }
            if(active&&!started&&d.get_io$$start$$ready()) {
                started=true;unsigned mask=d.get_io$$startSlots();need(mask&&!(mask&(mask-1)),"atomic start unique slot");slot=0;while(!(mask&(1U<<slot)))++slot;
                scSuccess=a.opcode==3&&reserved;
                expectedBeats=a.opcode==3?(scSuccess?1:0):(a.opcode==2||a.readError?1:2);
                if(a.opcode==2||a.opcode==3||reserved)reserved=false;
            }
            if(d.get_io$$requestOwned()) {
                need(started&&!owed&&!translated,"atomic must create exactly one LSU owner");
                need(d.get_io$$requestToken$$tag()==tag&&d.get_io$$requestToken$$index()==cursor%16,"atomic full request owner");owed=true;++requests;
            }
            if(d.get_io$$translatedRequest()) {
                need(started&&owed&&!translated,"atomic physical transaction ownership");
                need(d.get_io$$translated$$atomic()&&d.get_io$$translated$$atomicOp()==a.opcode&&d.get_io$$translated$$address()==addr,"atomic translated payload");
                translated=true;acceptedAt=cycle;
            }
            bool request=d.get_io$$memory$$request$$valid()&&ready;
            if(request) {
                need(translated&&beats<expectedBeats,"unowned or excess atomic subordinate phase");
                bool write=a.opcode==3||beats==1;
                if(injection=="phase"&&!injected){write=!write;injected=true;std::cout<<"CHAIN_INJECTION_REACHED kind=phase\n";}
                need(bool(d.get_io$$memory$$request$$bits$$write())==write,"atomic independent phase order mismatch");
                need(d.get_io$$memory$$request$$bits$$address()==addr&&d.get_io$$memory$$request$$bits$$size()==3&&d.get_io$$memory$$request$$bits$$mask()==255,"atomic subordinate address/size/mask");
                uint64_t value=a.opcode==0?old+operand:a.opcode==4?old^operand:operand;
                if(write)need(d.get_io$$memory$$request$$bits$$data()==value,"atomic independent computed write mismatch");
                pending.push_back({write,write?a.writeError:a.readError,old,cycle+(immediate?0:4)});
                ++beats;++physical;
            }
            if((offer||instant)&&d.get_io$$memory$$response$$ready()) {
                need(!pending.empty(),"atomic reply before independent subordinate request");
                if(instant)need(request,"zero-cycle subordinate reply did not accompany request");
                pending.pop_front();++beatReplies;++returned;
            }
            if(d.get_io$$translatedResponse())need(translated&&beatReplies==expectedBeats,"atomic physical completion before all independent phases");
            if(d.get_io$$integerReply()){need(owed,"atomic duplicated LSU reply");owed=false;++replies;}
            bool cv=d.get_io$$complete$$valid();
            if(injection=="completion"&&cursor+1==program.size()&&cv&&completeReady){
                cv=false;if(!injected){injected=true;std::cout<<"CHAIN_INJECTION_REACHED kind=completion\n";}
            }
            if(cv) {
                need(started&&translated&&!owed&&beatReplies==expectedBeats,"atomic complete before obligations drained");
                need(d.get_io$$complete$$bits$$token$$tag()==tag&&d.get_io$$complete$$bits$$token$$index()==cursor%16,"atomic full completion owner");
                bool fault=a.readError||a.writeError;
                need(bool(d.get_io$$complete$$bits$$exception())==fault,"atomic exception mismatch");
                if(fault)need(d.get_io$$complete$$bits$$cause()==(a.opcode==2?5:7)&&d.get_io$$complete$$bits$$tval()==addr,"atomic fault cause/tval");
                uint64_t result=a.opcode==3?(scSuccess?0:1):old;
                need(d.get_io$$complete$$bits$$data()==result,"atomic independent result mismatch");
                if(completeReady) {
                    if(a.opcode==2&&!a.readError)reserved=true;
                    ++completed;++cursor;started=false;translated=false;beats=beatReplies=0;
                }
            }
            hash(d.get_io$$requestOwned());hash(d.get_io$$integerReply());hash(request);hash(cv);hash(d.get_io$$phases());hash(d.get_io$$atomicPhase());
            if(cursor==program.size()&&d.get_io$$allIdle()&&pending.empty()) {
                need(requests==program.size()&&replies==requests&&completed==requests&&physical==returned,"atomic terminal conservation");
                std::cout<<"ORDERED_OWNER_CHAIN_CASE name=atomic_"<<(immediate?"zero_cycle":"delayed")<<" cycles="<<cycle<<" starts="<<requests<<" requests="<<physical<<" replies="<<returned<<" completions="<<completed<<" trace="<<trace<<"\n";return;
            }
        }
        throw std::runtime_error("atomic missing completion/phase terminal timeout");
    }

    // Translation faults come from actual Sv39 walking/PMP, never a host pageFault bit.
    void translationFault(bool pmpDenied) {
        defaults();
        d.set_io$$vm$$satp(pmpDenied?0:0x8000000000080200ULL);
        d.set_io$$vm$$dataPrivilege(1);
        // Sv39 page-table reads are allowed via an unlocked NAPOT all-memory entry.
        d.set_io$$pmpCfg(pmpDenied?0:0x1f);d.set_io$$pmpAddress(pmpDenied?0:((1ULL<<54)-1));
        Op op{11,3,0xfedcba9876543210ULL,0x40000000};
        bool started=false,owed=false,consumed=false,done=false;unsigned slot=0,pteCount=0;
        std::deque<uint64_t> ptes;uint64_t trace=1469598103934665603ULL;
        for(uint64_t cycle=0;cycle<400;++cycle) {
            drive(op);d.set_io$$start$$bits$$virtualized(1);d.set_io$$parallel(0);
            d.set_io$$start$$valid(cycle>=5&&!started);d.set_io$$complete$$ready(cycle>=70);
            bool pte=!ptes.empty()&&cycle>=ptes.front();
            d.set_io$$pte$$response$$valid(pte);d.set_io$$pte$$response$$bits$$data(0);
            d.step(); sample(false,pte);
            need(!d.get_io$$memory$$request$$valid()&&!d.get_io$$translatedRequest(),"faulting DTA request escaped to physical memory");
            need(d.get_io$$ownerCount()==unsigned(owed),"DTA fault owner count");
            if(owed)need(((d.get_io$$phases()>>(2*slot))&3)==2,"DTA fault lost response owner");
            if(!started&&cycle>=5&&d.get_io$$start$$ready()){started=true;unsigned mask=d.get_io$$startSlots();need(mask&&!(mask&(mask-1)),"DTA fault start slot");while(!(mask&(1U<<slot)))++slot;}
            if(d.get_io$$requestOwned()){need(started&&!owed&&!consumed,"DTA duplicate request owner");owed=true;}
            if(d.get_io$$integerReply()){need(owed&&!consumed,"DTA fault unowned reply");owed=false;consumed=true;}
            if(pte&&d.get_io$$pte$$response$$ready())ptes.pop_front();
            if(d.get_io$$pte$$request$$valid()){need(!pmpDenied,"PMP denied Bare request walked");ptes.push_back(cycle+3);++pteCount;}
            if(d.get_io$$complete$$valid()) {
                need(consumed&&!done,"DTA fault completion obligation");
                need(d.get_io$$complete$$bits$$token$$tag()==op.tag&&d.get_io$$complete$$bits$$token$$index()==op.index,"DTA full completion token");
                need(d.get_io$$complete$$bits$$exception()&&d.get_io$$complete$$bits$$cause()==(pmpDenied?5:13)&&d.get_io$$complete$$bits$$tval()==op.address,"DTA independent fault cause/tval");
                if(cycle>=70)done=true;
            }
            trace^=d.get_io$$phases()|(uint64_t(d.get_io$$integerReply())<<8)|(uint64_t(d.get_io$$complete$$valid())<<9);trace*=1099511628211ULL;
            if(done&&d.get_io$$allIdle()) {
                need(ptes.empty()&&(pmpDenied?pteCount==0:pteCount==1),"DTA expected page walk obligation count");
                std::cout<<"ORDERED_OWNER_CHAIN_CASE name=dta_"<<(pmpDenied?"pmp_denied":"invalid_pte")<<" cycles="<<cycle<<" pte="<<pteCount<<" trace="<<trace<<"\n";return;
            }
        }
        throw std::runtime_error("DTA fault missing completion timeout");
    }

    void localFaults() {
        struct L {uint64_t address;bool atomic,denied,forward;unsigned cause;};
        const std::vector<L> ops{{0x80209003,false,false,false,4},{0x80209000,false,true,false,5},
                                {0x1000,true,false,false,7},{0x80209000,false,false,true,0}};
        unsigned cursor=0;bool started=false;uint64_t trace=0;
        for(uint64_t cycle=0;cycle<200;++cycle) {
            bool active=cursor<ops.size();const L o=active?ops[cursor]:ops[0];
            Op op{cursor,3,0xa000000000000000ULL+cursor,o.address};drive(op);
            d.set_io$$parallel(0);d.set_io$$start$$bits$$atomic(o.atomic);d.set_io$$start$$bits$$atomicOp(0);
            d.set_io$$start$$bits$$accessDenied(o.denied);d.set_io$$start$$bits$$forward$$valid(o.forward);
            d.set_io$$start$$bits$$forward$$bits(0xdeadbeef12345678ULL);
            d.set_io$$start$$valid(active&&!started);
            bool ready=cycle%9!=4;d.set_io$$complete$$ready(ready);d.step();sample();
            need(!d.get_io$$requestOwned()&&!d.get_io$$integerReply()&&!d.get_io$$memory$$request$$valid()&&d.get_io$$ownerCount()==0,"local terminal illegally created response ownership");
            if(active&&!started&&d.get_io$$start$$ready())started=true;
            if(d.get_io$$complete$$valid()) {
                need(started&&d.get_io$$complete$$bits$$token$$tag()==op.tag&&d.get_io$$complete$$bits$$token$$index()==cursor,"local full completion ownership");
                need(bool(d.get_io$$complete$$bits$$exception())==bool(o.cause),"local independently derived exception");
                if(o.cause)need(d.get_io$$complete$$bits$$cause()==o.cause&&d.get_io$$complete$$bits$$tval()==o.address,"local independently derived cause/tval");
                else need(d.get_io$$complete$$bits$$data()==0xdeadbeef12345678ULL,"local forwarding data");
                if(ready){++cursor;started=false;}
            }
            trace=trace*1099511628211ULL+d.get_io$$phases();
            if(cursor==ops.size()&&d.get_io$$allIdle()) {
                std::cout<<"ORDERED_OWNER_CHAIN_CASE name=local_faults_forward_no_owner cycles="<<cycle<<" completions="<<cursor<<" trace="<<trace<<"\n";return;
            }
        }
        throw std::runtime_error("local terminal missing completion");
    }
    void fastPosted() {
        const uint64_t address=0x8020a000,data=0x123456789abcdef0ULL;
        bool accepted=false,requested=false,replied=false;uint64_t due=0,trace=0;
        for(uint64_t cycle=0;cycle<250;++cycle) {
            d.set_io$$fastStore$$valid(!accepted);
            d.set_io$$fastStore$$bits$$address(address);d.set_io$$fastStore$$bits$$data(data);
            d.set_io$$fastStore$$bits$$write(1);d.set_io$$fastStore$$bits$$size(3);d.set_io$$fastStore$$bits$$mask(255);
            bool offer=requested&&!replied&&cycle>=due;
            d.set_io$$memory$$response$$valid(offer);d.set_io$$memory$$response$$bits$$data(0);
            d.step(); sample(offer);
            need(!d.get_io$$requestOwned()&&!d.get_io$$integerReply()&&!d.get_io$$complete$$valid()&&d.get_io$$ownerCount()==0,"fast posted invented LSU ownership");
            if(!accepted&&d.get_io$$fastStore$$ready())accepted=true;
            if(d.get_io$$memory$$request$$valid()) {
                need(accepted&&!requested,"fast posted duplicate/unaccepted physical request");
                need(d.get_io$$memory$$request$$bits$$write()&&d.get_io$$memory$$request$$bits$$address()==address&&d.get_io$$memory$$request$$bits$$data()==data&&d.get_io$$memory$$request$$bits$$mask()==255,"fast posted independent bytes");
                requested=true;due=cycle+30;
            }
            if(offer&&d.get_io$$memory$$response$$ready()){need(!replied,"fast posted duplicate drain");replied=true;}
            if(requested&&!replied)need(!d.get_io$$allIdle(),"fast posted early idle lost responsibility");
            trace=trace*1099511628211ULL+d.get_io$$integerBusy();
            if(replied&&d.get_io$$allIdle()) {std::cout<<"ORDERED_OWNER_CHAIN_CASE name=fast_posted_independent_drain cycles="<<cycle<<" starts=0 physical=1 replies=1 trace="<<trace<<"\n";return;}
        }
        throw std::runtime_error("fast posted missing drain");
    }
    void coordinatedReset() {
        // The host resets its backing obligations at the same edge as all real modules.
        // No stale reply is subsequently injected: partial resets are out of contract.
        Op o{9,3,0xffff000000000009ULL,0x8020b000};bool started=false,owed=false,physical=false;
        for(unsigned cycle=0;cycle<100;++cycle) {
            drive(o);d.set_io$$start$$valid(!started);d.set_io$$parallel(0);d.step();sample();
            if(!started&&d.get_io$$start$$ready())started=true;
            if(d.get_io$$requestOwned()){need(!owed,"reset duplicate owner");owed=true;}
            if(d.get_io$$memory$$request$$valid()) {need(owed&&!physical,"reset unexpected backing request");physical=true;break;}
        }
        need(started&&owed&&physical,"reset abandonment preconditions not established");
        defaults();d.set_reset(1);d.step();d.step();d.set_reset(0);
        for(unsigned i=0;i<8;++i){d.step();sample();need(!d.get_io$$ownerCount()&&!d.get_io$$live()&&!d.get_io$$complete$$valid()&&!d.get_io$$integerReply()&&!d.get_io$$memory$$request$$valid(),"reset failed to abandon accepted responsibilities");}
        need(d.get_io$$allIdle(),"reset failed to return chain idle");
        std::cout<<"ORDERED_OWNER_CHAIN_CASE name=coordinated_reset abandoned_starts=1 abandoned_lsu=1 abandoned_backing=1\n";
    }

    void cancelAtCompletion() {
        const Op op{6,3,0xf000000000000006ULL,0x8020c000};
        bool started=false,requested=false,physical=false,backingReplied=false,consumed=false,discarded=false;
        unsigned slot=0;uint64_t replyDue=0;unsigned offeredCompletion=0;
        for(unsigned cycle=0;cycle<90;++cycle) {
            drive(op);d.set_io$$parallel(0);d.set_io$$start$$valid(!started);
            bool cancel=cycle==30;d.set_io$$cancel(cancel?(1U<<slot):0);
            d.set_io$$complete$$ready(cycle>=30);
            bool reply=physical&&!backingReplied&&cycle>=replyDue;
            d.set_io$$memory$$response$$valid(reply);d.set_io$$memory$$response$$bits$$data(beat(op.address));
            d.step();sample(reply);
            if(!started&&d.get_io$$start$$ready()) {
                started=true;unsigned mask=d.get_io$$startSlots();need(mask&&!(mask&(mask-1)),"supp cancel unique start slot");while(!(mask&(1U<<slot)))++slot;
                need(d.get_io$$requestOwned(),"supp fixed topology unexpectedly delayed initial request");
            }
            if(d.get_io$$requestOwned()){need(started&&!requested,"supp cancel duplicate request");requested=true;}
            if(d.get_io$$memory$$request$$valid()){need(requested&&!physical,"supp cancel physical owner");physical=true;replyDue=cycle+4;}
            if(reply&&d.get_io$$memory$$response$$ready()){need(!backingReplied,"supp cancel duplicate backing reply");backingReplied=true;}
            if(d.get_io$$integerReply()){need(requested&&backingReplied&&!consumed,"supp cancel consumer ownership");consumed=true;}
            if(d.get_io$$complete$$valid()) {
                need(consumed&&!discarded,"supp cancel completion without drained operation");
                need(d.get_io$$complete$$bits$$token$$index()==op.index&&d.get_io$$complete$$bits$$token$$tag()==op.tag,"supp cancel full completion owner");
                need(!d.get_io$$complete$$bits$$exception()&&d.get_io$$complete$$bits$$data()==beat(op.address),"supp cancel independent completion data");
                need(cycle<=30,"supp canceled completion reappeared");++offeredCompletion;
                // On cycle 30 the slot still offers VALID; architectural acceptance is
                // denied by the independently supplied recovery identity at that edge.
                if(cycle==30)need(cancel&&d.get_io$$slotDiscard()==(1U<<slot),"supp cancellation failed to coincide with completion/discard");
            }
            if(cycle==30)need(d.get_io$$complete$$valid()&&consumed&&offeredCompletion>1,"supp fixed-time cancel was not on a held completion");
            if(d.get_io$$slotDiscard()){need(cancel&&!discarded&&consumed,"supp unexpected discard terminal");discarded=true;
                if(injection=="discard"){discarded=false;injected=true;std::cout<<"SUPPLEMENT_INJECTION_REACHED kind=discard\n";}
            }
            if(cycle>33&&d.get_io$$allIdle()) {
                need(started&&requested&&physical&&backingReplied&&consumed&&discarded,"supp cancellation incomplete terminal ledger");
                std::cout<<"ORDERED_OWNER_SUPPLEMENT_CASE name=cancel_on_completion cycles="<<cycle<<" architectural_completions=0 discarded=1 held_offers="<<offeredCompletion<<"\n";return;
            }
        }
        throw std::runtime_error("supp cancel completion terminal timeout");
    }

    void successfulVmEpoch() {
        constexpr uint64_t va=0x40004000ULL,root=0x80200000ULL,l1=0x80201000ULL,l2=0x80202000ULL;
        constexpr uint64_t pa0=0x80210000ULL,pa1=0x80218000ULL;
        const uint64_t satp=(8ULL<<60)|(root>>12),pmp=(1ULL<<54)-1;
        d.set_io$$vm$$satp(satp);d.set_io$$vm$$dataPrivilege(1);
        d.set_io$$pmpCfg(0x1f);d.set_io$$pmpAddress(pmp);
        // Reset with the target architectural context already driven. GSIM applies
        // reset to CURRENT/NEXT then computes the first NEXT: nonzero context gives
        // epoch NEXT=1, previous-context NEXT=target, stable NEXT=false. No DUT read
        // initializes this oracle; this follows the documented step/reset phase.
        d.set_reset(1);d.step();d.step();d.set_reset(0);
        unsigned cursor=0,slot=0,pteReads=0,backingRequests=0,completions=0;
        bool started=false,owed=false,physical=false,replied=false,consumed=false;
        bool changedContext=false,flushDone=false,flushNext=false,stableQ=false;
        unsigned expectedEpoch=1;bool previousContext=true;
        uint64_t backingDue=0;
        struct P {uint64_t data,due;};std::deque<P> ptes;
        std::array<unsigned,4> ptePerOperation{};
        for(uint64_t cycle=0;cycle<600;++cycle) {
            const uint64_t pa=cursor<2?pa0:pa1;
            bool active=cursor<4;
            // Context changes occur only after the first two transactions and every
            // downstream/PTE obligation drained. A new ASID/root context also flushes.
            bool flush=flushNext;flushNext=false;
            if(flush){changedContext=true;flushDone=true;}
            uint64_t contextSatp=satp|(changedContext?(1ULL<<44):0);
            d.set_io$$vm$$satp(contextSatp);d.set_io$$flush(flush);
            const bool contextChanged=!previousContext||flush;
            Op op{5,3,0xe000000000000000ULL+cursor,va};drive(op);
            d.set_io$$start$$bits$$virtualized(1);d.set_io$$parallel(0);
            bool valid=active&&!started&&cycle>=4&&!flush&&
                (cursor!=2||flushDone)&&stableQ;
            d.set_io$$start$$valid(valid);d.set_io$$complete$$ready(1);
            bool pte=!ptes.empty()&&cycle>=ptes.front().due;
            d.set_io$$pte$$response$$valid(pte);d.set_io$$pte$$response$$bits$$data(pte?ptes.front().data:0);
            bool reply=physical&&!replied&&cycle>=backingDue;
            d.set_io$$memory$$response$$valid(reply);d.set_io$$memory$$response$$bits$$data(beat(pa));
            d.step();sample(reply,pte);
            unsigned observedEpoch=d.get_io$$epoch();
            if(injection=="epoch"&&expectedEpoch==2&&!injected){observedEpoch^=1;injected=true;std::cout<<"SUPPLEMENT_INJECTION_REACHED kind=epoch\n";}
            if(observedEpoch!=expectedEpoch)std::cerr<<"epoch cycle="<<cycle<<" actual="<<observedEpoch<<" expected="<<expectedEpoch<<" flush="<<flush<<" contextChanged="<<contextChanged<<"\n";
            need(observedEpoch==expectedEpoch,"supp independently derived authorization epoch mismatch");
            need(bool(d.get_io$$stable())==(stableQ&&!flush),"supp independently derived epoch stability mismatch");
            if(contextChanged||flush)++expectedEpoch;
            stableQ=!contextChanged&&!flush;previousContext=true;
            need(d.get_io$$ownerCount()==unsigned(owed),"supp VM queued owner count");
            if(owed)need(((d.get_io$$phases()>>(2*slot))&3)==2,"supp VM lost owed response phase");
            if(valid&&d.get_io$$start$$ready()) {
                need(!started,"supp VM duplicate start");started=true;unsigned mask=d.get_io$$startSlots();need(mask&&!(mask&(mask-1)),"supp VM unique slot");slot=0;while(!(mask&(1U<<slot)))++slot;
                need(d.get_io$$requestOwned(),"supp VM fixed topology unexpectedly delayed request");
            }
            if(d.get_io$$requestOwned()) {
                need(started&&!owed&&!physical,"supp VM request lifecycle");
                need(d.get_io$$requestToken$$tag()==op.tag&&d.get_io$$requestToken$$index()==5,"supp VM full request token");owed=true;
            }
            if(pte&&d.get_io$$pte$$response$$ready())ptes.pop_front();
            if(d.get_io$$pte$$request$$valid()) {
                uint64_t address=d.get_io$$pte$$request$$bits(),value=0;
                if(address==root+8)value=((l1>>12)<<10)|1;
                else if(address==l1)value=((l2>>12)<<10)|1;
                else if(address==l2+32)value=((pa>>12)<<10)|0xc7; // V,R,W,A,D; supervisor page.
                else throw std::runtime_error("supp independent page-table address mismatch");
                need(started&&cursor<4,"supp unowned walker request");
                ptes.push_back({value,cycle+3});++pteReads;++ptePerOperation[cursor];
            }
            if(d.get_io$$translatedRequest())need(started&&owed&&d.get_io$$translated$$address()==pa&&!d.get_io$$translated$$write(),"supp successful VM independent PA mismatch");
            if(d.get_io$$memory$$request$$valid()) {
                need(started&&owed&&!physical,"supp VM backing ownership");
                need(d.get_io$$memory$$request$$bits$$address()==pa&&!d.get_io$$memory$$request$$bits$$write(),"supp VM backing PA differs from page tables");
                physical=true;backingDue=cycle+5;++backingRequests;
            }
            if(reply&&d.get_io$$memory$$response$$ready()){need(!replied,"supp VM duplicate reply");replied=true;}
            if(d.get_io$$integerReply()){need(owed&&replied&&!consumed,"supp VM reply lifecycle");owed=false;consumed=true;}
            if(d.get_io$$complete$$valid()) {
                need(started&&consumed&&!owed&&ptes.empty(),"supp VM completion before obligations");
                need(d.get_io$$complete$$bits$$token$$tag()==op.tag&&d.get_io$$complete$$bits$$token$$index()==5,"supp VM ABA full token mismatch");
                need(!d.get_io$$complete$$bits$$exception()&&d.get_io$$complete$$bits$$data()==beat(pa),"supp VM independently translated result mismatch");
                ++cursor;++completions;started=physical=replied=consumed=false;
            }
            if(cursor==2&&!flushDone&&d.get_io$$allIdle()){need(ptes.empty(),"supp context change with walker responsibility");flushNext=true;}
            if(cursor==4&&d.get_io$$allIdle()) {
                need(completions==4&&backingRequests==4&&pteReads==6&&ptePerOperation==std::array<unsigned,4>{3,0,3,0},"supp VM miss/hit/epoch-rewalk coverage mismatch");
                need(expectedEpoch==2&&d.get_io$$epoch()==2&&d.get_io$$stable(),"supp final epoch mismatch");
                std::cout<<"ORDERED_OWNER_SUPPLEMENT_CASE name=successful_vm_epoch_aba cycles="<<cycle<<" completions=4 pte_reads=6 epochs=2\n";return;
            }
        }
        throw std::runtime_error("supp VM missing completion/epoch timeout");
    }

};
int main(int argc,char**argv){try {
    const std::string mutation=argc==2?argv[1]:"";
    std::vector<Op> loads;
    for(unsigned i=0;i<48;++i){Op o{i%16,3,0xb000000000000000ULL+i,0x80220000ULL+8*i};o.delay=25;loads.push_back(o);}
    Test(mutation=="tag"?mutation:"").run("continuous_index_aba_pressure",loads,false,90);
    std::cout<<"ORDERED_OWNER_SUPPLEMENT_CASE name=continuous_index_aba_pressure starts=48 indices=16 generations=3 accepted_start_same_edge_request=48\n";
    Test(mutation=="discard"?mutation:"").cancelAtCompletion();Test(mutation=="epoch"?mutation:"").successfulVmEpoch();
    std::cout<<"ORDERED_OWNER_SUPPLEMENT_PASS cancel_before_request=UNREACHABLE_FIXED_TOPOLOGY no_new_DUT=1\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
