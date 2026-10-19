#include "CommonFabricScalarArbiter.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <memory>
#include <random>
#include <stdexcept>
#include <string>

static void check(bool good, const char* message) {
    if (!good) throw std::runtime_error(message);
}

// The software oracle owns the requests and actual delayed memory completions.
// It does not derive its expected owner, routing, payload, or grant from the DUT.
struct MemoryRequest {
    bool atomic = false;
    unsigned atomicOp = 0;
    uint64_t address = 0;
    bool write = false;
    unsigned size = 0;
    uint64_t data = 0;
    unsigned mask = 0;
    bool virtualized = false;
    bool precheckedLoad = false;
    uint32_t translationEpoch = 0;
    bool prefetchNextAllowed = false;
    bool uncached = false;
    bool operator==(const MemoryRequest&) const = default;
};
struct Request {
    unsigned owner = 0;
    bool clear = false, lookup = false;
    MemoryRequest memory;
    enum class Role { Ordinary, Lr, Sc } role = Role::Ordinary;
};
struct Response {
    unsigned owner = 0;
    bool clear = false;
    uint64_t data = 0;
    bool error = false, pageFault = false;
    bool operator==(const Response&) const = default;
};
struct Expected {
    unsigned lane, accepted, due;
    Request request;
    Response response;
    bool completed = false;
};

struct Driver {
    SCommonFabricScalarArbiter dut;
    // GSIM preserves this top-level Vec as per-field arrays. Keep the other
    // lane's driven value when an individual source updates its input.
    uint8_t drive$$request$$valid[2]{};
    uint8_t drive$$request$$bits$$owner[2]{};
    uint8_t drive$$request$$bits$$clearReservation[2]{};
    uint8_t drive$$request$$bits$$needsCoherenceLookup[2]{};
    uint8_t drive$$request$$bits$$memory$$atomic[2]{};
    uint8_t drive$$request$$bits$$memory$$atomicOp[2]{};
    uint64_t drive$$request$$bits$$memory$$address[2]{};
    uint8_t drive$$request$$bits$$memory$$write[2]{};
    uint8_t drive$$request$$bits$$memory$$size[2]{};
    uint64_t drive$$request$$bits$$memory$$data[2]{};
    uint8_t drive$$request$$bits$$memory$$mask[2]{};
    uint8_t drive$$request$$bits$$memory$$virtualized[2]{};
    uint8_t drive$$request$$bits$$memory$$precheckedLoad[2]{};
    uint32_t drive$$request$$bits$$memory$$translationEpoch[2]{};
    uint8_t drive$$request$$bits$$memory$$prefetchNextAllowed[2]{};
    uint8_t drive$$request$$bits$$memory$$uncached[2]{};
    uint8_t drive$$response$$ready[2]{};
    std::mt19937 random{0x57ca1a2};
    std::array<std::deque<Request>, 2> input;
    std::array<std::deque<std::shared_ptr<Expected>>, 2> expected;
    std::deque<std::shared_ptr<Expected>> physical;
    std::array<bool, 2> laneReady{true, true};
    std::array<bool, 2> heldResponse{false, false};
    std::array<Response, 2> heldResponseBits;
    std::array<unsigned, 2> laneAccepted{0, 0};
    bool memoryReady = true, randomReady = false, randomLaneReady = false;
    bool holdResponses = false, stop = false, inject = false;
    bool heldRequest = false, heldLookup = false, clearOwned = false;
    MemoryRequest heldRequestBits;
    bool reserved = false;
    uint64_t reservedAddress = 0;
    unsigned cycles = 0, delay = 7, accepted = 0, returned = 0, nativeReturned = 0;
    unsigned clearAccepted = 0, clearReturned = 0, heldRequests = 0, heldReplies = 0;
    unsigned writes = 0, writeReplies = 0, errors = 0, faults = 0, lookups = 0, noLookups = 0;
    unsigned maxOutstanding = 0, requestStreak = 0, maxRequestStreak = 0;
    unsigned responseStreak = 0, maxResponseStreak = 0, fairGrants = 0;
    int previousCompetitiveLane = -1;
    bool checkFairness = false;

    Driver() {
        dut.set_io$$stop(0);
        dut.set_io$$memory$$request$$ready(0);
        dut.set_io$$memory$$response$$valid(0);
        dut.set_io$$memory$$response$$bits$$data(0);
        dut.set_io$$memory$$response$$bits$$error(0);
        dut.set_io$$memory$$response$$bits$$pageFault(0);
        driveLane(0, Request{}, false, true);
        driveLane(1, Request{}, false, true);
        dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    }

