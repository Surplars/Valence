#include "FetchTokenReadyCaptureGsim.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>
#include <vector>

static void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}
struct Word { uint32_t bits; bool access, page; unsigned faultOffset; };
struct Retained { uint32_t bits; bool access, page; uint64_t pc, next, fault; };
static unsigned length(uint32_t bits) { return (bits & 3) == 3 ? 4 : 2; }
// Independent ISA bit assembly, no DUT split-adder/lookup implementation.
static int64_t jumpOffset(uint32_t bits) {
    uint32_t value = ((bits >> 31) & 1) << 20 | ((bits >> 12) & 255) << 12 |
        ((bits >> 20) & 1) << 11 | ((bits >> 21) & 1023) << 1;
    return int64_t(value) - ((value & (1U << 20)) ? (1LL << 21) : 0);
}
static int64_t compressedJumpOffset(uint32_t bits) {
    const unsigned value = ((bits >> 12) & 1) << 11 | ((bits >> 11) & 1) << 4 |
        ((bits >> 9) & 3) << 8 | ((bits >> 8) & 1) << 10 | ((bits >> 7) & 1) << 6 |
        ((bits >> 6) & 1) << 7 | ((bits >> 3) & 7) << 1 | ((bits >> 2) & 1) << 5;
    return int64_t(value) - ((value & 0x800) ? 4096 : 0);
}
struct Oracle {
    SFetchTokenReadyCaptureGsim dut;
    std::deque<Retained> queue;
    std::vector<Word> token;
    uint64_t tokenPc = 0, pc = 0x80000000ULL;
    unsigned tokenDenied = 0;
    bool inject = false;
    uint64_t checks = 0, held = 0, refill = 0, emptyPoison = 0, cancelled = 0;
    uint64_t correction = 0, denied = 0, pageFault = 0, wrong = 0, wraps = 0, compressedCorrections = 0;
    uint64_t refillCorrection=0, refillCancel=0, heldCancel=0, correctionCancel=0, flushMismatch=0;
    void reset() {
        dut.set_io$$present(0); dut.set_io$$instruction0(0); dut.set_io$$instruction1(0);
        dut.set_io$$access(0); dut.set_io$$page(0); dut.set_io$$denied(0);
        dut.set_io$$faultOffset0(0); dut.set_io$$faultOffset1(0);
        dut.set_io$$pause(0); dut.set_io$$consumed(0); dut.set_io$$flush(0);
        dut.set_io$$flushTarget(0); dut.set_io$$expected(0); dut.set_io$$invalidate(0);
        dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
        queue.clear(); token.clear(); pc = 0x80000000ULL;
    }
    Retained read(unsigned lane) {
#define READ(n) case n: return {uint32_t(dut.get_io$$out##n##$$bits$$instruction()), \
        bool(dut.get_io$$out##n##$$bits$$accessFault()), bool(dut.get_io$$out##n##$$bits$$pageFault()), \
        dut.get_io$$out##n##$$bits$$pc(), dut.get_io$$out##n##$$bits$$nextPc(), \
        dut.get_io$$out##n##$$bits$$faultAddress()}
        switch (lane) { READ(0); READ(1); default: throw std::runtime_error("bad lane"); }
#undef READ
    }
    void step(unsigned present, std::array<Word,2> supply, unsigned permission,
              unsigned consume, bool pause, bool flush, uint64_t target, bool mismatch, bool invalidate) {
        require(consume <= std::min<size_t>(2, queue.size()), "host over-consume");
        const uint64_t observed = queue.size() > consume ? queue[consume].pc :
            !token.empty() ? tokenPc : pc;
        const uint64_t expected = mismatch ? observed ^ 16 : observed;
        const bool wrongPath = consume && observed != expected;
        const bool cancel = flush || wrongPath;
        const bool transfer = !token.empty() && !pause && queue.size() + token.size() <= 4;
        const bool ready = token.empty() || transfer;
        const unsigned scan = !pause && ready && (present & 1) ? (present & 2 ? 2 : 1) : 0;
        std::vector<Retained> captured;
        bool rawCorrection = false, priorFault = false;
        uint64_t current = tokenPc;
        unsigned offset = 0;
        if (transfer) for (const auto& word : token) {
            const unsigned bytes = length(word.bits);
            const bool firstDenied = tokenDenied >> (offset / 2) & 1;
            const bool secondDenied = bytes == 4 && (tokenDenied >> (offset / 2 + 1) & 1);
            const bool permissionDenied = firstDenied || secondDenied;
            const bool access = word.access || permissionDenied;
            const bool fault = access || word.page;
            uint64_t faultAddress = (tokenPc & ~uint64_t(7)) + word.faultOffset;
            if (permissionDenied && !word.access && !word.page)
                faultAddress = current + (firstDenied ? 0 : 2);
            const bool jump = bytes == 4 && (word.bits & 127) == 0x6f;
            const bool cjump = bytes == 2 && (word.bits & 0xe003) == 0xa001;
            const int64_t delta = jump ? jumpOffset(word.bits) : cjump ? compressedJumpOffset(word.bits) : 0;
            const uint64_t destination = current + uint64_t(delta);
            const bool taken = (jump || cjump) && !fault && !priorFault && !(destination & 1) && delta != int64_t(bytes);
            const uint64_t next = taken ? destination : current + bytes;
            captured.push_back({word.bits, access, word.page, current, next, faultAddress});
            denied += permissionDenied; pageFault += word.page;
            priorFault |= fault; current += bytes; offset += bytes;
            compressedCorrections += taken && cjump;
            if (taken) { rawCorrection = true; break; }
        }
        uint64_t scanNext = pc;
        for (unsigned lane = 0; lane < scan; ++lane) scanNext += length(supply[lane].bits);
        const uint64_t nextPc = cancel ? (flush ? target : expected) :
            rawCorrection ? captured.back().next : scanNext;
        const unsigned capturedMask = cancel ? 0 : (1U << captured.size()) - 1;
        const unsigned acceptedMask = cancel || rawCorrection ? 0 : (1U << scan) - 1;
        dut.set_io$$present(present); dut.set_io$$instruction0(supply[0].bits);
        dut.set_io$$instruction1(supply[1].bits);
        dut.set_io$$access(unsigned(supply[0].access) | unsigned(supply[1].access) << 1);
        dut.set_io$$page(unsigned(supply[0].page) | unsigned(supply[1].page) << 1);
        dut.set_io$$denied(permission); dut.set_io$$faultOffset0(supply[0].faultOffset);
        dut.set_io$$faultOffset1(supply[1].faultOffset); dut.set_io$$consumed(consume);
        dut.set_io$$pause(pause); dut.set_io$$flush(flush); dut.set_io$$flushTarget(target);
        dut.set_io$$expected(expected); dut.set_io$$invalidate(invalidate); dut.step();
        require(dut.get_io$$pc() == pc && dut.get_io$$nextPc() == nextPc,
            "token independent cursor oracle mismatch");
        require(dut.get_io$$occupancy() == queue.size(), "token independent occupancy oracle mismatch");
        require(bool(dut.get_io$$out0$$valid()) == !queue.empty() &&
            bool(dut.get_io$$out1$$valid()) == (queue.size() > 1), "token independent output validity mismatch");
        for (unsigned lane = 0; lane < std::min<size_t>(2, queue.size()); ++lane) {
            auto actual = read(lane); const auto& want = queue[lane];
            if (inject && checks > 10 && lane == 0) actual.bits ^= 1;
            require(actual.bits == want.bits && actual.access == want.access && actual.page == want.page &&
                actual.pc == want.pc && actual.next == want.next && actual.fault == want.fault,
                "token independent instruction/permission oracle mismatch");
        }
        require(dut.get_io$$captured() == capturedMask && dut.get_io$$accepted() == acceptedMask &&
            bool(dut.get_io$$transferred()) == (transfer && !cancel) &&
            bool(dut.get_io$$suppress()) == (cancel || rawCorrection), "token independent authority oracle mismatch");
        require(bool(dut.get_io$$tokenValid()) == !token.empty() &&
            dut.get_io$$tokenPresent() == (1U << token.size()) - 1 &&
            dut.get_io$$frontier() == (token.empty() ? pc : tokenPc), "token independent lifecycle oracle mismatch");
        if (!token.empty()) require(dut.get_io$$tokenPc() == tokenPc, "token independent live PC mismatch");
        refillCorrection += transfer && scan && rawCorrection; refillCancel += transfer && scan && cancel;
        heldCancel += !token.empty() && !transfer && cancel; correctionCancel += rawCorrection && cancel;
        flushMismatch += flush && wrongPath;
        held += !token.empty() && !transfer; refill += transfer && scan;
        emptyPoison += ready && !(present & 1); cancelled += cancel; correction += rawCorrection;
        wrong += wrongPath; wraps += nextPc < pc;
        for (unsigned n = 0; n < consume; ++n) queue.pop_front();
        for (const auto& value : captured) queue.push_back(value);
        if (cancel) queue.clear();
        if (transfer) token.clear();
        if (scan) { token.assign(supply.begin(), supply.begin() + scan); tokenPc = pc; tokenDenied = permission; }
        if (cancel || rawCorrection) token.clear();
        pc = nextPc; ++checks;
    }
};
int main(int argc, char** argv) { try {
    Oracle model; model.inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
    require(argc == 1 || model.inject, "unknown token test argument"); model.reset();
    std::array<Word,2> ordinary{{{0x00000013, false, false, 0}, {0x0001, false, false, 4}}};
    // Fill both stages, hold a live token while input payload is poison, then
    // drain with no new offer. The final token must remain exactly its owner.
    for (unsigned n = 0; n < 12; ++n) model.step(3, ordinary, 0, 0, false, false, 0, false, false);
    for (unsigned n = 0; n < 8; ++n)
        model.step(0, {{{0x0080006f,true,true,31},{0xffffffff,true,true,30}}}, 15, 0,
            n & 1, false, 0, false, false);
    for (unsigned n = 0; n < 8; ++n) model.step(0, ordinary, 0,
        std::min<size_t>(2, model.queue.size()), false, false, 0, false, false);
    std::mt19937_64 random(0x746f6b656e6365ULL);
    for (unsigned n = 0; n < 40000; ++n) {
        std::array<Word,2> supply{};
        for (auto& word : supply) {
            const unsigned kind = random() % 8;
            word.bits = kind == 0 ? 0x0080006f : kind == 1 ? 0xffdff06f : kind == 2 ? 0xa021 : kind == 3 ? 0xbff5 : kind == 4 ? 0x2001 : kind & 1 ? 0x0001 : 0x00100093;
            word.access = random() % 19 == 0; word.page = random() % 23 == 0;
            word.faultOffset = random() % 16;
        }
        unsigned present = random() & 3;
        if (!(present & 1)) { supply[0].bits = uint32_t(random()); supply[1].bits = uint32_t(random()); }
        unsigned consume = random() % (std::min<size_t>(2, model.queue.size()) + 1);
        const bool flush = n % 173 == 0;
        const uint64_t target = n % 3 == 0 ? UINT64_MAX - 1 : n % 3 == 1 ? 0x1ffffe : 0x80000006ULL;
        model.step(present, supply, random() % 7 == 0 ? random() & 15 : 0,
            consume, n % 17 == 0, flush, target, n % 37 == 0, n % 13 == 0);
    }
    require(model.held && model.refill && model.emptyPoison && model.cancelled && model.correction &&
        model.compressedCorrections && model.denied && model.pageFault && model.wrong && model.wraps, "token short coverage missing");
    require(model.refillCorrection && model.refillCancel && model.heldCancel && model.correctionCancel && model.flushMismatch,
        "token same-edge priority coverage missing");
    std::cout << "PASS_FETCH_TOKEN_READY checks=" << model.checks << " held=" << model.held
        << " refill=" << model.refill << " invalidPoison=" << model.emptyPoison << " cancelled=" << model.cancelled
        << " rawCorrections=" << model.correction << " compressedCorrections=" << model.compressedCorrections << " permissionDenied=" << model.denied
        << " refillCorrection=" << model.refillCorrection << " refillCancel=" << model.refillCancel
        << " heldCancel=" << model.heldCancel << " correctionCancel=" << model.correctionCancel
        << " flushMismatch=" << model.flushMismatch << " pageFaults=" << model.pageFault << " wrongPath=" << model.wrong << " wraps=" << model.wraps << '\n';
    return 0;
} catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; } }
