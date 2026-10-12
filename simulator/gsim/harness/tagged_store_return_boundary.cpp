#include "TaggedStoreReturnBoundaryGsim.h"
#include <cstdint>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>

#ifndef TAGGED_STORE_RETURNS
#define TAGGED_STORE_RETURNS 0
#endif

static constexpr bool tagged = TAGGED_STORE_RETURNS;
static void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

struct Request {
    uint64_t address = 0, data = 0;
    unsigned size = 0, mask = 0, op = 0, epoch = 0, handle = 0;
    bool write = false, atomic = false, virtualized = false;
    bool prechecked = false, prefetch = false, uncached = false;
    bool operator==(const Request &) const = default;
};
struct Reply {
    uint64_t data = 0;
    bool error = false, page = false;
    unsigned handle = 0;
    bool operator==(const Reply &) const = default;
};
struct RegisterRequest {
    uint64_t address = 0, data = 0;
    unsigned size = 0, mask = 0;
    bool write = false;
    bool operator==(const RegisterRequest &) const = default;
};
struct Snapshot {
    bool storeReady = false, storeValid = false, storeMemoryValid = false, storeMemoryReady = false;
    bool busy = false, forwarded = false;
    Request storeMemory;
    Reply storeReply;
    bool routeReady = false, routeValid = false, routeMemoryValid = false, routeMemoryReady = false;
    bool registerValid = false, registerReady = false;
    Request routeMemory;
    RegisterRequest registers;
    Reply routeReply;
};

// The software oracle owns requests and replies. It observes only public handshakes and payloads.
class Harness {
public:
    STaggedStoreReturnBoundaryGsim d;
    Request store, route;
    bool storeValid = false, storeReady = false, storeMemoryReady = false;
    bool routeValid = false, routeReady = false, routeMemoryReady = false, registerReady = false;
    std::optional<Reply> storeReturn, routeReturn, registerReturn;

    Harness() {
        d.set_io$$namespaceHandle(0);
        d.set_io$$namespaceSlot(0);
        d.set_reset(1);
        tick(); tick();
        d.set_reset(0);
        const auto s = tick();
        check(bool(d.get_io$$taggedEnabled()) == tagged, "host/model tagged mode mismatch");
        check(!s.busy && !s.storeValid && !s.routeValid, "reset did not clear real boundary state");
    }