    void driveLane(unsigned lane, const Request& r, bool valid, bool ready) {
#define SET(field, value) do { drive##field[lane] = (value); \
                              dut.set_io$$lanes##field(drive##field); } while (0)
        SET($$request$$valid, valid);
        SET($$request$$bits$$owner, r.owner);
        SET($$request$$bits$$clearReservation, r.clear);
        SET($$request$$bits$$needsCoherenceLookup, r.lookup);
        SET($$request$$bits$$memory$$atomic, r.memory.atomic);
        SET($$request$$bits$$memory$$atomicOp, r.memory.atomicOp);
        SET($$request$$bits$$memory$$address, r.memory.address);
        SET($$request$$bits$$memory$$write, r.memory.write);
        SET($$request$$bits$$memory$$size, r.memory.size);
        SET($$request$$bits$$memory$$data, r.memory.data);
        SET($$request$$bits$$memory$$mask, r.memory.mask);
        SET($$request$$bits$$memory$$virtualized, r.memory.virtualized);
        SET($$request$$bits$$memory$$precheckedLoad, r.memory.precheckedLoad);
        SET($$request$$bits$$memory$$translationEpoch, r.memory.translationEpoch);
        SET($$request$$bits$$memory$$prefetchNextAllowed, r.memory.prefetchNextAllowed);
        SET($$request$$bits$$memory$$uncached, r.memory.uncached);
        SET($$response$$ready, ready);
#undef SET
    }
    bool laneRequestReady(unsigned lane) {
        return dut.get_io$$lanes$$request$$ready()[lane];
    }
    bool laneResponseValid(unsigned lane) {
        return dut.get_io$$lanes$$response$$valid()[lane];
    }
    Response laneResponse(unsigned lane) {
#define GET(field) dut.get_io$$lanes##field()[lane]
        Response result;
        result.owner = GET($$response$$bits$$owner);
        result.clear = GET($$response$$bits$$clearReservation);
        result.data = GET($$response$$bits$$memory$$data);
        result.error = GET($$response$$bits$$memory$$error);
        result.pageFault = GET($$response$$bits$$memory$$pageFault);
#undef GET
        return result;
    }
    MemoryRequest memoryRequest() {
        MemoryRequest r;
#define READ(field) r.field = dut.get_io$$memory$$request$$bits$$##field()
        READ(atomic); READ(atomicOp); READ(address); READ(write); READ(size); READ(data); READ(mask);
        READ(virtualized); READ(precheckedLoad); READ(translationEpoch); READ(prefetchNextAllowed); READ(uncached);
#undef READ
        return r;
    }
    Response responseFor(const Request& r) const {
        Response reply{r.owner, r.clear, 0, false, false};
        if (r.clear) return reply;
        // Nonzero write response data makes a fabricated zero enqueue ack visible.
        reply.data = r.memory.data ^ (r.memory.address * UINT64_C(0x9e3779b97f4a7c15)) ^
                     (uint64_t(r.memory.translationEpoch) << 23) ^ UINT64_C(0xd15ea5e012345678);
        reply.error = (r.memory.address & 0x78) == 0x18;
        reply.pageFault = (r.memory.address & 0x78) == 0x50;
        if (r.role == Request::Role::Lr) {
            reply.data = UINT64_C(0xfedcba9876543210);
            reply.error = reply.pageFault = false;
        } else if (r.role == Request::Role::Sc) {
            reply.data = reserved && reservedAddress == r.memory.address ? 0 : 1;
            reply.error = reply.pageFault = false;
            check(reply.data == 1, "SC observed an uncleared LR reservation");
        }
        return reply;
    }

