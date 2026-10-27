#include "DualWriterRobCompletionDataGsim.h"
#include "completion_payload_byte_oracle.h"
#include <iostream>
#include <map>
#include <random>
#include <string>
using namespace completion_bytes;

static void drive_write(SDualWriterRobCompletionDataGsim &m, unsigned lane, const Write &w) {
#define W(N) case N: m.set_io$$write##N##$$valid(w.valid); m.set_io$$write##N##$$bits$$index(w.index); \
    m.set_io$$write##N##$$bits$$data(w.value.data); m.set_io$$write##N##$$bits$$nextPc(w.value.next_pc); \
    m.set_io$$write##N##$$bits$$tval(w.value.tval); break
    switch (lane) { W(0); W(1); default: throw std::runtime_error("ORACLE_BAD_LANE"); }
#undef W
}
int main(int argc, char **argv) { try {
    const std::string mode = argc == 2 ? argv[1] : "";
    require(argc <= 2 && (mode.empty() || mode == "--observe-data-byte" || mode == "--observe-nextpc-field" ||
        mode == "--observe-tval-high" || mode == "--assert-duplicate" || mode == "--rtl-write-field-swap" ||
        mode == "--rtl-write-index-xor1" || mode == "--rtl-output-lane-swap"), "RAW_COMPLETION_BAD_ARGUMENT");
    const unsigned rtl_mutation = mode == "--rtl-write-field-swap" ? 1 : mode == "--rtl-write-index-xor1" ? 2 :
        mode == "--rtl-output-lane-swap" ? 3 : 0;
    SDualWriterRobCompletionDataGsim m;
    m.set_io$$mutation(rtl_mutation);
    bool rtl_reached = false;
    std::array<FlatMemory, 4> memory{FlatMemory(4), FlatMemory(8), FlatMemory(16), FlatMemory(32)};
    std::map<std::string, uint64_t> cover;
    std::mt19937_64 rng(UINT64_C(0x618ca4d280b5e3f7));
    bool mutated = false;
    uint64_t serial = 1;
    auto tick = [&](unsigned select, unsigned head, const std::array<Write, 2> &writes, bool reset = false) {
        auto &gold = memory[select]; const unsigned next = head + 1 == gold.size() ? 0 : head + 1;
        m.set_io$$select(select); m.set_io$$head(head); m.set_reset(reset);
        bool defined_domain = true;
        for (unsigned row = 0; row < gold.size(); ++row) defined_domain &= gold.rows[row].defined;
        const unsigned active_mutation = defined_domain ? rtl_mutation : 0;
        m.set_io$$mutation(active_mutation);
        if (active_mutation && !rtl_reached) {
            std::cerr << "RAW_COMPLETION_RTL_BOUNDARY_MUTATION_REACHED " << mode << '\n';
            rtl_reached = true;
        }
        drive_write(m, 0, writes[0]); drive_write(m, 1, writes[1]);
        m.step();
        std::array<uint64_t, 2> data{m.get_io$$data0(), m.get_io$$data1()};
        std::array<uint64_t, 2> nextpc{m.get_io$$nextPc0(), m.get_io$$nextPc1()};
        uint64_t tval = m.get_io$$headTval();
        if (!mutated && mode.starts_with("--observe-") && gold.rows[head].defined) {
            if (mode == "--observe-data-byte") data[0] ^= UINT64_C(1) << 56;
            if (mode == "--observe-nextpc-field") nextpc[0] = field(gold.rows[head], 0);
            if (mode == "--observe-tval-high") tval ^= UINT64_C(1) << 63;
            mutated = true; std::cerr << "RAW_COMPLETION_OBSERVATION_MUTATION_REACHED " << mode << '\n';
        }
        for (unsigned lane = 0; lane < 2; ++lane) {
            const unsigned row = lane ? next : head;
            if (gold.rows[row].defined) {
                compare_field(data[lane], gold.rows[row], 0, "RAW_COMPLETION_DATA_BYTE_ORACLE");
                compare_field(nextpc[lane], gold.rows[row], 1, "RAW_COMPLETION_NEXTPC_BYTE_ORACLE");
                ++cover["defined_reads"];
                for (const auto &w : writes) cover["old_value_read_write"] += w.valid && w.index == row;
            } else ++cover["undefined_reads_skipped"];
        }
        if (gold.rows[head].defined) compare_field(tval, gold.rows[head], 2, "RAW_COMPLETION_TVAL_BYTE_ORACLE");
        if (writes[0].valid && writes[1].valid) {
            ++cover["dual_write"];
            cover["dual_same_parity"] += (writes[0].index % 2) == (writes[1].index % 2);
            cover["reversed_index_order"] += writes[0].index > writes[1].index;
        }
        cover["wrap_read"] += head + 1 == gold.size();
        cover["reset_preserved_defined"] += reset && gold.rows[head].defined;
        cover["reset_write"] += reset && (writes[0].valid || writes[1].valid);
        gold.write(writes); ++cover["cycles"];
    };
    // Unknown physical bytes are deliberately not observed as initialized zeros.
    for (unsigned select = 0; select < 4; ++select) tick(select, 0, {}, true);
    for (unsigned select = 0; select < 4; ++select) {
        const unsigned n = memory[select].size();
        for (unsigned row = 0; row < n; ++row) {
            std::array<Write, 2> w{}; w[row % 2] = {true, row, pattern(serial++)}; tick(select, row, w);
        }
        // Opposite writer overwrites prove latest-writer selection both ways;
        // reversed same-parity arbitrary rows prove no even/odd conflict bubble.
        for (unsigned pass = 0; pass < 4; ++pass) for (unsigned row = 0; row < n; ++row) {
            std::array<Write, 2> w{};
            const unsigned lane = (row + pass + 1) % 2;
            w[lane] = {true, row, pattern(serial++)};
            w[1 - lane] = {true, (row + 2) % n, pattern(serial++)}; tick(select, row, w);
        }
        for (unsigned cycle = 0; cycle < 4096; ++cycle) {
            std::array<Write, 2> w{};
            w[0] = {rng() % 4 != 0, unsigned(rng() % n), pattern(serial++)};
            w[1] = {rng() % 4 != 0, unsigned(rng() % n), pattern(serial++)};
            if (w[1].index == w[0].index) w[1].index = (w[1].index + 1) % n;
            tick(select, unsigned(rng() % n), w, cycle == 1024 || cycle == 2048);
        }
        for (unsigned row = 0; row < n; ++row) tick(select, row, {});
    }
    if (mode == "--assert-duplicate") {
        std::cerr << "RAW_COMPLETION_DUPLICATE_ASSERTION_REACHED\n";
        std::array<Write, 2> w{{{true, 2, pattern(serial++)}, {true, 2, pattern(serial++)}}};
        m.set_io$$select(2); m.set_io$$head(2); m.set_reset(0);
        drive_write(m, 0, w[0]); drive_write(m, 1, w[1]); m.step();
        throw std::runtime_error("NEGATIVE_CONTROL_ESCAPED");
    }
    require(mode.empty(), "NEGATIVE_CONTROL_ESCAPED");
    for (const auto *name : {"dual_write", "dual_same_parity", "reversed_index_order", "wrap_read",
            "old_value_read_write", "reset_preserved_defined", "reset_write", "undefined_reads_skipped"})
        require(cover[name] > 0, std::string("RAW_COMPLETION_MISSING_COVERAGE ") + name);
    std::cout << "RAW_COMPLETION_BYTE_ORACLE_PASS geometries=4,8,16,32";
    for (const auto &[key, value] : cover) std::cout << ' ' << key << '=' << value;
    std::cout << " raw_uninitialized_not_zero=1 bank_formula_in_oracle=0\n";
    return 0;
} catch (const std::exception &e) { std::cerr << "RAW_COMPLETION_FAIL " << e.what() << '\n'; return 1; } }
