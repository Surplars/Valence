#include "FixedPmpWalkerGsim.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <unordered_map>
#include <vector>
#include <string_view>
#include "pmp_csr_oracle.h"
#ifndef MAX_LEVELS
#define MAX_LEVELS 5
#endif
static pmp_csr_oracle::Entries observedPmp{};
static uint64_t observedCycles=0;
static bool injectRaw=false;

static void check(bool value, const char *message) {
    if (!value) throw std::runtime_error(message);
}
static uint64_t pte(uint64_t ppn, unsigned flags, unsigned pbmt = 0, bool napot = false) {
    return (uint64_t(napot) << 63) | (uint64_t(pbmt) << 61) | (ppn << 10) | flags;
}
static unsigned vpn(uint64_t va, unsigned level) { return (va >> (12 + 9 * level)) & 511; }

struct Case {
    unsigned mode = 8, privilege = 1, access = 0;
    uint64_t va = 0x3456789abcULL, root = 0x100;
    bool sum = false, mxr = false, denyPmp = false, readError = false;
    bool customPmp = false;
    int denyAfterReads = -1, denyFromCycle = -1;
    pmp_csr_oracle::Entries pmp{};
    uint64_t expectedPa = 0;
    bool pageFault = false, accessFault = false, global = false;
    unsigned expectedLevel = 0, expectedPbmt = 0, reads = 0;
    std::unordered_map<uint64_t, uint64_t> memory;
};
static Case mapping(unsigned levels, unsigned leafLevel, unsigned flags = 0xcf, unsigned pbmt = 0,
                    uint64_t va = 0x3456789abcULL) {
    Case c;
    c.va = va;
    c.mode = levels + 5;
    c.expectedLevel = leafLevel;
    c.expectedPbmt = pbmt;
    c.reads = levels - leafLevel;
    uint64_t table = c.root;
    for (int level = int(levels) - 1; level > int(leafLevel); --level) {
        const uint64_t next = 0x100 + uint64_t(levels - level) * 0x10;
        c.memory[(table << 12) + vpn(c.va, level) * 8] = pte(next, level == int(levels) - 1 ? 0x21 : 0x01);
        table = next;
    }
    // A naturally aligned leaf PPN; VPN chunks below leafLevel supply the superpage offset.
    const uint64_t ppn = leafLevel <= 2 ? 0x40000 : uint64_t(1) << (9 * leafLevel);
    c.memory[(table << 12) + vpn(c.va, leafLevel) * 8] = pte(ppn, flags, pbmt);
    const unsigned offsetBits = 12 + 9 * leafLevel;
    c.expectedPa = (ppn << 12) | (c.va & ((uint64_t(1) << offsetBits) - 1));
    c.global = leafLevel != levels - 1;
    return c;
}

static void inputs(SFixedPmpWalkerGsim &dut, const Case &c, bool start, bool readReady,
                   bool reply, uint64_t data = 0, bool error = false, bool completeReady = true) {
    dut.set_io$$startValid(start);
    dut.set_io$$virtualAddress(c.va);
    dut.set_io$$rootPpn(c.root);
    dut.set_io$$mode(c.mode);
    dut.set_io$$privilege(c.privilege);
    dut.set_io$$access(c.access);
    dut.set_io$$sum(c.sum);
    dut.set_io$$mxr(c.mxr);
    dut.set_io$$completeReady(completeReady);
    dut.set_io$$pteReady(readReady);
    dut.set_io$$pteReplyValid(reply);
    dut.set_io$$pteData(data);
    dut.set_io$$pteError(error);
    observedPmp = c.customPmp ? c.pmp : pmp_csr_oracle::Entries{};
    if (!c.customPmp) observedPmp[0] = {c.denyPmp ? 0u : 0x1fu, (uint64_t(1) << 54) - 1};
    dut.set_io$$pmpCfg(observedPmp[0].cfg); dut.set_io$$pmpAddr(observedPmp[0].addr);
    dut.set_io$$pmpCfg1(observedPmp[1].cfg); dut.set_io$$pmpAddr1(observedPmp[1].addr);
}

