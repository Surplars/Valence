#include "FiveStageAtomicMemory.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <map>
#include <optional>
#include <random>
#include <stdexcept>
#include <string>
#ifndef DUT_XLEN
#define DUT_XLEN 64
#endif
static constexpr unsigned WORD = DUT_XLEN / 8;
static constexpr uint64_t BASE = 0x80000000, FIT = DUT_XLEN == 64 ? UINT64_MAX : UINT32_MAX;
static void need(bool ok, const char *s) { if (!ok) throw std::runtime_error(s); }
static uint64_t amo(unsigned op, uint64_t a, uint64_t b, unsigned size) {
    uint64_t mask = size == 2 ? UINT32_MAX : UINT64_MAX; a &= mask; b &= mask;
    int64_t sa = size == 2 ? int64_t(int32_t(a)) : int64_t(a);
    int64_t sb = size == 2 ? int64_t(int32_t(b)) : int64_t(b);
    switch (op) {
        case 0: return (a+b) & mask; case 1: return b; case 4: return a^b;
        case 8: return a|b; case 12: return a&b;
        case 16: return sa < sb ? a : b; case 20: return sa < sb ? b : a;
        case 24: return a < b ? a : b; case 28: return a < b ? b : a;
    }
    throw std::runtime_error("independent AMO operation oracle");
}
struct Test {
    SFiveStageAtomicMemory d;
    std::map<uint64_t,uint8_t> bytes;
    struct Pending { uint64_t address, data, due, value; unsigned mask; bool write, error; };
    std::optional<Pending> pending;
    std::optional<std::array<uint64_t,7>> held;
    std::optional<std::array<uint64_t,3>> heldResponse;
    uint64_t cycle = 0, cases = 0, reads = 0, writes = 0;
    std::mt19937_64 random{0x41544f4d};
    bool reserved = false; uint64_t reservation = 0; unsigned reservedSize = 0;
    bool injectRead = false, injectWrite = false, sideEffectOnError = false;
    Test() {
        for (unsigned i = 0; i < 16384; ++i) bytes[BASE+i] = i*29+7;
        d.set_reset(1); d.set_io$$request$$valid(0); d.set_io$$response$$ready(0);
        d.set_io$$memoryRequest$$ready(0); d.set_io$$memoryResponse$$valid(0);
        d.set_io$$invalidateReservation(0); d.step(); d.step(); d.set_reset(0);
    }
    uint64_t load(uint64_t address) {
        address &= ~(WORD-1ULL); uint64_t value = 0;
        for (unsigned i = 0; i < WORD; ++i) value |= uint64_t(bytes[address+i]) << (8*i);
        return value;
    }
    void step(bool ready, bool invalidate = false) {
        bool mr = !pending && cycle % 4 != 1;
        bool mv = pending && cycle >= pending->due;
        d.set_io$$response$$ready(ready); d.set_io$$invalidateReservation(invalidate);
        d.set_io$$memoryRequest$$ready(mr); d.set_io$$memoryResponse$$valid(mv);
        d.set_io$$memoryResponse$$bits$$data(pending ? pending->value : 0);
        d.set_io$$memoryResponse$$bits$$error(pending && pending->error);
        d.set_io$$memoryResponse$$bits$$pageFault(0); d.set_io$$memoryResponse$$bits$$fetchSpan(0);
        d.step(); ++cycle;
        std::array<uint64_t,7> req{d.get_io$$memoryRequest$$bits$$address(),
            d.get_io$$memoryRequest$$bits$$write(), d.get_io$$memoryRequest$$bits$$data(),
            d.get_io$$memoryRequest$$bits$$mask(), d.get_io$$memoryRequest$$bits$$size(),
            d.get_io$$memoryRequest$$bits$$atomic(), d.get_io$$memoryRequest$$bits$$noAllocate()};
        if (held) need(d.get_io$$memoryRequest$$valid() && req == *held, "atomic memory offer changed under stalls");
        held.reset(); if (d.get_io$$memoryRequest$$valid() && !mr) held = req;
        std::array<uint64_t,3> rsp{d.get_io$$response$$bits$$data(),d.get_io$$response$$bits$$error(),
            d.get_io$$response$$bits$$pageFault()};
        if (heldResponse) need(d.get_io$$response$$valid() && rsp == *heldResponse, "atomic reply changed under stalls");
        heldResponse.reset(); if (d.get_io$$response$$valid() && !ready) heldResponse = rsp;
        if (mv && d.get_io$$memoryResponse$$ready()) {
            if (pending->write && (!pending->error || sideEffectOnError)) {
                auto at = pending->address & ~(WORD-1ULL);
                for (unsigned i = 0; i < WORD; ++i) if (pending->mask >> i & 1) bytes[at+i] = pending->data >> (8*i);
            }
            pending.reset();
        }
        if (mr && d.get_io$$memoryRequest$$valid()) {
            need(!pending && !req[5], "atomic memory owner duplication/raw A escaped");
            pending = Pending{req[0],req[2],cycle+2+random()%9,load(req[0]),unsigned(req[3]),bool(req[1]),
                req[1] ? injectWrite : injectRead};
            if (req[1]) ++writes; else ++reads;
        }
    }
    void invalidate() { d.set_io$$request$$valid(0); step(false,true); reserved = false; }
    void transact(uint64_t address, unsigned op, uint64_t operand, unsigned size = 2,
                  bool atomic = true, bool normalWrite = false, bool killRead = false, bool mutate = false) {
        uint64_t at = address & ~(WORD-1ULL), old = load(address), expectedWord = old;
        unsigned offset = address % WORD, count = 1U << size;
        uint64_t mask = count == 8 ? UINT64_MAX : (1ULL << (8*count))-1;
        unsigned lanes = ((1U << count)-1) << offset;
        uint64_t inputData = (operand << (8*offset)) & FIT;
        bool legal = address >= BASE && address+count <= BASE+0x10000000ULL &&
            (size == 2 || DUT_XLEN == 64 && size == 3) && !(address & (count-1)) &&
            (op == 0 || op == 1 || op == 2 || op == 3 || op == 4 || op == 8 || op == 12 ||
             op == 16 || op == 20 || op == 24 || op == 28);
        bool success = reserved && reservation == address && reservedSize == size;
        bool error = atomic && !legal;
        uint64_t result = old; unsigned expectedReads = 0, expectedWrites = 0;
        if (!atomic) {
            expectedWrites = normalWrite; expectedReads = !normalWrite;
            error = normalWrite ? injectWrite : injectRead;
            if (normalWrite && (!error || sideEffectOnError))
                expectedWord = (old & ~(mask << (8*offset))) | (inputData & (mask << (8*offset)));
        } else if (legal) {
            if (op == 3) {
                result = success ? 0 : 1;
                if (success) {
                    expectedWrites = 1; error = injectWrite;
                    if (!error || sideEffectOnError) expectedWord = (old & ~(mask << (8*offset))) |
                        (inputData & (mask << (8*offset)));
                }
            } else {
                expectedReads = 1; error = injectRead;
                if (op != 2 && !error) {
                    expectedWrites = 1; error = injectWrite;
                    auto value = amo(op, old >> (8*offset), operand, size);
                    if (!error || sideEffectOnError) expectedWord = (old & ~(mask << (8*offset))) |
                        ((value & mask) << (8*offset));
                }
            }
        }
        if (atomic && (op == 2 || op == 3)) reserved = false;
        if ((atomic && op != 2 || normalWrite) && reservation / WORD == address / WORD) reserved = false;
        uint64_t beforeRead = reads, beforeWrite = writes;
        d.set_io$$request$$bits$$address(address); d.set_io$$request$$bits$$size(size);
        d.set_io$$request$$bits$$write(atomic ? op != 2 : normalWrite);
        d.set_io$$request$$bits$$data(inputData); d.set_io$$request$$bits$$mask(lanes);
        d.set_io$$request$$bits$$atomic(atomic); d.set_io$$request$$bits$$atomicOperation(op);
        d.set_io$$request$$bits$$noAllocate(0);
        bool accepted = false, killed = false; unsigned stalls = 0;
        for (unsigned n = 0; n < 500; ++n) {
            d.set_io$$request$$valid(!accepted);
            bool ready = stalls >= 6 && cycle % 3 == 0;
            bool inv = accepted && killRead && !killed && bool(pending);
            step(ready,inv); killed |= inv; if (inv) reserved = false;
            if (!accepted && d.get_io$$request$$ready()) accepted = true;
            if (d.get_io$$response$$valid()) {
                ++stalls; if (!ready) continue;
                if (mutate) result ^= 1;
                need(bool(d.get_io$$response$$bits$$error()) == error &&
                    (!error || !d.get_io$$response$$bits$$pageFault()), "independent atomic error oracle");
                if (!error) need(d.get_io$$response$$bits$$data() == (result & FIT), "independent LR_SC_AMO result oracle");
                need(load(at) == (expectedWord & FIT) && reads-beforeRead == expectedReads &&
                    writes-beforeWrite == expectedWrites, "independent atomic byte/owner/order oracle");
                if (atomic && op == 2 && !error && !killed) {
                    reserved = true; reservation = address; reservedSize = size;
                }
                d.set_io$$request$$valid(0); ++cases; return;
            }
        }
        throw std::runtime_error("atomic bounded completion failed");
    }
};
int main(int argc,char **argv) { try {
    Test t; bool mutate = argc>1 && std::string(argv[1])=="--wrong-amo";
    t.transact(BASE,1,0x80000001,2,true,false,false,mutate);
    for (unsigned size : {2U,3U}) {
        if (size==3 && DUT_XLEN==32) continue;
        unsigned offset = size==2 && WORD==8 ? 4 : 0;
        t.transact(BASE+offset,2,0,size); t.transact(BASE+offset,3,0xf00d,size);
        t.transact(BASE+offset,3,0xbeef,size);
        t.transact(BASE+offset,2,0,size); t.transact(BASE+WORD,1,55,size);
        t.transact(BASE+offset,3,66,size);
        t.transact(BASE+offset,2,0,size); t.transact(BASE+offset,0,1,size);
        t.transact(BASE+offset,3,88,size);
        t.transact(BASE+offset,2,0,size); t.invalidate(); t.transact(BASE+offset,3,99,size);
        t.transact(BASE+offset,2,0,size,true,false,true); t.transact(BASE+offset,3,99,size);
        for (unsigned op : {0U,1U,4U,8U,12U,16U,20U,24U,28U})
            for (uint64_t v : {0ULL,1ULL,0x80000000ULL,0xffffffffULL,0x8000000000000000ULL,~0ULL})
                t.transact(BASE+offset,op,v,size);
        t.injectRead=true; t.transact(BASE+offset,0,1,size); t.transact(BASE+offset,2,0,size);
        t.injectRead=false;
        t.transact(BASE+offset,2,0,size); t.injectWrite=true; t.sideEffectOnError=true;
        t.transact(BASE+offset,3,0xaaaa,size); t.transact(BASE+offset,1,0xbbbb,size);
        t.injectWrite=false; t.sideEffectOnError=false; t.transact(BASE+offset,3,0,size);
    }
    t.transact(0x10000000,0,123); t.transact(BASE,31,123);
    for (unsigned n=0;n<1200;++n) {
        unsigned size = DUT_XLEN==64 && n%3==0 ? 3 : 2;
        uint64_t address=BASE+(t.random()%100)*WORD;
        if (size==2 && WORD==8 && n%2) address+=4;
        unsigned ops[]{0,1,2,3,4,8,12,16,20,24,28};
        t.transact(address,ops[t.random()%11],t.random(),size);
        if (n%43==0) t.invalidate();
        if (n%17==0) t.transact(address,0,t.random(),size,false,true);
    }
    std::cout << "FIVE_STAGE_ATOMIC_PASS xlen=" << DUT_XLEN << " cases=" << t.cases
        << " reads=" << t.reads << " writes=" << t.writes
        << " LR_SC_all_AMO_W_D_physical_reservation_context_errors_stalls_order=PASS\n";
    return 0;
} catch(const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
