#include "StoreBufferGsim.h"
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

#ifndef BUFFER_ENTRIES
#define BUFFER_ENTRIES 4
#endif
static void check(bool ok, const char *message) { if (!ok) throw std::runtime_error(message); }
struct Request {
    uint64_t address, data;
    unsigned size, mask;
    bool write;
    bool operator==(const Request &) const = default;
};
struct Reply { uint64_t data; bool error; unsigned due; bool write=false; };
using Memory = std::array<uint8_t, 256>;
static Request request(uint64_t address, unsigned size, bool write, uint64_t data = 0) {
    return {address, data << (8 * (address & 7)), size, ((1U << (1U << size)) - 1) << (address & 7), write};
}
static Reply access(Memory &memory, const Request &r) {
    if (r.address < 4096 || r.address >= 4352) return {0, true, 0};
    const unsigned index = (r.address - 4096) & ~7U;
    uint64_t value = 0;
    for (unsigned i = 0; i < 8; ++i) {
        value |= uint64_t(memory[index + i]) << (8 * i);
        if (r.write && (r.mask & (1U << i))) memory[index + i] = r.data >> (8 * i);
    }
    return {r.write ? 0 : value, false, 0, r.write};
}
static void fastStore(SStoreBufferGsim &dut, bool valid, const Request &r) {
    dut.set_io$$fastStore$$valid(valid);
    dut.set_io$$fastStore$$bits$$address(r.address);
    dut.set_io$$fastStore$$bits$$data(r.data);
    dut.set_io$$fastStore$$bits$$size(r.size);
    dut.set_io$$fastStore$$bits$$mask(r.mask);
    dut.set_io$$fastStore$$bits$$write(r.write);
    dut.set_io$$fastStore$$bits$$atomic(0);
    dut.set_io$$fastStore$$bits$$atomicOp(0);
    dut.set_io$$fastStore$$bits$$virtualized(0);
    dut.set_io$$fastStore$$bits$$uncached(0);
}
static void dualIngress() {
    SStoreBufferGsim dut;
    dut.set_io$$upstream$$response$$ready(1);
    dut.set_io$$memory$$request$$ready(1);
    dut.set_io$$memory$$response$$valid(0);
    dut.set_io$$upstream$$request$$bits$$atomic(0);
    dut.set_io$$upstream$$request$$bits$$atomicOp(0);
    dut.set_io$$upstream$$request$$bits$$virtualized(0);
    dut.set_io$$upstream$$request$$bits$$uncached(0);
    fastStore(dut, false, request(4096, 3, true, 0));
    dut.set_io$$upstream$$request$$valid(0);
    dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    const auto write = request(4096, 3, true, UINT64_C(0x8877665544332211));
    const auto read = request(4104, 3, false);
    fastStore(dut, true, write);
    dut.set_io$$upstream$$request$$valid(1);
    dut.set_io$$upstream$$request$$bits$$address(read.address);
    dut.set_io$$upstream$$request$$bits$$data(read.data);
    dut.set_io$$upstream$$request$$bits$$size(read.size);
    dut.set_io$$upstream$$request$$bits$$mask(read.mask);
    dut.set_io$$upstream$$request$$bits$$write(0);
    dut.step();
    check(dut.get_io$$fastStore$$ready() && dut.get_io$$upstream$$request$$ready() &&
          dut.get_io$$memory$$request$$valid() &&
          dut.get_io$$memory$$request$$bits$$address() == read.address,
          "disjoint read and head store were not accepted together");
    fastStore(dut, false, write);
    dut.set_io$$upstream$$request$$valid(0);
    dut.step();
    check(dut.get_io$$memory$$request$$valid() && dut.get_io$$memory$$request$$bits$$write() &&
          dut.get_io$$memory$$request$$bits$$address() == write.address,
          "independent head store did not drain after the read");

    dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    fastStore(dut, true, write);
    dut.step();
    check(dut.get_io$$fastStore$$ready() && dut.get_io$$memory$$request$$valid() &&
          dut.get_io$$memory$$request$$bits$$write() &&
          dut.get_io$$memory$$request$$bits$$address() == write.address,
          "uncontended head store lost its same-cycle memory request");

    fastStore(dut, false, write);
    dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    fastStore(dut, true, write);
    dut.set_io$$upstream$$request$$valid(1);
    dut.set_io$$upstream$$request$$bits$$address(write.address);
    dut.set_io$$upstream$$request$$bits$$size(write.size);
    dut.set_io$$upstream$$request$$bits$$mask(write.mask);
    dut.step();
    check(dut.get_io$$fastStore$$ready() && !dut.get_io$$upstream$$request$$ready(),
          "overlapping younger read passed the independent store");
    fastStore(dut, false, write);
    dut.step();
    check(dut.get_io$$upstream$$request$$ready() && dut.get_io$$upstream$$response$$valid() &&
          dut.get_io$$upstream$$response$$bits$$data() == write.data,
          "overlapping read did not forward the newly buffered store");

    dut.set_io$$upstream$$request$$valid(0);
    dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    dut.set_io$$memory$$request$$ready(0);
    fastStore(dut, true, write);
    dut.set_io$$upstream$$request$$valid(1);
    dut.set_io$$upstream$$request$$bits$$address(read.address);
    dut.set_io$$upstream$$request$$bits$$mask(read.mask);
    dut.step();
    check(dut.get_io$$fastStore$$ready() && !dut.get_io$$upstream$$request$$ready() &&
          dut.get_io$$memory$$request$$valid() &&
          dut.get_io$$memory$$request$$bits$$address() == read.address,
          "backpressured disjoint read did not retain its request");
    fastStore(dut, false, write);
    dut.step();
    check(dut.get_io$$memory$$request$$valid() &&
          dut.get_io$$memory$$request$$bits$$address() == read.address,
          "queued store replaced a backpressured read");
    dut.set_io$$memory$$request$$ready(1);
    dut.step();
    check(dut.get_io$$upstream$$request$$ready() &&
          dut.get_io$$memory$$request$$bits$$address() == read.address,
          "backpressured read did not complete first");
    dut.set_io$$upstream$$request$$valid(0);
    dut.step();
    check(dut.get_io$$memory$$request$$valid() && dut.get_io$$memory$$request$$bits$$write() &&
          dut.get_io$$memory$$request$$bits$$address() == write.address,
          "queued store did not follow held read");
}
static void sameCycleWrite() {
    SStoreBufferGsim dut;
    fastStore(dut, false, request(4096, 3, true, 0));
    dut.set_io$$upstream$$request$$valid(0);
    dut.set_io$$upstream$$response$$ready(1);
    dut.set_io$$memory$$request$$ready(1);
    dut.set_io$$memory$$response$$valid(0);
    dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    const auto r = request(4096, 3, true, UINT64_C(0x8877665544332211));
    dut.set_io$$upstream$$request$$valid(1);
    dut.set_io$$upstream$$request$$bits$$address(r.address);
    dut.set_io$$upstream$$request$$bits$$data(r.data);
    dut.set_io$$upstream$$request$$bits$$size(r.size);
    dut.set_io$$upstream$$request$$bits$$mask(r.mask);
    dut.set_io$$upstream$$request$$bits$$write(1);
    dut.set_io$$upstream$$request$$bits$$atomic(0);
    dut.set_io$$upstream$$request$$bits$$atomicOp(0);
    dut.step();
    check(dut.get_io$$upstream$$request$$ready() && dut.get_io$$upstream$$response$$valid() &&
          dut.get_io$$memory$$request$$valid() && dut.get_io$$memory$$request$$bits$$write() &&
          dut.get_io$$memory$$request$$bits$$address() == r.address &&
          dut.get_io$$memory$$request$$bits$$data() == r.data,
          "buffered store was not issued and acknowledged in its acceptance cycle");
}
static void run(unsigned seed, bool zeroLatency, bool injectWriteError = false, bool injectReadMismatch = false) {
    SStoreBufferGsim dut;
    fastStore(dut, false, request(4096, 3, true, 0));
    dut.set_io$$upstream$$request$$valid(0);
    dut.set_io$$upstream$$request$$bits$$address(0);dut.set_io$$upstream$$request$$bits$$atomic(0);dut.set_io$$upstream$$request$$bits$$atomicOp(0);
    dut.set_io$$upstream$$request$$bits$$data(0);
    dut.set_io$$upstream$$request$$bits$$size(0);
    dut.set_io$$upstream$$request$$bits$$mask(0);
    dut.set_io$$upstream$$request$$bits$$write(0);
    dut.set_io$$upstream$$response$$ready(0);
    dut.set_io$$memory$$request$$ready(0);
    dut.set_io$$memory$$response$$valid(0);
    dut.set_io$$memory$$response$$bits$$data(0);
    dut.set_io$$memory$$response$$bits$$error(0);
    dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    Memory architectural{}, physical{};
    for (unsigned i = 0; i < 256; ++i) architectural[i] = physical[i] = uint8_t(i * 37 + 128);
    std::mt19937_64 rng(seed);
    std::vector<Request> input{
        request(4096, 3, true, UINT64_C(0x8877665544332211)),
        request(4097, 0, true, 0xaa), request(4098, 1, true, 0xbbcc), request(4096, 3, false),
        request(4104, 3, true, 17), request(4112, 0, true, 19), // fifth store stalls while full
        request(4113, 0, false), // same beat as older byte store, but no overlapping byte
        request(4120, 3, false), // different beat while write responses remain pending
        request(4112, 1, false), // partially covered: must wait for RAM
        request(8192, 3, false), request(8192, 3, true, 99) // serial access errors after drain
    };
    for (unsigned i = 0; i < 3000; ++i) {
        const unsigned size = rng() % 4;
        const unsigned offset = (rng() % 256) & ~((1U << size) - 1);
        input.push_back(request(4096 + offset, size, rng() % 3 != 0, rng()));
    }
    std::deque<Reply> expected, responses;
    std::deque<Request> expectedWrites, actualWrites, inflightWrites;
    std::optional<Request> held;
    std::optional<Reply> heldReply;
    unsigned earlyReads=0,earlySameBeat=0;
    unsigned pendingWrites=0,maxWrites=0,writeRun=0,maxWriteRun=0;
    unsigned cursor = 0, forwards = 0, fullStalls = 0, writeCount = 0, maxPending = 0;
    unsigned immediateWrites = 0, immediateForwards = 0;
    for (unsigned cycle = 0; cycle < 300000; ++cycle) {
        const bool valid = cursor < input.size() && expected.size() < 4;
        const Request r = valid ? input[cursor] : request(4096, 0, false);
        const bool ready = rng() % 4 != 0;
        const bool memoryReady = cycle >= 300 && (zeroLatency ? bool(held) && responses.empty() : (cycle < 320 || rng() % 4 != 0));
        bool responseValid = !responses.empty() && responses.front().due <= cycle;
        Reply reply = responseValid ? responses.front() : Reply{};
        if (zeroLatency && held && memoryReady) {
            auto copy = physical;
            reply = access(copy, *held);
            responseValid = true;
        }
        if (injectWriteError && responseValid) reply.error = true;
        if(injectReadMismatch && responseValid && !reply.write && !reply.error)reply.data=~reply.data;
        dut.set_io$$upstream$$request$$valid(valid);
        dut.set_io$$upstream$$request$$bits$$address(r.address);
        dut.set_io$$upstream$$request$$bits$$data(r.data);
        dut.set_io$$upstream$$request$$bits$$size(r.size);
        dut.set_io$$upstream$$request$$bits$$mask(r.mask);
        dut.set_io$$upstream$$request$$bits$$write(r.write);
        dut.set_io$$upstream$$response$$ready(ready);
        dut.set_io$$memory$$request$$ready(memoryReady);
        dut.set_io$$memory$$response$$valid(responseValid);
        dut.set_io$$memory$$response$$bits$$data(reply.data);
        dut.set_io$$memory$$response$$bits$$error(reply.error);
        dut.step();
        const bool upstreamAccepted = valid && dut.get_io$$upstream$$request$$ready();
        if (upstreamAccepted && r.write && r.address >= 4096 && r.address < 4352) {
            check(dut.get_io$$upstream$$response$$valid(), "buffered RAM write did not acknowledge in request cycle");
            ++immediateWrites;
        }
        if (dut.get_io$$forwarded()) {
            check(dut.get_io$$upstream$$response$$valid(), "forwarded RAM read did not reply in request cycle");
            ++immediateForwards;
        }
        if (upstreamAccepted) {
            expected.push_back(access(architectural, r));
            if (r.write && r.address < 4352) expectedWrites.push_back(r);
            ++cursor;
        }
        if (cycle < 300 && valid && !dut.get_io$$upstream$$request$$ready()) ++fullStalls;
        forwards += bool(dut.get_io$$forwarded());
        const bool busValid = dut.get_io$$memory$$request$$valid();
        check(!held || busValid, "withdrawn external request");
        bool acceptedWrite=false;
        if (busValid) {
            const Request bus{dut.get_io$$memory$$request$$bits$$address(), dut.get_io$$memory$$request$$bits$$data(),
                dut.get_io$$memory$$request$$bits$$size(), dut.get_io$$memory$$request$$bits$$mask(),
                bool(dut.get_io$$memory$$request$$bits$$write())};
            check(!held || *held == bus, "external request changed during backpressure");
            if (memoryReady) {
                if(!bus.write && pendingWrites){
                    check(bus.address>=4096&&bus.address<4352,"non-RAM access before write drain");
                    check(expectedWrites.size()==actualWrites.size(),"read issued before older store request");
                    ++earlyReads;
                    for(const auto &w:inflightWrites)if((w.address&~7ULL)==(bus.address&~7ULL)){
                        check(!(w.mask&bus.mask),"overlapping read before write response");++earlySameBeat;
                    }
                }
                if(bus.address>=4352)check(pendingWrites==0,"MMIO before write drain");
                auto snapshot=physical;
                auto out = access(snapshot, bus); // Writes become visible only when their response is consumed.
                out.due = cycle + (cycle < 320 ? 40 : 1 + rng() % 20);
                if (!zeroLatency) responses.push_back(out);
                if (bus.write && !out.error) { acceptedWrite=true;inflightWrites.push_back(bus);actualWrites.push_back(bus); ++writeCount; ++pendingWrites;maxWrites=std::max(maxWrites,pendingWrites); }
                held.reset();
            } else held = bus;
        }
        writeRun=acceptedWrite?writeRun+1:0;maxWriteRun=std::max(maxWriteRun,writeRun);
        if(responseValid && dut.get_io$$memory$$response$$ready() && reply.write){--pendingWrites;check(!inflightWrites.empty(),"write response owner");access(physical,inflightWrites.front());inflightWrites.pop_front();}
        if (responseValid && dut.get_io$$memory$$response$$ready() && !zeroLatency) responses.pop_front();
        // For zero-latency replies held under upstream backpressure, the request has already fired.
        // Continue that reply independently until consumed.
        if (zeroLatency && responseValid && !dut.get_io$$memory$$response$$ready() && responses.empty())
            responses.push_back({reply.data, reply.error, cycle, reply.write});
        else if (zeroLatency && responseValid && dut.get_io$$memory$$response$$ready() && !responses.empty())
            responses.pop_front();
        const bool outValid = dut.get_io$$upstream$$response$$valid();
        check(!heldReply || outValid, "withdrawn upstream response");
        if (outValid) {
            const Reply out{dut.get_io$$upstream$$response$$bits$$data(), bool(dut.get_io$$upstream$$response$$bits$$error()), 0};
            if (heldReply) check(out.data == heldReply->data && out.error == heldReply->error, "unstable upstream response");
            check(!expected.empty(), "extra response");
            // Only requested load bytes are defined for forwarding; compare using the matching request.
            const Request &origin = input[cursor - expected.size()];
            check(out.error == expected.front().error, "response error/order mismatch");
            if (!origin.write && !out.error) for (unsigned byte = 0; byte < 8; ++byte)
                if (origin.mask & (1U << byte)) check(uint8_t(out.data >> (8 * byte)) == uint8_t(expected.front().data >> (8 * byte)), "load forwarding/value mismatch");
            if (ready) { expected.pop_front(); heldReply.reset(); } else heldReply = out;
        }
        while (!expectedWrites.empty() && !actualWrites.empty()) {
            check(expectedWrites.front() == actualWrites.front(), "lost/reordered/corrupted store");
            expectedWrites.pop_front(); actualWrites.pop_front();
        }
        maxPending = std::max(maxPending, unsigned(responses.size()));
        // A same-cycle local acknowledgement may retire the final input before its buffered write
        // becomes visible in the next registered state; sample drain only from the next cycle.
        if (cursor == input.size() && expected.empty() && !upstreamAccepted && !dut.get_io$$busy()) {
            check(responses.empty() && !held && expectedWrites.empty() && actualWrites.empty() && architectural == physical, "final memory/drain mismatch");
            check(zeroLatency || (earlyReads>0 && earlySameBeat>0), "disjoint early read coverage");
            check(zeroLatency || maxWriteRun>=std::min(unsigned(BUFFER_ENTRIES),5U), "consecutive write throughput coverage");
            check(pendingWrites==0 && (zeroLatency || maxWrites==std::min(unsigned(BUFFER_ENTRIES),5U)), ("multiple writes outstanding coverage pending="+std::to_string(pendingWrites)+" max="+std::to_string(maxWrites)+" zero="+std::to_string(zeroLatency)).c_str());
            check(forwards > 0 && immediateWrites > 1500 && immediateForwards > 0 &&
                  (BUFFER_ENTRIES>4 || fullStalls > 100) && writeCount > 1500, "store buffer coverage");
            std::cout << "GSIM StoreBuffer: PASS capacity=" << BUFFER_ENTRIES << " seed=" << seed << " zeroLatency=" << zeroLatency
                      << " requests=" << cursor << " stores=" << writeCount << " forwarded=" << forwards
                      << " earlyReads=" << earlyReads << " sameBeat=" << earlySameBeat
                      << " cycles=" << cycle+1 << " maxWrites=" << maxWrites << " consecutiveWrites=" << maxWriteRun
                      << " fullStalls=" << fullStalls << " maxPending=" << maxPending
                      << " immediateWrites=" << immediateWrites << " immediateForwards=" << immediateForwards << '\n';
            return;
        }
    }
    throw std::runtime_error("store buffer timeout");
}
int main(int argc, char **argv) {
    try {
        dualIngress();
        sameCycleWrite();
        if (argc == 2 && std::string(argv[1]) == "--inject-write-error") run(17, false, true);
        else if(argc==2 && std::string(argv[1])=="--inject-read-mismatch")run(17,false,false,true);
        else for (unsigned seed : {17, 129, 8191}) { run(seed, false); run(seed, true); }
    }
    catch (const std::exception &e) { std::cerr << "GSIM StoreBuffer: FAIL " << e.what() << '\n'; return 1; }
}