    void tick() {
        check(cycles < 12000, "bounded scalar completion failure");
        const unsigned ownersBefore = unsigned(expected[0].size() + expected[1].size());
        const bool ready = memoryReady && (!randomReady || random() % 4 != 0);
        std::array<bool, 2> responseReady;
        for (unsigned lane = 0; lane < 2; ++lane) {
            responseReady[lane] = laneReady[lane] && (!randomLaneReady || random() % 3 != 0);
            driveLane(lane, input[lane].empty() ? Request{} : input[lane].front(),
                      !input[lane].empty(), responseReady[lane]);
        }
        const auto pending = physical.empty() ? nullptr : physical.front();
        const bool reply = !holdResponses && pending && pending->due <= cycles;
        dut.set_io$$stop(stop);
        dut.set_io$$memory$$request$$ready(ready);
        dut.set_io$$memory$$response$$valid(reply);
        dut.set_io$$memory$$response$$bits$$data(reply ? pending->response.data : 0);
        dut.set_io$$memory$$response$$bits$$error(reply && pending->response.error);
        dut.set_io$$memory$$response$$bits$$pageFault(reply && pending->response.pageFault);
        dut.step();

        check(dut.get_io$$outstanding() == ownersBefore, "scalar outstanding-owner count mismatch");
        const bool memoryValid = dut.get_io$$memory$$request$$valid();
        const bool memoryFire = memoryValid && ready;
        const auto offered = memoryRequest();
        const bool lookup = dut.get_io$$needsCoherenceLookup();
        const bool clearPulse = dut.get_io$$clearReservation();
        const bool wasHeld = heldRequest;
        const bool wasClearOwned = clearOwned;
        if (heldRequest) {
            check(memoryValid && offered == heldRequestBits && lookup == heldLookup,
                  "held native request or coherence lookup changed");
        }
        if (stop && !wasHeld) check(!memoryValid, "stop selected a new native request");
        if (wasClearOwned) check(!memoryValid && !clearPulse, "native request passed held clear completion");
        heldRequest = memoryValid && !ready;
        heldRequestBits = offered;
        heldLookup = lookup;
        heldRequests += heldRequest;
        if (heldRequest || !physical.empty() || clearOwned ||
            !expected[0].empty() || !expected[1].empty()) {
            check(!dut.get_io$$idle(), "idle dropped an outstanding owner or held offer");
        }

        // A real memory completion precedes the corresponding CPU consumption.
        // Direct routing may perform both handshakes in this same cycle.
        const bool nativeResponseFire = reply && dut.get_io$$memory$$response$$ready();
        if (nativeResponseFire) {
            pending->completed = true;
            if (pending->request.role == Request::Role::Lr) {
                reserved = true;
                reservedAddress = pending->request.memory.address;
            }
            physical.pop_front();
            ++nativeReturned;
        }
        unsigned scalarResponses = 0;
        for (unsigned lane = 0; lane < 2; ++lane) {
            const bool valid = laneResponseValid(lane);
            const auto actual = laneResponse(lane);
            if (heldResponse[lane]) check(valid && actual == heldResponseBits[lane], "held tagged response changed");
            heldResponse[lane] = valid && !responseReady[lane];
            heldResponseBits[lane] = actual;
            heldReplies += heldResponse[lane];
            if (!valid) continue;
            check(!expected[lane].empty(), "scalar response has no accepted lane owner");
            const auto owner = expected[lane].front();
            const bool realOffer = reply && pending == owner;
            check(owner->completed || realOffer, "scalar write/read response acknowledged before real memory response");
            if (owner->request.clear) check(cycles > owner->accepted, "clear completion was not registered");
            auto wanted = owner->response;
            if (inject && !wanted.clear) wanted.owner ^= 1;
            check(actual == wanted, "SCALAR lane/owner/payload oracle mismatch");
            if (!responseReady[lane]) continue;
            check(owner->completed, "scalar response consumed before real memory completion handshake");
            if (owner->request.clear) {
                check(clearOwned, "clear response has no retained clear owner");
                clearOwned = false;
                ++clearReturned;
            } else {
                ++returned;
                writeReplies += owner->request.memory.write;
                errors += actual.error;
                faults += actual.pageFault;
                ++scalarResponses;
            }
            expected[lane].pop_front();
        }
        check(scalarResponses <= 1, "two scalar lanes consumed one native response");
        if (scalarResponses) maxResponseStreak = std::max(maxResponseStreak, ++responseStreak);
        else responseStreak = 0;

        int selected = -1;
        const bool both = !input[0].empty() && !input[1].empty();
        for (unsigned lane = 0; lane < 2; ++lane) {
            if (input[lane].empty() || !laneRequestReady(lane)) continue;
            check(selected == -1, "both scalar lanes accepted one native slot");
            selected = int(lane);
        }
        check((selected >= 0) == (memoryFire || clearPulse), "scalar/native acceptance conservation failure");
        check(!(memoryFire && clearPulse), "clear event reached native memory");
        if (selected >= 0) {
            const unsigned lane = unsigned(selected);
            const Request r = input[lane].front();
            check(r.clear == clearPulse, "clear request/pulse kind mismatch");
            check(!stop || wasHeld, "stop accepted a new unheld scalar request");
            if (r.clear) {
                check(!wasClearOwned && physical.empty() && expected[0].empty() && expected[1].empty(),
                      "clear overtook older real completion from either scalar lane");
                check(!memoryValid, "clear reservation event escaped to native memory");
                reserved = false;
                clearOwned = true;
                ++clearAccepted;
            } else {
                check(memoryFire && offered == r.memory && lookup == r.lookup,
                      "native request/lookup field preservation mismatch");
                ++accepted;
                ++laneAccepted[lane];
                writes += r.memory.write;
                lookups += r.lookup;
                noLookups += !r.lookup;
            }
            auto owner = std::make_shared<Expected>(Expected{lane, cycles,
                cycles + delay + (randomReady ? unsigned(random() % 11) : 0U), r, responseFor(r), r.clear});
            expected[lane].push_back(owner);
            if (!r.clear) physical.push_back(owner);
            input[lane].pop_front();
            if (checkFairness && both && !r.clear) {
                check(previousCompetitiveLane != selected, "continuously offered scalar lane starved");
                previousCompetitiveLane = selected;
                ++fairGrants;
            } else previousCompetitiveLane = -1;
        } else if (!both) previousCompetitiveLane = -1;
        if (memoryFire) maxRequestStreak = std::max(maxRequestStreak, ++requestStreak);
        else requestStreak = 0;
        maxOutstanding = std::max(maxOutstanding, unsigned(physical.size()));
        check(physical.size() <= 16, "native owner capacity exceeded");
        ++cycles;
    }

