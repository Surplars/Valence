#pragma once
#include <algorithm>
#include <cstdint>
#include <limits>
#include <map>
#include <optional>
#include <ostream>
#include <stdexcept>
#include <string>
#include <utility>

// Passive measurements. No expected ISA values or DUT control are derived here.
struct CycleDistribution {
    uint64_t count = 0, sum = 0, minimum = std::numeric_limits<uint64_t>::max(), maximum = 0;
    void add(uint64_t n) { ++count; sum += n; minimum = std::min(minimum, n); maximum = std::max(maximum, n); }
    void json(std::ostream& o, const char* name) const {
        o << ",\"" << name << "\":{\"count\":" << count << ",\"sum\":" << sum
          << ",\"min\":" << (count ? minimum : 0) << ",\"max\":" << maximum << '}';
    }
};
struct LoadOwnerTiming {
    using Key = std::pair<uint64_t, unsigned>; // full generation and ROB index
    struct Owner { uint64_t start, pc, address; std::optional<uint64_t> result; };
    std::map<Key, Owner> owners;
    std::optional<uint64_t> previousStart;
    uint64_t starts = 0, results = 0, retired = 0;
    CycleDistribution startGap, startToResult, startToRetire, resultToRetire;
    void start(Key key, uint64_t cycle, uint64_t pc, uint64_t address) {
        if (owners.contains(key)) throw std::runtime_error("load timing duplicate full owner");
        owners.emplace(key, Owner{cycle, pc, address, {}});
        if (previousStart) startGap.add(cycle - *previousStart);
        previousStart = cycle; ++starts;
    }
    void result(Key key, uint64_t cycle) {
        auto it = owners.find(key);
        if (it == owners.end()) return; // selected store completion
        if (it->second.result) throw std::runtime_error("load timing duplicate accepted result");
        it->second.result = cycle; startToResult.add(cycle - it->second.start); ++results;
    }
    void commit(Key key, uint64_t cycle, uint64_t pc) {
        auto it = owners.find(key);
        if (it == owners.end() || !it->second.result || it->second.pc != pc)
            throw std::runtime_error("load timing retirement lost full-token start/result owner");
        startToRetire.add(cycle - it->second.start); resultToRetire.add(cycle - *it->second.result);
        owners.erase(it); ++retired;
    }
    void json(std::ostream& o) const {
        o << ",\"load_starts\":" << starts << ",\"accepted_results\":" << results
          << ",\"retired_loads\":" << retired << ",\"unretired_started_owners\":" << owners.size();
        startGap.json(o, "lsu_start_gap"); startToResult.json(o, "lsu_start_to_result");
        startToRetire.json(o, "lsu_start_to_retire"); resultToRetire.json(o, "lsu_result_to_retire");
    }
};