    Snapshot tick() {
#define DRIVE_REQUEST(P, R, V) \
        d.set_io$$##P##$$request$$valid(V); \
        d.set_io$$##P##$$request$$bits$$address(R.address); \
        d.set_io$$##P##$$request$$bits$$data(R.data); \
        d.set_io$$##P##$$request$$bits$$size(R.size); \
        d.set_io$$##P##$$request$$bits$$mask(R.mask); \
        d.set_io$$##P##$$request$$bits$$write(R.write); \
        d.set_io$$##P##$$request$$bits$$atomic(R.atomic); \
        d.set_io$$##P##$$request$$bits$$atomicOp(R.op); \
        d.set_io$$##P##$$request$$bits$$virtualized(R.virtualized); \
        d.set_io$$##P##$$request$$bits$$precheckedLoad(R.prechecked); \
        d.set_io$$##P##$$request$$bits$$translationEpoch(R.epoch); \
        d.set_io$$##P##$$request$$bits$$prefetchNextAllowed(R.prefetch); \
        d.set_io$$##P##$$request$$bits$$uncached(R.uncached)
        DRIVE_REQUEST(store, store, storeValid);
        DRIVE_REQUEST(route, route, routeValid);
#undef DRIVE_REQUEST
        d.set_io$$store$$response$$ready(storeReady);
        d.set_io$$route$$response$$ready(routeReady);
        d.set_io$$storeMemory$$request$$ready(storeMemoryReady);
        d.set_io$$routeMemory$$request$$ready(routeMemoryReady);
        d.set_io$$registers$$request$$ready(registerReady);
#define DRIVE_REPLY(P, R) \
        d.set_io$$##P##$$response$$valid(bool(R)); \
        d.set_io$$##P##$$response$$bits$$data(R ? R->data : 0); \
        d.set_io$$##P##$$response$$bits$$error(R && R->error)
        DRIVE_REPLY(storeMemory, storeReturn);
        DRIVE_REPLY(routeMemory, routeReturn);
        DRIVE_REPLY(registers, registerReturn);
#undef DRIVE_REPLY
        d.set_io$$storeMemory$$response$$bits$$pageFault(storeReturn && storeReturn->page);
        d.set_io$$routeMemory$$response$$bits$$pageFault(routeReturn && routeReturn->page);
#if TAGGED_STORE_RETURNS
        d.set_io$$store$$request$$bits$$returnHandle(store.handle);
        d.set_io$$route$$request$$bits$$returnHandle(route.handle);
        d.set_io$$storeMemory$$response$$bits$$returnHandle(storeReturn ? storeReturn->handle : 0);
        d.set_io$$routeMemory$$response$$bits$$returnHandle(routeReturn ? routeReturn->handle : 0);
#endif
        d.step();
        Snapshot s;
#define READ_REQUEST(P, R) \
        R.address = d.get_io$$##P##$$request$$bits$$address(); \
        R.data = d.get_io$$##P##$$request$$bits$$data(); \
        R.size = d.get_io$$##P##$$request$$bits$$size(); \
        R.mask = d.get_io$$##P##$$request$$bits$$mask(); \
        R.write = d.get_io$$##P##$$request$$bits$$write(); \
        R.atomic = d.get_io$$##P##$$request$$bits$$atomic(); \
        R.op = d.get_io$$##P##$$request$$bits$$atomicOp(); \
        R.virtualized = d.get_io$$##P##$$request$$bits$$virtualized(); \
        R.prechecked = d.get_io$$##P##$$request$$bits$$precheckedLoad(); \
        R.epoch = d.get_io$$##P##$$request$$bits$$translationEpoch(); \
        R.prefetch = d.get_io$$##P##$$request$$bits$$prefetchNextAllowed(); \
        R.uncached = d.get_io$$##P##$$request$$bits$$uncached()
        if(d.get_io$$storeMemory$$request$$valid()) { READ_REQUEST(storeMemory, s.storeMemory); }
        if(d.get_io$$routeMemory$$request$$valid()) { READ_REQUEST(routeMemory, s.routeMemory); }
#undef READ_REQUEST
#define READ_REPLY(P, R) \
        R.data = d.get_io$$##P##$$response$$bits$$data(); \
        R.error = d.get_io$$##P##$$response$$bits$$error(); \
        R.page = d.get_io$$##P##$$response$$bits$$pageFault()
        if(d.get_io$$store$$response$$valid()) { READ_REPLY(store, s.storeReply); }
        if(d.get_io$$route$$response$$valid()) { READ_REPLY(route, s.routeReply); }
#undef READ_REPLY
#if TAGGED_STORE_RETURNS
        if(d.get_io$$storeMemory$$request$$valid()) s.storeMemory.handle = d.get_io$$storeMemory$$request$$bits$$returnHandle();
        if(d.get_io$$routeMemory$$request$$valid()) s.routeMemory.handle = d.get_io$$routeMemory$$request$$bits$$returnHandle();
        if(d.get_io$$store$$response$$valid()) s.storeReply.handle = d.get_io$$store$$response$$bits$$returnHandle();
        if(d.get_io$$route$$response$$valid()) s.routeReply.handle = d.get_io$$route$$response$$bits$$returnHandle();
#endif
        s.storeReady = d.get_io$$store$$request$$ready();
        s.storeValid = d.get_io$$store$$response$$valid();
        s.storeMemoryValid = d.get_io$$storeMemory$$request$$valid();
        s.storeMemoryReady = d.get_io$$storeMemory$$response$$ready();
        s.busy = d.get_io$$storeBusy();
        s.forwarded = d.get_io$$storeForwarded();
        s.routeReady = d.get_io$$route$$request$$ready();
        s.routeValid = d.get_io$$route$$response$$valid();
        s.routeMemoryValid = d.get_io$$routeMemory$$request$$valid();
        s.routeMemoryReady = d.get_io$$routeMemory$$response$$ready();
        s.registerValid = d.get_io$$registers$$request$$valid();
        s.registerReady = d.get_io$$registers$$response$$ready();
        if(s.registerValid) s.registers = {d.get_io$$registers$$request$$bits$$address(),
            d.get_io$$registers$$request$$bits$$data(), d.get_io$$registers$$request$$bits$$size(),
            d.get_io$$registers$$request$$bits$$byteEnable(), bool(d.get_io$$registers$$request$$bits$$write())};
        return s;
    }
};

