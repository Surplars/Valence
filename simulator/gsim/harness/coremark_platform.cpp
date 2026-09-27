#include "CoremarkPlatformGsim.h"
#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <numeric>
#include <stdexcept>
#include <unordered_map>
#include <vector>

#ifndef ROB_ENTRIES
#define ROB_ENTRIES 32
#endif

static void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}
static void drive(SCoremarkPlatformGsim &dut) {
    dut.set_io$$hold(0);
    dut.set_io$$romWrite(0);
    dut.set_io$$romIndex(0);
    dut.set_io$$romData(0);
    dut.set_io$$inspectRegister(0);
}
int main(int argc, char **argv) {
    try {
        check(argc == 2, "expected CoreMark ROM binary");
        std::ifstream firmware(argv[1], std::ios::binary);
        check(firmware.good(), "cannot open CoreMark firmware");
        std::vector<uint8_t> code((std::istreambuf_iterator<char>(firmware)), {});
        check(!code.empty() && code.size() % 4 == 0 && code.size() <= 16384, "invalid CoreMark ROM size");
        SCoremarkPlatformGsim dut;
        drive(dut);
        dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
        for (unsigned i = 0; i < code.size() / 4; ++i) {
            const uint32_t word = uint32_t(code[4 * i]) | (uint32_t(code[4 * i + 1]) << 8) |
                (uint32_t(code[4 * i + 2]) << 16) | (uint32_t(code[4 * i + 3]) << 24);
            drive(dut);
            dut.set_io$$hold(1);
            dut.set_io$$romWrite(1);
            dut.set_io$$romIndex(i);
            dut.set_io$$romData(word);
            dut.step();
        }
        drive(dut); dut.set_io$$hold(1); dut.step();
        uint64_t retired = 0, waits = 0, gets = 0, redirects = 0, recovering = 0;
        uint64_t committedLoads = 0, committedStores = 0;
        uint64_t loadReplays = 0;
        auto isLoadAt = [&](uint64_t pc) {
            constexpr uint64_t romBase = UINT64_C(0x80000000);
            if (pc < romBase || pc - romBase + 1 >= code.size()) return false;
            const size_t offset = pc - romBase;
            const uint16_t low = uint16_t(code[offset]) | (uint16_t(code[offset + 1]) << 8);
            if ((low & 3) != 3) {
                const unsigned quadrant = low & 3, funct3 = (low >> 13) & 7;
                return (quadrant == 0 || quadrant == 2) && (funct3 == 2 || funct3 == 3);
            }
            if (offset + 3 >= code.size()) return false;
            return (low & 0x7f) == 0x03;
        };
        auto isStoreAt = [&](uint64_t pc) {
            constexpr uint64_t romBase = UINT64_C(0x80000000);
            if (pc < romBase || pc - romBase + 1 >= code.size()) return false;
            const size_t offset = pc - romBase;
            const uint16_t low = uint16_t(code[offset]) | (uint16_t(code[offset + 1]) << 8);
            if ((low & 3) != 3) {
                const unsigned quadrant = low & 3, funct3 = (low >> 13) & 7;
                return (quadrant == 0 || quadrant == 2) && (funct3 == 6 || funct3 == 7);
            }
            if (offset + 3 >= code.size()) return false;
            return (low & 0x7f) == 0x23;
        };
        uint64_t waitWithoutRecovery = 0, zeroCommit = 0, dualCommit = 0, quadCommit = 0, memoryRequests = 0;
        uint64_t ramRequestStalls = 0, ramResponseStalls = 0;
        uint64_t issueZero = 0, issueOne = 0, issueTwo = 0, issueThree = 0, issueFour = 0;
        uint64_t robEmpty = 0, robFull = 0, memoryBusy = 0;
        uint64_t idleRecovery = 0, idleEmpty = 0, idleDone = 0;
        uint64_t idleDependency = 0, idleStructural = 0, idleExecuting = 0;
        uint64_t structuralLoads = 0, structuralStores = 0, structuralOther = 0;
        uint64_t executingLoads = 0, executingStores = 0, executingOther = 0;
        uint64_t structuralStoreStarting = 0, structuralStorePrepared = 0, structuralStoreSlotBlocked = 0;
        uint64_t structuralLoadStarting = 0, structuralLoadSlotBlocked = 0, structuralLoadOther = 0;
        uint64_t headLoadStartNotSelected = 0, headLoadStartCauses[8] = {};
        uint64_t headMemoryRequest = 0, headMemoryResponse = 0, headMemoryDone = 0;
        uint64_t headRequestNotSelected = 0, headRequestCauses[8] = {};
        uint64_t headMemoryDoneBlocked = 0;
        uint64_t headMemoryUntracked = 0, headOtherExecuting = 0;
        uint64_t youngerLoadStoreBlocked = 0, youngerLoadUnknownStoreBlocked = 0;
        uint64_t cacheHits = 0, cacheMisses = 0;
        uint64_t emptySlotMisses = 0, replacementMisses = 0, dirtyEvictions = 0;
        uint64_t readMisses = 0, writeMisses = 0;
        uint64_t missBlockedCycles = 0, bypassBlockedCycles = 0, probeBlockedCycles = 0;
        uint64_t evictionCycles = 0, refillCycles = 0;
        struct StallCycles {
            uint64_t dependency = 0, structural = 0, executing = 0;
            uint64_t memoryRequest = 0, memoryResponse = 0, memoryDone = 0;
        };
        std::unordered_map<uint64_t, StallCycles> headStalls;
        struct StoreBlockCycles { uint64_t blocked = 0, unknown = 0; };
        std::unordered_map<uint64_t, StoreBlockCycles> storeBlockedLoads;
        std::unordered_map<uint64_t, uint64_t> redirectCounts;
        std::unordered_map<uint64_t, uint64_t> commitCounts;
        std::unordered_map<uint64_t, uint32_t> getCounts;
        for (uint64_t cycle = 1; cycle <= 3000000; ++cycle) {
            drive(dut);
            dut.step();
            const bool commit0 = dut.get_io$$commit0(), commit1 = dut.get_io$$commit1();
            const bool commit2 = dut.get_io$$commit2(), commit3 = dut.get_io$$commit3();
            const bool commits[] = {commit0, commit1, commit2, commit3};
            const uint64_t commitPcs[] = {dut.get_io$$commitPc0(), dut.get_io$$commitPc1(),
                dut.get_io$$commitPc2(), dut.get_io$$commitPc3()};
            for (unsigned lane = 0; lane < 4; ++lane) {
                if (!commits[lane]) continue;
                ++retired;
                const auto pc = commitPcs[lane];
                ++commitCounts[pc];
                committedLoads += isLoadAt(pc);
                committedStores += isStoreAt(pc);
            }
            zeroCommit += !commit0;
            dualCommit += commit1;
            quadCommit += commit3;
            const bool fetchWait = dut.get_io$$fetchWait(), recovery = dut.get_io$$recovering();
            const bool redirect = dut.get_io$$redirect();
            waits += fetchWait;
            waitWithoutRecovery += fetchWait && !recovery;
            redirects += redirect;
            if (redirect) {
                const auto pc = dut.get_io$$redirectPc();
                ++redirectCounts[pc];
                loadReplays += isLoadAt(pc);
            }
            recovering += recovery;
            if (!commit0) {
                if (recovery || redirect) ++idleRecovery;
                else if (!dut.get_io$$headProfile$$valid()) ++idleEmpty;
                else if (dut.get_io$$headProfile$$done()) ++idleDone;
                else {
                    auto &stall = headStalls[dut.get_io$$headProfile$$pc()];
                    if (!dut.get_io$$headProfile$$queued()) {
                        ++idleExecuting; ++stall.executing;
                        executingLoads += isLoadAt(dut.get_io$$headProfile$$pc());
                        executingStores += isStoreAt(dut.get_io$$headProfile$$pc());
                        executingOther += !isLoadAt(dut.get_io$$headProfile$$pc()) &&
                            !isStoreAt(dut.get_io$$headProfile$$pc());
                        if (!dut.get_io$$headProfile$$memory()) ++headOtherExecuting;
                        else switch (dut.get_io$$headProfile$$memoryPhase()) {
                            case 1:
                                ++headMemoryRequest; ++stall.memoryRequest;
                                if (!dut.get_io$$headProfile$$memoryRequestSelected()) ++headRequestNotSelected;
                                else {
                                    const unsigned cause = dut.get_io$$headProfile$$memoryRequestStallCause();
                                    check(cause < 8, "head request stall cause out of range");
                                    ++headRequestCauses[cause];
                                }
                                break;
                            case 2: ++headMemoryResponse; ++stall.memoryResponse; break;
                            case 3:
                                ++headMemoryDone; ++stall.memoryDone;
                                headMemoryDoneBlocked += dut.get_io$$headProfile$$memoryCompletionBlocked();
                                break;
                            default: ++headMemoryUntracked; break;
                        }
                    } else if (!dut.get_io$$headProfile$$operandsReady()) {
                        ++idleDependency; ++stall.dependency;
                    } else {
                        ++idleStructural; ++stall.structural;
                        structuralLoads += isLoadAt(dut.get_io$$headProfile$$pc());
                        structuralStores += isStoreAt(dut.get_io$$headProfile$$pc());
                        structuralOther += !isLoadAt(dut.get_io$$headProfile$$pc()) &&
                            !isStoreAt(dut.get_io$$headProfile$$pc());
                        if (isLoadAt(dut.get_io$$headProfile$$pc())) {
                            if (dut.get_io$$headProfile$$memoryStarting()) {
                                ++structuralLoadStarting;
                                if (!dut.get_io$$headProfile$$memoryRequestSelected()) ++headLoadStartNotSelected;
                                else {
                                    const unsigned cause = dut.get_io$$headProfile$$memoryRequestStallCause();
                                    check(cause < 8, "head load start stall cause out of range");
                                    ++headLoadStartCauses[cause];
                                }
                            }
                            else if (!dut.get_io$$headProfile$$memorySlotAvailable()) ++structuralLoadSlotBlocked;
                            else ++structuralLoadOther;
                        }
                        if (isStoreAt(dut.get_io$$headProfile$$pc())) {
                            structuralStoreStarting += dut.get_io$$headProfile$$memoryStarting();
                            structuralStorePrepared += dut.get_io$$headProfile$$storePrepared();
                            structuralStoreSlotBlocked += !dut.get_io$$headProfile$$memorySlotAvailable();
                        }
                    }
                }
            }
            memoryRequests += dut.get_io$$cpuMemoryFire();
            ramRequestStalls += dut.get_io$$ramRequestStall();
            ramResponseStalls += dut.get_io$$ramResponseStall();
            const auto issueCount = dut.get_io$$issueCount(), occupancy = dut.get_io$$robOccupancy();
            issueZero += issueCount == 0;
            issueOne += issueCount == 1;
            issueTwo += issueCount == 2;
            issueThree += issueCount == 3;
            issueFour += issueCount == 4;
            robEmpty += occupancy == 0;
            robFull += occupancy == ROB_ENTRIES;
            memoryBusy += dut.get_io$$memoryBusy();
            if (dut.get_io$$headProfile$$candidateLoadBlockedByStore()) {
                ++youngerLoadStoreBlocked;
                auto &entry = storeBlockedLoads[dut.get_io$$headProfile$$candidateLoadPc()];
                ++entry.blocked;
                if (dut.get_io$$headProfile$$candidateLoadBlockedByUnknownStore()) {
                    ++youngerLoadUnknownStoreBlocked;
                    ++entry.unknown;
                }
            }
            cacheHits += dut.get_io$$cacheHit();
            cacheMisses += dut.get_io$$cacheMiss();
            emptySlotMisses += dut.get_io$$coherentCacheProfile$$emptySlotMiss();
            replacementMisses += dut.get_io$$coherentCacheProfile$$replacementMiss();
            readMisses += dut.get_io$$coherentCacheProfile$$readMiss();
            writeMisses += dut.get_io$$coherentCacheProfile$$writeMiss();
            dirtyEvictions += dut.get_io$$coherentCacheProfile$$dirtyEviction();
            missBlockedCycles += dut.get_io$$coherentCacheProfile$$missBlocked();
            bypassBlockedCycles += dut.get_io$$coherentCacheProfile$$bypassBlocked();
            probeBlockedCycles += dut.get_io$$coherentCacheProfile$$probeBlocked();
            evictionCycles += dut.get_io$$coherentCacheProfile$$evictionCycle();
            refillCycles += dut.get_io$$coherentCacheProfile$$refillCycle();
            if (dut.get_io$$fetchGetFire()) {
                ++gets;
                ++getCounts[dut.get_io$$fetchGetAddress()];
            }
            if (dut.get_io$$trap()) {
                const auto cause = dut.get_io$$trapCause();
                if (cause != 3) {
                    std::cerr << "unexpected trap cause=" << cause << " pc=0x" << std::hex
                              << dut.get_io$$trapPc() << std::dec << " cycle=" << cycle << '\n';
                    throw std::runtime_error("CoreMark trapped before completion");
                }
                auto reg = [&](unsigned index) {
                    drive(dut); dut.set_io$$inspectRegister(index); dut.step();
                    return uint64_t(dut.get_io$$committedValue());
                };
                const auto validationErrors = reg(10), guestTicks = reg(11);
                check(validationErrors == 0, "CoreMark workload validation mismatch");
                check(guestTicks > 0 && guestTicks <= cycle, "CoreMark guest timing invalid");
                check(committedLoads > 100 && committedStores > 100, "ROM memory-op classification coverage");
                check(idleRecovery + idleEmpty + idleDone + idleDependency + idleStructural + idleExecuting ==
                    zeroCommit, "retirement stall categories must partition zero-commit cycles");
                check(headMemoryRequest + headMemoryResponse + headMemoryDone + headMemoryUntracked +
                    headOtherExecuting == idleExecuting, "executing-head phases must partition executing stalls");
                check(headRequestNotSelected +
                    std::accumulate(std::begin(headRequestCauses), std::end(headRequestCauses), uint64_t(0)) ==
                    headMemoryRequest, "head request causes must partition request stalls");
                check(structuralLoads + structuralStores + structuralOther == idleStructural,
                    "structural head classes must partition structural stalls");
                check(structuralLoadStarting + structuralLoadSlotBlocked + structuralLoadOther == structuralLoads,
                    "load start/slot/other classes must partition structural load stalls");
                check(headLoadStartNotSelected +
                    std::accumulate(std::begin(headLoadStartCauses), std::end(headLoadStartCauses), uint64_t(0)) ==
                    structuralLoadStarting, "head load start causes must partition load starts");
                check(executingLoads + executingStores + executingOther == idleExecuting,
                    "executing head classes must partition executing stalls");
                std::vector<std::pair<uint64_t, StallCycles>> hotspots(headStalls.begin(), headStalls.end());
                std::sort(hotspots.begin(), hotspots.end(), [](const auto &a, const auto &b) {
                    const auto total = [](const StallCycles &s) {
                        return s.dependency + s.structural + s.executing;
                    };
                    return total(a.second) > total(b.second);
                });
                std::vector<std::pair<uint64_t, uint64_t>> redirectHotspots(redirectCounts.begin(), redirectCounts.end());
                std::sort(redirectHotspots.begin(), redirectHotspots.end(), [](const auto &a, const auto &b) {
                    return a.second > b.second;
                });
                std::vector<std::pair<uint64_t, StoreBlockCycles>> storeBlockedHotspots(
                    storeBlockedLoads.begin(), storeBlockedLoads.end());
                std::sort(storeBlockedHotspots.begin(), storeBlockedHotspots.end(), [](const auto &a, const auto &b) {
                    return a.second.blocked > b.second.blocked;
                });
                std::cout << "COREMARK {\"validation_errors\":" << validationErrors << ",\"guest_ticks\":" << guestTicks
                          << ",\"total_cycles\":" << cycle << ",\"retired\":" << retired
                          << ",\"committed_loads\":" << committedLoads
                          << ",\"committed_stores\":" << committedStores
                          << ",\"ipc\":" << std::setprecision(8) << double(retired) / cycle
                          << ",\"fetch_wait_cycles\":" << waits << ",\"fetch_gets\":" << gets
                          << ",\"unique_fetch_beats\":" << getCounts.size()
                          << ",\"redirects\":" << redirects << ",\"load_replays\":" << loadReplays
                          << ",\"recovery_cycles\":" << recovering
                          << ",\"fetch_wait_without_recovery\":" << waitWithoutRecovery
                          << ",\"zero_commit_cycles\":" << zeroCommit << ",\"dual_commit_cycles\":" << dualCommit
                          << ",\"quad_commit_cycles\":" << quadCommit
                          << ",\"cpu_memory_requests\":" << memoryRequests
                          << ",\"ram_request_stalls\":" << ramRequestStalls
                          << ",\"ram_response_stalls\":" << ramResponseStalls
                          << ",\"issue_zero_cycles\":" << issueZero
                          << ",\"issue_one_cycles\":" << issueOne
                          << ",\"issue_two_cycles\":" << issueTwo
                          << ",\"issue_three_cycles\":" << issueThree
                          << ",\"issue_four_cycles\":" << issueFour
                          << ",\"rob_empty_cycles\":" << robEmpty
                          << ",\"rob_full_cycles\":" << robFull
                          << ",\"memory_busy_cycles\":" << memoryBusy
                          << ",\"cache_hits\":" << cacheHits
                          << ",\"cache_misses\":" << cacheMisses
                          << ",\"cache_empty_slot_misses\":" << emptySlotMisses
                          << ",\"cache_replacement_misses\":" << replacementMisses
                          << ",\"cache_read_misses\":" << readMisses
                          << ",\"cache_write_misses\":" << writeMisses
                          << ",\"cache_dirty_evictions\":" << dirtyEvictions
                          << ",\"cache_miss_blocked_cycles\":" << missBlockedCycles
                          << ",\"cache_bypass_blocked_cycles\":" << bypassBlockedCycles
                          << ",\"cache_probe_blocked_cycles\":" << probeBlockedCycles
                          << ",\"cache_eviction_cycles\":" << evictionCycles
                          << ",\"cache_refill_cycles\":" << refillCycles
                          << ",\"idle_recovery_cycles\":" << idleRecovery
                          << ",\"idle_empty_cycles\":" << idleEmpty
                          << ",\"idle_done_cycles\":" << idleDone
                          << ",\"idle_dependency_cycles\":" << idleDependency
                          << ",\"idle_structural_cycles\":" << idleStructural
                          << ",\"idle_executing_cycles\":" << idleExecuting
                          << ",\"structural_load_cycles\":" << structuralLoads
                          << ",\"younger_load_store_blocked_cycles\":" << youngerLoadStoreBlocked
                          << ",\"younger_load_unknown_store_blocked_cycles\":" << youngerLoadUnknownStoreBlocked
                          << ",\"structural_load_starting_cycles\":" << structuralLoadStarting
                          << ",\"head_load_start_not_selected\":" << headLoadStartNotSelected
                          << ",\"head_load_start_stall_causes\":[";
                for (unsigned i = 0; i < 8; ++i) {
                    if (i) std::cout << ',';
                    std::cout << headLoadStartCauses[i];
                }
                std::cout << ']'
                          << ",\"structural_load_slot_blocked_cycles\":" << structuralLoadSlotBlocked
                          << ",\"structural_load_other_cycles\":" << structuralLoadOther
                          << ",\"structural_store_cycles\":" << structuralStores
                          << ",\"structural_other_cycles\":" << structuralOther
                          << ",\"structural_store_starting_cycles\":" << structuralStoreStarting
                          << ",\"structural_store_prepared_cycles\":" << structuralStorePrepared
                          << ",\"structural_store_slot_blocked_cycles\":" << structuralStoreSlotBlocked
                          << ",\"executing_load_cycles\":" << executingLoads
                          << ",\"executing_store_cycles\":" << executingStores
                          << ",\"executing_other_cycles\":" << executingOther
                          << ",\"head_memory_request_cycles\":" << headMemoryRequest
                          << ",\"head_memory_request_not_selected\":" << headRequestNotSelected
                          << ",\"head_memory_request_stall_causes\":[";
                for (unsigned i = 0; i < 8; ++i) {
                    if (i) std::cout << ',';
                    std::cout << headRequestCauses[i];
                }
                std::cout << ']'
                          << ",\"head_memory_response_cycles\":" << headMemoryResponse
                          << ",\"head_memory_done_cycles\":" << headMemoryDone
                          << ",\"head_memory_done_blocked_cycles\":" << headMemoryDoneBlocked
                          << ",\"head_memory_untracked_cycles\":" << headMemoryUntracked
                          << ",\"head_other_executing_cycles\":" << headOtherExecuting
                          << ",\"head_stall_hotspots\":[";
                for (size_t i = 0; i < std::min<size_t>(12, hotspots.size()); ++i) {
                    if (i) std::cout << ',';
                    const auto &[pc, stalls] = hotspots[i];
                    std::cout << "{\"pc\":" << pc << ",\"dependency\":" << stalls.dependency
                              << ",\"structural\":" << stalls.structural
                              << ",\"executing\":" << stalls.executing
                              << ",\"memory_request\":" << stalls.memoryRequest
                              << ",\"memory_response\":" << stalls.memoryResponse
                              << ",\"memory_done\":" << stalls.memoryDone << '}';
                }
                std::cout << "],\"store_blocked_load_hotspots\":[";
                for (size_t i = 0; i < std::min<size_t>(12, storeBlockedHotspots.size()); ++i) {
                    if (i) std::cout << ',';
                    std::cout << "{\"pc\":" << storeBlockedHotspots[i].first
                              << ",\"blocked\":" << storeBlockedHotspots[i].second.blocked
                              << ",\"unknown\":" << storeBlockedHotspots[i].second.unknown << '}';
                }
                std::cout << "],\"redirect_hotspots\":[";
                for (size_t i = 0; i < std::min<size_t>(16, redirectHotspots.size()); ++i) {
                    if (i) std::cout << ',';
                    std::cout << "{\"pc\":" << redirectHotspots[i].first
                              << ",\"count\":" << redirectHotspots[i].second
                              << ",\"commits\":" << commitCounts[redirectHotspots[i].first] << '}';
                }
                std::cout << "]}\n";
                return 0;
            }
        }
        throw std::runtime_error("CoreMark did not finish within 3 million guest cycles");
    } catch (const std::exception &e) {
        std::cerr << "COREMARK FAIL: " << e.what() << '\n';
        return 1;
    }
}