static void tick(SFixedPmpWalkerGsim &dut) {
    dut.step(); ++observedCycles;
    const uint64_t address=dut.get_io$$rawPteAddress();
    check((address & 7)==0,"actual walker raw PTE address lost alignment");
    const bool expected=pmp_csr_oracle::denied(observedPmp,16,address,3,0,1);
    bool actual=dut.get_io$$rawPmpDenied();
    if(injectRaw && observedCycles==6){std::cerr<<"REACHED raw-permission-observer\n";actual=!actual;}
    check(actual==expected,"WALKER_RAW_BYTE_ORACLE");
}
static void run(SFixedPmpWalkerGsim &dut, const Case &c) {
    inputs(dut, c, true, true, false);
    tick(dut);
    check(dut.get_io$$startReady(), "walker did not accept an idle request");
    bool reply = false;
    uint64_t replyData = 0;
    bool replyError = false;
    unsigned reads = 0;
    for (unsigned cycle = 0; cycle < 100; ++cycle) {
        // Exercise stable request payload under one cycle of memory backpressure.
        const bool ready = cycle % 3 != 0;
        Case driven=c;
        if((c.denyAfterReads>=0 && reads>=unsigned(c.denyAfterReads)) ||
           (c.denyFromCycle>=0 && cycle>=unsigned(c.denyFromCycle))) driven.denyPmp=true;
        inputs(dut, driven, false, ready, reply, replyData, replyError, false);
        tick(dut);
        const bool readFire = dut.get_io$$pteValid() && ready;
        if (reply) check(dut.get_io$$pteReplyReady(), "walker dropped an outstanding PTE reply");
        reply = false;
        if (readFire) {
            ++reads;
            const auto found = c.memory.find(dut.get_io$$pteAddress());
            check(found != c.memory.end(), "walker requested an unexpected PTE address");
            replyData = found->second;
            replyError = c.readError;
            reply = true;
        }
        if (dut.get_io$$completeValid()) {
            check(reads == c.reads, "walker made the wrong number of PTE reads");
            check(bool(dut.get_io$$pageFault()) == c.pageFault, "page-fault classification mismatch");
            check(bool(dut.get_io$$accessFault()) == c.accessFault, "access-fault classification mismatch");
            if (!c.pageFault && !c.accessFault) {
                check(dut.get_io$$physicalAddress() == c.expectedPa, "translated address mismatch");
                check(dut.get_io$$level() == c.expectedLevel, "leaf level mismatch");
                check(bool(dut.get_io$$global()) == c.global, "global mapping mismatch");
                check(dut.get_io$$pbmt() == c.expectedPbmt, "PBMT mismatch");
            }
            inputs(dut, c, false, true, false, 0, false, true);
            tick(dut);
            check(dut.get_io$$completeValid(), "completion was not held under backpressure");
            return;
        }
    }
    throw std::runtime_error("walker timed out");
}

