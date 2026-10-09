#pragma once
#include <dlfcn.h>
#include <array>
#include <sstream>
// This reference is initialized from frozen guest bytes and independently stated
// RAM/ROM semantics, never from observed DUT state or memory.
namespace board_nemu {
constexpr uint64_t base=0x80200000ULL, dataBase=base;
constexpr size_t memoryBytes=0x400040; // Entire guest-to-signature aperture, including gaps.
using Memory=std::vector<uint8_t>;
#include "reference.h"
inline std::string hex(uint64_t n) { std::ostringstream s;s<<"0x"<<std::hex<<n;return s.str(); }
struct Observer {
    std::unique_ptr<Reference> reference;
    ReferenceState expected{};
    bool pending=false, boundary=false, finalized=false;
    uint64_t bootRetired=0, guestRetired=0, guestEdges=0, dualEdges=0, gprEdges=0, bootGprEdges=0;
    uint64_t gprComparisons=0, pcHash=1469598103934665603ULL, lastPc=0, memoryCompared=0;
    bool pendingGuest=false;
    std::string injection;
    void initialize(const Bytes &image,const char *path,const std::string &mode) {
        injection=mode;
        reference=std::make_unique<Reference>(path);
        reference->initializeAfterBoardRom();
        Memory bytes(memoryBytes,0);
        check(image.size()%4==0,"NEMU guest is not fixed-width aligned");
        std::copy(image.begin(),image.end(),bytes.begin());
        auto put=[&](uint64_t address,uint64_t value) {
            for(unsigned b=0;b<8;++b)bytes.at(address-base+b)=uint8_t(value>>(8*b));
        };
        for(unsigned i=0;i<HOT_BYTES/8;++i) {
            put(0x80400000ULL+8*i,0x10203040ULL+i);
            put(0x80402000ULL+8*i,~(0x10203040ULL+i));
        }
        for(unsigned i=0;i<4;++i)put(0x80600000ULL+8*i,0xdeadbeef);
        reference->initializeMemory(bytes);
        std::vector<uint32_t> program;
        for(size_t i=0;i<image.size();i+=4)program.push_back(wordAt(image,i));
        reference->load(program);
        // expected begins with the architectural reset state; reference begins
        // after the fixed ROM. Boot observation is checked separately below.
    }
    static std::array<uint64_t,32> registers(const SBoardSocGsim &d) {
        std::array<uint64_t,32> values{};
        for(unsigned r=0;r<32;++r) {
            unsigned p=d.board$platform$core$core$core$backend$ledger$committed[r];
            check(p<48,"NEMU committed physical mapping outside selected capacity");
            if(r==0)check(p==0,"NEMU architectural zero mapping corruption");
            if(p!=0&&d.board$platform$core$core$core$backend$physicalFile$initialized[p]) {
                const unsigned owner=d.board$platform$core$core$core$backend$physicalFile$owner[p];
                check(owner<2,"NEMU physical owner outside two banks");
                values[r]=owner?d.board$platform$core$core$core$backend$physicalFile$banks_1[p]:
                    d.board$platform$core$core$core$backend$physicalFile$banks_0[p];
            }
        }
        return values;
    }
    void sample(SBoardSocGsim &d) {
        if(d.get_backendReset())return;
        // callback N sees registered committed map/owner state from retire edge
        // N-1. Compare before executing this callback's retirement candidates.
        // NEMU executed every lane at N-1 independently; dual-lane state is the
        // state after both instructions, not an invented intermediate snapshot.
        if(pending) {
            auto actual=registers(d);
            if(injection=="--inject-nemu-gpr"&&pendingGuest)actual[5]^=1;
            for(unsigned r=0;r<32;++r) {
                check(actual[r]==expected.gpr[r],"NEMU GPR mismatch x"+std::to_string(r)+
                    " after retire edge ending "+hex(lastPc)+" expected="+hex(expected.gpr[r])+" actual="+hex(actual[r]));
                ++gprComparisons;
            }
            if(pendingGuest)++gprEdges;else ++bootGprEdges;
            pending=false;
        }
        if(boundary) { finalized=true;return; }
        unsigned n=0;
        for(unsigned lane=0;lane<2;++lane) {
            const bool valid=lane?d.get_io$$commit1():d.get_io$$commit0();
            if(!valid)continue;
            check(!lane||d.get_io$$commit0(),"NEMU non-prefix retirement");
            uint64_t pc=lane?d.get_io$$commit1Pc():d.get_io$$commit0Pc();
            lastPc=pc;
            if(pc<base) {
                check(guestRetired==0&&bootRetired<5&&pc==0x80000000ULL+bootRetired*4,
                    "NEMU fixed ROM retirement PC mismatch");
                // auipc t0,0x200; lui t1,0x10000; li t2,7;
                // sb t2,2(t1); jalr ra,0(t0). ROM UART configuration is outside
                // NEMU memory coverage; every boot integer update is specified.
                if(bootRetired==0)expected.gpr[5]=0x80200000ULL;
                if(bootRetired==1)expected.gpr[6]=0x10000000ULL;
                if(bootRetired==2)expected.gpr[7]=7;
                if(bootRetired==4)expected.gpr[1]=0x80000014ULL;
                ++bootRetired;pending=true;continue;
            }
            check(bootRetired==5,"NEMU guest retired before fixed ROM completed");
            check(pc>=base&&pc<HOT_IMAGE_END&&!(pc&3),"NEMU guest PC outside frozen image");
            if(injection=="--inject-nemu-pc")pc^=4;
            const auto before=reference->inspectState();
            check(before.pc==pc,"NEMU PC mismatch expected="+hex(before.pc)+" observed="+hex(pc));
            expected=reference->executeOne(); // Never repair or resynchronize.
            check(expected.mode==3,"NEMU guest left M-mode");
            pcHash^=pc;pcHash*=1099511628211ULL;
            ++guestRetired;++n;pending=true;pendingGuest=true;
            if(pc==HOT_DONE)boundary=true;
        }
        if(n) {++guestEdges;dualEdges+=n==2;}
    }
    void verifyMemory(const Test &test) {
        check(finalized&&!pending&&boundary,"NEMU final retire-edge state not checked");
        check(guestRetired>0&&gprEdges==guestEdges,"NEMU retirement/GPR boundary coverage gap");
        check(test.ddr.pendingWrites.empty()&&test.ddr.pendingB.empty(),"NEMU final memory before DDR write drain");
        auto actual=Memory(memoryBytes,0);
        for(const auto &[offset,value]:test.ddr.memory) {
            check(uint64_t(offset)+8<=memoryBytes,"NEMU observed DDR outside final checked aperture");
            for(unsigned b=0;b<8;++b)actual[offset+b]=uint8_t(value>>(8*b));
        }
        if(injection=="--inject-nemu-memory")actual[0x400000]^=1;
        const auto ref=reference->inspectMemory();
        for(size_t i=0;i<actual.size();++i)
            if(actual[i]!=ref[i])check(false,"NEMU memory mismatch at "+hex(base+i)+" expected="+
                hex(ref[i])+" actual="+hex(actual[i]));
        memoryCompared=actual.size();
    }
    void report() const {
        std::cout<<"NEMU_PASS guest_pc_checks="<<guestRetired<<" boot_pc_checks="<<bootRetired
            <<" guest_retire_edges="<<guestEdges<<" dual_retire_edges="<<dualEdges
            <<" guest_gpr_edges="<<gprEdges<<" boot_gpr_edges="<<bootGprEdges
            <<" gpr_value_checks="<<gprComparisons<<" final_memory_bytes="<<memoryCompared
            <<" guest_pc_trace="<<pcHash<<" reference_resynchronizations=0"
            <<" gpr_boundary=post_entire_retire_edge independent_lane_intermediate_gpr=0"
            <<" speculative_requests_stepped=0\n";
    }
};
}
