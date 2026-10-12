#include "Rank1PrfAddressPairGsim.h"
#include <array>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <type_traits>

namespace {
constexpr unsigned slots = 16, registers = 48;
struct Row {
    bool programmed = false;
    unsigned source1 = 0, source2 = 0;
    uint64_t tag = 0, immediate = 0;
    bool store = false;
    unsigned size = 0;
    bool saved = false;
    uint64_t savedAddress = 0, savedData = 0;
};
struct Write { bool valid = false; unsigned address = 63; uint64_t data = 0; };
struct Input {
    unsigned eligible = 0, head = 0;
    bool issued = false;
    unsigned issuedIndex = 0;
    bool ready = true, rowWrite = false;
    unsigned rowIndex = 0;
    Row row;
    std::array<Write, 2> writes;
};
struct Rank {
    bool valid = false;
    unsigned index = 0, owner = 0, source1 = 0, source2 = 0;
    uint64_t left = 0, right = 0, immediate = 0, address = 0, data = 0, tag = 0;
    bool store = false;
    unsigned size = 0;
    bool saved = false;
    bool operator==(const Rank&) const = default;
};
struct Payload {
    unsigned index = 0;
    uint64_t tag = 0, address = 0, data = 0;
    unsigned size = 0;
    bool operator==(const Payload&) const = default;
};
struct Observation {
    std::array<Rank, 2> ranks;
    bool selectedValid = false;
    unsigned selectedIndex = 0;
    bool useSecond = false, requestFire = false;
    Payload request;
    bool completeFire = false;
    Payload complete;
    uint64_t requestCount = 0, completeCount = 0;
    bool operator==(const Observation&) const = default;
};

static Observation read(SRank1PrfAddressPairGsim& d, bool candidate) {
    Observation o;
#define RANK(P,N) \
    o.ranks[N] = {bool(d.get_io$$##P##$$rank##N##$$valid()), \
        unsigned(d.get_io$$##P##$$rank##N##$$index()), unsigned(d.get_io$$##P##$$rank##N##$$owner()), \
        unsigned(d.get_io$$##P##$$rank##N##$$source1()), unsigned(d.get_io$$##P##$$rank##N##$$source2()), \
        d.get_io$$##P##$$rank##N##$$left(), d.get_io$$##P##$$rank##N##$$right(), \
        d.get_io$$##P##$$rank##N##$$immediate(), d.get_io$$##P##$$rank##N##$$address(), \
        d.get_io$$##P##$$rank##N##$$data(), d.get_io$$##P##$$rank##N##$$tag(), \
        bool(d.get_io$$##P##$$rank##N##$$store()), unsigned(d.get_io$$##P##$$rank##N##$$size()), \
        bool(d.get_io$$##P##$$rank##N##$$saved())}
#define SIDE(P) \
    RANK(P,0); RANK(P,1); \
    o.selectedValid = d.get_io$$##P##$$selectedValid(); \
    o.selectedIndex = d.get_io$$##P##$$selectedIndex(); o.useSecond = d.get_io$$##P##$$useSecond(); \
    o.requestFire = d.get_io$$##P##$$requestFire(); \
    o.request = {unsigned(d.get_io$$##P##$$requestIndex()), d.get_io$$##P##$$requestTag(), \
        d.get_io$$##P##$$requestAddress(), d.get_io$$##P##$$requestData(), unsigned(d.get_io$$##P##$$requestSize())}; \
    o.completeFire = d.get_io$$##P##$$completeFire(); \
    o.complete = {unsigned(d.get_io$$##P##$$completeIndex()), d.get_io$$##P##$$completeTag(), \
        d.get_io$$##P##$$completeAddress(), d.get_io$$##P##$$completeData(), unsigned(d.get_io$$##P##$$completeSize())}; \
    o.requestCount = d.get_io$$##P##$$requestCount(); o.completeCount = d.get_io$$##P##$$completeCount()
    if (candidate) { SIDE(candidate); } else { SIDE(reference); }
#undef SIDE
#undef RANK
    return o;
}

struct Coverage {
    uint64_t cycles = 0, empty = 0, single = 0, multiple = 0, wrap = 0, exclude = 0, excludeOnly = 0;
    uint64_t secondDisappeared = 0, saved = 0, zeroRead = 0, uninitializedRead = 0, rangeRead = 0;
    uint64_t collisions = 0, zeroWrite = 0, disabledHighWrite = 0, readDuringWrite = 0;
    uint64_t requests = 0, completions = 0, invalidCaptured = 0, reset = 0;
    unsigned highEmpty = 0, highSelected = 0;
};

class Bench {
public:
    SRank1PrfAddressPairGsim dut;
    std::array<Row, slots> rows{};
    // Independent ordinary word values. No DUT bank or last-writer-table model.
    std::array<uint64_t, registers> words{};
    std::array<bool, registers> initialized{};
    Payload captured;
    bool pending = false, capturedKnown = false, previousSecond = false;
    uint64_t requestCount = 0, completeCount = 0, corruptions = 0;
    Coverage cover;
    std::string mode, phase;
    explicit Bench(std::string control) : mode(std::move(control)) {
        static_assert(std::is_trivially_copyable_v<SRank1PrfAddressPairGsim>);
        std::memset(&dut, 0, sizeof(dut));
        dut.LOG_START = 1;
        dut.activateAll();
    }
    void require(bool good, const std::string& reason) const {
        if (!good) throw std::runtime_error(reason + " phase=" + phase + " cycle=" + std::to_string(cover.cycles));
    }
    uint64_t word(unsigned id) const { return id > 0 && id < registers ? words[id] : 0; }
    int oldest(unsigned mask, unsigned head) const {
        for (unsigned age = 0; age < slots; ++age) {
            const unsigned index = (head + age) % slots;
            if ((mask >> index) & 1U) return int(index);
        }
        return -1;
    }
    Rank rank(int index) const {
        if (index < 0) return {};
        const Row& r = rows[unsigned(index)];
        require(r.programmed, "host selected an unprogrammed metadata row");
        const bool saved = r.store && r.saved;
        return {true, unsigned(index), 1U << unsigned(index), r.source1, r.source2,
            word(r.source1), word(r.source2), r.immediate,
            saved ? r.savedAddress : word(r.source1) + r.immediate,
            saved ? r.savedData : word(r.source2), r.tag, r.store, r.size, saved};
    }
    Observation expected(const Input& in) const {
        Observation o;
        const int first = oldest(in.eligible, in.head);
        const int second = oldest(first < 0 ? 0 : in.eligible & ~(1U << unsigned(first)), in.head);
        o.ranks = {rank(first), rank(second)};
        // Independently rescan after exclusion; do not obtain the expected
        // selected owner by reproducing the DUT's late rank mux.
        const int selected = oldest(in.eligible & ~(in.issued ? 1U << in.issuedIndex : 0), in.head);
        const Rank choice = rank(selected);
        o.selectedValid = selected >= 0;
        o.selectedIndex = selected < 0 ? 0 : unsigned(selected);
        o.useSecond = in.issued && first == int(in.issuedIndex);
        o.requestFire = o.selectedValid && in.ready;
        o.request = {o.selectedIndex, choice.tag, choice.address, choice.data, choice.size};
        o.completeFire = pending;
        o.complete = captured;
        o.requestCount = requestCount;
        o.completeCount = completeCount;
        return o;
    }
    void check(const Observation& got, const Observation& want, const char* side) const {
        const std::string label = std::string("RANK1_PRF_ORACLE ") + side + " ";
        for (unsigned i = 0; i < 2; ++i) {
            const auto& a = got.ranks[i]; const auto& b = want.ranks[i];
            require(a.valid == b.valid && a.index == b.index && a.owner == b.owner, label + "selector owner");
            require(a.source1 == b.source1 && a.source2 == b.source2, label + "source ID");
            require(a.left == b.left && a.right == b.right, label + "PRF data");
            require(a.immediate == b.immediate, label + "guarded immediate");
            require(a.tag == b.tag && a.store == b.store && a.size == b.size && a.saved == b.saved,
                label + "selected metadata");
            require(a.address == b.address && a.data == b.data, label + "prepared payload");
        }
        require(got.selectedValid == want.selectedValid && got.selectedIndex == want.selectedIndex &&
            got.useSecond == want.useSecond, label + "late exclusion");
        require(got.request == want.request, label + "selected payload including invalid");
        require(got.requestFire == want.requestFire, label + "request validity");
        require(got.completeFire == want.completeFire, label + "completion validity");
        if (capturedKnown) require(got.complete == want.complete, label + "captured payload including invalid");
        require(got.requestCount == want.requestCount && got.completeCount == want.completeCount,
            label + "side effect counters");
    }
    void corrupt(Observation& c, const Observation& want) {
        if (corruptions || mode.empty() || mode == "--mutate-raw-index0") return;
        bool changed = false;
        // These controls change real sampled candidate observations, never the
        // oracle. The raw-index0 control below instead changes actual RTL PRF IDs.
        if (mode == "--mutate-source" && c.ranks[1].valid) { c.ranks[1].source1 ^= 1; changed = true; }
        if (mode == "--mutate-data" && c.ranks[1].valid && c.ranks[1].left) {
            c.ranks[1].left ^= 1; changed = true;
        }
        if (mode == "--mutate-address" && c.ranks[1].valid) { c.ranks[1].address ^= 8; changed = true; }
        if (mode == "--mutate-owner" && c.ranks[1].valid) { c.ranks[1].owner ^= 1; changed = true; }
        if (mode == "--mutate-immediate" && !c.ranks[1].valid && rows[0].programmed && rows[0].immediate) {
            c.ranks[1].immediate = rows[0].immediate; changed = true;
        }
        if (mode == "--mutate-invalid-request" && !want.selectedValid) { c.requestFire = true; changed = true; }
        if (mode == "--mutate-invalid-completion" && !want.completeFire) { c.completeFire = true; changed = true; }
        if (mode == "--mutate-invalid-capture" && capturedKnown && !want.completeFire) {
            c.complete.address ^= 8; changed = true;
        }
        if (changed) {
            ++corruptions;
            std::cerr << "ACTUAL_CORRUPTION count=" << corruptions << " mode=" << mode
                      << " kind=sampled-candidate-observation\n";
        }
    }
    void tick(const Input& in, const std::string& label, bool reset = false) {
        phase = label;
        const Observation want = expected(in);
        const bool rawIndex0 = !reset && mode == "--mutate-raw-index0" && rows[0].programmed;
        dut.set_reset(reset);
        dut.set_io$$in$$eligible(in.eligible); dut.set_io$$in$$head(in.head);
        dut.set_io$$in$$issued(in.issued); dut.set_io$$in$$issuedIndex(in.issuedIndex);
        dut.set_io$$in$$ready(in.ready); dut.set_io$$in$$rawIndex0(rawIndex0);
        dut.set_io$$in$$row$$valid(in.rowWrite); dut.set_io$$in$$row$$index(in.rowIndex);
        dut.set_io$$in$$row$$source1(in.row.source1); dut.set_io$$in$$row$$source2(in.row.source2);
        dut.set_io$$in$$row$$tag(in.row.tag); dut.set_io$$in$$row$$immediate(in.row.immediate);
        dut.set_io$$in$$row$$store(in.row.store); dut.set_io$$in$$row$$size(in.row.size);
        dut.set_io$$in$$row$$saved(in.row.saved); dut.set_io$$in$$row$$savedAddress(in.row.savedAddress);
        dut.set_io$$in$$row$$savedData(in.row.savedData);
#define WRITE(N) \
        dut.set_io$$in$$write##N##$$valid(in.writes[N].valid); \
        dut.set_io$$in$$write##N##$$address(in.writes[N].address); \
        dut.set_io$$in$$write##N##$$data(in.writes[N].data)
        WRITE(0); WRITE(1);
#undef WRITE
        dut.step();
        const auto reference = read(dut, false);
        auto candidate = read(dut, true);
        if (reset) {
            words.fill(0); initialized.fill(false); requestCount = completeCount = 0;
            pending = false; ++cover.reset;
        } else {
            ++cover.cycles;
            if (dut.get_io$$candidate$$rawIndex0Applied()) {
                require(rawIndex0, "unrequested raw-index0 RTL corruption");
                ++corruptions;
                std::cerr << "ACTUAL_CORRUPTION count=" << corruptions << " mode=" << mode
                          << " kind=RTL-raw-index0-PRF-address\n";
            }
            require(!dut.get_io$$reference$$rawIndex0Applied(), "reference enabled test mutant");
            corrupt(candidate, want);
            check(reference, want, "reference");
            check(candidate, want, "candidate");
            require(candidate == reference, "RANK1_PRF_PAIR complete cycle parity");
            const auto& first = want.ranks[0]; const auto& second = want.ranks[1];
            cover.empty += !first.valid; cover.single += first.valid && !second.valid;
            cover.multiple += second.valid; cover.wrap += want.selectedValid && want.selectedIndex < in.head;
            cover.exclude += want.useSecond; cover.excludeOnly += want.useSecond && !second.valid;
            cover.secondDisappeared += previousSecond && !second.valid;
            previousSecond = second.valid;
            for (const auto& r : want.ranks) {
                if (r.valid) {
                    cover.saved += r.saved;
                    for (unsigned id : {r.source1, r.source2}) {
                        cover.zeroRead += id == 0;
                        cover.uninitializedRead += id > 0 && id < registers && !initialized[id];
                        cover.rangeRead += id >= registers;
                        if (id >= 48) cover.highSelected |= 1U << (id - 48);
                        for (const auto& w : in.writes) cover.readDuringWrite += w.valid && id == w.address;
                    }
                }
            }
            if (!second.valid) for (const auto& row : rows) if (row.programmed) {
                for (unsigned id : {row.source1, row.source2}) if (id >= 48) cover.highEmpty |= 1U << (id - 48);
            }
            cover.collisions += in.writes[0].valid && in.writes[1].valid && in.writes[0].address &&
                in.writes[0].address == in.writes[1].address;
            for (const auto& w : in.writes) {
                cover.zeroWrite += w.valid && w.address == 0;
                cover.disabledHighWrite += !w.valid && w.address >= registers;
                if (w.valid && w.address > 0 && w.address < registers) {
                    // Later write lane wins; data must not bypass the edge.
                    words[w.address] = w.data; initialized[w.address] = true;
                }
            }
            cover.requests += want.requestFire; cover.completions += want.completeFire;
            cover.invalidCaptured += capturedKnown && !want.completeFire;
            requestCount += want.requestFire; completeCount += want.completeFire;
            pending = want.requestFire;
        }
        // Payload capture is unconditional, including reset and invalid edges.
        captured = want.request; capturedKnown = true;
        if (in.rowWrite) { rows[in.rowIndex] = in.row; rows[in.rowIndex].programmed = true; }
    }
    void reset() { tick({}, "reset", true); tick({}, "reset", true); tick({}, "post-reset"); }
    void program(unsigned index, Row row) {
        Input in; in.rowWrite = true; in.rowIndex = index; in.row = row; tick(in, "program-row");
    }
};
} // namespace

int main(int argc, char** argv) {
    try {
        const std::array<std::string, 9> modes{"--mutate-raw-index0", "--mutate-source", "--mutate-data",
            "--mutate-address", "--mutate-owner", "--mutate-immediate", "--mutate-invalid-request",
            "--mutate-invalid-completion", "--mutate-invalid-capture"};
        if (argc > 2) throw std::runtime_error("usage: run [one known --mutate-* control]");
        std::string mode = argc == 2 ? argv[1] : "";
        if (!mode.empty()) {
            bool known = false; for (const auto& allowed : modes) known |= mode == allowed;
            if (!known) throw std::runtime_error("unknown corruption control: " + mode);
        }
        Bench b(mode); b.reset();
        std::mt19937_64 rng(0x72616e6b31707266ULL);
        // Every disabled row carries poisoned 48..63 IDs and a nonzero immediate.
        // Empty owner must mask the whole actual metadata entry and immediate port.
        for (unsigned i = 0; i < slots; ++i) {
            Row row; row.source1 = 48 + i; row.source2 = 63 - i;
            row.tag = 0x8000000000000100ULL + i; row.immediate = UINT64_MAX - i;
            row.store = i & 1; row.size = i & 3; row.saved = i % 3 == 0;
            row.savedAddress = 0x80000000ULL + 64 * i; row.savedData = 0xcafef00d00000000ULL + i;
            b.program(i, row);
        }
        for (unsigned head = 0; head < slots; ++head) {
            Input in; in.head = head; b.tick(in, "empty-poisoned-owners");
            for (unsigned i = 0; i < slots; ++i) {
                in.eligible = 1U << i; in.issued = false; b.tick(in, "singleton-high-range");
                in.issued = true; in.issuedIndex = i; b.tick(in, "sole-issued-owner-excluded");
                in.eligible |= 1U << ((i + 1) % slots); b.tick(in, "second-wrap-issued-exclusion");
                in.eligible = 0; b.tick(in, "second-disappears-on-eligibility-clear");
            }
        }
        // Program distinct ordinary IDs while retaining signed/wrapping immediates,
        // saved stores, tags and sizes. Exercise uninitialized PRF locations first.
        for (unsigned i = 0; i < slots; ++i) {
            Row row = b.rows[i]; row.source1 = 2 * i; row.source2 = 2 * i + 1; b.program(i, row);
        }
        Input in; in.eligible = 0xffff; in.head = 15; in.issued = true; in.issuedIndex = 15;
        b.tick(in, "uninitialized-wrap");
        for (unsigned address = 0; address < registers; ++address) {
            in.head = (address / 2) % slots; in.issued = false;
            in.writes = {{{true, address, 0x1111000000000000ULL + address},
                          {true, address, 0xeeee000000000000ULL + address}}};
            b.tick(in, "collision-pre-edge-old-value");
            in.writes = {}; b.tick(in, "collision-post-edge-higher-lane-wins");
            in.writes[0] = {true, address, 0x2222000000000000ULL + address};
            b.tick(in, "alternate-owner-pre-edge");
            in.writes = {}; b.tick(in, "alternate-owner-post-edge");
        }
        // Changed ready and effective eligible masks model the selector boundary
        // of same-edge readiness/kill inputs, not backend generation cancellation.
        in = {}; in.head = 15; in.eligible = (1U << 15) | 1U;
        b.tick(in, "ready-two-live");
        in.ready = false; in.eligible = 1U << 15; b.tick(in, "same-edge-second-kill-and-backpressure");
        in.ready = true; in.eligible = 0; b.tick(in, "same-edge-all-kill-and-ready");
        in.eligible = (1U << 15) | 1U; in.issued = true; in.issuedIndex = 15;
        b.tick(in, "same-edge-second-ready-and-issued-first");
        in.eligible = 1U << 15; b.tick(in, "issued-only-after-second-disappears");
        for (unsigned n = 0; n < 2048; ++n) {
            in = {}; in.eligible = unsigned(rng()) & 0xffff; in.head = rng() % slots;
            in.ready = rng() % 4 != 0; in.issued = rng() & 1; in.issuedIndex = rng() % slots;
            for (auto& w : in.writes) {
                w.valid = rng() % 3 != 0; w.address = w.valid ? rng() % registers : 63; w.data = rng();
            }
            if (n % 7 == 0) in.writes[1].address = in.writes[0].valid ? in.writes[0].address : 0;
            if (n % 11 == 0) {
                in.rowWrite = true; in.rowIndex = rng() % slots; in.row = b.rows[in.rowIndex];
                in.row.source1 = rng() & 63; in.row.source2 = rng() & 63;
                in.row.tag = rng(); in.row.immediate = rng(); in.row.store = rng() & 1;
                in.row.saved = rng() & 1; in.row.savedAddress = rng(); in.row.savedData = rng();
            }
            b.tick(in, "seeded-mixed-ownership");
        }
        // Reset must clear PRF initialization/owner metadata and sink authorization,
        // while issue/immediate RAM retains its ordinary stale payload contents.
        b.reset(); in = {}; in.eligible = 0xffff;
        for (unsigned head = 0; head < slots; ++head) { in.head = head; b.tick(in, "reset-uninitialized-reread"); }
        b.tick({}, "final-drain"); b.tick({}, "final-invalid-capture");
        if (!mode.empty()) b.require(b.corruptions != 0, "requested corruption control was not exercised");
        const auto& c = b.cover;
        b.require(c.empty && c.single && c.multiple && c.wrap && c.exclude && c.excludeOnly &&
            c.secondDisappeared && c.saved && c.zeroRead && c.uninitializedRead && c.rangeRead &&
            c.collisions && c.zeroWrite && c.disabledHighWrite && c.readDuringWrite && c.requests &&
            c.completions && c.invalidCaptured && c.reset >= 4 && c.highEmpty == 0xffff && c.highSelected == 0xffff,
            "directed coverage incomplete");
        b.require(b.requestCount == b.completeCount, "fixture sink failed to drain");
        std::cout << "RANK1_PRF_ADDRESS_PAIR_PASS rob=16 physical=48 cycles=" << c.cycles
                  << " empty=" << c.empty << " single=" << c.single << " multiple=" << c.multiple
                  << " wrapped=" << c.wrap << " excluded=" << c.exclude << " excluded_only=" << c.excludeOnly
                  << " second_disappeared=" << c.secondDisappeared << " high_empty_mask=" << c.highEmpty
                  << " high_selected_mask=" << c.highSelected << " range_reads=" << c.rangeRead
                  << " saved=" << c.saved << " x0_reads=" << c.zeroRead << " uninitialized=" << c.uninitializedRead
                  << " collisions=" << c.collisions << " read_during_write=" << c.readDuringWrite
                  << " zero_writes=" << c.zeroWrite << " disabled_high_writes=" << c.disabledHighWrite
                  << " requests=" << c.requests << " completions=" << c.completions
                  << " invalid_captures=" << c.invalidCaptured << " resets=" << c.reset << '\n';
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "RANK1_PRF_ADDRESS_PAIR_FAIL " << e.what() << '\n';
        return 1;
    }
}