static Request request(uint64_t address, bool write, uint64_t data, unsigned handle) {
    Request r;
    r.address = address; r.write = write; r.data = data; r.handle = tagged ? handle : 0;
    r.size = 3; r.mask = 255; r.op = 19; r.epoch = 0x19a3b5c7; r.prefetch = true;
    return r;
}
static Reply reply(uint64_t data, bool error, bool page, unsigned handle) {
    return {data, error, page, tagged ? handle : 0};
}
static Request drained(Request r) { r.handle = tagged ? 2 : 0; return r; }
static void expectStoreReply(const Snapshot &s, Reply expected, bool corrupt = false) {
    auto actual = s.storeReply;
    if (corrupt) { actual.data ^= 1; std::cerr << "ACTUAL_CORRUPTION count=1\n"; }
    check(s.storeValid && actual == expected, "independent store response payload/handle mismatch");
}
static void expectRouteReply(const Snapshot &s, Reply expected, bool corrupt = false) {
    auto actual = s.routeReply;
    if (corrupt) { actual.data ^= 1; std::cerr << "ACTUAL_CORRUPTION count=1\n"; }
    check(s.routeValid && actual == expected, "independent router response payload/handle mismatch");
}

static void namespaces() {
    Harness h;
    for (unsigned i = 0; i < 32; ++i) {
        h.d.set_io$$namespaceHandle(i);
        h.d.set_io$$namespaceSlot(i & 7);
        h.tick();
        check(bool(h.d.get_io$$standardInteger()) == (i < 4), "4/2/FP integer namespace");
        check(bool(h.d.get_io$$standardStore()) == (i >= 4 && i < 6), "4/2/FP store namespace");
        check(bool(h.d.get_io$$standardLegal()) == (i < 7), "4/2/FP legal namespace including unused handle");
        check(h.d.get_io$$standardStoreHandle() == 4 + (i & 1), "4/2/FP store handle encoding");
        check(bool(h.d.get_io$$largestInteger()) == (i < 8), "8/8/FP integer namespace");
        check(bool(h.d.get_io$$largestStore()) == (i >= 8 && i < 16), "8/8/FP store namespace");
        check(bool(h.d.get_io$$largestLegal()) == (i < 17), "8/8/FP legal namespace including unused handles");
        check(h.d.get_io$$largestStoreHandle() == 8 + (i & 7), "8/8/FP store handle encoding");
    }
}

