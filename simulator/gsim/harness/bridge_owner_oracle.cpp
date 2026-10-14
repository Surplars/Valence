#include "BridgeOwnerPairGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>

// All bus requests and memory returns below originate in this input-side owner
// ledger. DUT addresses, sources, data, and internal state never create an
// expected Get, a memory reply, or an expected instruction word.
namespace {
constexpr uint64_t ROM = 0x80000000ULL;
constexpr uint64_t ROM_END = ROM + 8192;
void need(bool v, const std::string &s) { if (!v) throw std::runtime_error(s); }
uint32_t word(uint64_t a) {
    const uint64_t x = a ^ (a >> 17) ^ (a >> 43);
    return uint32_t(x * 0x9e3779b97f4a7c15ULL) ^ uint32_t(x >> 32) ^ 0x6a09e667U;
}
uint64_t memoryBeat(uint64_t a) {
    a &= ~uint64_t(7);
    return uint64_t(word(a)) | (uint64_t(word(a + 4)) << 32);
}
bool inRom(uint64_t a) { return a >= ROM && a <= ROM_END - 8; }
struct Request { uint64_t pc; unsigned mask; };
struct Get {
    uint64_t address = 0;
    unsigned source = 0, size = 0, mask = 0, index = 0;
};
struct Reply { Get get; bool denied = false, corrupt = false; };
struct Response { uint64_t data = 0; unsigned errors = 0; };
struct Input {
    std::optional<Request> request;
    std::optional<Reply> reply;
    bool responseReady = true, aReady = true;
    unsigned poisonSource = 0;
};
struct Owner {
    Request request;
    unsigned group;
    bool hit;
    std::array<std::optional<Get>, 2> gets;
    std::array<bool, 2> sent{{true, true}}, received{{true, true}}, good{{false, false}};
    std::array<uint64_t, 2> data{{0, 0}};
};
struct Counts {
    uint64_t cycles = 0, requests = 0, responses = 0, aGets = 0, aStalls = 0;
    uint64_t responseHolds = 0, dBeats = 0, reordered = 0, denied = 0, corrupt = 0;
    uint64_t odd = 0, even = 0, hits = 0, bypass = 0, lastDNewOwner = 0;
    uint64_t lockHit = 0, lockMiss = 0, cacheUpdateAtLock = 0, heldTurnover = 0;
    uint64_t invalidPoison = 0, wrappedGets = 0, dReadyPoison = 0;
    std::array<uint64_t, 4> masks{{0, 0, 0, 0}};
};
struct View {
    bool requestReady = false, aValid = false, dReady = false, responseValid = false;
    bool completion = false, oldA = false, hit = false, bypass = false;
    Get a;
    Response response;
    uint64_t hitData = 0;
    std::optional<Owner> afterD;
};
class Oracle {
public:
    std::optional<Owner> owner;
    std::optional<Response> held;
    unsigned nextGroup = 0;
    bool cacheValid = false, locked = false, lockedHit = false;
    uint64_t cacheAddress = 0, cacheData = 0, lockedData = 0;
    Counts counts;