    void idle(unsigned n) { while (n--) tick(); }
    void drain() {
        while (!input[0].empty() || !input[1].empty() || !expected[0].empty() ||
               !expected[1].empty() || !physical.empty() || clearOwned) tick();
        idle(2);
        check(dut.get_io$$idle() && dut.get_io$$outstanding() == 0,
              "scalar fabric did not become idle after all real responses");
    }
    static Request request(unsigned serial, unsigned lane) {
        Request r;
        // Deliberately nonsequential four-bit owners, independent per lane.
        r.owner = (serial * 7 + lane * 3 + 11) & 15;
        r.lookup = (serial + lane) % 3 != 0;
        r.memory.atomic = serial % 9 == 4;
        r.memory.atomicOp = (serial * 5 + lane) & 31;
        r.memory.address = UINT64_C(0x80010000) + uint64_t(serial * 2 + lane) * 8;
        r.memory.write = serial % 3 == 1;
        r.memory.size = serial & 3;
        r.memory.data = UINT64_C(0x12345678acdef000) ^ (uint64_t(serial) << 35) ^ (lane * 0x7a31);
        r.memory.mask = (serial * 19 + lane * 71 + 1) & 255;
        r.memory.virtualized = false; // The shared boundary accepts only physical requests.
        r.memory.precheckedLoad = serial & 1;
        r.memory.translationEpoch = UINT32_C(0x87650000) ^ serial * 9871 ^ lane;
        r.memory.prefetchNextAllowed = serial & 2;
        r.memory.uncached = serial & 4;
        return r;
    }

    void clearBarrier(unsigned clearLane) {
        const unsigned lrLane = 1 - clearLane;
        randomReady = randomLaneReady = false;
        holdResponses = true;
        delay = 21;
        Request lr = request(700 + clearLane, lrLane);
        lr.owner = clearLane ? 4 : 13;
        lr.role = Request::Role::Lr;
        lr.memory.atomic = true; lr.memory.atomicOp = 2;
        lr.memory.write = false; lr.memory.size = 3; lr.memory.mask = 255;
        lr.memory.address = UINT64_C(0x80018000) + clearLane * 64;
        Request oldWrite = request(800 + clearLane, clearLane);
        oldWrite.memory.write = true;
        const unsigned before = accepted, beforeClear = clearAccepted, beforeReturned = returned;
        input[lrLane].push_back(lr);
        input[clearLane].push_back(oldWrite);
        while (accepted != before + 2) tick();
        Request clear;
        clear.clear = true; clear.owner = clearLane ? 14 : 5; clear.lookup = true;
        Request sc = lr;
        sc.owner = clearLane ? 2 : 10;
        sc.role = Request::Role::Sc;
        sc.memory.atomicOp = 3; sc.memory.write = true;
        input[clearLane].push_back(clear);
        input[clearLane].push_back(sc);
        idle(9);
        check(clearAccepted == beforeClear && accepted == before + 2 && returned == beforeReturned,
              "clear or SC passed a delayed older LR/write response");
        holdResponses = false;
        while (clearAccepted == beforeClear) tick();
        check(returned == beforeReturned + 2 && !reserved,
              "cross-lane reservation clear preceded real older responses");
        // Both lanes have newer requests, but the tagged clear response is held.
        laneReady[clearLane] = false;
        input[lrLane].push_back(request(900 + clearLane, lrLane));
        const unsigned blockedAt = accepted;
        idle(8);
        check(clearOwned && accepted == blockedAt && heldResponse[clearLane],
              "clear completion did not block younger native requests");
        laneReady[clearLane] = true;
        delay = 2;
        drain();
        check(clearReturned == beforeClear + 1, "clear completion was lost or repeated");
    }

