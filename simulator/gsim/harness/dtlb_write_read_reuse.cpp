#include "VirtualLoadPrecheckGsim.h"
#include "virtual_load_test_memory.h"
#include <deque>
#include <optional>
#include <tuple>
#include <vector>
#include <iostream>
#ifndef DTLB_WRITE_READ_REUSE
#define DTLB_WRITE_READ_REUSE 0
#endif
#ifndef DTLB_ENTRIES
#define DTLB_ENTRIES 8
#endif
using namespace virtual_load_test;
// Independent expected permissions/PA/ordered responses; no private TLB index
// or cached permission is consulted. Writes use the existing word value and
// AMOADD adds zero, so a missing or unauthorized physical operation is checked
// by the transaction ledger, not hidden by a mutable data oracle.
struct Op {
    uint64_t address, pa;
    bool write = false, atomic = false, fault = false, page = false;
};
struct Reply { uint64_t due, data; };
using PhysicalPayload = std::tuple<uint64_t, uint64_t, unsigned, unsigned, bool, bool, unsigned>;
class Bench {
    SVirtualLoadPrecheckGsim d;
    std::deque<Reply> ptes, replies;
    std::deque<Op> physicalExpected, responsesExpected;
    std::optional<PhysicalPayload> held;
    std::optional<std::tuple<uint64_t, bool, bool>> heldResponse;
public:
    PageTables tables;
    uint64_t cycle = 0, contextSatp = satp;
    unsigned privilege = 1, cfg = 0x1f, pteDelay = 12;
    unsigned accepted = 0, completed = 0, physicalAccepted = 0, walks = 0, hits = 0, pteReads = 0;
    unsigned blockPhysical = 0, blockResponse = 0, holds = 0;
    bool sum = false, mxr = false, flush = false, mutateAddress = false, mutatePermission = false;
    Bench() { drive({}); d.set_reset(1); d.step(); d.step(); d.set_reset(0); for (int i=0;i<4;++i) tick(); }
    void drive(std::optional<Op> op) {
        Op r = op.value_or(Op{});
        d.set_io$$upstream$$request$$valid(op.has_value());
        d.set_io$$upstream$$request$$bits$$address(r.address);
        d.set_io$$upstream$$request$$bits$$data(r.atomic ? 0 : readValue(r.pa));
        d.set_io$$upstream$$request$$bits$$size(3); d.set_io$$upstream$$request$$bits$$mask(255);
        d.set_io$$upstream$$request$$bits$$write(r.write); d.set_io$$upstream$$request$$bits$$atomic(r.atomic);
        d.set_io$$upstream$$request$$bits$$atomicOp(0);
        d.set_io$$upstream$$request$$bits$$virtualized(1); d.set_io$$upstream$$request$$bits$$uncached(0);
        d.set_io$$upstream$$request$$bits$$prefetchNextAllowed(0);
        d.set_io$$upstream$$request$$bits$$precheckedLoad(0); d.set_io$$upstream$$request$$bits$$translationEpoch(0);
        d.set_io$$upstream$$response$$ready(cycle >= blockResponse && cycle % 11 != 7);
        d.set_io$$physical$$request$$ready(cycle >= blockPhysical && cycle % 7 != 5);
        bool rv = !replies.empty() && replies.front().due <= cycle;
        d.set_io$$physical$$response$$valid(rv);
        d.set_io$$physical$$response$$bits$$data(rv ? replies.front().data : 0);
        d.set_io$$physical$$response$$bits$$error(0); d.set_io$$physical$$response$$bits$$pageFault(0);
        d.set_io$$pte$$request$$ready(cycle % 5 != 3);
        bool pv = !ptes.empty() && ptes.front().due <= cycle;
        d.set_io$$pte$$response$$valid(pv); d.set_io$$pte$$response$$bits$$data(pv ? ptes.front().data : 0);
        d.set_io$$pte$$response$$bits$$error(0);
        d.set_io$$context$$satp(contextSatp); d.set_io$$context$$dataPrivilege(privilege);
        d.set_io$$context$$sum(sum); d.set_io$$context$$mxr(mxr);
        d.set_io$$pmpCfg(cfg); d.set_io$$pmpAddress(allPmp);
        d.set_io$$queryValid(0); d.set_io$$queryAddress(va); d.set_io$$querySize(3); d.set_io$$flush(flush);
    }
    bool tick(std::optional<Op> op = {}) {
        bool rv = !replies.empty() && replies.front().due <= cycle;
        bool pv = !ptes.empty() && ptes.front().due <= cycle;
        drive(op); d.step();
        bool take = op && d.get_io$$upstream$$request$$ready();
        if (take) {
            Op e = *op;
            if (mutatePermission && e.fault) e.fault = e.page = false;
            responsesExpected.push_back(e); if (!e.fault) physicalExpected.push_back(e); ++accepted;
        }
        if (rv && d.get_io$$physical$$response$$ready()) replies.pop_front();
        if (pv && d.get_io$$pte$$response$$ready()) ptes.pop_front();
        if (d.get_io$$pte$$request$$valid() && cycle % 5 != 3) {
            uint64_t a = d.get_io$$pte$$request$$bits();
            require(a >= tables.rootAddress && a < tables.rootAddress + 12288 && !(a & 7), "unexpected PTE address");
            ptes.push_back({cycle + pteDelay, tables.pte(a)}); ++pteReads;
        }
        PhysicalPayload payload = {d.get_io$$physical$$request$$bits$$address(),
            d.get_io$$physical$$request$$bits$$data(), d.get_io$$physical$$request$$bits$$size(),
            d.get_io$$physical$$request$$bits$$mask(), bool(d.get_io$$physical$$request$$bits$$write()),
            bool(d.get_io$$physical$$request$$bits$$atomic()), d.get_io$$physical$$request$$bits$$atomicOp()};
        bool valid = d.get_io$$physical$$request$$valid(), ready = cycle >= blockPhysical && cycle % 7 != 5;
        if (held) require(valid && payload == *held, "DTLB physical payload changed while held");
        held = valid && !ready ? std::optional{payload} : std::nullopt; holds += valid && !ready;
        if (valid && ready) {
            require(!physicalExpected.empty(), "DTLB unauthorized or duplicate physical operation");
            Op e = physicalExpected.front(); physicalExpected.pop_front();
            PhysicalPayload wanted = {e.pa ^ (mutateAddress ? 8ULL : 0ULL), e.atomic ? 0 : readValue(e.pa),
                3, 255, e.write, e.atomic, 0};
            require(payload == wanted, "DTLB independent physical operation mismatch");
            require(!d.get_io$$physical$$request$$bits$$virtualized() &&
                !d.get_io$$physical$$request$$bits$$precheckedLoad(), "DTLB private authorization escaped");
            replies.push_back({cycle + 16, e.write && !e.atomic ? 0 : readValue(e.pa)}); ++physicalAccepted;
        }
        auto response = std::make_tuple(uint64_t(d.get_io$$upstream$$response$$bits$$data()),
            bool(d.get_io$$upstream$$response$$bits$$error()), bool(d.get_io$$upstream$$response$$bits$$pageFault()));
        bool responseValid = d.get_io$$upstream$$response$$valid();
        bool responseReady = cycle >= blockResponse && cycle % 11 != 7;
        if (heldResponse) require(responseValid && response == *heldResponse, "DTLB held response changed");
        heldResponse = responseValid && !responseReady ? std::optional{response} : std::nullopt;
        if (responseValid && responseReady) {
            require(!responsesExpected.empty(), "DTLB response has no independent owner");
            Op e = responsesExpected.front(); responsesExpected.pop_front();
            uint64_t data = e.fault || (e.write && !e.atomic) ? 0 : readValue(e.pa);
            require(response == std::make_tuple(data, e.fault, e.page), "DTLB independent ordered permission/fault mismatch");
            ++completed;
        }
        walks += d.get_io$$translationWalk(); hits += d.get_io$$translationHit(); ++cycle; return take;
    }
    void stream(const std::vector<Op>& ops) {
        const unsigned target = completed + ops.size(); unsigned sent = 0;
        for (unsigned n=0;n<100000 && completed<target;++n) {
            if (sent < ops.size()) { if (tick(ops[sent])) ++sent; } else tick();
        }
        require(completed == target && sent == ops.size(), "DTLB stream did not complete");
        for (int n=0;n<4;++n) tick();
        require(d.get_io$$idle() && ptes.empty() && replies.empty() && physicalExpected.empty() && responsesExpected.empty(),
            "DTLB adapter/walker/independent owners did not drain");
    }
    void run(Op op) { stream({op}); }
    void invalidate() { flush = true; tick(); flush = false; for (int i=0;i<4;++i) tick(); }
};
static void throughput(const char* label, unsigned pages, unsigned rounds, bool writes) {
    Bench b; b.tables.pages.clear();
    for (unsigned i=0;i<pages;++i) b.tables.pages[i] = {ram + 4096*i, 0xc7};
    std::vector<Op> ops;
    for (unsigned round=0;round<rounds;++round) for (unsigned i=0;i<pages;++i) {
        ops.push_back({va+4096*i, ram+4096*i});
        if (writes) ops.push_back({va+4096*i+8, ram+4096*i+8, true});
    }
    auto start = b.cycle; b.stream(ops); uint64_t elapsed = b.cycle - start;
    if (writes && DTLB_WRITE_READ_REUSE) require(b.walks == pages*2, "DTLB write/read capacity reuse missing");
    if (!writes) require(b.walks == pages, "DTLB read-only compulsory walk count changed");
    std::cout << "DTLB_REUSE_METRIC case=" << label << " reuse=" << DTLB_WRITE_READ_REUSE
        << " operations=" << ops.size() << " useful_bytes=" << ops.size()*8 << " cycles=" << elapsed
        << " walks=" << b.walks << " pte_reads=" << b.pteReads << " hits=" << b.hits << "\n";
}
static void contracts(bool mutateAddress, bool mutatePermission) {
    Bench b; b.mutateAddress = mutateAddress; b.mutatePermission = mutatePermission;
    b.run({va, ram, true}); const auto initial = b.walks;
    b.run({va+8, ram+8}); b.run({va+16, ram+16, false, true});
    require(b.walks == initial + (DTLB_WRITE_READ_REUSE ? 0 : 2), "DTLB write/R/RW reuse count mismatch");
    // Successful read does NOT imply writable; nor may MXR executable reads.
    b.tables.pages[1] = {ram+4096, 0xc3};
    b.run({va+4096, ram+4096}); b.run({va+4096, ram+4096, true, false, true, true});
    b.tables.pages[2] = {ram+8192, 0x47}; // A=1, D=0: Svade store fault.
    b.run({va+8192, ram+8192}); b.run({va+8192, ram+8192, true, false, true, true});
    const auto failedWalks = b.walks; b.run({va+8192+8, ram+8192+8});
    require(b.walks == failedWalks, "DTLB failed store replaced read authorization");
    b.mxr = true; b.run({va+5*4096, ram+12288});
    b.run({va+5*4096, ram+12288, true, false, true, true}); b.mxr = false;
    b.run({va+5*4096, ram+12288, false, false, true, true});
    b.invalidate(); b.run({va, ram, true});
    auto checkContextWalk = [&] { auto w=b.walks; b.run({va, ram}); require(b.walks==w+1, "DTLB context key leaked write permission"); };
    b.contextSatp ^= 1ULL<<44; checkContextWalk(); b.contextSatp ^= 1ULL<<44;
    b.sum = true; checkContextWalk(); b.sum = false;
    b.mxr = true; checkContextWalk(); b.mxr = false;
    b.privilege = 0; b.run({va, ram, false, false, true, true}); b.privilege = 1;
    b.tables.rootAddress = root + 0x10000; b.contextSatp = (8ULL<<60)|(7ULL<<44)|(b.tables.rootAddress>>12);
    checkContextWalk(); b.tables.rootAddress = root; b.contextSatp = satp;
    b.invalidate(); b.tables.pages[0].physical = ram+24576;
    b.run({va, ram+24576, true}); b.run({va+8, ram+24576+8});
    // Warm TLB entries still pass the current final physical PMP check.
    b.cfg = 0x18; b.run({va, ram+24576, false, false, true, false}); b.cfg = 0x1f;
    b.blockPhysical = b.cycle+80; b.blockResponse = b.cycle+120;
    b.stream({{va,ram+24576,true}, {va+8,ram+24576+8}, {va+9*4096,0,false,false,true,true},
        {va+16,ram+24576+16,false,true}});
    require(b.holds > 0, "DTLB backpressure coverage missing");
    std::cout << "DTLB_REUSE_CONTRACT_PASS reuse=" << DTLB_WRITE_READ_REUSE << " accepted=" << b.accepted
        << " completed=" << b.completed << " physical=" << b.physicalAccepted << "\n";
}
int main(int argc, char** argv) { try {
    std::string arg = argc>1 ? argv[1] : "";
    contracts(arg=="--mutate-address", arg=="--mutate-permission");
    const std::string mixed = "mixed-" + std::to_string(DTLB_ENTRIES) + "-pages";
    const std::string reads = "read-only-" + std::to_string(DTLB_ENTRIES) + "-pages";
    throughput(mixed.c_str(),DTLB_ENTRIES,8,true); throughput(reads.c_str(),DTLB_ENTRIES,8,false);
    std::cout << "DTLB_WRITE_READ_REUSE_PASS\n"; return 0;
} catch (const std::exception& e) { std::cerr << "DTLB_WRITE_READ_REUSE_FAIL " << e.what() << "\n"; return 1; } }