static void localAckAndDrain(const std::string &mode) {
    Harness h;
    const auto write = request(4096, true, UINT64_C(0x8877665544332211), 1);
    const auto ack = reply(0, false, false, 1);
    h.store = write; h.storeValid = true;
    auto s = h.tick();
    check(s.storeReady && !s.storeValid, "registered local ACK acceptance boundary");
    check(s.storeMemoryValid && s.storeMemory == drained(write), "independent store drain request mismatch");
    h.storeValid = false;
    for (unsigned i = 0; i < 4; ++i) {
        // Invalid source payload may change; the accepted local ACK and drain payload may not.
        h.store = request(4160 + 8 * i, false, ~write.data, 0);
        s = h.tick();
        expectStoreReply(s, ack, mode == "--corrupt-local-ack" && i == 0);
        check(s.busy && s.storeMemoryValid && s.storeMemory == drained(write),
            "held drain request changed while local ACK was held");
    }
    h.storeMemoryReady = true;
    s = h.tick();
    expectStoreReply(s, ack);
    check(s.storeMemoryValid && s.storeMemory == drained(write), "store drain acceptance lost payload");
    h.storeMemoryReady = false;
    s = h.tick();
    check(!s.storeMemoryValid && s.busy, "drain was duplicated or declared complete before response");

    if (mode == "--invalid-sb-return") {
        check(tagged, "invalid SB return requires tagged model");
        std::cerr << "INJECT_ORPHAN_SB_RETURN handle=3 expected=2\n";
        h.storeReturn = reply(0, false, false, 3);
        h.tick(); h.tick();
        throw std::runtime_error("INVALID_SB_RETURN_NOT_REJECTED");
    }
    h.storeReady = true;
    s = h.tick();
    expectStoreReply(s, ack);
    h.storeReady = false;
    s = h.tick();
    check(!s.storeValid && s.busy, "local ACK completed the external drain reservation");

    // Reuse the integer owner after its local ACK while the separate store handle is still live.
    const auto read = request(4112, false, UINT64_C(0x1029384756abcdef), 1);
    h.store = read; h.storeValid = true;
    for (unsigned i = 0; i < 3; ++i) {
        s = h.tick();
        check(!s.storeReady && s.storeMemoryValid && s.storeMemory == read,
            "independent read request changed under backpressure");
    }
    h.storeMemoryReady = true;
    s = h.tick();
    check(s.storeReady && s.storeMemoryValid && s.storeMemory == read,
        "independent read could not use released integer handle before store drain");
    h.storeValid = false; h.storeMemoryReady = false;
    const auto data = reply(UINT64_C(0xfedcba9876543210), true, true, 1);
    if (!tagged) {
        h.storeReturn = reply(UINT64_C(0x55aa55aa55aa55aa), false, false, 2);
        s = h.tick();
        check(s.storeMemoryReady && !s.storeValid, "ordered store drain leaked an upstream ACK");
        h.storeReturn.reset();
    }
    h.storeReturn = data;
    for (unsigned i = 0; i < 3; ++i) {
        s = h.tick();
        expectStoreReply(s, data);
        check(!s.storeMemoryReady && s.busy, "held read response was consumed early");
    }
    h.storeReady = true;
    s = h.tick();
    expectStoreReply(s, data);
    check(s.storeMemoryReady, "direct read return did not handshake");
    h.storeReturn.reset(); h.storeReady = false;
    if (tagged) {
        s = h.tick();
        check(s.busy && !s.storeValid, "integer read return released the outstanding store handle");
        h.storeReturn = reply(UINT64_C(0x55aa55aa55aa55aa), false, false, 2);
        s = h.tick();
        check(s.storeMemoryReady && !s.storeValid, "tagged store drain leaked a second upstream ACK");
        h.storeReturn.reset();
    }
    for (unsigned i = 0; i < 4; ++i) {
        s = h.tick();
        check(!s.busy && !s.storeValid && !s.storeMemoryValid, "final store/read boundary did not drain");
    }
}

