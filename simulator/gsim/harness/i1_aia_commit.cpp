#include "I1AiaCommitHarness.h"
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#ifndef I1_AIA_FPGA8
#define I1_AIA_FPGA8 0
#endif
constexpr uint64_t BASE = 0x80000000ULL, DATA = BASE + 0x2000;
static void check(bool ok, const std::string &why) { if (!ok) throw std::runtime_error(why); }
static uint32_t ri(unsigned opcode, unsigned rd, unsigned f, unsigned rs, int imm) {
    return (uint32_t(imm) & 4095) << 20 | rs << 15 | f << 12 | rd << 7 | opcode;
}
struct Csr {
    unsigned file = 0, selector = 0, op = 0;
    uint64_t data = 0;
    bool topei = false;
    bool operator==(const Csr &) const = default;
};
struct Reply { uint64_t data = 0; bool error = false; bool operator==(const Reply &) const = default; };
// Independent architectural oracle: individual identity bits and a linear priority search.
// No DUT encodings, pipeline controls or generated internal state are used.
struct File {
    std::array<bool, 128> pending{}, enabled{};
    unsigned threshold = 0;
    bool delivery = false;
    unsigned top() const {
        for (unsigned i = 1; i <= 127; ++i)
            if (pending[i] && enabled[i] && (!threshold || i < threshold)) return i;
        return 0;
    }
};
struct ImsicOracle {
    std::array<File, 2> files;
    Reply access(Csr r) {
        if (r.file >= 2 || (!r.topei && (r.selector < 0x70 || r.selector > 0xff ||
            (r.selector >= 0x80 && r.selector % 2)))) return {0, true};
        auto &f = files[r.file];
        if (r.topei) {
            unsigned id = f.top();
            if (r.op && id) f.pending[id] = false;
            return {uint64_t(id) * 0x10001, false};
        }
        uint64_t old = r.selector == 0x70 ? f.delivery : r.selector == 0x72 ? f.threshold : 0;
        bool bitmap = r.selector >= 0x80;
        unsigned start = (r.selector % 64) * 32;
        if (bitmap) for (unsigned bit = 0; bit < 64; ++bit) {
            unsigned id = start + bit;
            if (id && id < 128 && (r.selector < 0xc0 ? f.pending[id] : f.enabled[id])) old |= uint64_t(1) << bit;
        }
        uint64_t value = r.op == 1 ? r.data : r.op == 2 ? old | r.data : r.op == 3 ? old & ~r.data : old;
        if (r.op) {
            if (r.selector == 0x70) f.delivery = value & 1;
            if (r.selector == 0x72 && value < 128) f.threshold = value;
            if (bitmap) for (unsigned bit = 0; bit < 64; ++bit) {
                unsigned id = start + bit;
                if (id && id < 128) (r.selector < 0xc0 ? f.pending[id] : f.enabled[id]) = (value >> bit) & 1;
            }
        }
        return {old, false};
    }
    void msi(unsigned file, unsigned id) { if (id && id < 128) files[file].pending[id] = true; }
    unsigned interrupts() const {
        unsigned value = 0;
        for (unsigned f = 0; f < 2; ++f) if (files[f].delivery && files[f].top()) value |= 1 << f;
        return value;
    }
};
struct Entry {
    uint64_t pc, next, value = 0, cause = 0, tval = 0;
    uint32_t ins;
    unsigned rd = 0, privilege = 3;
    bool write = false, trap = false;
    int external = -1;
};
struct Request { Csr csr; uint64_t pc; unsigned collide = 0; };
struct Memory { uint64_t address, data; bool error = false; };
struct Program {
    std::string name;
    std::vector<uint32_t> code;
    std::vector<Entry> ledger;
    std::vector<Request> requests;
    std::vector<Memory> memory;
    unsigned privilege = 3;
    std::optional<uint64_t> fetchError;
    bool cancelFence = false, holdFetch = false, delayFetch = false;
    std::optional<uint64_t> fencePc;
    std::array<unsigned, 2> selectors{};
    explicit Program(std::string n): name(std::move(n)) {}
    uint64_t pc() const { return BASE + 4 * code.size(); }
    void emit(uint32_t ins, unsigned rd = 0, uint64_t value = 0) {
        uint64_t address = pc(); code.push_back(ins);
        ledger.push_back(Entry{address, address + 4, value, 0, 0, ins, rd, privilege, rd != 0, false, -1});
    }
    void li(unsigned rd, int value) {
        if (value >= -2048 && value <= 2047) emit(ri(0x13, rd, 0, 0, value), rd, int64_t(value));
        else {
            uint32_t upper = (uint32_t(value) + 2048) & 0xfffff000U;
            emit(upper | rd << 7 | 0x37, rd, int64_t(int32_t(upper)));
            emit(ri(0x13, rd, 0, rd, value), rd, int64_t(value));
        }
    }
    void local(unsigned csr, unsigned rs, unsigned f = 1, unsigned rd = 0, uint64_t old = 0) {
        emit(ri(0x73, rd, f, rs, csr), rd, old);
    }
    void select(unsigned file, unsigned selector) {
        li(1, selector);
        local(file ? 0x150 : 0x350, 1, 1, 5, selectors[file]);
        selectors[file] = selector & 4095;
    }
    void aia(unsigned file, unsigned f, int value, bool zeroRegister = false,
             bool topei = false, unsigned rd = 10, unsigned collision = 0) {
        unsigned rs = zeroRegister ? 0 : 1;
        if (f & 4) rs = value;
        else if (!zeroRegister) li(rs, value);
        uint64_t source = f & 4 ? rs : zeroRegister ? 0 : uint64_t(int64_t(value));
        unsigned op = (f & 3) == 1 || rs ? f & 3 : 0;
        unsigned address = (file ? 0x150 : 0x350) + (topei ? 12 : 1);
        uint64_t here = pc();
        emit(ri(0x73, rd, f, rs, address), rd);
        ledger.back().external = requests.size();
        requests.push_back({Csr{file, selectors[file], op, source, topei}, here, collision});
    }
    void trap(uint32_t ins, unsigned cause, uint64_t tval) {
        emit(ins); ledger.back().trap = true; ledger.back().cause = cause; ledger.back().tval = tval;
    }
    void stop() { uint64_t here = pc(); trap(0x00100073, 3, here); }
    void enter(unsigned target) {
        // AUIPC obtains the actual target without relying on RV64 LUI sign extension.
        uint64_t here = pc(); emit(0x00000117, 2, here);
        emit(ri(0x13, 2, 0, 2, 28), 2, here + 28);
        local(0x341, 2);
        li(1, target == 1 ? 1 : 0);
        emit(ri(0x13, 1, 1, 1, 11), 1, uint64_t(target == 1 ? 1 : 0) << 11);
        local(0x300, 1);
        emit(0x30200073); ledger.back().next = here + 28;
        privilege = target;
    }
    void address() { uint64_t here = pc(); emit(0x00002217, 4, here + 0x2000); }
    void load(unsigned offset, bool fault = false) {
        uint64_t address = BASE + 0x2000 + offset;
        uint64_t value = 0x1234000000000000ULL + offset;
        unsigned rd = 12 + (offset / 8) % 16;
        emit(ri(0x03, rd, 3, 4, offset), rd, value);
        if (fault) {
            ledger.back().write = false; ledger.back().trap = true;
            ledger.back().cause = 5; ledger.back().tval = address;
        }
        memory.push_back({address, value, fault});
    }
};
static Program operations(unsigned file, bool supervisor) {
    Program p(supervisor ? "supervisor-operations" : "machine-operations");
    if (supervisor) p.enter(1);
    p.select(file, 0x1070); // selector WARL truncation keeps only twelve bits
    p.aia(file, 1, 1); p.aia(file, 2, 0, true); p.aia(file, 3, 0, true);
    p.aia(file, 3, 1); p.aia(file, 2, 1); p.aia(file, 1, 0);
    p.aia(file, 5, 1); p.aia(file, 6, 0); p.aia(file, 7, 0); p.aia(file, 7, 1); p.aia(file, 6, 1);
    p.select(file, 0xc0); p.aia(file, 1, 10); p.aia(file, 2, 16); p.aia(file, 3, 16);
    p.select(file, 0xc2); p.aia(file, 1, 2);
    p.select(file, 0x80); p.aia(file, 1, 10);
    p.select(file, 0x82); p.aia(file, 1, 2);
    p.aia(file, 2, 0, true, true); p.aia(file, 3, 0, true, true);
    p.aia(file, 6, 0, false, true); p.aia(file, 7, 0, false, true);
    p.aia(file, 1, 0, false, true, 10, 1); // actual claim and same-ID MSI on the same edge
    p.aia(file, 2, 0, true, true); // must still be identity 1
    p.aia(file, 2, 0, false, true); // nonzero rs1 holding zero still claims
    p.aia(file, 2, 0, true, true); // identity 3
    p.aia(file, 3, 0, false, true); // claims identity 3 despite a zero mask
    p.aia(file, 2, 0, true, true); // identity 65, cross-group priority
    p.aia(file, 5, 0, false, true, 0); // CSRRWI rd=x0 still claims
    p.aia(file, 2, 0, true, true); // empty
    p.select(file, 0x80); p.aia(file, 1, 10);
    p.select(file, 0x72); p.aia(file, 1, 1); p.aia(file, 2, 0, true, true);
    p.aia(file, 1, 0); p.aia(file, 2, 0, true, true);
    // The other file has never received an enable or pending write.
    if (!supervisor) { p.select(1, 0x80); p.aia(1, 2, 0, true); p.aia(1, 2, 0, true, true); }
    p.stop(); return p;
}
struct Stats { unsigned requests = 0, responses = 0, retires = 0, msi = 0, reqHeld = 0, rspHeld = 0, overlap = 0, cycles = 0; };
static Stats run(const Program &p, bool blocked, bool negative) {
    SI1AiaCommitHarness d;
    d.set_reset(1);
    d.set_io$$instructionRequest$$ready(0); d.set_io$$instructionResponse$$valid(0);
    d.set_io$$dataRequest$$ready(0); d.set_io$$dataResponse$$valid(0);
    d.set_io$$requestGate(0); d.set_io$$responseGate(0);
    d.set_io$$fenceReady(0); d.set_io$$offReadAddress(0x350);
    d.set_io$$msiValid(0); d.set_io$$msiFile(0); d.set_io$$msiIdentity(0); d.set_io$$msiWithCsr(1);
    d.step(); d.step(); d.set_reset(0);
    struct Pending { uint64_t due, value; bool error; };
    std::optional<Pending> fetch, data;
    std::optional<Csr> held;
    std::optional<uint64_t> heldFetch;
    std::deque<Reply> responses;
    std::vector<Reply> values;
    ImsicOracle oracle;
    Stats s;
    unsigned requestWait = 0, responseWait = 0, memoryAccepted = 0, memoryRetired = 0, successful = 0;
    unsigned msiResponses = 0, fenceWait = 0, fences = 0, drainWait = 0, heldFetchCycles = 0;
    bool fetchedFence = false;
    bool finished = false;
    auto require = [&](bool condition, const std::string &why) {
        check(condition, p.name + " cycle=" + std::to_string(s.cycles) + ": " + why);
    };
    for (unsigned cycle = 0; cycle < 20000 && !finished; ++cycle) {
        s.cycles = cycle;
        bool fv = fetch && fetch->due <= cycle, dv = data && data->due <= cycle;
        bool ir = !(p.holdFetch && fetchedFence && drainWait < 5);
        d.set_io$$instructionRequest$$ready(ir);
        d.set_io$$instructionResponse$$valid(fv);
        d.set_io$$instructionResponse$$bits$$instruction(fetch ? fetch->value : 0x13);
        d.set_io$$instructionResponse$$bits$$error(fetch && fetch->error); d.set_io$$instructionResponse$$bits$$pageFault(0);
        d.set_io$$instructionResponse$$bits$$compressed(0); d.set_io$$instructionResponse$$bits$$secondHalfFault(0);
        d.set_io$$dataRequest$$ready(1); d.set_io$$dataResponse$$valid(dv);
        d.set_io$$dataResponse$$bits$$data(data ? data->value : 0);
        d.set_io$$dataResponse$$bits$$error(data && data->error);
        d.set_io$$dataResponse$$bits$$pageFault(0); d.set_io$$dataResponse$$bits$$fetchSpan(0);
        d.set_io$$fenceReady(!blocked || fenceWait >= 6);
        constexpr std::array<unsigned, 6> offAddresses{0x350, 0x351, 0x35c, 0x150, 0x151, 0x15c};
        d.set_io$$offReadAddress(offAddresses[cycle % offAddresses.size()]);
        d.set_io$$requestGate(!blocked || requestWait >= 4 + s.requests % 3);
        d.set_io$$responseGate(!blocked || responseWait >= 7 + s.responses % 3);
        bool collision = s.requests < p.requests.size() && p.requests[s.requests].collide;
        d.set_io$$msiValid(collision);
        d.set_io$$msiFile(collision ? p.requests[s.requests].csr.file : 0);
        d.set_io$$msiIdentity(collision ? p.requests[s.requests].collide : 0);
        d.step();
        require(!d.get_io$$offReadLegal(), "default-off AIA CSR must be illegal");
        if (d.get_io$$fenceValid()) {
            require(s.retires < p.ledger.size() && p.ledger[s.retires].ins == 0x0000100f &&
                !p.ledger[s.retires].trap, "FENCE.I request lacks oldest nonfault authority");
            if ((blocked && fenceWait < 6) || !d.get_io$$fenceDrained()) {
                require(!d.get_io$$retire$$valid() && !d.get_io$$invalidateInstruction() && !d.get_io$$recovery(),
                    "FENCE.I retired, invalidated, or redirected before maintenance completion");
                if (blocked && fenceWait < 6) ++fenceWait;
                if (!d.get_io$$fenceDrained()) ++drainWait;
                if (p.cancelFence && fenceWait == 3) {
                    d.set_io$$instructionRequest$$ready(0); d.set_io$$instructionResponse$$valid(0);
                    d.set_io$$dataRequest$$ready(0); d.set_io$$dataResponse$$valid(0);
                    d.set_reset(1); d.step(); d.step(); d.set_reset(0); d.step();
                    require(!d.get_io$$fenceValid() && !d.get_io$$invalidateInstruction() &&
                        !d.get_io$$requestValid() && d.get_io$$instructions() == 0,
                        "synchronous reset failed to cancel a held FENCE.I owner");
                    finished = true; break;
                }
            } else {
                require(d.get_io$$retire$$valid() && d.get_io$$invalidateInstruction(),
                    "completed FENCE.I did not retire and invalidate on the same edge");
                ++fences;
            }
        } else require(!d.get_io$$invalidateInstruction(), "I-cache invalidate without FENCE.I authority");
        require(d.get_io$$interrupts() == oracle.interrupts(), "independent interrupt-level oracle");
        require(d.get_io$$instructions() == successful, "exactly-once architectural instruction counter");
        if (d.get_io$$msiResponseValid()) {
            require(msiResponses < s.msi && !d.get_io$$msiResponseError(), "MSI completion ledger"); ++msiResponses;
        }
        bool rv = d.get_io$$requestValid(), rr = d.get_io$$requestReady();
        Csr offer{unsigned(d.get_io$$request$$file()), unsigned(d.get_io$$request$$selector()),
            unsigned(d.get_io$$request$$operation()), d.get_io$$request$$data(), bool(d.get_io$$request$$topei())};
        if (held) require(rv && offer == *held, "request changed under backpressure");
        held.reset();
        if (rv && !rr) { held = offer; ++requestWait; ++s.reqHeld; }
        require(bool(d.get_io$$responseValid()) == !responses.empty(), "IMSIC response ownership/valid");
        if (!responses.empty()) {
            Reply got{d.get_io$$responseData(), bool(d.get_io$$responseError())};
            require(got == responses.front(), "independent IMSIC response oracle");
            if (d.get_io$$responseReady()) { responses.pop_front(); ++s.responses; responseWait = 0; }
            else { ++responseWait; ++s.rspHeld; }
        }
        if (d.get_io$$retire$$valid()) {
            require(s.retires < p.ledger.size(), "duplicate or wrong-path retirement");
            const Entry &e = p.ledger[s.retires];
            require(d.get_io$$retire$$bits$$pc() == e.pc && d.get_io$$retire$$bits$$instruction() == e.ins,
                "independent retirement PC/instruction ledger index=" + std::to_string(s.retires));
            require(d.get_io$$privilege() == e.privilege, "privilege changed at wrong architectural boundary");
            Reply expected{e.value, e.trap};
            if (e.external >= 0) {
                require(unsigned(e.external) < s.responses && unsigned(e.external) < values.size(),
                    "AIA retired before its exactly-once response");
                expected = values[e.external];
            }
            bool trap = e.trap || expected.error;
            require(bool(d.get_io$$retire$$bits$$trap()) == trap, "independent trap oracle");
            if (trap) {
                uint64_t cause = e.trap ? e.cause : 2, tval = e.trap ? e.tval : e.ins;
                require(d.get_io$$retire$$bits$$cause() == cause && d.get_io$$retire$$bits$$tval() == tval,
                    "precise exception cause/tval oracle");
                require(!d.get_io$$retire$$bits$$writesRd(), "fault wrote architectural register");
                finished = true;
            } else {
                require(bool(d.get_io$$retire$$bits$$writesRd()) == e.write, "independent write-enable oracle");
                if (negative && e.external == 0) expected.data ^= 1;
                if (e.write) require(d.get_io$$retire$$bits$$rd() == e.rd &&
                    d.get_io$$retire$$bits$$data() == expected.data, "independent AIA/register retirement oracle");
                require(d.get_io$$retire$$bits$$nextPc() == e.next, "next-PC oracle");
                ++successful;
            }
            if ((e.ins & 127) == 3) ++memoryRetired;
            ++s.retires;
        }
        if (rv && rr) {
            require(s.requests < p.requests.size(), "unauthorized or duplicate IMSIC request");
            const auto &want = p.requests[s.requests];
            require(offer == want.csr, "independent CSR operation/source/file/selector oracle");
            require(s.retires < p.ledger.size() && p.ledger[s.retires].pc == want.pc,
                "IMSIC request overtook an older instruction or a fault/flush");
            Reply reply = oracle.access(want.csr);
            values.push_back(reply); responses.push_back(reply); ++s.requests; requestWait = 0;
        }
        if (collision && d.get_io$$msiReady()) {
            require(rv && rr, "MSI/claim collision was not simultaneous");
            const auto &want = p.requests[s.requests - 1];
            oracle.msi(want.csr.file, want.collide); ++s.msi;
        }
        if (fv && d.get_io$$instructionResponse$$ready()) fetch.reset();
        if (dv && d.get_io$$dataResponse$$ready()) data.reset();
        if (heldFetch) require(d.get_io$$instructionRequest$$valid() &&
            d.get_io$$instructionRequest$$bits() == *heldFetch, "held fetch offer withdrawn or changed by FENCE.I");
        heldFetch.reset();
        if (d.get_io$$instructionRequest$$valid() && !ir) {
            heldFetch = d.get_io$$instructionRequest$$bits(); ++heldFetchCycles;
        }
        if (d.get_io$$instructionRequest$$valid() && ir) {
            require(!fetch, "duplicate fetch owner");
            uint64_t address = d.get_io$$instructionRequest$$bits();
            uint64_t index = (address - BASE) / 4;
            bool stale = p.fencePc && address > *p.fencePc && !fences;
            // A pre-completion younger fetch returns poison. A correct drain kills it,
            // and the same PC is fetched again after the FENCE.I redirect.
            uint32_t instruction = stale ? 0xffffffffU : index < p.code.size() ? p.code[index] : 0x13;
            fetch = Pending{cycle + (p.delayFetch && stale ? 40U : 1U), instruction,
                p.fetchError && address == *p.fetchError};
            if (p.fencePc && address == *p.fencePc) fetchedFence = true;
        }
        if (d.get_io$$dataRequest$$valid()) {
            require(!data, "duplicate LSU owner without response turnover");
            require(memoryAccepted < p.memory.size(), "unexpected or wrong-path LSU request");
            const auto &want = p.memory[memoryAccepted];
            require(d.get_io$$dataRequest$$bits$$address() == want.address &&
                !d.get_io$$dataRequest$$bits$$write() && d.get_io$$dataRequest$$bits$$size() == 3 &&
                !d.get_io$$dataRequest$$bits$$atomic(), "independent LSU request ledger");
            s.overlap += memoryAccepted > memoryRetired;
            data = Pending{cycle + (blocked ? 9U : 1U), want.data, want.error}; ++memoryAccepted;
        }
    }
    require(finished && (p.cancelFence || s.retires == p.ledger.size()), "finite program did not complete exact retirement ledger");
    require(s.requests == p.requests.size() && s.responses == s.requests && responses.empty(),
        "exactly-once CSR request/response totals");
    require(memoryAccepted == p.memory.size(), "missing LSU traffic");
    if (p.holdFetch) require(heldFetchCycles && drainWait, "held fetch drain stimulus not exercised");
    if (p.delayFetch) require(drainWait >= 10, "delayed outstanding fetch drain stimulus not exercised");
    require(msiResponses == s.msi, "uncompleted MSI response");
    if (blocked && !p.requests.empty()) require(s.reqHeld >= 4 * s.requests && s.rspHeld >= 7 * s.responses,
        "directed request/response backpressure was not exercised");
    d.set_io$$instructionRequest$$ready(0); d.set_io$$instructionResponse$$valid(0);
    d.set_io$$dataRequest$$ready(0); d.set_io$$dataResponse$$valid(0); d.set_io$$msiValid(0);
    d.set_io$$requestGate(1); d.set_io$$responseGate(1);
    for (unsigned i = 0; i < 12; ++i) {
        d.step(); require(!d.get_io$$requestValid(), "fault/flush leaked a late IMSIC request");
    }
    std::cout << "CASE " << p.name << " blocked=" << blocked << " retires=" << s.retires
        << " requests=" << s.requests << " responses=" << s.responses << " collisions=" << s.msi
        << " drain_held=" << drainWait << " fetch_held=" << heldFetchCycles << " fences=" << fences << " fence_held=" << fenceWait << " reset_cancel=" << p.cancelFence
        << " req_held=" << s.reqHeld << " rsp_held=" << s.rspHeld << " lsu_overlap=" << s.overlap << '\n';
    return s;
}
int main(int argc, char **argv) try {
    std::cout << std::unitbuf;
    bool negative = argc == 2 && std::string(argv[1]) == "--wrong-retire";
    auto m = operations(0, false); run(m, false, negative); run(m, true, false);
    run(operations(1, true), true, false);
    for (unsigned selector : {0x69U, 0x81U, 0x100U, 0xfffU}) {
        Program p("illegal-selector-" + std::to_string(selector)); p.select(0, selector);
        p.aia(0, 1, 7); // Endpoint rejects it, so this is the terminal illegal instruction.
        run(p, true, false);
    }
    for (unsigned privilege : {0U, 1U}) for (unsigned address : {0x350U, 0x351U, 0x35cU, 0x150U, 0x151U, 0x15cU}) {
        if (privilege == 1 && address < 0x300) continue;
        Program p("privilege-" + std::to_string(privilege) + "-csr-" + std::to_string(address)); p.enter(privilege);
        uint32_t ins = ri(0x73, 10, 2, 0, address); p.trap(ins, 2, ins); run(p, true, false);
    }
    {
        Program p("taken-branch-flush"); p.select(0, 0x70);
        p.emit(0x0080006f); p.ledger.back().next += 4;
        p.code.push_back(ri(0x73, 0, 5, 1, 0x351)); // wrong path must never request or retire
        p.stop(); run(p, true, false);
    }
    {
        Program p("older-load-fault"); p.address(); p.load(0, true);
        p.code.push_back(0x0000100f);
        p.code.push_back(ri(0x73, 0, 5, 1, 0x351)); run(p, true, false);
    }
    {
        Program p("ordinary-lsu-overlap"); p.address();
        for (unsigned i = 0; i < 32; ++i) p.load(i * 8);
        p.stop(); auto s = run(p, false, false);
        if (I1_AIA_FPGA8) check(s.overlap > 0, "ordinary LSU retirement overlap was globally serialized by AIA");
    }
    {
        Program p("fence-i-completion"); p.li(1, 17); p.fencePc = p.pc(); p.emit(0x0000100f); p.li(2, 19); p.stop();
        run(p, false, false); run(p, true, false);
        p.name = "fence-i-held-fetch"; p.holdFetch = true; run(p, false, false); p.holdFetch = false;
        p.name = "fence-i-delayed-fetch"; p.delayFetch = true; run(p, false, false); p.delayFetch = false;
        p.name = "fence-i-reset-cancel"; p.cancelFence = true; run(p, true, false);
    }
    {
        Program p("fence-i-fetch-fault-ready-high"); p.fetchError = p.pc();
        p.trap(0x0000100f, 1, p.pc()); run(p, false, false);
    }
    std::cout << "I1_AIA_COMMIT_PASS profile_fpga8=" << I1_AIA_FPGA8 << '\n';
    return 0;
} catch (const std::exception &e) { std::cerr << "FAIL: " << e.what() << '\n'; return 1; }
