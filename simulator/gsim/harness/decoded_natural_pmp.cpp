#include "DecodedNaturalPmpGsim.h"
#include "pmp_csr_oracle.h"
#include <array>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <map>
#include <random>
#include <stdexcept>
#include <string>
#include <type_traits>

// Raw decoded-state tests deliberately include synthetic W-only cfg values.
// They are not represented as reachable MachineSystemUnit CSR states.
using namespace pmp_csr_oracle;
namespace {
struct Summary { unsigned hit=0, deny=0; bool defaultDeny=false; };
struct Coverage {
    uint64_t trials=0, comparisons=0, allows=0, denies=0, partial=0;
    uint64_t highMachineAllow=0, highOtherDeny=0, inactiveArbitrary=0, syntheticWriteOnly=0;
    std::array<uint64_t,4> sizes{}, accesses{}, modes{};
    std::array<uint64_t,8> isolatedHighBits{};
    std::array<uint64_t,3> entryBoundaries{};
    uint64_t boundaryPriorityPairs=0;
} coverage;
void check(bool ok, const std::string& why) { if (!ok) throw std::runtime_error(why); }
Summary expectedSummary(const Entries& entries, unsigned count, uint64_t a,
                        unsigned size, unsigned access, unsigned privilege) {
    Summary result;
    result.defaultDeny=count!=0 && privilege!=3;
    for (unsigned i=0;i<count;++i) {
        const auto r=range(entries,i);
        bool any=false, all=true;
        // Independent byte membership, not the DUT's high/low comparator formula.
        for (unsigned byte=0;byte<(1U<<size);++byte) {
            const Wide location=Wide(a)+byte;
            const bool inside=r.active && location>=r.low && location<=r.end;
            any|=inside; all&=inside;
        }
        if (!any) continue;
        result.hit|=1U<<i;
        const unsigned cfg=entries[i].cfg;
        const bool permit=access==0 ? (cfg&1) : access==1 ? (cfg&2) :
            access==2 ? (cfg&4) : ((cfg&3)==3);
        const bool bypass=privilege==3 && !(cfg&128);
        if (!all || (!bypass && !permit)) result.deny|=1U<<i;
        coverage.partial+=!all;
    }
    return result;
}
void drive(SDecodedNaturalPmpGsim& d, const Entries& e) {
#define ENTRY(N) d.set_io$$cfg##N(e[N].cfg); d.set_io$$addr##N(e[N].addr);
    ENTRY(0); ENTRY(1); ENTRY(2); ENTRY(3); ENTRY(4); ENTRY(5); ENTRY(6); ENTRY(7);
    ENTRY(8); ENTRY(9); ENTRY(10); ENTRY(11); ENTRY(12); ENTRY(13); ENTRY(14); ENTRY(15);
#undef ENTRY
}
void compareSummary(const Summary& expected, unsigned hit, unsigned deny, bool def,
                    const std::string& name) {
    check(hit==expected.hit, name+"_HIT_BYTE_ORACLE");
    check(deny==expected.deny, name+"_DENY_BYTE_ORACLE");
    check(def==expected.defaultDeny, name+"_DEFAULT_ORACLE");
}
void one(SDecodedNaturalPmpGsim& d, const Entries& e, uint64_t a, unsigned size,
         unsigned privilege, unsigned access, unsigned mutation=0, unsigned contract=0) {
    drive(d,e);
    d.set_io$$address(a); d.set_io$$size(size); d.set_io$$privilege(privilege); d.set_io$$access(access);
    d.set_io$$mutation(mutation); d.set_io$$contract(contract); d.step();
    ++coverage.trials;
    if (size<4) ++coverage.sizes[size];
    ++coverage.accesses[access];
    coverage.inactiveArbitrary+=contract==4;
    for (const auto& x:e) { ++coverage.modes[(x.cfg>>3)&3]; coverage.syntheticWriteOnly+=(x.cfg&3)==2; }
#define TYPED(N) { \
    const bool want=denied(e,N,a,size,access,privilege); \
    const auto summary=expectedSummary(e,N,a,size,access,privilege); \
    check(bool(d.get_io$$denied##N())==want,"DECODED_PMP_TYPED" #N "_BYTE_ORACLE"); \
    compareSummary(summary,d.get_io$$hit##N(),d.get_io$$deny##N(),d.get_io$$defaultDeny##N(), \
                   "DECODED_PMP_TYPED" #N); \
    ++coverage.comparisons; coverage.allows+=!want; coverage.denies+=want; \
}
    TYPED(0); TYPED(8); TYPED(16);
#undef TYPED
    const bool want=denied(e,16,a,size,access,privilege);
    const auto summary=expectedSummary(e,16,a,size,access,privilege);
    check(bool(d.get_io$$genericDenied())==want,"DECODED_PMP_GENERIC_BYTE_ORACLE");
    compareSummary(summary,d.get_io$$genericHit(),d.get_io$$genericDeny(),d.get_io$$genericDefaultDeny(),
                   "DECODED_PMP_GENERIC");
    // Test-only RTL mutant changes hardware logic, not the host expected result.
    check(bool(d.get_io$$mutantDenied())==want,"DECODED_PMP_RTL_MUTANT_DENIED_ORACLE");
    compareSummary(summary,d.get_io$$mutantHit(),d.get_io$$mutantDeny(),d.get_io$$mutantDefaultDeny(),
                   "DECODED_PMP_RTL_MUTANT");
    coverage.comparisons+=2;
    coverage.highMachineAllow+=(a>>56)!=0 && privilege==3 && !want;
    coverage.highOtherDeny+=(a>>56)!=0 && privilege!=3 && want;
}
void negative(SDecodedNaturalPmpGsim& d, const std::string& flag) {
    Entries e{};
    uint64_t a=0x1000;
    unsigned size=2, privilege=1, access=0, mutation=0, contract=0;
    if (flag=="--mutant-high-address") { mutation=1; e[0]={0x11,0x400}; a|=UINT64_C(1)<<56; }
    else if (flag=="--mutant-machine-nohit") { mutation=2; privilege=3; a=UINT64_C(1)<<63; }
    else if (flag=="--mutant-cover") { mutation=3; e[0]={0x11,0x401}; e[1]={0x19,0x400}; size=3; }
    else if (flag=="--mutant-priority") { mutation=4; e[0]={0x10,0x400}; e[1]={0x11,0x400}; }
    else if (flag=="--mutant-lock") { mutation=5; e[0]={0x90,0x400}; privilege=3; }
    else if (flag=="--mutant-read") { mutation=6; e[0]={0x10,0x400}; }
    else if (flag=="--mutant-write") { mutation=7; e[0]={0x11,0x400}; access=1; }
    else if (flag=="--mutant-readwrite") { mutation=8; e[0]={0x11,0x400}; access=3; }
    else if (flag=="--mutant-active") { mutation=9; e[0]={0x01,0x400}; }
    else if (flag=="--mutant-lower-endpoint") { mutation=10; e[0]={0x11,0x401}; size=3; }
    else if (flag=="--mutant-upper-endpoint") { mutation=11; e[0]={0x11,0x400}; size=3; }
    else if (flag=="--mutant-tor-predecessor") { mutation=12; e[0]={0,0x400}; e[1]={0x09,0x800}; a=0; }
    else if (flag=="--mutant-execute") { mutation=13; e[0]={0x11,0x400}; access=2; }
    else if (flag=="--contract-high-bound") { contract=1; e[0]={0x11,0x400}; }
    else if (flag=="--contract-granule") { contract=2; e[0]={0x11,0x400}; }
    else if (flag=="--contract-reversed") { contract=3; e[0]={0x11,0x400}; }
    else if (flag=="--contract-size") { size=4; e[0]={0x1f,0x7ff}; }
    else if (flag=="--contract-alignment") { a|=1; e[0]={0x1f,0x7ff}; }
    else throw std::runtime_error("unknown negative mode: "+flag);
    std::cout << (mutation ? "DECODED_PMP_RTL_MUTATION_REACHED " : "DECODED_PMP_CONTRACT_REACHED ")
              << flag << " mode=" << mutation << " contract=" << contract << std::endl;
    one(d,e,a,size,privilege,access,mutation,contract);
    throw std::runtime_error("DECODED_PMP_NEGATIVE_CONTROL_ESCAPED");
}
void directed(SDecodedNaturalPmpGsim& d) {
    Entries e{};
    const std::array<uint64_t,14> edges={0,1,3,4,7,8,UINT64_C(0xfffffffc),UINT64_C(0x100000000),
        (UINT64_C(1)<<56)-1,UINT64_C(1)<<56,(UINT64_C(1)<<63)-1,UINT64_C(1)<<63,
        UINT64_MAX-7,UINT64_MAX};
    // Exhaust permission bits and both halves of a beat, including W-only cfg.
    for (unsigned mode=0;mode<4;++mode) for (unsigned bits=0;bits<8;++bits)
    for (unsigned lock=0;lock<2;++lock) for (unsigned privilege=0;privilege<4;++privilege)
    for (unsigned access=0;access<4;++access) for (unsigned size=0;size<4;++size) {
        e={}; e[0]={mode*8+bits+lock*128,mode==1?0x401ULL:mode==2?0x400ULL:0x401ULL};
        e[1]={0x1f,0x403};
        for (unsigned offset=0;offset<16;offset+=(1U<<size))
            one(d,e,0x1000+offset,size,privilege,access);
        for (auto a:edges) one(d,e,a&~((UINT64_C(1)<<size)-1),size,privilege,access);
    }
    // Both partial first overlaps defeat later covering regions, even unlocked M.
    for (unsigned half=0;half<2;++half) for (unsigned privilege=0;privilege<4;++privilege)
    for (unsigned access=0;access<4;++access) for (unsigned bits=0;bits<8;++bits) {
        e={}; e[0]={0x10U|bits,0x400U+half}; e[1]={0x1f,0x401};
        one(d,e,0x1000,3,privilege,access);
    }
    // TOR top-zero underflow, empty/decreasing regions, dynamic predecessor changes.
    for (unsigned low=0;low<20;++low) for (unsigned top=0;top<20;++top)
    for (unsigned size=0;size<4;++size) {
        e={}; e[0]={0,low}; e[1]={0x09,top}; e[2]={0x1f,0x1f};
        for (unsigned a=0;a<96;a+=(1U<<size)) one(d,e,a,size,(low+top)%4,(low^top)%4);
    }
    // Every NAPOT mask length, including 2^56 full-domain clamp at trailing53/54.
    for (unsigned trailing=0;trailing<=54;++trailing) for (unsigned bits=0;bits<8;++bits)
    for (unsigned size=0;size<4;++size) for (unsigned privilege=0;privilege<4;++privilege) {
        const uint64_t suffix=trailing==54?addressMask:((UINT64_C(1)<<trailing)-1);
        e={}; e[0]={0x18U|bits,suffix};
        const auto r=range(e,0);
        const std::array<uint64_t,6> a={uint64_t(r.low),uint64_t(r.end),uint64_t(r.end+1),
            (UINT64_C(1)<<56)-8,UINT64_C(1)<<56,UINT64_MAX};
        for (auto x:a) one(d,e,x&~((UINT64_C(1)<<size)-1),size,privilege,(bits+trailing)%4);
    }
    // Inactive synthetic bounds violate every typed active premise but cannot hit.
    for (unsigned k=0;k<256;++k) {
        e={}; e[0]={0,k}; e[1]={0x1f,0x401};
        one(d,e,(k%2?0x1000:UINT64_MAX)&~UINT64_C(7),3,k%4,k%4,0,4);
    }
    // Every high address bit independently prevents aliasing into the low PA.
    // Locked/no-match M is still allowed; S/U/reserved privilege still default deny.
    for (unsigned bit=56;bit<64;++bit) for (unsigned privilege=0;privilege<4;++privilege)
    for (unsigned access=0;access<4;++access) for (unsigned size=0;size<4;++size)
    for (unsigned lock=0;lock<2;++lock) {
        e={}; e[0]={0x1fU|(lock<<7),0x400};
        one(d,e,(UINT64_C(1)<<bit)|UINT64_C(0x1000),size,privilege,access);
        ++coverage.isolatedHighBits[bit-56];
    }
    // Entry7 is visible to N=8; entry8 and entry15 are visible only to N=16.
    // Independent raw-oracle comparisons therefore check cardinality, not just priority.
    const std::array<unsigned,3> boundarySlots={7,8,15};
    for (unsigned boundary=0;boundary<boundarySlots.size();++boundary)
    for (unsigned permission:{0U,7U}) for (unsigned lock=0;lock<2;++lock)
    for (unsigned privilege=0;privilege<4;++privilege) for (unsigned access=0;access<4;++access)
    for (unsigned size=0;size<4;++size) {
        e={}; e[boundarySlots[boundary]]={0x18U|permission|(lock<<7),0x400};
        one(d,e,0x1000,size,privilege,access);
        ++coverage.entryBoundaries[boundary];
    }
    // First-match and partial-overlap priority on both sides of the N=8 boundary.
    for (unsigned first=0;first<boundarySlots.size();++first)
    for (unsigned second=first+1;second<boundarySlots.size();++second)
    for (unsigned privilege=0;privilege<4;++privilege) for (unsigned access=0;access<4;++access) {
        const unsigned a=boundarySlots[first], b=boundarySlots[second];
        e={}; e[a]={0x91,0x401}; e[b]={0x1f,0x400};
        one(d,e,0x1000,3,privilege,access); // Early half-beat cannot be rescued.
        e[a]={0x98,0x400};
        one(d,e,0x1000,3,privilege,access); // Early locked denial wins.
        e[a]={0x9f,0x400}; e[b]={0x98,0x400};
        one(d,e,0x1000,3,privilege,access); // Later locked denial cannot override.
        coverage.boundaryPriorityPairs+=3;
    }
    // Explicit top NA4 region, at every allowed natural width and access type.
    for (unsigned size=0;size<4;++size) for (unsigned privilege=0;privilege<4;++privilege)
    for (unsigned access=0;access<4;++access) {
        e={}; e[0]={0x97,addressMask};
        one(d,e,((UINT64_C(1)<<56)-1)&~((UINT64_C(1)<<size)-1),size,privilege,access);
        one(d,e,(UINT64_C(1)<<56),size,privilege,access);
    }
}
void randomCases(SDecodedNaturalPmpGsim& d) {
    std::mt19937_64 rng(0xdec0ded56a11c0deULL);
    Entries e{};
    for (unsigned i=0;i<20000;++i) {
        for (auto& x:e) { x.cfg=rng()&255; x.addr=rng()&addressMask; }
        const unsigned size=i%4, entry=i%16;
        if (i%7==0) e[entry].addr=addressMask;
        uint64_t a=rng();
        if (i%3) {
            const auto r=range(e,entry);
            a=uint64_t(i%2?r.low:r.end)+(int(i%5)-2)*4;
        }
        a&=~((UINT64_C(1)<<size)-1);
        one(d,e,a,size,rng()%4,rng()%4);
    }
}
}
int main(int argc, char** argv) {
    try {
        check(argc==1 || argc==2,"expected zero or one negative argument");
        SDecodedNaturalPmpGsim d;
        static_assert(std::is_trivially_copyable_v<SDecodedNaturalPmpGsim>);
        std::memset(&d,0,sizeof(d)); d.LOG_START=1; d.activateAll();
        d.set_reset(1); d.set_io$$size(0); d.step(); d.step(); d.set_reset(0);
        if (argc==2) negative(d,argv[1]);
        directed(d); randomCases(d);
        check(coverage.trials>100000 && coverage.allows>10000 && coverage.denies>10000 &&
              coverage.partial>1000 && coverage.highMachineAllow>1000 && coverage.highOtherDeny>1000 &&
              coverage.inactiveArbitrary==256 && coverage.syntheticWriteOnly>1000,
              "DECODED_PMP_COVERAGE_LOW");
        for (unsigned i=0;i<4;++i) check(coverage.sizes[i]>1000 && coverage.accesses[i]>1000 &&
                                        coverage.modes[i]>1000,"DECODED_PMP_DOMAIN_COVERAGE_LOW");
        for (auto count:coverage.isolatedHighBits)
            check(count==128,"DECODED_PMP_ISOLATED_HIGH_BIT_COVERAGE_LOW");
        for (auto count:coverage.entryBoundaries)
            check(count==256,"DECODED_PMP_ENTRY_BOUNDARY_COVERAGE_LOW");
        check(coverage.boundaryPriorityPairs==144,"DECODED_PMP_BOUNDARY_PRIORITY_COVERAGE_LOW");
        std::cout << "DECODED_NATURAL_PMP_PASS entries=0,8,16 trials=" << coverage.trials
                  << " independent_checks=" << coverage.comparisons << " partial=" << coverage.partial
                  << " high_M_allow=" << coverage.highMachineAllow << " high_other_deny=" << coverage.highOtherDeny
                  << " inactive_arbitrary=" << coverage.inactiveArbitrary
                  << " synthetic_W_only=" << coverage.syntheticWriteOnly
                  << " isolated_high_bits=56..63x128 entry_boundaries=7,8,15x256"
                  << " boundary_priority_checks=" << coverage.boundaryPriorityPairs
                  << " generic_65bit_source=unchanged rtl_mutant_mode=0" << std::endl;
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "DECODED_NATURAL_PMP_FAIL " << e.what() << std::endl;
        return 1;
    }
}