int main(int argc, char**argv) {
    if(argc>1){check(std::string_view(argv[1])=="--inject-raw-denied","unknown argument");injectRaw=true;}
    try {
        SFixedPmpWalkerGsim dut;
        Case reset;
        inputs(dut, reset, false, true, false);
        dut.set_reset(1); tick(dut); tick(dut); dut.set_reset(0);
        unsigned cases = 0;
        for (unsigned levels : {3u, 4u, 5u}) {
            if(levels>MAX_LEVELS) continue;
            for (unsigned leaf = 0; leaf < levels; ++leaf) {
                auto c = mapping(levels, leaf);
                run(dut, c); ++cases;
            }
            auto c = mapping(levels, 0, 0xcf, 2);
            run(dut, c); ++cases;
            const unsigned signBit = 12 + 9 * levels - 1;
            c = mapping(levels, 0, 0xcf, 0,
                        (uint64_t(1) << signBit) | (~uint64_t(0) << (signBit + 1)) | 0x1234);
            run(dut, c); ++cases;
            c = mapping(levels, 0); c.va |= uint64_t(1) << (12 + 9 * levels);
            c.pageFault = true; c.reads = 0;
            run(dut, c); ++cases;
        }
        auto c = mapping(3, 0); c.memory[(c.root << 12) + vpn(c.va, 2) * 8] |= uint64_t(1) << 54;
        c.pageFault = true; c.reads = 1; run(dut, c); ++cases;
        c = mapping(3, 0); c.denyPmp = true; c.accessFault = true; c.reads = 0;
        run(dut, c); ++cases;
        c = mapping(3, 0); c.readError = true; c.accessFault = true; c.reads = 1;
        run(dut, c); ++cases;
        c = mapping(3, 0); c.access = 1;
        run(dut, c); ++cases;
        c = mapping(3, 0); c.access = 3;
        run(dut, c); ++cases;
        c = mapping(3, 0); c.access = 1;
        c.memory[(0x120ULL << 12) + vpn(c.va, 0) * 8] &= ~(uint64_t(1) << 7);
        c.pageFault = true; run(dut, c); ++cases;
        c = mapping(3, 0);
        c.memory[(0x120ULL << 12) + vpn(c.va, 0) * 8] &= ~(uint64_t(1) << 6);
        c.pageFault = true; run(dut, c); ++cases;
        c = mapping(3, 0, 0xc5); c.pageFault = true; // W without R.
        run(dut, c); ++cases;
        if(MAX_LEVELS>=4){
        c = mapping(4, 2);
        c.memory[(0x110ULL << 12) + vpn(c.va, 2) * 8] |= uint64_t(1) << 10;
        c.pageFault = true; run(dut, c); ++cases;
        }
        c = mapping(3, 0, 0xcf, 3); c.pageFault = true;
        run(dut, c); ++cases;
        c = mapping(3, 0);
        c.memory[(c.root << 12) + vpn(c.va, 2) * 8] |= uint64_t(1) << 4;
        c.pageFault = true; c.reads = 1; run(dut, c); ++cases;
        c = mapping(3, 0); c.privilege = 0; c.pageFault = true;
        run(dut, c); ++cases;
        c = mapping(3, 0, 0xdf); c.privilege = 0; c.pageFault = false;
        run(dut, c); ++cases;
        c = mapping(3, 0, 0xdf); c.pageFault = true; // SUM absent.
        run(dut, c); ++cases;
        c = mapping(3, 0, 0xdf); c.sum = true; c.pageFault = false;
        run(dut, c); ++cases;
        c = mapping(3, 0, 0xdf); c.sum = true; c.access = 2; c.pageFault = true;
        run(dut, c); ++cases;
        c = mapping(3, 0, 0xc9); c.pageFault = true;
        run(dut, c); ++cases;
        c = mapping(3, 0, 0xc9); c.mxr = true;
        run(dut, c); ++cases;
        c = mapping(3, 0);
        c.memory[(0x120ULL << 12) + vpn(c.va, 0) * 8] = pte(0x40008, 0xcf, 0, true);
        c.expectedPa = (0x40000ULL << 12) | (c.va & 0xffff);
        run(dut, c); ++cases;
        c = mapping(3, 0);
        c.memory[(0x120ULL << 12) + vpn(c.va, 0) * 8] = pte(0x40004, 0xcf, 0, true);
        c.pageFault = true; run(dut, c); ++cases;
        c = mapping(3, 0); c.mode = 0; c.reads = 0; c.expectedPa = c.va; c.global = false;
        run(dut, c); ++cases;
        unsigned partialCases=0;
        for(unsigned levels=3;levels<=MAX_LEVELS;++levels){
            for(unsigned target=0;target<levels;++target) for(unsigned half: {0u,4u}){
                c=mapping(levels,0); c.customPmp=true;
                const uint64_t table=target==levels-1 ? c.root : 0x100+uint64_t(levels-1-target)*0x10;
                const uint64_t address=(table<<12)+vpn(c.va,target)*8;
                c.pmp[0]={0x11,(address+half)/4}; c.pmp[1]={0x1f,(uint64_t(1)<<54)-1};
                check(pmp_csr_oracle::denied(c.pmp,16,address,3,0,1),"partial-first oracle precondition");
                c.accessFault=true;c.reads=levels-1-target;run(dut,c);++cases;++partialCases;
            }
            c=mapping(levels,levels-1); c.root=(uint64_t(1)<<44)-1;c.va=~uint64_t(0);
            c.memory.clear();const uint64_t ppn=levels-1<=2?0x40000:uint64_t(1)<<(9*(levels-1));
            c.memory[(c.root<<12)+4088]=pte(ppn,0xcf);
            c.expectedPa=(ppn<<12)|(c.va&((uint64_t(1)<<(12+9*(levels-1)))-1));
            run(dut,c);++cases;
        }
        // Deny before an implicit read: access fault suppresses even an invalid PTE fetch.
        c=mapping(3,0);c.denyPmp=true;c.readError=true;c.pageFault=false;c.accessFault=true;c.reads=0;
        c.memory[(c.root<<12)+vpn(c.va,2)*8]=0;run(dut,c);++cases;
        // Once a request is queued, a later PMP update must not retract that accepted approval.
        c=mapping(3,2);c.denyFromCycle=1;run(dut,c);++cases;
        // The next level observes the changed PMP state, before generating a second read.
        c=mapping(3,0);c.denyAfterReads=1;c.accessFault=true;c.reads=1;run(dut,c);++cases;
        // Bus error takes priority over malformed PTE content on the same response.
        c=mapping(3,0);c.memory[(c.root<<12)+vpn(c.va,2)*8]=0;c.readError=true;
        c.accessFault=true;c.reads=1;run(dut,c);++cases;
        for(unsigned mode: {1u,unsigned(MAX_LEVELS+6)}){
            c=mapping(3,0);c.mode=mode;c.pageFault=true;c.reads=0;run(dut,c);++cases;
            c.privilege=3;c.pageFault=false;c.expectedPa=c.va;c.expectedLevel=0;c.global=false;
            run(dut,c);++cases;
        }
        // Invalid external payloads do not reach the PTE-address construction.
        for(unsigned i=0;i<64;++i){c=Case{};c.va=~uint64_t(i)*0x123456789ULL;c.root=~uint64_t(i)&((uint64_t(1)<<44)-1);c.mode=i&15;inputs(dut,c,false,false,false);tick(dut);}
        std::cout<<"FIXED_CALLER_WALKER_PASS maxLevels="<<MAX_LEVELS<<" raw_oracle_cycles="<<observedCycles<<" partial_first_cases="<<partialCases<<" ";
        std::cout << "GSIM Sv39/Sv48/Sv57 walker: PASS cases=" << cases << '\n';
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "GSIM Sv walker: FAIL " << e.what() << '\n';
        return 1;
    }
}
