// Actual executed RV64I guest + production coherent MemoryCopyDma.
// Reuses the unchanged board driver, AXI model, and full-token CPU flow ledger.
#ifndef DDR_BENCHMARK_MODEL
#error "Use the existing credit-aware independent benchmark AXI model"
#endif
#define main board_boot_regression_main
#include "board_boot.cpp"
#undef main
#define DATA_PATH_OWNERSHIP_PROBES
#include "backend_observer.h"
#include "cpu_flow_bandwidth.h"
#include <array>
#include <deque>
#include <map>
#include <optional>
#include <string_view>

namespace {
using P = DataPathSample;
constexpr uint64_t src = 0x80210000, dst = 0x80211000, scratch = 0x80212000;
constexpr uint64_t coldSrc = 0x80230000, coldDst = 0x80234000;
constexpr uint64_t stride = 0x01010101;
uint64_t pattern(unsigned generation, unsigned i) {
    return 0x1122334400000000ULL + uint64_t(generation - 1) * 0x100000000ULL + i * stride;
}
uint64_t cold(unsigned i) { return 0x8877665500000000ULL + i * stride; }
bool in(uint64_t a, uint64_t start, uint64_t bytes) { return a >= start && a < start + bytes; }
struct Pending { bool verify; uint64_t expected; };
struct Observer {
    Test *test = nullptr;
    BackendOwnershipLedger backend;
    FlowDataPathOwnershipLedger data;
    std::deque<Pending> pending;
    std::map<uint64_t,uint64_t> oracle;
    std::map<std::string,uint64_t> symbols;
    std::string mutation;
    bool previousBusy = false, finished = false;
    unsigned starts = 0, completions = 0, generationMarkers = 0, errorMarkers = 0;
    uint64_t cycles = 0, retired = 0, cpuRamWhileDma = 0, scratchReadsWhileDma = 0, scratchWritesWhileDma = 0;
    uint64_t commitsWhileDma = 0, dirtySourceCycles = 0, dirtyDestinationCycles = 0;
    uint64_t sourceStores = 0, destinationStores = 0, scratchStores = 0, verifiedLoads = 0;
    uint64_t dirtySourceBeats = 0, dirtyDestinationBeats = 0, dmaResidentPeak = 0;
    unsigned oldProbeState = 0, oldProbeBeat = 0;
    bool oldProbeDirty = false;
    uint64_t oldProbeAddress = 0, oldProbeData = 0;
    std::array<uint64_t,4> overlapReads{}, overlapWrites{};
    bool negativeApplied = false;
    static void sample(SBoardSocGsim &d, void *context) { static_cast<Observer*>(context)->sample(d); }
    void initialize(Test &t) {
        test = &t;
        for (unsigned i=0;i<512;++i) {
            t.ddr.memory[uint32_t(src-ramBase+i*8)] = 0xdead000000000000ULL+i;
            t.ddr.memory[uint32_t(dst-ramBase+i*8)] = 0xbeef000000000000ULL+i;
        }
        for (unsigned i=0;i<64;++i) {
            oracle[coldSrc+i*8] = t.ddr.memory[uint32_t(coldSrc-ramBase+i*8)] = cold(i);
            oracle[coldDst+i*8] = t.ddr.memory[uint32_t(coldDst-ramBase+i*8)] = ~cold(i);
        }
        // This cold source is touched only by descriptors 3 and 4. A denied R
        // response is an actual host-to-DUT AXI error, not an oracle mutation.
        t.ddr.denyReadAddress = uint32_t(coldSrc-ramBase);
    }
    void checkDrain(uint64_t source, uint64_t destination, uint64_t bytes) {
        for (const auto &r:test->ddr.pendingReads)
            check(!in(uint64_t(r.address)+ramBase,source,bytes),"DMA idle before source AXI read drain");
        for (const auto &w:test->ddr.pendingWrites)
            check(!in(uint64_t(w.address)+ramBase,destination,bytes),"DMA idle before destination W drain");
        for (const auto &w:test->ddr.pendingB)
            check(!in(uint64_t(w.address)+ramBase,destination,bytes),"DMA idle before destination B drain");
    }
    void sample(SBoardSocGsim &d) {
        ++cycles;
        auto b = BackendObserver::read(d);
        auto p = BackendObserver::readData(d);
        data.flowEvents=d.get_cpuFlowEvents(); data.ingressAuth=d.get_cpuFlowIngressAuth();
        data.checkedAuth=d.get_cpuFlowCheckedAuth(); data.checkedAddress=d.get_cpuFlowCheckedAddress();
        data.checkedData=d.get_cpuFlowCheckedData(); data.checkedHeadAuth=d.get_cpuFlowCheckedHeadAuth();
        data.physicalAuth=d.get_cpuFlowPhysicalAuth();
        if (b.reset) { data.advance(b,p,backend); backend.advance(b); return; }
        if (!negativeApplied && mutation=="--inject-route" && p.bit(P::virtualRequest)) {
            data.flowEvents ^= 1ULL<<1; negativeApplied = true;
        }
        if (!negativeApplied && mutation=="--inject-return-token" && b.reply()) {
            b.slots[b.returnSlot].tag ^= 1; negativeApplied = true;
        }
        check(!d.get_io$$trap$$valid(),"unexpected executing CPU trap");
        const bool busy = d.board$platform$dma$busy;
        unsigned resident = 0;
        for (unsigned slot=0;slot<4;++slot) resident += d.board$platform$dma$phases[slot]!=0;
        dmaResidentPeak = std::max(dmaResidentPeak,uint64_t(resident));
        // pSend is 2. Its only progress transition is a C handshake: increment
        // the beat, or leave pSend on the final beat. This observes the previous
        // cycle's accepted payload without depending on generated temporary names.
        const unsigned probeState=d.board$platform$privateCache$probeState;
        const unsigned probeBeat=d.board$platform$privateCache$probeBeat;
        if (oldProbeState==2 && (probeState!=2 || probeBeat!=oldProbeBeat) && oldProbeDirty) {
            check(probeState==0 || (probeState==2 && probeBeat==oldProbeBeat+1),"dirty probe beat progression mismatch");
            if (in(oldProbeAddress,src,4096) || in(oldProbeAddress,dst,4096)) {
                check(oracle.at(oldProbeAddress+8*oldProbeBeat)==oldProbeData,"independent dirty probe payload mismatch");
                dirtySourceBeats += in(oldProbeAddress,src,4096);
                dirtyDestinationBeats += in(oldProbeAddress,dst,4096);
            }
        }
        oldProbeState=probeState; oldProbeBeat=probeBeat;
        oldProbeDirty=d.board$platform$privateCache$probeDirty;
        oldProbeAddress=d.board$platform$privateCache$probeAddress;
        oldProbeData=probeState==2?d.board$platform$privateCache$probeWords[probeBeat]:0;
        if (test && busy && !previousBusy) {
            ++starts;
            check(starts<=4 && completions+1==starts,"DMA descriptor generation overlap");
            uint64_t source = starts<=2?src:coldSrc, destination = starts<=2?dst:coldDst;
            uint64_t bytes = starts<=2?4096:512;
            check(d.board$platform$dma$source==source && d.board$platform$dma$destination==destination &&
                  d.board$platform$dma$length==bytes,"CPU-programmed DMA descriptor mismatch");
            if (starts<=2) {
                check(sourceStores==starts*512 && destinationStores==starts*512,"DMA began before CPU dirty initialization");
                check(test->ddr.memory[uint32_t(src-ramBase)]!=oracle.at(src),"source backing was not stale at DMA start");
                check(test->ddr.memory[uint32_t(dst-ramBase)]!=oracle.at(dst),"destination backing was not stale at DMA start");
                for (unsigned i=0;i<512;++i)
                    check(oracle.at(src+i*8)==pattern(starts,i),"independent dirty-source generation mismatch");
            }
        }
        if (test && !busy && previousBusy) {
            ++completions;
            check(d.board$platform$dma$done,"DMA dropped busy without completion");
            uint64_t source = starts<=2?src:coldSrc, destination = starts<=2?dst:coldDst;
            uint64_t bytes = starts<=2?4096:512;
            checkDrain(source,destination,bytes);
            check(resident==0 && !d.board$platform$dma$held,"DMA idle before line slots/irrevocable offer drained");
            if (starts==3) {
                check(d.board$platform$dma$failed,"injected AXI R error was not reported");
                // Partial writes before failure are legal; drain is mandatory.
                test->ddr.denyReadAddress.reset();
            } else {
                check(!d.board$platform$dma$failed,"unexpected DMA failure");
                check(d.board$platform$dma$readsSent==bytes/8 && d.board$platform$dma$writesDone==bytes/8,
                      "DMA done before full descriptor retirement");
                for (unsigned i=0;i<bytes/8;++i) {
                    uint64_t expected = starts<=2?pattern(starts,i):cold(i);
                    if (!negativeApplied && mutation=="--inject-destination" && i==0) {
                        expected ^= 1; negativeApplied = true;
                    }
                    check(test->ddr.memory[uint32_t(destination-ramBase+i*8)]==expected,
                          "independent DMA destination generation mismatch");
                    oracle[destination+i*8] = expected;
                }
                if (starts<=2) check(overlapReads[starts-1] && overlapWrites[starts-1],
                    "descriptor lacked simultaneous executed CPU scratch read/write traffic");
            }
        }
        previousBusy = busy;
        if (test && busy) {
            commitsWhileDma += b.commits;
            // These are named registered-state occupancy witnesses, not probe
            // handshake/byte counts. The schema is checked before compilation.
            if (d.board$platform$privateCache$probeState && d.board$platform$privateCache$probeDirty) {
                dirtySourceCycles += in(d.board$platform$privateCache$probeAddress,src,4096);
                dirtyDestinationCycles += in(d.board$platform$privateCache$probeAddress,dst,4096);
            }
        }
        // Independent ordered physical reply queue, in addition to full-token
        // backend/flow lineage. No expected value is taken from a DUT load.
        if (p.bit(P::physicalReply)) {
            check(!pending.empty(),"CPU physical reply without independent owner");
            auto q=pending.front(); pending.pop_front();
            check(p.reply[0].flags==0,"CPU physical memory response error");
            if (q.verify) { check(p.reply[0].data==q.expected,"independent CPU RAM load mismatch"); ++verifiedLoads; }
        }
        if (p.bit(P::physicalRequest)) {
            if (!negativeApplied && mutation=="--inject-read-region" &&
                !p.request[P::physical].write() && in(p.request[P::physical].address,ramBase,0x80000000ULL)) {
                p.request[P::physical].address = 0x80270000ULL; negativeApplied = true;
            }
            const auto &r=p.request[P::physical];
            bool ram = in(r.address,ramBase,0x80000000ULL);
            Pending q{false,0};
            if (ram) {
                check(!(r.address&7) && ((r.meta>>7)&3)==3 && !r.atomic(),"guest RAM request shape changed");
                if (r.write()) {
                    check(((r.meta>>9)&255)==255,"guest RAM write mask changed");
                    if (in(r.address,src,4096)) {
                        auto g=unsigned(sourceStores/512)+1, i=unsigned(sourceStores%512);
                        check(g<=2 && r.address==src+i*8 && r.data==pattern(g,i),"CPU source store generation/order mismatch");
                        ++sourceStores;
                    } else if (in(r.address,dst,4096)) {
                        auto g=unsigned(destinationStores/512)+1, i=unsigned(destinationStores%512);
                        check(g<=2 && r.address==dst+i*8 && r.data==~pattern(g,i),"CPU destination dirty store mismatch");
                        ++destinationStores;
                    } else {
                        check(in(r.address,scratch,64),"unexpected guest RAM write address");
                        unsigned n=unsigned(scratchStores%1032), i=n%8, iteration=n/8;
                        check(r.address==scratch+i*8 && r.data==0x55779900ULL+i+iteration,
                              "intermediate scratch store generation mismatch");
                        ++scratchStores;
                    }
                    check(!busy || in(r.address,scratch,64),"CPU raced DMA-owned source/destination");
                    oracle[r.address]=r.data;
                } else {
                    check(test!=nullptr,"CPU load before host initialization");
                    // Fixed useful regions plus exact one-past speculative guards.
                    // Guard traffic remains in raw ownership and elapsed-cycle counts.
                    const bool useful = in(r.address,src,4096) || in(r.address,dst,4096) ||
                        in(r.address,scratch,64) || in(r.address,coldDst,512);
                    const bool guard = r.address==scratch+64 || r.address==coldDst+512;
                    check(useful || guard,"unexpected guest RAM read region");
                    check(((r.meta>>9)&255)==255,"guest RAM read mask changed");
                    q.verify=true;
                    auto it=oracle.find(r.address);
                    q.expected=it==oracle.end()?test->ddr.memory[uint32_t(r.address-ramBase)]:it->second;
                }
                if (busy) {
                    ++cpuRamWhileDma;
                    if (in(r.address,scratch,64)) {
                        if (r.write()) { ++scratchWritesWhileDma; ++overlapWrites.at(starts-1); }
                        else { ++scratchReadsWhileDma; ++overlapReads.at(starts-1); }
                    }
                }
            }
            pending.push_back(q);
        }
        auto retire=[&](uint64_t pc) {
            ++retired;
            check(pc!=symbols.at("exec_fail"),"executed guest independent check failed");
            generationMarkers += pc==symbols.at("exec_generation_done");
            errorMarkers += pc==symbols.at("exec_error_done");
            if (pc==symbols.at("exec_done")) finished=true;
        };
        if (test) {
            if (d.get_io$$commit0()) retire(d.get_io$$commit0Pc());
            if (d.get_io$$commit1()) retire(d.get_io$$commit1Pc());
        }
        data.advance(b,p,backend); backend.advance(b);
    }
    void verify() {
        check(finished && starts==4 && completions==4 && generationMarkers==2 && errorMarkers==1,
              "executed guest/descriptor completion coverage incomplete");
        check(sourceStores==1024 && destinationStores==1024 && scratchStores==2064,
              "CPU intermediate store conservation failed");
        check(commitsWhileDma && scratchReadsWhileDma && scratchWritesWhileDma,
              "no actual CPU/DMA runtime overlap");
        check(dirtySourceCycles && dirtyDestinationCycles && dirtySourceBeats && dirtyDestinationBeats,
              "missing dirty source/destination coherence witness");
        check(dmaResidentPeak>=2,"configured DMA line pipeline never held multiple residents");
        check(pending.empty() && backend.requests.empty() && backend.responses.empty(),"CPU owners did not drain");
        check(data.fifo.empty() && data.stores.empty() && data.storeOwners.empty() && data.ingress.empty() &&
              data.translated.empty() && data.checked.empty() && data.owners.empty() && data.physicalPending.empty() &&
              data.returns.empty() && !data.waiting && !data.localReply,"CPU flow ownership did not fully drain");
        check(test->ddr.pendingReads.empty() && test->ddr.pendingWrites.empty() && test->ddr.pendingB.empty(),
              "final fence.i did not drain external AXI owners");
        for (const auto &[address,expected]:oracle)
            check(test->ddr.memory[uint32_t(address-ramBase)]==expected,"final flushed RAM oracle mismatch");
        if (PHYSICAL_INGRESS_FLOW) check(data.counters.at("physical_ingress_pass")>0,"enabled CPU ingress shortcut unexercised");
        std::cout << "EXEC_CPU_DMA_PASS descriptors=" << starts << " success=3 injected_read_error=1 restart=1"
                  << " cycles=" << cycles << " retired=" << retired << " cpu_ram_while_dma=" << cpuRamWhileDma
                  << " scratch_reads_while_dma=" << scratchReadsWhileDma << " scratch_writes_while_dma=" << scratchWritesWhileDma
                  << " dirty_source_state_cycles=" << dirtySourceCycles << " dirty_destination_state_cycles=" << dirtyDestinationCycles
                  << " dirty_source_checked_beats=" << dirtySourceBeats << " dirty_destination_checked_beats=" << dirtyDestinationBeats
                  << " dma_resident_slots_peak=" << dmaResidentPeak
                  << " verified_cpu_loads=" << verifiedLoads << " physical_ingress_flow=" << PHYSICAL_INGRESS_FLOW
                  << " physical_ingress_passes=" << data.counters.at("physical_ingress_pass")
                  << " packet_dma=0 mac_cdc=0 stop_abort=unsupported\n";
        data.report();
    }
};
}
int main(int argc,char **argv) {
    try {
        check(argc==3 || argc==4,"usage: run guest.bin symbols.txt [--inject-destination|--inject-route|--inject-return-token|--inject-read-region]");
        Observer o;
        if (argc==4) {
            o.mutation=argv[3];
            check(o.mutation=="--inject-destination" || o.mutation=="--inject-route" || o.mutation=="--inject-return-token" || o.mutation=="--inject-read-region","unknown negative mode");
        }
        std::ifstream symbols(argv[2]); check(bool(symbols),"cannot open guest symbols");
        std::string name; uint64_t value;
        while (symbols>>name>>std::hex>>value) o.symbols[name]=value;
        check(o.symbols.size()==5 && o.symbols.at("_start")==0x80000000,"guest symbol manifest mismatch");
        Test t(readFile(argv[1]),Observer::sample,&o); o.initialize(t);
        while (!o.finished) { check(t.cycles<300000,"bounded executing CPU/DMA fixture timed out"); t.tick(); }
        o.verify(); return 0;
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
