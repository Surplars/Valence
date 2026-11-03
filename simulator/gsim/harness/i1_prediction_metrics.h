#pragma once
// Shared test-only prediction ledger; include after the independent ISA oracle's need().
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <map>
#include <optional>
#include <string>

struct Resolution { uint64_t pc, predicted, next, cycle; };
struct PredictionCounts { uint64_t count=0, correct=0, directionCount=0, directionCorrect=0; };
template <class Model> struct I1PredictionMetrics {
    std::deque<Resolution> resolved;
    std::map<uint64_t, unsigned> visits, pcKinds;
    std::map<uint64_t, PredictionCounts> perPc, perPcWarm;
    std::optional<Resolution> recovery;
    std::array<PredictionCounts, 4> kinds{};
    PredictionCounts total, warm;
    uint64_t instructions=0, first=0, last=0, redirects=0, fetchStalls=0, memoryStalls=0;
    uint64_t loadStalls=0, mduStalls=0, requests=0, recoveryCount=0, recoverySum=0, recoveryMax=0;
    bool injectObservation=false, injected=false;

    void cycle(Model &d, uint64_t cycle) {
        fetchStalls += d.get_io$$stallFetch(); memoryStalls += d.get_io$$stallMemory();
        loadStalls += d.get_io$$stallLoadUse(); mduStalls += d.get_io$$stallMulDiv();
        requests += d.get_io$$dataRequestAccepted();
        if (d.get_io$$branchMispredict()) ++redirects;
        if (d.get_observation$$resolveValid()) {
            Resolution row{d.get_observation$$resolvePc(), d.get_observation$$resolvePrediction(),
                d.get_observation$$resolveNextPc(), cycle};
            if (injectObservation && !injected) { row.predicted ^= 4; injected=true; }
            if (bool(d.get_io$$branchMispredict()) != (row.predicted != row.next))
                std::cerr << std::hex << "prediction debug pc=" << row.pc << " predicted=" << row.predicted
                    << " next=" << row.next << std::dec << " cycle=" << cycle
                    << " redirect=" << unsigned(d.get_io$$branchMispredict()) << '\n';
            need(bool(d.get_io$$branchMispredict()) == (row.predicted != row.next),
                "prediction observation mismatch: resolved redirect");
            resolved.push_back(row);
        } else need(!d.get_io$$branchMispredict(), "prediction observation mismatch: unclassified redirect");
    }
    void retire(Model &d, uint64_t cycle, uint64_t pc, uint32_t instruction,
                uint64_t next, bool trap) {
        if (recovery) {
            need(pc == recovery->next, "prediction observation mismatch: recovery retirement PC");
            const uint64_t delay=cycle-recovery->cycle;
            ++recoveryCount; recoverySum+=delay; recoveryMax=std::max(recoveryMax,delay); recovery.reset();
        }
        if (trap) { need(instruction==0x00100073, "performance guest stopped on an unexpected trap"); return; }
        if (!instructions) first=cycle;
        last=cycle; ++instructions;
        const unsigned opcode=instruction&127;
        if (opcode!=0x63 && opcode!=0x6f && opcode!=0x67) return;
        need(!resolved.empty(), "prediction observation mismatch: missing resolved owner");
        Resolution row=resolved.front(); resolved.pop_front();
        need(row.pc==pc && row.next==next && row.predicted==d.get_observation$$retiredPrediction(),
            "prediction observation mismatch: retired owner");
        const bool correct=row.predicted==next;
        const bool conditional=opcode==0x63;
        const bool isReturn=opcode==0x67 && ((instruction>>7)&31)==0 &&
            (((instruction>>15)&31)==1 || ((instruction>>15)&31)==5) && instruction>>20==0;
        const unsigned kind=conditional?0:opcode==0x6f?1:isReturn?2:3;
        ++total.count; total.correct+=correct; ++kinds[kind].count; kinds[kind].correct+=correct;
        pcKinds[pc]=kind; ++perPc[pc].count; perPc[pc].correct+=correct;
        // Effective direction is next-PC != fall-through. Targets equal to
        // fall-through are excluded because that direction is not observable.
        if (conditional) {
            const uint32_t encoded=((instruction>>31)<<12)|(((instruction>>7)&1)<<11)|
                (((instruction>>25)&63)<<5)|(((instruction>>8)&15)<<1);
            if (signExtend(encoded,13)!=4) {
                ++total.directionCount; ++kinds[0].directionCount;
                const bool direction=(row.predicted!=pc+4)==(next!=pc+4);
                total.directionCorrect+=direction; kinds[0].directionCorrect+=direction;
            }
        }
        if (visits[pc]++>=8) {
            ++warm.count; warm.correct+=correct; ++perPcWarm[pc].count; perPcWarm[pc].correct+=correct;
        }
        if (!correct) recovery=row;
    }
    void report(const std::string &name,unsigned latency,uint64_t totalCycles) {
        need(resolved.empty() && !recovery, "prediction observation mismatch: unfinished owner ledger");
        need(instructions>100 && last>=first, "performance ROI did not complete");
        std::cout << "I1_PERF name=" << name << " latency=" << latency
            << " retired=" << instructions << " cycles=" << totalCycles << " retirement_window=" << last-first+1
            << " branches=" << total.count << " correct=" << total.correct
            << " conditional=" << kinds[0].count << " conditional_correct=" << kinds[0].correct
            << " direction_queries=" << total.directionCount << " direction_correct=" << total.directionCorrect
            << " direct=" << kinds[1].count << " direct_correct=" << kinds[1].correct
            << " returns=" << kinds[2].count << " returns_correct=" << kinds[2].correct
            << " indirect=" << kinds[3].count << " indirect_correct=" << kinds[3].correct
            << " warm_branches=" << warm.count << " warm_correct=" << warm.correct
            << " redirects=" << redirects << " retired_misses=" << total.count-total.correct
            << " recovery_count=" << recoveryCount << " recovery_sum=" << recoverySum << " recovery_max=" << recoveryMax
            << " fetch_stalls=" << fetchStalls << " memory_stalls=" << memoryStalls
            << " load_use_stalls=" << loadStalls << " mdu_stalls=" << mduStalls << " data_requests=" << requests << '\n';
        need(redirects==total.count-total.correct && recoveryCount==redirects,
            "prediction observation mismatch: redirect/retirement reconciliation");
        uint64_t reconciled=0;
        for (const auto &[pc,counts]:perPc) {
            reconciled+=counts.count;
            std::cout << "I1_PRED_PC name=" << name << " latency=" << latency << " pc=" << pc
                << " kind=" << pcKinds[pc] << " count=" << counts.count << " correct=" << counts.correct
                << " warm_count=" << perPcWarm[pc].count << " warm_correct=" << perPcWarm[pc].correct << '\n';
        }
        need(reconciled==total.count,"prediction observation mismatch: per-PC ledger");
    }
};
