#ifndef DDR_MULTI_ID_MODEL
#error "The matched virtual-load board experiment requires the same multi-ID AXI model"
#endif
#define main board_boot_regression_main
#include "board_boot.cpp"
#undef main
#include "backend_observer.h"
#include "performance_observer.h"
#include "virtual_load_guest_symbols.h"
#include <array>
#include <deque>
#include <map>
#include <optional>

namespace {
constexpr uint64_t virtualBase = 0x40000000ULL;
constexpr uint64_t dataBase = 0x80400000ULL;
constexpr uint64_t signatureBase = 0x80600000ULL;
constexpr uint64_t tableBase = 0x80300000ULL;
constexpr uint64_t expectedFaultVa = virtualBase + 8 * 4096;
constexpr uint64_t uartLsr = 0x10000005ULL;
struct PhysicalOwner { uint64_t address, expected; bool write, device; };
struct Region {
    const char *name;
    uint64_t begin, end;
    PerfCounts perf;
    uint64_t physicalRequests = 0, physicalReplies = 0, parallelStarts = 0;
    uint64_t physicalPeak = 0, lsuPeak = 0, axiPeak = 0, multiplePhysicalCycles = 0;
    uint64_t beginCycle = 0, endCycle = 0, pcTrace = 1469598103934665603ULL;
    bool begun = false, finished = false;
};
struct Observer {
    Test *test = nullptr;
    BackendOwnershipLedger ownership;
    std::map<uint64_t, uint64_t> reference;
    std::deque<PhysicalOwner> physical;
    std::array<Region, 3> regions{{
        {"warm_independent", VIRTUAL_GUEST_WARM_BEGIN, VIRTUAL_GUEST_WARM_END},
        {"cold_pages", VIRTUAL_GUEST_COLD_BEGIN, VIRTUAL_GUEST_COLD_END},
        {"dependent_chase", VIRTUAL_GUEST_CHASE_BEGIN, VIRTUAL_GUEST_CHASE_END}}};
    std::optional<unsigned> active;
    bool entered = false, cancelRegion = false, finished = false;
    bool injectSignature = false, injectTrap = false, injectMarker = false;
    uint64_t cycles = 0, guestRetired = 0, guestTrace = 1469598103934665603ULL;
    uint64_t traps = 0, lsrReads = 0, physicalRequests = 0, physicalReplies = 0, physicalPeak = 0;
    uint64_t trapPc = 0, trapVa = 0, trapCause = 0;
    static bool bit(uint64_t value, unsigned index) { return (value >> index) & 1; }
    static void sample(SBoardSocGsim &d, void *context) {
        static_cast<Observer *>(context)->sample(d);
    }
    void sample(SBoardSocGsim &d) {
        const auto backend = BackendObserver::read(d);
        ownership.advance(backend);
        if (backend.reset) { physical.clear(); ++cycles; return; }
        if (d.get_io$$trap$$valid()) {
            trapPc = d.get_io$$trap$$bits$$pc(); trapVa = d.get_io$$trap$$bits$$tval();
            trapCause = d.get_io$$trap$$bits$$cause(); ++traps;
            check(entered && traps == 1 && trapPc == VIRTUAL_GUEST_FAULT_LOAD && trapCause == 13 &&
                trapVa == (expectedFaultVa ^ (injectTrap ? 8ULL : 0ULL)), "independent full-core trap provenance mismatch");
            // This precisely verified trap is part of the guest. Every other trap
            // remains fatal, including any before Test construction has completed.
            check(test != nullptr, "guest trap before host initialization");
            test->running = false;
        }
        std::array<unsigned, 3> included{};
        std::array<bool, 3> includeCycle{};
        if (active) includeCycle[*active] = true;
        for (unsigned lane = 0; lane < 2; ++lane) {
            const bool valid = lane ? d.get_io$$commit1() : d.get_io$$commit0();
            const uint64_t pc = lane ? d.get_io$$commit1Pc() : d.get_io$$commit0Pc();
            if (!valid) continue;
            if (pc == VIRTUAL_GUEST_ENTRY) entered = true;
            if (!entered) continue;
            check(pc >= ramBase && pc < VIRTUAL_GUEST_IMAGE_END, "guest retired outside frozen executable image");
            check(pc != VIRTUAL_GUEST_FAIL, "guest architectural self-check reached fail");
            check(pc < VIRTUAL_GUEST_WRONG_PATH_BEGIN || pc >= VIRTUAL_GUEST_WRONG_PATH_END,
                "cancelled wrong-path instruction retired");
            ++guestRetired; guestTrace ^= pc; guestTrace *= 1099511628211ULL;
            if (pc == VIRTUAL_GUEST_CANCEL_BEGIN) { check(lsrReads == 1, "missing device-TLB warmup"); cancelRegion = true; }
            for (unsigned region = 0; region < regions.size(); ++region) {
                auto &r = regions[region];
                if (pc == r.begin) {
                    check(!active && !r.begun && (region == 0 || regions[region - 1].finished),
                        "ROI boundary order/uniqueness mismatch");
                    active = region; r.begun = true; r.beginCycle = cycles; includeCycle[region] = true;
                }
            }
            if (active) {
                auto &r = regions[*active]; ++included[*active];
                r.pcTrace ^= pc; r.pcTrace *= 1099511628211ULL;
                const uint64_t end = r.end + ((injectMarker && *active == 0) ? 2 : 0);
                if (pc == end) { r.finished = true; r.endCycle = cycles; active.reset(); }
            }
            if (pc == VIRTUAL_GUEST_DONE) {
                check(!active && std::all_of(regions.begin(), regions.end(), [](const Region &r) { return r.finished; }),
                    "ROI boundary completion mismatch");
                finished = true;
                break;
            }
        }
        const uint64_t events = d.get_dataPathEvents();
        const bool response = bit(events, 21), request = bit(events, 19);
        if (response) {
            check(!physical.empty(), "physical reply lost independent ordered owner");
            auto owner = physical.front(); physical.pop_front();
            check(d.get_dataPathReply0Flags() == 0, "unexpected physical data error/page fault");
            if (!owner.write && !owner.device)
                check(d.get_dataPathReply0Data() == owner.expected, "independent physical read-data oracle mismatch");
            ++physicalReplies;
        }
        if (request) {
            const uint64_t address = d.get_dataPathRequest9Address(), data = d.get_dataPathRequest9Data();
            const uint64_t meta = d.get_dataPathRequest9Meta();
            const bool write = meta & 1, device = address < ramBase;
            check(!(meta & (1ULL << 17)), "virtual address escaped physical adapter");
            if (entered && device) {
                check(address == uartLsr && !write && !cancelRegion && lsrReads == 0,
                    "forbidden speculative MMIO request"); ++lsrReads;
            }
            if (entered && !device) check(address < uint64_t(ramBase) + BOARD_DDR_BYTES, "physical data outside DDR aperture");
            const uint64_t aligned = address & ~7ULL;
            const auto value = reference.find(aligned);
            const uint64_t expected = value == reference.end() ? 0 : value->second;
            if (write && !device) {
                uint64_t result = expected; const unsigned mask = (meta >> 9) & 255;
                for (unsigned byte = 0; byte < 8; ++byte) if (mask & (1U << byte))
                    result = (result & ~(255ULL << (8 * byte))) | (data & (255ULL << (8 * byte)));
                reference[aligned] = result;
            }
            physical.push_back({address, expected, write, device}); ++physicalRequests;
            physicalPeak = std::max<uint64_t>(physicalPeak, physical.size());
        }
        for (unsigned region = 0; region < regions.size(); ++region) if (includeCycle[region]) {
            auto &r = regions[region]; const unsigned allCommits = backend.commits;
            const uint64_t priorRetired = r.perf.retired;
            r.perf.sample(d);
            // Cycle bounds are inclusive, while retirement is lane-exact: an
            // instruction beside the begin/end marker stays outside its ROI.
            r.perf.retired = priorRetired + included[region];
            --r.perf.commits[allCommits]; ++r.perf.commits[included[region]];
            r.physicalRequests += request; r.physicalReplies += response;
            r.parallelStarts += backend.bit(3) && backend.bit(8);
            r.physicalPeak = std::max<uint64_t>(r.physicalPeak, physical.size());
            r.multiplePhysicalCycles += physical.size() > 1;
            r.lsuPeak = std::max<uint64_t>(r.lsuPeak, unsigned(backend.live[0]) + unsigned(backend.live[1]));
            if (test) r.axiPeak = std::max<uint64_t>(r.axiPeak, test->ddr.pendingReads.size());
        }
        ++cycles;
    }
    void initialize(Test &t, const Bytes &image) {
        test = &t;
        auto put = [&](uint64_t address, uint64_t value) {
            reference[address] = value; t.ddr.memory[uint32_t(address - ramBase)] = value;
        };
        for (size_t offset = 0; offset < image.size(); offset += 8) {
            uint64_t value = 0;
            for (unsigned byte = 0; byte < 8 && offset + byte < image.size(); ++byte)
                value |= uint64_t(image[offset + byte]) << (8 * byte);
            put(ramBase + offset, value);
        }
        put(tableBase + 8, (((tableBase + 4096) >> 12) << 10) | 1);
        put(tableBase + 4096, (((tableBase + 8192) >> 12) << 10) | 1);
        for (unsigned page = 0; page < 8; ++page) {
            const uint64_t address = page == 7 ? 0x10000000ULL : page == 6 ? dataBase : dataBase + page * 4096;
            put(tableBase + 8192 + page * 8, ((address >> 12) << 10) | 0xc7);
        }
        for (unsigned word = 0; word < 8; ++word) put(dataBase + 8 * word, word + 1);
        for (unsigned node = 0; node < 64; ++node)
            put(dataBase + 4096 + node * 64, virtualBase + 4096 + ((node + 1) % 64) * 64);
        for (unsigned page = 2; page <= 5; ++page) put(dataBase + page * 4096, 0x100 + page);
        for (unsigned word = 0; word < 10; ++word) put(signatureBase + word * 8, 0);
    }
    void verify() const {
        check(finished && traps == 1 && lsrReads == 1, "missing guest completion/trap/device witnesses");
        check(physical.empty() && ownership.requests.empty() && ownership.responses.empty(),
            "done marker preceded accepted memory drain");
        uint64_t warm = 0, cold = 0;
        for (unsigned repetition = 0; repetition < 64; ++repetition)
            for (unsigned word = 1; word <= 8; ++word) warm += word;
        for (unsigned page = 2; page <= 5; ++page) cold += 0x100 + page;
        const uint64_t chase = virtualBase + 4096 + (256 % 64) * 64;
        const std::array<uint64_t, 10> expected{{0x564952544c4f4144ULL, warm ^ (injectSignature ? 1ULL : 0ULL),
            cold, chase, 0x123, 1, 13, expectedFaultVa, VIRTUAL_GUEST_FAULT_LOAD, 0x99}};
        for (unsigned word = 0; word < expected.size(); ++word) {
            auto actual = test->ddr.memory.find(uint32_t(signatureBase - ramBase + word * 8));
            check(actual != test->ddr.memory.end() && actual->second == expected[word],
                "independent full-core signature mismatch word=" + std::to_string(word));
        }
        check(test->ddr.memory.at(uint32_t(dataBase - ramBase)) == 0x99, "physical alias store missing from flushed DDR backing");
    }
    void report() {
        for (auto &r : regions) {
            check(r.perf.cycles == r.endCycle - r.beginCycle + 1 && r.perf.retired > 0, "ROI cycle/retirement conservation");
            r.perf.report(r.name);
            std::cout << "VIRTUAL_BOARD_ROI name=" << r.name << " cycles=" << r.perf.cycles << " retired=" << r.perf.retired
                << " pc_trace=" << r.pcTrace << " physical_requests=" << r.physicalRequests << " physical_replies=" << r.physicalReplies
                << " physical_peak=" << r.physicalPeak << " lsu_peak=" << r.lsuPeak << " axi_peak=" << r.axiPeak
                << " parallel_starts=" << r.parallelStarts << " multiple_physical_cycles=" << r.multiplePhysicalCycles << "\n";
        }
        uint64_t signatureHash = 1469598103934665603ULL;
        for (unsigned word = 0; word < 10; ++word) {
            signatureHash ^= test->ddr.memory.at(uint32_t(signatureBase - ramBase + word * 8));
            signatureHash *= 1099511628211ULL;
        }
        std::cout << "VIRTUAL_BOARD_ARCH signature_hash=" << signatureHash << " retired=" << guestRetired << " pc_trace=" << guestTrace << " traps=" << traps
            << " trap_pc=" << trapPc << " trap_cause=" << trapCause << " trap_tval=" << trapVa
            << " lsr_reads=" << lsrReads << " owner_checks=" << ownership.checks
            << " cancelled_outstanding_cycles=" << ownership.cancellationWhileOutstanding << "\n";
        std::cout << "VIRTUAL_BOARD_PASS total_cycles=" << cycles << " regions=3 physical_peak=" << physicalPeak
            << " DDR_READ_LATENCY=" << DDR_READ_LATENCY << " DDR_READ_CREDITS=" << DDR_READ_CREDITS
            << " DDR_READ_BEAT_GAP=" << DDR_READ_BEAT_GAP << " forced_response_holds=0\n";
    }
};
}
int main(int argc, char **argv) { try {
    check(argc >= 2 && argc <= 3, "usage: run guest.bin [--inject-signature|--inject-trap|--inject-marker]");
    Observer observer;
    const std::string mutation = argc == 3 ? argv[2] : "";
    observer.injectSignature = mutation == "--inject-signature";
    observer.injectTrap = mutation == "--inject-trap";
    observer.injectMarker = mutation == "--inject-marker";
    check(mutation.empty() || observer.injectSignature || observer.injectTrap || observer.injectMarker, "unknown oracle mutation");
    const auto image = readFile(argv[1]); check(!image.empty() && image.size() < 0x100000, "guest binary bounds");
    Bytes rom; word(rom, 0x00200297); word(rom, 0x10000337); word(rom, 0x00700393); word(rom, 0x00730123);
    word(rom, 0x000280e7); word(rom, 0x0000006f);
    Test test(rom, Observer::sample, &observer); observer.initialize(test, image);
    while (!observer.finished && test.cycles < 1000000) {
        test.running = true; test.tick();
        check(test.received.empty(), "guest unexpectedly emitted UART output");
        if (test.cycles % 100000 == 0) std::cout << "VIRTUAL_BOARD_PROGRESS cycles=" << test.cycles << "\n" << std::flush;
    }
    check(observer.finished, "bounded virtual-load full-core guest timed out");
    observer.verify(); observer.report(); return 0;
} catch (const std::exception &error) { std::cerr << "VIRTUAL_BOARD_FAIL " << error.what() << "\n"; return 1; } }