    void run() {
        idle(3);
        check(dut.get_io$$idle(), "reset did not produce an idle scalar fabric");
        // stop blocks selection, but a native offer already visible must finish.
        stop = true;
        input[0].push_back(request(0, 0));
        input[1].push_back(request(0, 1));
        idle(5);
        check(accepted == 0, "stop accepted initial traffic");
        stop = false; memoryReady = false;
        tick();
        check(heldRequest, "held native request scenario did not create an offer");
        stop = true;
        idle(5);
        memoryReady = true;
        tick();
        check(accepted == 1, "stop discarded a previously locked native offer");
        idle(15);
        check(accepted == 1 && returned == 1, "stop did not drain only the preexisting locked owner");
        stop = false;
        drain();

        // Fill all 16 physical-response owners while withholding every response.
        // Continuous contenders must alternate and accept one request per cycle.
        checkFairness = true;
        holdResponses = true; delay = 3;
        const unsigned before = accepted;
        const auto beforeLane = laneAccepted;
        for (unsigned n = 1; n <= 40; ++n) {
            input[0].push_back(request(n, 0));
            input[1].push_back(request(n, 1));
        }
        idle(24);
        check(accepted == before + 16 && physical.size() == 16 && dut.get_io$$outstanding() == 16,
              "fabric lost sixteen concurrent real-response owners");
        check(laneAccepted[0] == beforeLane[0] + 8 && laneAccepted[1] == beforeLane[1] + 8,
              "fair scalar arbitration did not occupy both lanes");
        holdResponses = false;
        drain();
        check(maxRequestStreak >= 16 && maxResponseStreak >= 16,
              "scalar arbiter lost no-stall request/response II=1");
        checkFairness = false;

        // Reproducible independent delays and backpressure stress data, all metadata,
        // real write acks, error/page-fault propagation, owners, and held offers.
        randomReady = randomLaneReady = true;
        delay = 1;
        for (unsigned n = 100; n < 164; ++n) {
            input[0].push_back(request(n, 0));
            input[1].push_back(request(n, 1));
        }
        drain();
        clearBarrier(0);
        clearBarrier(1);
        check(accepted == returned && accepted == nativeReturned && writes == writeReplies,
              "final scalar real-response ledger mismatch");
        check(clearAccepted == 2 && clearReturned == 2 && maxOutstanding == 16 &&
              heldRequests > 0 && heldReplies > 0 && errors > 0 && faults > 0 &&
              lookups > 0 && noLookups > 0 && fairGrants >= 64,
              "scalar scenario coverage incomplete");
        std::cout << "COMMON_FABRIC_SCALAR_PASS cycles=" << cycles
                  << " native=" << accepted << " native_responses=" << nativeReturned
                  << " scalar_responses=" << returned << " writes=" << writes
                  << " write_responses=" << writeReplies << " clear=" << clearAccepted
                  << " clear_responses=" << clearReturned << " max_outstanding=" << maxOutstanding
                  << " request_ii1=" << maxRequestStreak << " response_ii1=" << maxResponseStreak
                  << " held_req=" << heldRequests << " held_rsp=" << heldReplies
                  << " fairness=" << fairGrants << " errors=" << errors << " faults=" << faults
                  << " lookup=" << lookups << " no_lookup=" << noLookups << "\n";
    }
};

int main(int argc, char** argv) {
    try {
        check(argc == 1 || (argc == 2 && std::string(argv[1]) == "--inject-mismatch"), "unknown argument");
        Driver driver;
        driver.inject = argc == 2;
        driver.run();
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << "\n";
        return 1;
    }
}