static void forwardAndReuse() {
    Harness h;
    const auto write = request(4120, true, UINT64_C(0x0189abcdef762354), 1);
    h.store = write; h.storeValid = true; h.storeReady = true;
    auto s = h.tick();
    check(s.storeReady && !s.storeValid, "forward setup store acceptance");
    h.storeValid = false;
    expectStoreReply(h.tick(), reply(0, false, false, 1));
    const auto read = request(4120, false, 0, 0);
    h.store = read; h.storeValid = true; h.storeReady = false;
    s = h.tick();
    check(s.storeReady && s.forwarded && !s.storeValid, "real buffered read did not forward locally");
    h.storeValid = false;
    for (unsigned i = 0; i < 3; ++i) {
        s = h.tick();
        expectStoreReply(s, reply(write.data, false, false, 0));
        check(s.storeMemoryValid && s.storeMemory == drained(write), "forward replaced held drain payload");
    }
    h.storeReady = true; h.storeMemoryReady = true;
    s = h.tick();
    expectStoreReply(s, reply(write.data, false, false, 0));
    check(s.storeMemoryValid && s.storeMemory == drained(write), "forwarded store did not drain");
    h.storeMemoryReady = false;
    h.storeReturn = reply(0, false, false, 2);
    s = h.tick();
    check(s.storeMemoryReady && !s.storeValid, "forwarded store drain emitted another local response");
    h.storeReturn.reset();
    check(!h.tick().busy, "forwarded store did not become idle");

    // The sole SB slot can be allocated again only after its actual external return.
    const auto again = request(4136, true, UINT64_C(0xaa55cc339966f00f), 0);
    h.store = again; h.storeValid = true; h.storeMemoryReady = true;
    s = h.tick();
    check(s.storeReady && s.storeMemoryValid && s.storeMemory == drained(again), "drained SB handle was not reusable");
    h.storeValid = false; h.storeMemoryReady = false;
    expectStoreReply(h.tick(), reply(0, false, false, 0));
    h.storeReturn = reply(0, false, false, 2);
    s = h.tick();
    check(s.storeMemoryReady && !s.storeValid, "reused SB slot return was lost or duplicated");
    h.storeReturn.reset();
    for (unsigned i = 0; i < 4; ++i) {
        s = h.tick();
        check(!s.busy && !s.storeValid && !s.storeMemoryValid, "forward/reuse final drain mismatch");
    }
}