    static Owner makeOwner(Request r, unsigned group, bool hit, uint64_t savedData) {
        Owner o{r, group, hit, {}};
        auto add = [&](unsigned i, uint64_t a, unsigned size) {
            o.gets[i] = Get{a, 2 * group + i, size, size == 3 ? 255U : ((a & 4) ? 240U : 15U), i};
            o.sent[i] = o.received[i] = false;
        };
        if (r.mask == 3) {
            if (hit) { o.data[0] = savedData; o.good[0] = true; }
            else add(0, r.pc & ~uint64_t(7), 3);
            if (r.pc & 4) add(1, (r.pc & ~uint64_t(7)) + 8, 3);
        } else {
            for (unsigned i = 0; i < 2; ++i) if (r.mask & (1U << i)) add(i, r.pc + 4 * i, 2);
        }
        return o;
    }
    static std::optional<Get> unsent(const Owner &o) {
        for (unsigned i = 0; i < 2; ++i) if (o.gets[i] && !o.sent[i]) return o.gets[i];
        return std::nullopt;
    }
    static Response assemble(const Owner &o) {
        Response r;
        for (unsigned lane = 0; lane < 2; ++lane) {
            if (!(o.request.mask & (1U << lane))) { r.errors |= 1U << lane; continue; }
            const uint64_t address = o.request.pc + 4 * lane;
            const unsigned index = o.request.mask == 3 ? unsigned(lane && (o.request.pc & 4)) : lane;
            if (!o.good[index]) r.errors |= 1U << lane;
            const uint32_t value = o.good[index] ? uint32_t(o.data[index] >> ((address & 4) * 8)) : 0;
            r.data |= uint64_t(value) << (32 * lane);
        }
        return r;
    }
    static unsigned lastIndex(const Owner &o) { return o.request.pc & 4 ? 1 : 0; }
    static uint64_t lastAddress(const Owner &o) {
        return (o.request.pc & ~uint64_t(7)) + 8 * lastIndex(o);
    }
    View view(const Input &in) const {
        View v;
        const unsigned source = in.reply ? in.reply->get.source : in.poisonSource;
        const unsigned i = source & 1;
        v.dReady = owner && source <= 3 && source / 2 == owner->group && owner->sent[i] && !owner->received[i];
        if (in.reply) {
            need(v.dReady, "test scheduler offered D without an independent outstanding owner");
            need(owner->gets[i].has_value(), "test scheduler replied to absent expected Get");
            const Get &g = *owner->gets[i];
            need(g.address == in.reply->get.address && g.size == in.reply->get.size,
                "test scheduler changed the owner Get");
            v.afterD = owner;
            v.afterD->received[i] = true;
            v.afterD->good[i] = !in.reply->denied && !in.reply->corrupt;
            // Authoritative bytes come from the expected request address, never DUT A or D.
            v.afterD->data[i] = v.afterD->good[i] ? memoryBeat(g.address) : 0;
            v.completion = v.afterD->received[0] && v.afterD->received[1];
        }
        v.responseValid = held.has_value() || v.completion;
        if (held) v.response = *held;
        else if (v.completion) v.response = assemble(*v.afterD);
        const bool canStart = (!owner || v.completion) && (!held || in.responseReady) &&
            (!v.completion || in.responseReady);
        const auto oldGet = owner ? unsent(*owner) : std::nullopt;
        const Request r = in.request.value_or(Request{0, 0});
        const unsigned maskForReady = in.request ? r.mask : unsigned(counts.cycles & 3);
        if (in.request && r.mask == 3 && (r.pc & 4)) {
            const uint64_t aligned = r.pc & ~uint64_t(7);
            v.bypass = v.completion && v.afterD->good[lastIndex(*v.afterD)] &&
                inRom(lastAddress(*v.afterD)) && lastAddress(*v.afterD) == aligned;
            v.hit = locked ? lockedHit : (inRom(aligned) && (v.bypass || (cacheValid && cacheAddress == aligned)));
            v.hitData = locked ? lockedData : (v.bypass ? v.afterD->data[lastIndex(*v.afterD)] : cacheData);
        }
        // Legal request producers hold PC and mask until ready. No eligible hit
        // is required outside full odd packets; invalid payload is deliberately poisoned.
        v.oldA = bool(oldGet);
        v.aValid = bool(oldGet) || (canStart && in.request && r.mask != 0);
        if (oldGet) v.a = *oldGet;
        else if (v.aValid) v.a = *unsent(makeOwner(r, nextGroup, v.hit, v.hitData));
        v.requestReady = canStart && !oldGet && (maskForReady == 0 || in.aReady);
        return v;
    }
    void commit(const Input &in, const View &v) {
        ++counts.cycles;
        if (!in.request) { ++counts.invalidPoison; if (v.dReady && !in.reply) ++counts.dReadyPoison; }
        if (v.aValid && !in.aReady) ++counts.aStalls;
        if (v.responseValid && !in.responseReady) ++counts.responseHolds;
        if (v.responseValid && in.responseReady) ++counts.responses;
        if (v.aValid && in.aReady) {
            ++counts.aGets;
            const uint64_t pc = v.oldA ? owner->request.pc : in.request->pc;
            if (v.a.address < 8 && pc >= ~uint64_t(7)) ++counts.wrappedGets;
            if (v.oldA) owner->sent[v.a.index] = true;
        }
        if (v.aValid && !v.oldA && !in.aReady) {
            if (!locked) { if (v.hit) ++counts.lockHit; else ++counts.lockMiss; }
            locked = true; lockedHit = v.hit; lockedData = v.hitData;
            if (v.completion && v.afterD->request.mask == 3) ++counts.cacheUpdateAtLock;
        }
        if (held && in.responseReady) held.reset();
        if (in.reply) {
            ++counts.dBeats;
            counts.denied += in.reply->denied; counts.corrupt += in.reply->corrupt;
            if ((in.reply->get.index == 1) && owner->gets[0] && !owner->received[0]) ++counts.reordered;
            // Preserve an independently issued old A if it handshook with this D.
            auto updated = *v.afterD;
            if (v.oldA && v.aValid && in.aReady) updated.sent[v.a.index] = true;
            owner = updated;
            if (v.completion) {
                if (owner->request.mask == 3) {
                    cacheAddress = lastAddress(*owner);
                    cacheData = owner->data[lastIndex(*owner)];
                    cacheValid = owner->good[lastIndex(*owner)] && inRom(cacheAddress);
                }
                if (!in.responseReady) held = v.response;
                owner.reset();
            }
        }
        if (in.request && v.requestReady) {
            const Request r = *in.request;
            ++counts.requests; ++counts.masks[r.mask];
            if (r.pc & 4) ++counts.odd; else ++counts.even;
            if (v.completion) ++counts.lastDNewOwner;
            if (v.responseValid && !v.completion) ++counts.heldTurnover;
            if (!r.mask) held = Response{0, 3};
            else {
                owner = makeOwner(r, nextGroup, v.hit, v.hitData);
                need(v.aValid && in.aReady && !v.oldA, "new owner missing expected first Get");
                owner->sent[v.a.index] = true;
                nextGroup ^= 1;
                if (v.hit) ++counts.hits;
                if (v.hit && v.bypass && !locked) ++counts.bypass;
                locked = false;
            }
        }
    }
};

class Fixture {
public:
    SBridgeOwnerPairGsim dut;
    Oracle model;
    std::string negative;
    bool injected = false;
    std::string label;
    explicit Fixture(std::string mode) : negative(std::move(mode)) { reset("initial"); }
    void drive(const Input &in) {
        const uint64_t poison = 0xdedecafe01234567ULL ^ (model.counts.cycles * 0x1111111111111111ULL);
        dut.set_io$$fetch$$request$$valid(bool(in.request));
        dut.set_io$$fetch$$request$$bits(in.request ? in.request->pc : poison);
        dut.set_io$$fetch$$requestMask(in.request ? in.request->mask : (model.counts.cycles & 3));
        dut.set_io$$fetch$$response$$ready(in.responseReady);
        dut.set_io$$tl$$a$$ready(in.aReady);
        dut.set_io$$tl$$d$$valid(bool(in.reply));
        dut.set_io$$tl$$d$$bits$$opcode(in.reply ? 1 : ((poison >> 3) & 7));
        dut.set_io$$tl$$d$$bits$$param(in.reply ? 0 : ((poison >> 6) & 7));
        dut.set_io$$tl$$d$$bits$$size(in.reply ? in.reply->get.size : (poison & 3));
        dut.set_io$$tl$$d$$bits$$source(in.reply ? in.reply->get.source : in.poisonSource);
        dut.set_io$$tl$$d$$bits$$sink(poison & 1);
        dut.set_io$$tl$$d$$bits$$denied(in.reply ? in.reply->denied : bool(poison & 1));
        dut.set_io$$tl$$d$$bits$$data(in.reply ? memoryBeat(in.reply->get.address) : poison);
        dut.set_io$$tl$$d$$bits$$corrupt(in.reply ? in.reply->corrupt : bool(poison & 2));
        dut.set_io$$tl$$b$$valid(0);
        dut.set_io$$tl$$b$$bits$$opcode((poison >> 5) & 7);
        dut.set_io$$tl$$b$$bits$$param((poison >> 8) & 7);
        dut.set_io$$tl$$b$$bits$$size(poison & 3);
        dut.set_io$$tl$$b$$bits$$source((poison >> 2) & 7);
        dut.set_io$$tl$$b$$bits$$address(poison);
        dut.set_io$$tl$$b$$bits$$mask(poison & 255);
        dut.set_io$$tl$$b$$bits$$data(~poison);
        dut.set_io$$tl$$b$$bits$$corrupt(poison & 1);
        dut.set_io$$tl$$c$$ready(poison & 1);
        dut.set_io$$tl$$e$$ready(bool(poison & 2));
        const bool mutate = negative == "--inject-pair-mismatch" && in.reply && !in.reply->denied && !in.reply->corrupt;
        dut.set_io$$mutateCandidateData(mutate);
    }
    void reset(const std::string &name) {
        label = name;
        const Counts saved = model.counts;
        model = Oracle{}; model.counts = saved;
        Input in; in.poisonSource = 7;
        drive(in); dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    }
    View tick(Input in = {}) {
        in.poisonSource = unsigned((model.counts.cycles * 5 + 3) & 7);
        View v = model.view(in);
        drive(in); dut.step();
        auto check = [&](bool ok, const char *message) {
            need(ok, label + " cycle=" + std::to_string(model.counts.cycles) + " " + message);
        };
        check(dut.get_io$$interfaceEqual(), "bridge frozen peer valid-interface mismatch");
        check(bool(dut.get_io$$fetch$$request$$ready()) == v.requestReady, "independent bridge request-ready oracle mismatch");
        check(bool(dut.get_io$$tl$$d$$ready()) == v.dReady, "independent bridge D-ready oracle mismatch");
        check(bool(dut.get_io$$tl$$a$$valid()) == v.aValid, "independent bridge A-valid oracle mismatch");
        check(bool(dut.get_io$$fetch$$response$$valid()) == v.responseValid, "independent bridge response-valid oracle mismatch");
        check(!dut.get_io$$tl$$b$$ready() && !dut.get_io$$tl$$c$$valid() && !dut.get_io$$tl$$e$$valid(), "bridge coherence tieoff mismatch");
        if (v.aValid) {
            Get expected = v.a;
            if (negative == "--inject-a-mismatch" && !injected) { expected.address ^= 8; injected = true; }
            check(dut.get_io$$tl$$a$$bits$$address() == expected.address &&
                dut.get_io$$tl$$a$$bits$$source() == expected.source &&
                dut.get_io$$tl$$a$$bits$$size() == expected.size &&
                dut.get_io$$tl$$a$$bits$$mask() == expected.mask &&
                dut.get_io$$tl$$a$$bits$$opcode() == 4 && dut.get_io$$tl$$a$$bits$$param() == 0 &&
                dut.get_io$$tl$$a$$bits$$data() == 0 && !dut.get_io$$tl$$a$$bits$$corrupt(),
                "independent bridge valid-A oracle mismatch");
        }
        if (v.responseValid) {
            Response expected = v.response;
            if (negative == "--inject-mismatch" && !injected) { expected.data ^= 1; injected = true; }
            check(dut.get_io$$fetch$$response$$bits() == expected.data &&
                dut.get_io$$fetch$$responseError() == expected.errors &&
                dut.get_io$$fetch$$responsePageFault() == 0,
                "independent bridge response oracle mismatch");
        }
        model.commit(in, v);
        return v;
    }
    Reply reply(unsigned index, bool denied = false, bool corrupt = false) const {
        need(model.owner && model.owner->gets[index] && model.owner->sent[index] && !model.owner->received[index],
            "test requested nonexistent oracle reply");
        return Reply{*model.owner->gets[index], denied, corrupt};
    }
    void take(Request request, unsigned stalls = 0) {
        for (unsigned n = 0; n < stalls; ++n) {
            const auto v = tick(Input{request, {}, true, false});
            need(v.aValid && !v.requestReady, "directed first A stall was not reached");
        }
        need(tick(Input{request, {}, true, true}).requestReady, "directed request was not accepted");
    }
    void drainOld(unsigned stalls = 0) {
        if (!model.owner || !Oracle::unsent(*model.owner)) return;
        for (unsigned n = 0; n < stalls; ++n)
            need(tick(Input{{}, {}, true, false}).oldA, "directed second A stall was not reached");
        need(tick().oldA, "directed second Get was not reached");
    }
    void finish(unsigned errorPattern = 0, bool hold = false) {
        if (!model.owner) {
            need(model.held.has_value(), "finish without owner or fault-only response");
            tick(Input{{}, {}, !hold, true});
        } else {
            // Return index 1 first whenever two Gets exist, proving out-of-order D assembly.
            for (int i : {1, 0}) if (model.owner && model.owner->gets[i] && !model.owner->received[i]) {
                const bool denied = (errorPattern == 1 && i == 0) || (errorPattern == 3 && i == 1);
                const bool corrupt = (errorPattern == 2 && i == 1) || (errorPattern == 3 && i == 0);
                const Reply r = reply(unsigned(i), denied, corrupt);
                tick(Input{{}, r, !hold, true});
            }
        }
        if (hold) {
            tick(Input{{}, {}, false, true});
            tick(Input{{}, {}, false, true});
            need(tick().responseValid, "held response did not survive to acceptance");
        }
        need(!model.owner && !model.held, "finish failed to drain oracle");
    }
};

void exact(uint64_t actual, uint64_t expected, const char *name) {
    need(actual == expected, std::string("coverage exact count ") + name + " expected=" +
        std::to_string(expected) + " got=" + std::to_string(actual));
}
void report(const char *phase, const Counts &c) {
    std::cout << phase << " cycles=" << c.cycles << " requests=" << c.requests << " responses=" << c.responses
        << " masks=" << c.masks[0] << ',' << c.masks[1] << ',' << c.masks[2] << ',' << c.masks[3]
        << " gets=" << c.aGets << " aStalls=" << c.aStalls << " responseHolds=" << c.responseHolds
        << " dBeats=" << c.dBeats << " reordered=" << c.reordered << " denied=" << c.denied
        << " corrupt=" << c.corrupt << " odd=" << c.odd << " even=" << c.even
        << " cacheHits=" << c.hits << " bypassHits=" << c.bypass << " lastDNewOwner=" << c.lastDNewOwner
        << " lockHit=" << c.lockHit << " lockMiss=" << c.lockMiss << " cacheUpdateAtLock=" << c.cacheUpdateAtLock
        << " heldTurnover=" << c.heldTurnover << " invalidPoison=" << c.invalidPoison
        << " wrappedGets=" << c.wrappedGets << " invalidDReady=" << c.dReadyPoison << '\n';
}
void matrix(Fixture &f) {
    const std::array<uint64_t, 12> addresses{{0, 4, 0x1000, 0x1004, ROM - 8, ROM - 4,
        ROM, ROM + 4, ROM_END - 8, ROM_END - 4, ~uint64_t(7), ~uint64_t(3)}};
    for (uint64_t pc : addresses) for (unsigned mask = 0; mask < 4; ++mask) for (unsigned errors = 0; errors < 4; ++errors) {
        f.reset("matrix pc=" + std::to_string(pc) + " mask=" + std::to_string(mask) + " error=" + std::to_string(errors));
        f.take(Request{pc, mask}, mask ? 2 : 0);
        f.drainOld(1);
        f.finish(errors, true);
        f.tick(Input{{}, {}, true, false});
        f.tick(Input{{}, {}, false, true});
    }
    const auto &c = f.model.counts;
    exact(c.cycles, 1704, "matrix cycles");
    exact(c.requests, 192, "matrix requests"); exact(c.responses, 192, "matrix responses");
    for (unsigned i = 0; i < 4; ++i) exact(c.masks[i], 48, "matrix mask");
    exact(c.odd, 96, "matrix odd"); exact(c.even, 96, "matrix even");
    exact(c.aGets, 168, "matrix gets"); exact(c.dBeats, 168, "matrix D beats");
    exact(c.aStalls, 312, "matrix A stalls"); exact(c.responseHolds, 576, "matrix response holds");
    exact(c.reordered, 24, "matrix reordered D"); exact(c.denied, 42, "matrix denied D");
    exact(c.corrupt, 42, "matrix corrupt D"); exact(c.wrappedGets, 8, "matrix wrapped Gets");
    exact(c.hits, 0, "matrix reset-cold cache"); exact(c.lockMiss, 144, "matrix cold A locks");
    exact(c.invalidPoison, 1224, "matrix invalid poison cycles");
    report("matrix", c);
}
void ownerCases(Fixture &f) {
    f.model.counts = Counts{};
    // lastD bypass and a new request/first A in precisely the same cycle.
    f.reset("lastD bypass turnover");
    f.take({ROM, 3});
    const auto overlap = f.tick(Input{Request{ROM + 4, 3}, f.reply(0), true, true});
    need(overlap.completion && overlap.hit && overlap.bypass && overlap.aValid && overlap.requestReady,
        "lastD new-owner bypass was not reached");
    f.finish();
    f.take({ROM + 12, 3}); f.finish(3); // denied final beat must invalidate retained ROM beat.
    f.take({ROM + 20, 3}); f.drainOld(); f.finish();
    exact(f.model.counts.hits, 2, "bypass and ordinary ROM hit");
    exact(f.model.counts.aGets, 5, "bypass/error-invalidate Gets");

    // Cache-hit A is held while another owner replaces the retained cache entry.
    f.reset("locked hit survives cache replacement");
    f.take({ROM, 3}); f.finish();
    f.take({ROM + 32, 3});
    auto v = f.tick(Input{Request{ROM + 4, 3}, f.reply(0), true, false});
    need(v.completion && v.hit && !v.requestReady && v.a.address == ROM + 8,
        "locked-hit cache-replacement overlap was not reached");
    f.tick(Input{Request{ROM + 4, 3}, {}, true, false});
    v = f.tick(Input{Request{ROM + 4, 3}, {}, true, true});
    need(v.hit && v.a.address == ROM + 8 && v.requestReady, "locked-hit A did not stay fixed");
    f.finish();

    // A retained immutable beat also remains legal after an errored completion
    // invalidates the single cache entry in the exact cycle the new A is locked.
    f.reset("locked hit survives cache invalidation");
    f.take({ROM, 3}); f.finish();
    f.take({ROM, 3});
    v = f.tick(Input{Request{ROM + 4, 3}, f.reply(0, true), true, false});
    need(v.hit && v.completion && !v.bypass, "locked-hit invalidation overlap was not reached");
    f.tick(Input{Request{ROM + 4, 3}, {}, true, true}); f.finish();

    // A miss is separately locked across cache replacement, then both Gets return.
    f.reset("locked miss survives cache replacement");
    f.take({ROM, 3});
    v = f.tick(Input{Request{ROM + 68, 3}, f.reply(0), true, false});
    need(!v.hit && v.completion && !v.requestReady, "locked-miss overlap was not reached");
    f.tick(Input{Request{ROM + 68, 3}, {}, true, false});
    f.tick(Input{Request{ROM + 68, 3}, {}, true, true});
    f.drainOld(1); f.finish();

    // Partial packets preserve an existing ROM cache entry; full even packets
    // cannot use its odd-packet hit shortcut. Fault-only response turns over too.
    f.reset("partial cache preservation and fault turnover");
    f.take({ROM, 3}); f.finish();
    f.take({0x1004, 1}); f.finish(1);
    f.take({0x2000, 2}); f.finish(2);
    f.take({ROM + 4, 3}); f.finish();
    f.take({ROM + 8, 3});
    v = f.tick(Input{Request{ROM_END - 4, 0}, f.reply(0), true, true});
    need(v.completion && v.requestReady && !v.aValid, "lastD fault-only turnover was not reached");
    f.tick(Input{{}, {}, false, false});
    v = f.tick(Input{Request{ROM + 12, 3}, {}, true, true});
    need(v.responseValid && v.requestReady && v.hit, "held fault-only response/new-owner turnover was not reached");
    f.finish();

    // Simultaneous old second A / first D, with poison request payload. This
    // catches scheduling and sent-bit mistakes that single-channel tests miss.
    f.reset("old A and D overlap");
    f.take({0x3004, 3});
    v = f.tick(Input{{}, f.reply(0), true, true});
    need(v.oldA && v.dReady && !v.completion, "old A/D overlap was not reached");
    f.finish();

    const auto &c = f.model.counts;
    exact(c.cycles, 46, "owner cycles");
    exact(c.requests, 20, "owner requests"); exact(c.responses, 20, "owner responses");
    exact(c.aGets, 22, "owner Gets"); exact(c.dBeats, 22, "owner D beats");
    exact(c.hits, 6, "owner cache hits"); exact(c.bypass, 1, "owner bypass hits");
    exact(c.lastDNewOwner, 2, "owner lastD accepted turnovers");
    exact(c.lockHit, 2, "owner locked hits"); exact(c.lockMiss, 1, "owner locked misses");
    exact(c.cacheUpdateAtLock, 3, "owner cache updates during first stalled A");
    exact(c.heldTurnover, 1, "owner held response turnover");
    exact(c.aStalls, 6, "owner A stalls"); exact(c.responseHolds, 1, "owner response hold");
    exact(c.masks[0], 1, "owner mask00"); exact(c.masks[1], 1, "owner mask01");
    exact(c.masks[2], 1, "owner mask10"); exact(c.masks[3], 17, "owner mask11");
    exact(c.odd, 11, "owner odd"); exact(c.even, 9, "owner even");
    exact(c.reordered, 2, "owner reordered D"); exact(c.denied, 3, "owner denied D");
    exact(c.corrupt, 1, "owner corrupt D"); exact(c.invalidPoison, 21, "owner invalid poison cycles");
    report("owner", c);
}
} // namespace

int main(int argc, char **argv) {
    const std::string mode = argc == 2 ? argv[1] : "";
    need(argc <= 2 && (mode.empty() || mode == "--inject-mismatch" || mode == "--inject-a-mismatch" ||
        mode == "--inject-pair-mismatch"), "unknown bridge oracle argument");
    Fixture f(mode);
    matrix(f);
    ownerCases(f);
    need(mode.empty(), "negative control did not reject");
    std::cout << "GSIM bridge independent owner oracle: PASS matrix=192 owner=20 frozenPeers=2 addressModes=2\n";
}
