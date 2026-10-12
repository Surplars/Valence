#include "TaggedPostedReturnHomeGsim.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <deque>
#include <iostream>
#include <map>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>
#include <vector>

#ifndef TAGGED_STORE_RETURNS
#define TAGGED_STORE_RETURNS 0
#endif
static void check(bool yes, const char* why) { if (!yes) throw std::runtime_error(why); }
#define BOARD_DDR_BYTES 4096ULL
#define DDR_READ_CREDITS 4
#define DDR_READ_LATENCY 80
#define DDR_READ_BEAT_GAP 1
#include "board_ddr_multiid.h"

// These are CPU return reservations, never coherence sources or ROB generations.
static constexpr unsigned fpHandle = 6;
static constexpr uint64_t ram = 4096;
static std::string mutation;
struct Request {
    uint64_t id = 0, address = 0, data = 0;
    unsigned handle = 0, size = 3, mask = 255;
    bool write = false, proof = false, uncached = false, error = false;
};
using Context = std::tuple<unsigned, unsigned, unsigned, unsigned, uint64_t, uint64_t>;
using Payload = std::tuple<unsigned, uint64_t, bool, bool>;
struct Record {
    Request q;
    uint64_t accepted = 0, returned = 0, expected = 0;
    unsigned kind = 0, ticket = 0;
    bool hit = false, acknowledged = false;
    Context context{};
};
class Test {
public:
    STaggedPostedReturnHomeGsim d;
    DdrModel ddr;
    std::map<uint64_t, uint64_t> memory;
    std::map<uint64_t, Record> records;
    std::deque<uint64_t> order;
    std::map<unsigned, uint64_t> handles;
    std::set<Context> contexts;
    std::map<unsigned, unsigned> releaseBeats;
    std::set<unsigned> releaseAcks;
    std::vector<uint64_t> returned;
    std::optional<Request> pending;
    std::optional<Payload> held;
    uint64_t cycle = 1, nextId = 1, posted = 0, postedAck = 0, fallback = 0, fallbackAck = 0;
    uint64_t nextGeneration = 0, heldCycles = 0, bypasses = 0, acquires = 0, installs = 0;
    uint64_t ordinaryBlocked = 0, flushBlocked = 0, releaseData = 0, mutationCount = 0;
    bool holdAcquire = false, holdAck = false, ready = true, flush = false, endEpisode = false, seal = false;
    bool mutate = false;
    static uint64_t initial(uint64_t a) { return 0x89abcdef01234567ULL ^ (a * 0x100100101ULL); }
    static uint64_t tokenTag(uint64_t id) { return 0xfedcba9876543200ULL + id; }
    void ok(bool yes, const std::string& why) const {
        if (!yes) throw std::runtime_error("cycle=" + std::to_string(cycle) + " " + why);
    }
    Test() {
        std::memset(&d, 0, sizeof(d)); d.LOG_START = 1; d.activateAll();
        for (unsigned a = 0; a < BOARD_DDR_BYTES; a += 8) memory[ram+a] = ddr.memory[a] = initial(ram+a);
        tick(true); tick(true); for (unsigned i = 0; i < 5; ++i) tick();
        ok(bool(d.get_io$$taggedEnabled()) == bool(TAGGED_STORE_RETURNS), "host/model tagging mismatch");
        ok(d.get_io$$configuredGenerationBits() == 2, "fixture did not bind two-bit legal exhaustion");
    }
    void drive() {
        const auto q = pending.value_or(Request{});
        d.set_io$$upstream$$request$$valid(bool(pending));
        d.set_io$$upstream$$request$$bits$$address(q.address);
        d.set_io$$upstream$$request$$bits$$data(q.data);
        d.set_io$$upstream$$request$$bits$$size(q.size);
        d.set_io$$upstream$$request$$bits$$mask(q.mask);
        d.set_io$$upstream$$request$$bits$$write(q.write);
        d.set_io$$upstream$$request$$bits$$atomic(false);
        d.set_io$$upstream$$request$$bits$$atomicOp(0);
        d.set_io$$upstream$$request$$bits$$virtualized(false);
        d.set_io$$upstream$$request$$bits$$precheckedLoad(false);
        d.set_io$$upstream$$request$$bits$$translationEpoch(0);
        d.set_io$$upstream$$request$$bits$$prefetchNextAllowed(false);
        d.set_io$$upstream$$request$$bits$$uncached(q.uncached);
#if TAGGED_STORE_RETURNS
        d.set_io$$upstream$$request$$bits$$returnHandle(q.handle);
#endif
        d.set_io$$upstream$$response$$ready(ready);
        d.set_io$$posted$$requestProof$$valid(bool(pending) && q.proof);
        d.set_io$$posted$$requestProof$$bits$$token$$index(q.id & 15);
        d.set_io$$posted$$requestProof$$bits$$token$$tag(tokenTag(q.id));
        d.set_io$$posted$$requestProof$$bits$$epoch(0);
        d.set_io$$posted$$requestProof$$bits$$address(q.address);
        d.set_io$$posted$$requestProof$$bits$$data(q.data);
        d.set_io$$posted$$requestProof$$bits$$size(q.size);
        d.set_io$$posted$$requestProof$$bits$$mask(q.mask);
        d.set_io$$posted$$requestProof$$bits$$headAuthorized(q.proof);
        d.set_io$$posted$$requestProof$$bits$$physicalPmpAllowed(q.proof);
        d.set_io$$posted$$requestProof$$bits$$originalPhysical(q.proof);
        d.set_io$$posted$$requestProof$$bits$$integerOrigin(q.proof);
        d.set_io$$posted$$requestProof$$bits$$legacyPostedAccepted(q.proof);
        d.set_io$$posted$$requestProof$$bits$$finalChecked(q.proof);
        d.set_io$$posted$$contextEpoch(0); d.set_io$$posted$$seal(seal); d.set_io$$posted$$endEpisode(endEpisode);
        d.set_io$$holdAcquire(holdAcquire); d.set_io$$holdGrantAck(false);
        d.set_io$$holdReleaseAck(holdAck); d.set_io$$holdCoherentC(false); d.set_io$$flushRequest(flush);
        d.set_io$$dma$$request$$valid(false); d.set_io$$dma$$response$$ready(true);
        ddr.drive(d, cycle);
    }
    void corrupt() { ++mutationCount; std::cerr << "ACTUAL_CORRUPTION count=" << mutationCount << '\n'; }
    void consume(unsigned handle, uint64_t data, bool error, bool page, uint64_t& responseId) {
        ok(!order.empty(), "response without accepted owner");
        uint64_t id = order.front();
        if (TAGGED_STORE_RETURNS) {
            ok(handles.count(handle), "unknown or stale tagged owner");
            id = handles.at(handle);
        }
        auto& r = records.at(id);
        ok(!r.returned, "duplicate cache response");
        if (id != order.front()) {
            const auto& old = records.at(order.front());
            ok(TAGGED_STORE_RETURNS && r.q.handle < 4 && r.q.write && r.hit && !r.q.proof &&
                !r.q.uncached && !r.kind && !error && !page && old.q.handle < 4 && !old.q.write &&
                !old.q.proof && !old.q.uncached && !old.kind, "response crossed posted, fallback, FP or ordered owner");
            ok(cycle >= r.accepted + 2, "bypass preceded registered store completion");
            ++bypasses;
        }
        ok(error == r.q.error && !page, "response fault flags changed owner");
        ok(data == r.expected, "response independent bytes changed owner");
        ok(cycle > r.accepted, "response preceded request acceptance");
        r.returned = cycle; responseId = id; returned.push_back(id);
        order.erase(std::find(order.begin(), order.end(), id)); handles.erase(r.q.handle);
    }
    void tick(bool reset = false) {
        ok(cycle < 12000, "bounded supplementary timeout");
        drive(); d.set_reset(reset); d.step();
        if (reset) { d.resetAll(); ++cycle; return; }
        ddr.sample(d);
#define CTX(P) Context{unsigned(d.get_io$$##P##$$context$$owner$$slot()), \
    unsigned(d.get_io$$##P##$$context$$owner$$generation()), \
    unsigned(d.get_io$$##P##$$context$$cohortRoot$$slot()), \
    unsigned(d.get_io$$##P##$$context$$cohortRoot$$generation()), \
    uint64_t(d.get_io$$##P##$$context$$epoch()), uint64_t(d.get_io$$##P##$$context$$lineAddress())}
#define TOKEN(P, Q) (d.get_io$$##P##$$token$$index() == ((Q).id & 15) && \
    d.get_io$$##P##$$token$$tag() == tokenTag((Q).id))
        if (pending && !d.get_io$$upstream$$request$$ready()) {
            ordinaryBlocked += !pending->proof && d.get_io$$posted$$busy();
            flushBlocked += flush;
        }
        const bool fire = pending && d.get_io$$upstream$$request$$ready();
        ok(!d.get_io$$accepted$$valid() || fire, "posted accepted detached from actual request.fire");
        ok(!d.get_io$$fallback$$valid() || fire, "fallback detached from actual request.fire");
        if (fire) {
            const auto q = *pending;
            ok(!handles.count(q.handle), "request reused live CPU handle");
            ok(!flush, "request crossed asserted cache/home flush");
            Record r; r.q = q; r.accepted = cycle; r.hit = d.get_io$$hit();
            r.expected = q.write || q.error ? 0 : memory.at(q.address & ~7ULL);
            if (q.write && !q.error) {
                auto& word = memory.at(q.address & ~7ULL);
                for (unsigned b = 0; b < 8; ++b) if (q.mask & (1U << b))
                    word = (word & ~(255ULL << (8*b))) | (q.data & (255ULL << (8*b)));
            }
            if (d.get_io$$accepted$$valid()) {
                ok(q.proof && q.write && !q.error && TOKEN(accepted$$bits$$member, q), "posted full token or premise changed");
                r.kind = 1; r.ticket = d.get_io$$accepted$$bits$$member$$responseTicket();
                r.context = CTX(accepted$$bits$$member);
                ok(std::get<5>(r.context) == (q.address & ~63ULL), "posted context lost request line");
                if (d.get_io$$accepted$$bits$$newLine()) {
                    ok(nextGeneration < 4 && std::get<1>(r.context) == nextGeneration++, "posted generation wrapped or skipped");
                    ok(contexts.insert(r.context).second, "posted reused live full context");
                } else ok(contexts.count(r.context), "posted join lost accepted line context");
                ++posted;
            }
            if (d.get_io$$fallback$$valid()) {
                ok(q.proof && q.write && TOKEN(fallback$$bits, q) && !r.kind, "fallback full token or route changed");
                ok(nextGeneration == 4 && contexts.empty(), "fallback preceded legal exhaustion and posted owner drain");
                r.kind = 2; r.ticket = d.get_io$$fallback$$bits$$responseTicket(); ++fallback;
            }
            handles.emplace(q.handle, q.id); records.emplace(q.id, r); order.push_back(q.id); pending.reset();
        }
        const bool responseValid = d.get_io$$upstream$$response$$valid();
        if (held) ok(responseValid, "held complete response withdrawn");
        unsigned handle = 0;
#if TAGGED_STORE_RETURNS
        if(responseValid) handle = d.get_io$$upstream$$response$$bits$$returnHandle();
#endif
        const Payload payload=responseValid?Payload{handle, uint64_t(d.get_io$$upstream$$response$$bits$$data()),
            bool(d.get_io$$upstream$$response$$bits$$error()), bool(d.get_io$$upstream$$response$$bits$$pageFault())}:Payload{};
        if (held) { ok(d.get_io$$upstream$$response$$valid() && payload == *held, "held complete response or handle changed"); ++heldCycles; }
        held = d.get_io$$upstream$$response$$valid() && !ready ? std::optional{payload} : std::nullopt;
        uint64_t responseId = 0;
        if (d.get_io$$upstream$$response$$valid() && ready) {
            if (mutate && mutation == "--mutate-owner" && TAGGED_STORE_RETURNS) { handle = 7; corrupt(); }
            consume(handle, std::get<1>(payload), std::get<2>(payload), std::get<3>(payload), responseId);
        }
        if (responseId) {
            const auto& r = records.at(responseId);
            ok(bool(d.get_io$$acknowledged$$valid()) == (r.kind == 1), "posted ACK kind detached from response.fire");
            ok(bool(d.get_io$$fallbackAck$$valid()) == (r.kind == 2), "fallback ACK kind detached from response.fire");
        } else ok(!d.get_io$$acknowledged$$valid() && !d.get_io$$fallbackAck$$valid(), "ACK without actual response.fire");
        if (d.get_io$$acknowledged$$valid()) {
            auto& r = records.at(responseId);
            uint64_t tag = d.get_io$$acknowledged$$bits$$token$$tag();
            if (mutate && mutation == "--mutate-posted-token") { tag ^= 1ULL << 48; corrupt(); }
            ok(d.get_io$$acknowledged$$bits$$token$$index() == (r.q.id & 15) && tag == tokenTag(r.q.id) &&
                d.get_io$$acknowledged$$bits$$responseTicket() == r.ticket && CTX(acknowledged$$bits) == r.context,
                "posted ACK lost exact full token, context or ticket");
            ok(!r.acknowledged, "duplicate posted ACK"); r.acknowledged = true; ++postedAck;
        }
        if (d.get_io$$fallbackAck$$valid()) {
            auto& r = records.at(responseId);
            unsigned ticket = d.get_io$$fallbackAck$$bits$$responseTicket();
            if (mutate && mutation == "--mutate-fallback-ticket") { ticket ^= 1; corrupt(); }
            ok(TOKEN(fallbackAck$$bits, r.q) && ticket == r.ticket, "fallback ACK lost exact full token or ticket");
            ok(!r.acknowledged, "duplicate fallback ACK"); r.acknowledged = true; ++fallbackAck;
        }
        if (d.get_io$$released$$valid()) ok(contexts.erase(CTX(released$$bits)) == 1, "released unknown full posted context");
        if (d.get_io$$lineWrite() && d.get_io$$lineWritePosted()) {
            const uint64_t a = d.get_io$$lineWriteAddress();
            const std::array<uint64_t, 8> words{d.get_io$$installWord0(), d.get_io$$installWord1(), d.get_io$$installWord2(),
                d.get_io$$installWord3(), d.get_io$$installWord4(), d.get_io$$installWord5(), d.get_io$$installWord6(), d.get_io$$installWord7()};
            for (unsigned i = 0; i < 8; ++i) ok(words[i] == memory.at((a & ~63ULL) + 8*i), "posted install independent byte overlay mismatch");
            ++installs;
        }
        if (d.get_io$$monAValid() && d.get_io$$monAReady()) ++acquires;
        if (d.get_io$$monCValid() && d.get_io$$monCReady() && d.get_io$$monCOpcode() >= 6) {
            unsigned source = d.get_io$$monCSource();
            ok(!releaseAcks.count(source), "cache reused unacknowledged release source");
            const unsigned beats = d.get_io$$monCOpcode() == 7 ? 8 : 1;
            if (++releaseBeats[source] == beats) {
                releaseBeats.erase(source); ok(releaseAcks.insert(source).second, "duplicate release");
                releaseData += beats == 8;
            }
        }
        if (d.get_io$$monDValid() && d.get_io$$monDReady() && d.get_io$$monDOpcode() == 6)
            ok(releaseAcks.erase(d.get_io$$monDSource()) == 1, "ReleaseAck without completed actual release");
        ok(!d.get_io$$failed(), "guaranteed posted backing failed");
#undef CTX
#undef TOKEN
        ++cycle;
    }
    template<class P> void until(P done, const char* why, unsigned budget = 2400) {
        unsigned n = 0; while (!done() && n++ < budget) tick(); ok(done(), why);
    }
    void cycles(unsigned n) { while (n--) tick(); }
    uint64_t begin(Request q) { ok(!pending, "held request overwritten"); q.id = nextId++; pending = q; return q.id; }
    uint64_t issue(Request q) { auto id = begin(q); until([&]{ return !pending; }, "request acceptance timeout"); return id; }
    bool replied(uint64_t id) const { auto i = records.find(id); return i != records.end() && i->second.returned; }
    void drain() {
        until([&]{ return !pending && order.empty() && contexts.empty() && !d.get_io$$posted$$busy() &&
            releaseAcks.empty() && releaseBeats.empty() && ddr.pendingReads.empty() && !ddr.writing && !ddr.responding; },
            "complete cache/home ownership did not drain"); tick();
        ok(handles.empty(), "response handle leaked at drain");
    }
    void end() { drain(); endEpisode = true; tick(); endEpisode = false; tick(); }
    void finish() {
        drain(); flush = true; until([&]{ return d.get_io$$flushDone(); }, "final actual cache/home flush timeout", 6000);
        ok(releaseAcks.empty() && releaseBeats.empty() && ddr.pendingReads.empty() && !ddr.writing && !ddr.responding,
            "flush completed with external transport owner");
        for (auto [a, value] : memory) ok(ddr.memory.at(unsigned(a-ram)) == value, "final flushed byte image mismatch");
        flush = false; tick();
        ok(posted == postedAck && fallback == fallbackAck && records.size() == returned.size(), "exact ACK/request count mismatch");
        std::cout << "cycles=" << cycle << " requests=" << records.size() << " posted=" << posted << " fallback=" << fallback
            << " held=" << heldCycles << " bypass=" << bypasses << " mutations=" << mutationCount << '\n';
    }
};
static Request load(unsigned handle, uint64_t a) { Request q; q.handle=handle; q.address=a; return q; }
static Request store(unsigned handle, uint64_t a, uint64_t value, bool proof=false) {
    auto q=load(handle,a); q.write=true; q.data=value; q.proof=proof; return q;
}
static void postedBarrier() {
    Test t; t.issue(store(0, ram, 0x1234)); t.drain();
    t.ready=false; t.holdAcquire=true; t.mutate=true;
    auto a=t.issue(store(4, ram+64, 0x1122334455667788ULL, true));
    auto b=t.issue(store(5, ram+72, 0x8877665544332211ULL, true));
    t.cycles(8); t.ok(t.posted==2 && t.postedAck==0 && t.contexts.size()==1 && t.heldCycles>=6,
        "posted joined credits were not held at the real response boundary");
    auto count=t.acquires; t.ready=true; t.until([&]{return t.replied(a)&&t.replied(b);}, "posted ACKs did not drain");
    t.ok(t.returned[t.returned.size()-2]==a && t.returned.back()==b && t.acquires==count,
        "posted ACK order changed or A crossed explicit hold");
    auto c=t.begin(store(1,ram,0xaabbccdd)); t.cycles(8);
    t.ok(t.pending && !t.records.count(c) && t.ordinaryBlocked>=8, "ordinary store crossed live posted owner");
    t.flush=true; t.cycles(8); t.ok(!t.d.get_io$$flushDone(), "flush crossed held posted acquire");
    t.holdAcquire=false; t.until([&]{return t.d.get_io$$flushDone();}, "posted barrier flush failed",6000);
    t.ok(t.pending && !t.records.count(c) && t.flushBlocked>=8, "held ordinary store crossed flush");
    t.flush=false; t.drain(); t.finish();
}
static void fallbackTail() {
    Test t;
    for (unsigned i=0;i<4;++i) { t.issue(store(4+(i&1),ram+64+i*64,100+i,true)); t.end(); }
    t.ok(t.nextGeneration==4 && t.posted==4 && t.fallback==0, "exhaustion prelude was not four actual owner allocations");
    t.issue(load(2,ram+576)); t.drain();
    t.holdAck=true; t.ready=false; t.mutate=true;
    auto a=t.issue(store(4,ram+1088,0xabcdef,true));
    t.until([&]{return t.fallback==1 && t.d.get_io$$upstream$$response$$valid() && !t.releaseAcks.empty();},
        "fallback did not retain actual dirty victim ReleaseAck");
    t.cycles(6); t.ok(!t.replied(a), "fallback response ignored backpressure");
    t.ready=true; t.until([&]{return t.replied(a);}, "fallback ACK missing");
    t.ok(t.d.get_io$$posted$$busy() && !t.releaseAcks.empty() && t.releaseData>=1,
        "fallback ACK released live real-home writeback responsibility");
    auto b=t.begin(store(5,ram+1152,0xdead,true)); t.cycles(8);
    t.ok(t.pending && !t.records.count(b) && t.fallback==1, "new fallback crossed old ReleaseAck owner");
    t.flush=true; t.cycles(8); t.ok(!t.d.get_io$$flushDone(), "flush crossed fallback ReleaseAck");
    t.holdAck=false; t.until([&]{return t.d.get_io$$flushDone();}, "fallback retained tail did not flush",6000);
    t.ok(t.pending && !t.records.count(b), "new fallback crossed active flush");
    t.flush=false; t.drain(); t.end();
    t.ok(t.posted==4 && t.fallback==2 && t.fallbackAck==2, "generation exhausted fallback wrapped or lost ACKs");
    t.finish();
}
static void domainPair(unsigned older, unsigned younger, bool fault) {
    Test t; t.issue(store(3,ram,0x12345678)); t.drain();
    const auto q0=load(older,ram+64); auto q=q0; q.error=fault;
    if(fault)t.ddr.denyReadAddress=64;
    t.holdAcquire=true;
    auto a=t.issue(q); auto y=store(younger,ram+4,0xa1b2c3d400000000ULL); y.size=2; y.mask=240;
    auto b=t.issue(y); t.ok(t.records.at(b).hit,"younger domain store was not actual resident SRAM hit");
    t.cycles(8);
    const bool bypass=TAGGED_STORE_RETURNS && older<4 && younger<4;
    t.ok(!t.replied(a) && t.replied(b)==bypass, "FP/ordered domain exclusion or integer positive control failed");
    t.holdAcquire=false; t.drain();
    const auto pa=std::find(t.returned.begin(),t.returned.end(),a), pb=std::find(t.returned.begin(),t.returned.end(),b);
    t.ok((pb<pa)==bypass, "domain response order mismatch");
    t.ddr.denyReadAddress.reset(); t.issue(load(fpHandle,ram)); t.drain();
    t.ok(t.bypasses==unsigned(bypass), "unexpected extra bypass"); t.finish();
}
static void orderedBarrier() {
    Test t; t.issue(store(0,ram,0x12345678)); t.drain();
    auto ordered=load(2,ram+128); ordered.uncached=true;
    t.ready=false; auto a=t.issue(ordered); auto b=t.begin(store(3,ram,0xaabbccddeeff0011ULL));
    t.until([&]{return t.d.get_io$$upstream$$response$$valid();}, "ordered downstream return missing");
    t.cycles(8); t.ok(t.pending && !t.records.count(b) && !t.replied(a) && t.heldCycles>=6,
        "resident store crossed held actual ordered owner");
    t.ready=true; t.drain();
    t.ok(t.records.at(b).accepted>t.records.at(a).returned && t.bypasses==0, "ordered owner did not retain drain barrier");
    t.finish();
}
int main(int argc,char** argv) {
    try {
        if(argc>1)mutation=argv[1];
        if(!mutation.empty() && mutation!="--mutate-owner" && mutation!="--mutate-posted-token" && mutation!="--mutate-fallback-ticket")
            throw std::runtime_error("unknown mutation");
        postedBarrier(); fallbackTail(); domainPair(1,0,false); domainPair(fpHandle,0,true);
        domainPair(1,fpHandle,false); orderedBarrier();
        check(mutation.empty(),"requested mutation did not activate");
        std::cout << "TAGGED_POSTED_RETURN_PASS tagged=" << TAGGED_STORE_RETURNS
            << " cases=6 generation_bits=2 namespace=4/2/FP posted_always_on=1\n";
        return 0;
    } catch(const std::exception& e) { std::cerr << "TAGGED_POSTED_RETURN_FAIL " << e.what() << '\n'; return 1; }
}