static void routerOrdering(const std::string &mode) {
    Harness h;
    const auto first = request(16384, false, UINT64_C(0x1234567812345678), 0);
    const auto second = request(16400, false, UINT64_C(0xabcdef1201234567), 1);
    h.routeReady = false; h.routeMemoryReady = true; h.registerReady = true;
    h.routeValid = true; h.route = first;
    auto s = h.tick();
    check(s.routeReady && s.routeMemoryValid && s.routeMemory == first, "first routed RAM request mismatch");
    h.route = second;
    s = h.tick();
    check(s.routeReady && s.routeMemoryValid && s.routeMemory == second, "second routed RAM request mismatch");
    h.routeValid = false;
    if (mode == "--invalid-router-return") {
        check(tagged, "invalid router return requires tagged model");
        std::cerr << "INJECT_ORPHAN_ROUTER_RETURN handle=3 live=0,1\n";
        h.routeReturn = reply(0, false, false, 3);
        h.tick(); h.tick();
        throw std::runtime_error("INVALID_ROUTER_RETURN_NOT_REJECTED");
    }

    auto local = request(8195, true, UINT64_C(0x12345678a5000000), 3);
    local.size = 0; local.mask = 8; local.uncached = true;
    const RegisterRequest wantedRegister{local.address, local.data >> 24, local.size, 1, true};
    const auto localRaw = reply(UINT64_C(0x8877665544), true, false, 3);
    const auto localPlaced = reply(localRaw.data << 24, true, false, 3);
    h.route = local; h.routeValid = true;
    bool localAccepted = false;
    unsigned localRequests = 0;
    auto step = [&]() {
        auto out = h.tick();
        check(!out.routeMemoryValid, "MMIO interval emitted an unexpected RAM request");
        if (out.registerValid) {
            check(h.routeValid && out.routeReady && !localAccepted && out.registers == wantedRegister,
                "independent MMIO register request payload/order mismatch");
            localAccepted = true; ++localRequests;
            h.routeValid = false;
            h.registerReturn = localRaw;
        }
        return out;
    };
    for (unsigned i = 0; i < 3; ++i) {
        s = step();
        check(!s.routeValid && !s.registerReady, "MMIO reply passed older unanswered RAM requests");
        check(tagged ? !localAccepted : localAccepted, "MMIO request did not obey the selected owner contract");
    }

    const auto a = reply(UINT64_C(0xc0decafe01234567), false, true, 0);
    const auto b = reply(UINT64_C(0xbadc0ffee00dd00d), true, false, 1);
    const Reply sequence[] = {tagged ? b : a, tagged ? a : b};
    for (unsigned n = 0; n < 2; ++n) {
        h.routeReturn = sequence[n];
        for (unsigned hold = 0; hold < 3; ++hold) {
            s = step();
            expectRouteReply(s, sequence[n], mode == "--corrupt-router-response" && n == 0 && hold == 0);
            check(!s.routeMemoryReady && !s.registerReady, "router consumed held RAM/MMIO response early");
            if (tagged) check(!localAccepted, "tagged MMIO request issued before all older RAM replies drained");
        }
        h.routeReady = true;
        s = step();
        expectRouteReply(s, sequence[n]);
        check(s.routeMemoryReady && !s.registerReady, "router RAM owner did not consume its own reply");
        h.routeReady = false; h.routeReturn.reset();
    }
    for (unsigned i = 0; i < 4 && !localAccepted; ++i) step();
    check(localAccepted && localRequests == 1, "drained MMIO request was lost or duplicated");

    const auto younger = request(16416, false, UINT64_C(0xa55aa55aa55aa55a), 0);
    for (unsigned hold = 0; hold < 3; ++hold) {
        if (tagged) { h.route = younger; h.routeValid = true; }
        s = h.tick();
        expectRouteReply(s, localPlaced);
        check(!s.registerReady && !s.routeMemoryValid, "held local owner escaped its drained interval");
        if (tagged) check(!s.routeReady, "younger RAM request entered a live ID-less MMIO interval");
    }
    h.routeReady = true;
    s = h.tick();
    expectRouteReply(s, localPlaced);
    check(s.registerReady && !s.routeMemoryValid, "MMIO owner did not consume the lane-placed reply");
    h.registerReturn.reset();
    h.route = younger; h.routeValid = true;
    s = h.tick();
    check(s.routeReady && s.routeMemoryValid && s.routeMemory == younger, "RAM did not resume after MMIO drain");
    h.routeValid = false;
    const auto final = reply(UINT64_C(0x3141592653589793), false, false, 0);
    h.routeReturn = final;
    s = h.tick();
    expectRouteReply(s, final);
    check(s.routeMemoryReady, "post-MMIO RAM response was lost");
    h.routeReturn.reset();
    for (unsigned i = 0; i < 4; ++i) {
        s = h.tick();
        check(!s.routeValid && !s.routeMemoryValid && !s.registerValid, "router final drain duplicated a request/reply");
    }
}

int main(int argc, char **argv) {
    try {
        const std::string mode = argc > 1 ? argv[1] : "";
        check(mode.empty() || mode == "--corrupt-local-ack" || mode == "--corrupt-router-response" ||
            mode == "--invalid-sb-return" || mode == "--invalid-router-return", "unknown negative mode");
        namespaces();
        localAckAndDrain(mode);
        forwardAndReuse();
        routerOrdering(mode);
        std::cout << "TAGGED_STORE_RETURN_BOUNDARY_PASS tagged=" << tagged
            << " namespace=4/2/FP,8/8/FP localAck=1 drainHandle=" << (tagged ? 2 : -1)
            << " readHandleReuse=" << tagged
            << " forwarded=1 sbSlotReuse=1 mmioDrained=" << tagged << " heldPayloads=full\n";
    } catch (const std::exception &error) {
        std::cerr << "TAGGED_STORE_RETURN_BOUNDARY_FAIL " << error.what() << "\n";
        return 1;
    }
}
