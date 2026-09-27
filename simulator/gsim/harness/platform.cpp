#include "SynchronousPlatformGsim.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <dlfcn.h>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <optional>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>
constexpr uint64_t base = 0x80000000, dataBase = base + 0x10000;
using Memory = std::array<uint8_t, 4096>;
static void check(bool ok, const std::string &message) { if (!ok) throw std::runtime_error(message); }
#include "reference.h"
#include "isa_model.h"
struct Request { uint64_t address, data; unsigned size, mask; bool write; };
struct Reply { uint64_t data; bool error; unsigned earliest = 0; };
static void drive(SSynchronousPlatformGsim &d, const Request &r, bool valid, bool ready) {
    d.set_io$$host$$request$$bits$$atomic(0); d.set_io$$host$$request$$bits$$atomicOp(0);
    d.set_io$$host$$request$$valid(valid); d.set_io$$host$$request$$bits$$address(r.address);
    d.set_io$$host$$request$$bits$$data(r.data); d.set_io$$host$$request$$bits$$size(r.size);
    d.set_io$$host$$request$$bits$$mask(r.mask); d.set_io$$host$$request$$bits$$write(r.write);
    d.set_io$$host$$response$$ready(ready);
}
static Reply access(Memory &m, const Request &r) {
    unsigned bytes = 1U << r.size, lane = r.address & 7;
    bool legal = r.address >= dataBase && r.address - dataBase <= m.size() - bytes &&
        !(r.address & (bytes - 1)) && r.mask == ((1U << bytes) - 1) << lane;
    if (!legal) return {0, true};
    uint64_t value = 0;
    size_t index = (r.address - dataBase) & ~UINT64_C(7);
    for (unsigned i = 0; i < 8; ++i) {
        value |= uint64_t(m[index + i]) << (8 * i);
        if (r.write && (r.mask & (1U << i))) m[index + i] = r.data >> (8 * i);
    }
    return {r.write ? 0 : value, false};
}
static Reply transaction(SSynchronousPlatformGsim &d, Request r) {
    drive(d, r, true, true);
    do { d.step(); } while (!d.get_io$$host$$request$$ready());
    drive(d, r, false, true);
    do { d.step(); } while (!d.get_io$$host$$response$$valid());
    Reply out{d.get_io$$host$$response$$bits$$data(), bool(d.get_io$$host$$response$$bits$$error())};
    d.step(); return out;
}
static void initialize(SSynchronousPlatformGsim &d, Memory &m) {
    d.set_io$$hostMode(1); d.set_io$$write(0); d.set_io$$writeIndex(0); d.set_io$$writeData(0); d.set_io$$commitEnable(1);
    drive(d, {}, false, true); d.step();
    for (unsigned i = 0; i < m.size(); ++i) m[i] = uint8_t(i * 37 + 128);
    for (unsigned offset = 0; offset < m.size(); offset += 8) {
        uint64_t data = 0; for (unsigned i = 0; i < 8; ++i) data |= uint64_t(m[offset + i]) << (8 * i);
        check(!transaction(d, {dataBase + offset, data, 3, 255, true}).error, "RAM initialization");
    }
}
static void compareRam(SSynchronousPlatformGsim &d, const Memory &m) {
    for (unsigned offset = 0; offset < m.size(); offset += 8) {
        auto r = transaction(d, {dataBase + offset, 0, 3, 255, false});
        check(!r.error, "RAM scan error");
        for (unsigned i = 0; i < 8; ++i) check(uint8_t(r.data >> (8 * i)) == m[offset + i], "RAM final byte mismatch");
    }
}
static void ramTest(SSynchronousPlatformGsim &d) {
    Memory model{}; initialize(d, model);
    // Alternate a masked write and same-address read; accept one request each cycle.
    std::deque<Reply> pipeline;
    for (unsigned cycle = 0; cycle <= 256; ++cycle) {
        unsigned size = (cycle / 2) % 4;
        Request r{dataBase + (cycle / 2) * 8, UINT64_C(0x1122334455667788) + cycle,
                  size, (1U << (1U << size)) - 1, !(cycle & 1)};
        drive(d, r, cycle < 256, true); d.step();
        if (cycle) {
            check(d.get_io$$host$$response$$valid() && !pipeline.empty(), "RAM pipeline response bubble");
            check(!d.get_io$$host$$response$$bits$$error() && d.get_io$$host$$response$$bits$$data() == pipeline.front().data,
                  "RAM masked write/read ordering");
            pipeline.pop_front();
        }
        if (cycle < 256) {
            check(d.get_io$$host$$request$$ready(), "RAM one-request-per-cycle throughput");
            pipeline.push_back(access(model, r));
        }
    }
    drive(d, {}, false, true); d.step();
    std::mt19937_64 rng(0x773191);
    std::deque<Reply> expected;
    std::optional<Request> held;
    unsigned requests = 0, responses = 0, errors = 0, stalled = 0;
    std::array<unsigned,4> narrow{};
    for (unsigned cycle = 0; cycle < 16000; ++cycle) {
        bool valid = cycle < 15000 || bool(held), ready = rng() % 3 == 0;
        unsigned size = rng() % 4, offset = (rng() % model.size()) & ~((1U << size) - 1);
        Request r{dataBase + offset, rng(), size, ((1U << (1U << size)) - 1) << (offset & 7), bool(rng() & 1)};
        switch (rng() % 10) {
        case 0: r.address = dataBase + model.size(); break;
        case 1: r.address = UINT64_MAX; break;
        case 2: r.mask ^= 1; break;
        case 3: r.address |= 1; break;
        default: break;
        }
        if (held) r = *held;
        drive(d, r, valid, ready); d.step();
        if (d.get_io$$host$$response$$valid()) {
            check(!expected.empty() && cycle >= expected.front().earliest, "RAM response ownership/latency");
            check(d.get_io$$host$$response$$bits$$data() == expected.front().data &&
                  bool(d.get_io$$host$$response$$bits$$error()) == expected.front().error, "RAM data/error or stalled response mismatch");
            if (ready) { expected.pop_front(); ++responses; } else ++stalled;
        }
        if (valid && d.get_io$$host$$request$$ready()) {
            auto reply = access(model, r); reply.earliest = cycle + 1; expected.push_back(reply);
            ++requests; errors += reply.error; if (r.write && !reply.error) ++narrow[r.size]; held.reset();
        } else if (valid) held = r;
    }
    check(expected.empty() && requests == responses && errors > 100 && stalled > 1000, "RAM coverage/drain");
    for (auto count : narrow) check(count > 100, "RAM byte width coverage");
    compareRam(d, model);
    std::cout << "GSIM SynchronousDataRam: PASS requests=" << requests << " errors=" << errors << " responseStalls=" << stalled << " pipelineRequests=256" << '\n';
}
static std::vector<uint32_t> loadBinary(const char *path) {
    std::ifstream file(path, std::ios::binary); check(bool(file), "payload file");
    std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(file)), {});
    check(!bytes.empty() && bytes.size() % 4 == 0 && bytes.size() <= 4096, "ROM image size");
    std::vector<uint32_t> words;
    for (size_t i = 0; i < bytes.size(); i += 4)
        words.push_back(uint32_t(bytes[i]) | (uint32_t(bytes[i+1]) << 8) | (uint32_t(bytes[i+2]) << 16) | (uint32_t(bytes[i+3]) << 24));
    return words;
}
static void runProgram(SSynchronousPlatformGsim &d, Reference &ref, const std::vector<uint32_t> &program,
                       uint64_t seed, bool inject) {
    Memory memory{}; initialize(d, memory);
    for (unsigned i = 0; i < 1024; ++i) {
        d.set_io$$write(1); d.set_io$$writeIndex(i); d.set_io$$writeData(i < program.size() ? program[i] : 0); d.step();
    }
    d.set_io$$write(0); d.step(); ref.load(program); ref.initializeMemory(memory);
    std::array<uint64_t,32> registers{};
    std::deque<Request> architecturalWrites, externalWrites;
    uint64_t pc = base, end = base + program.size() * 4;
    uint64_t retired = 0, retirementCycles = 0, fetchWait = 0, memoryBusy = 0, loads = 0, stores = 0, commitBlocked = 0;
    bool finished = false, sawEndException = false;
    unsigned quiet = 0;
    std::mt19937_64 rng(seed);
    d.set_io$$hostMode(0);
    for (unsigned cycle = 0; cycle < 30000; ++cycle) {
        bool enable = !seed || rng() % 4 != 0;
        d.set_io$$commitEnable(enable); d.step();
        if (!finished) { fetchWait += bool(d.get_io$$fetchWait()); memoryBusy += bool(d.get_io$$memoryBusy()); commitBlocked += !enable; }
        if (d.get_io$$dataRequest$$valid()) {
            Request r{d.get_io$$dataRequest$$bits$$address(), d.get_io$$dataRequest$$bits$$data(),
                d.get_io$$dataRequest$$bits$$size(), d.get_io$$dataRequest$$bits$$mask(), bool(d.get_io$$dataRequest$$bits$$write())};
            if (r.write) { externalWrites.push_back(r); ++stores; } else ++loads;
        }
        struct Commit { bool valid, writes; unsigned rd; uint64_t pc, next, data; uint32_t inst; };
        std::array<Commit,2> commits{};
#define COMMIT(N) commits[N] = {bool(d.get_io$$commit##N##$$valid()), bool(d.get_io$$commit##N##$$bits$$writesRd()), d.get_io$$commit##N##$$bits$$rd(), d.get_io$$commit##N##$$bits$$pc(), d.get_io$$commit##N##$$bits$$nextPc(), d.get_io$$commit##N##$$bits$$data(), d.get_io$$commit##N##$$bits$$instruction()};
        COMMIT(0) COMMIT(1)
#undef COMMIT
        check(!commits[1].valid || commits[0].valid, "commit prefix");
        for (auto c : commits) if (c.valid) {
            check(enable && pc >= base && pc < end, "unexpected commit");
            auto inst = program[(pc-base)/4]; auto e = decode(inst); check(e, "illegal instruction committed");
            auto expected = interpret(*e, inst, pc, registers, memory);
            check(!expected.fault && c.pc == pc && c.inst == inst && c.next == expected.nextPc &&
                c.writes == bool(expected.rd) && (!expected.rd || (c.rd == expected.rd && c.data == expected.result)), "synchronous platform ISA mismatch");
            if (e->memory == 2) {
                unsigned size = (inst >> 12) & 3, count = 1U << size, lane = expected.target & 7;
                uint64_t value = registers[(inst >> 20) & 31];
                architecturalWrites.push_back({expected.target, value << (8 * lane), size, ((1U << count) - 1) << lane, true});
                for (unsigned i = 0; i < count; ++i) memory[expected.target-dataBase+i] = value >> (8*i);
            }
            if (expected.rd) registers[expected.rd] = c.data;
            if (inject && retired == 0) registers[1] ^= 1;
            pc = expected.nextPc; ref.compare(registers, pc);
            if (e->memory) ref.compareMemory(memory);
            ++retired; retirementCycles = cycle + 1;
        }
        while (!architecturalWrites.empty() && !externalWrites.empty()) {
            auto a = architecturalWrites.front(), b = externalWrites.front();
            check(a.address == b.address && a.size == b.size && a.mask == b.mask, "physical store stream mismatch");
            for (unsigned i = 0; i < 8; ++i) if (a.mask & (1U << i))
                check(uint8_t(a.data >> (8*i)) == uint8_t(b.data >> (8*i)), "physical store byte mismatch");
            architecturalWrites.pop_front(); externalWrites.pop_front();
        }
        if (pc == end) finished = true;
        if (d.get_io$$exception$$valid()) {
            check(finished && d.get_io$$exception$$bits$$pc() == end && d.get_io$$exception$$bits$$cause() == 2 &&
                  d.get_io$$exception$$bits$$tval() == 0, "unexpected platform exception"); sawEndException = true;
        }
        if (sawEndException && !d.get_io$$memoryBusy()) {
            if (++quiet == 32) {
                check(retired == 1310 && registers[10] == 42 && loads > 0 && stores == 197, "C workload coverage/result");
                check(architecturalWrites.empty() && externalWrites.empty(), "undrained physical store stream");
                d.set_io$$hostMode(1); d.step(); compareRam(d, memory); ref.compareMemory(memory);
                std::cout << "PLATFORM {\"name\":\"compiled_c_array_sum\",\"seed\":" << seed << ",\"retired\":" << retired
                    << ",\"cycles\":" << retirementCycles << ",\"ipc\":" << std::setprecision(9) << double(retired)/retirementCycles
                    << ",\"fetch_wait_cycles\":" << fetchWait << ",\"memory_busy_cycles\":" << memoryBusy
                    << ",\"commit_disabled_cycles\":" << commitBlocked << ",\"loads\":" << loads << ",\"stores\":" << stores << "}\n";
                return;
            }
        } else quiet = 0;
    }
    throw std::runtime_error("synchronous C workload timeout");
}
static void faultTest(SSynchronousPlatformGsim &d, Reference &ref, bool store) {
    Memory memory{}; initialize(d, memory);
    std::vector<uint32_t> program{0x00010197U, 0x00000093U, store ? 0x0000b023U : 0x0000b103U, 0x0001b023U};
    for (unsigned i = 0; i < 1024; ++i) {
        d.set_io$$write(1); d.set_io$$writeIndex(i); d.set_io$$writeData(i < program.size() ? program[i] : 0); d.step();
    }
    d.set_io$$write(0); d.step(); ref.load(program); ref.initializeMemory(memory);
    std::array<uint64_t,32> regs{}; uint64_t pc = base;
    unsigned retired = 0, requests = 0, quiet = 0;
    d.set_io$$hostMode(0); d.set_io$$commitEnable(1);
    for (unsigned cycle = 0; cycle < 1000; ++cycle) {
        d.step();
        if (d.get_io$$dataRequest$$valid()) {
            check(d.get_io$$dataRequest$$bits$$address() == 0 && bool(d.get_io$$dataRequest$$bits$$write()) == store,
                  "faulting memory operation leaked a younger request"); ++requests;
        }
#define NORMAL(N) if (d.get_io$$commit##N##$$valid()) { \
    check(retired < 2 && d.get_io$$commit##N##$$bits$$pc() == pc, "faulting or younger instruction retired"); \
    auto inst = program[retired]; auto e = decode(inst); auto expected = interpret(*e, inst, pc, regs, memory); \
    check(d.get_io$$commit##N##$$bits$$instruction() == inst && d.get_io$$commit##N##$$bits$$data() == expected.result, "fault prefix result"); \
    regs[expected.rd] = expected.result; pc = expected.nextPc; ref.compare(regs, pc); ++retired; }
        NORMAL(0) NORMAL(1)
#undef NORMAL
        if (d.get_io$$exception$$valid()) {
            check(retired == 2 && d.get_io$$exception$$bits$$pc() == base + 8 &&
                  d.get_io$$exception$$bits$$cause() == (store ? 7 : 5) && d.get_io$$exception$$bits$$tval() == 0,
                  "RAM access error did not stop precisely");
            if (!d.get_io$$memoryBusy() && ++quiet == 32) {
                check(requests == 1, "access fault request count");
                d.set_io$$hostMode(1); d.step(); compareRam(d, memory); ref.compareMemory(memory);
                std::cout << "GSIM synchronous platform access fault: PASS store=" << store << " youngerStoreSuppressed=1\n";
                return;
            }
        }
    }
    throw std::runtime_error("platform access fault timeout");
}
int main(int argc, char **argv) {
    try {
        check(argc >= 3, "NEMU and C image required"); SSynchronousPlatformGsim dut;
        dut.set_io$$hostMode(1); dut.set_io$$write(0); dut.set_io$$writeIndex(0); dut.set_io$$writeData(0); dut.set_io$$commitEnable(1);
        drive(dut, {}, false, true); dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
        ramTest(dut); Reference ref(argv[1]); auto program = loadBinary(argv[2]);
        for (uint64_t seed : {0, 17, 8191}) runProgram(dut, ref, program, seed, argc > 3);
        faultTest(dut, ref, false); faultTest(dut, ref, true);
        std::cout << "GSIM synchronous ROM/core/RAM + NEMU: PASS programs=5 commits=3934 preciseAccessFaults=2\n";
    } catch (const std::exception &e) { std::cerr << "GSIM synchronous platform: FAIL " << e.what() << '\n'; return 1; }
}
