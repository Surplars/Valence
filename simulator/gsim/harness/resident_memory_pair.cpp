#include "ResidentMemoryPairGsim.h"
#include <array>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <new>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
constexpr unsigned slots = 16, physical = 48;
constexpr uint64_t allReady = (uint64_t(1) << physical) - 1;
constexpr unsigned bit(unsigned index) { return 1U << index; }

struct Row {
    bool programmed = false;
    uint64_t tag = 0, immediate = 0;
    unsigned source1 = 0, source2 = 0, size = 0;
    bool store = false, atomic = false;
    bool prepared = false;
    uint64_t savedAddress = 0, savedData = 0;
};
struct Write { bool valid = false; unsigned address = 63; uint64_t data = 0; };
struct Input {
    unsigned pending = 0, kill = 0, head = 0, commits = 0;
    uint64_t readyMask = allReady, reserveMask = 0;
    unsigned fallbackQualified = 0, poolSuppress = 0, authority = 0xffff;
    bool postedWindow = false, startReady = true;
    bool rowValid = false; unsigned rowIndex = 0; Row row{};
    bool savedValid = false; unsigned savedIndex = 0; bool prepared = false;
    uint64_t savedAddress = 0, savedData = 0;
    std::array<Write, 2> writes{};
};
struct Tuple {
    unsigned index = 0; uint64_t tag = 0, address = 0, data = 0; unsigned size = 0;
    bool operator==(const Tuple&) const = default;
};
struct Stage { bool valid = false; Tuple tuple{}; };
struct Observation {
    unsigned head = 0, original = 0, preparation = 0;
    Stage stage{}, next{};
    bool residentLive = false, offer = false, fire = false;
    bool freshValid = false, reuse = false; unsigned freshIndex = 0;
};
struct Accepted {
    uint64_t cycle = 0; Tuple tuple{};
    bool operator==(const Accepted&) const = default;
};
struct Coverage {
    uint64_t cycles = 0, next = 0, accepted = 0, held = 0, reused = 0;
    uint64_t olderDisplacement = 0, absentPoolStart = 0, staleTag = 0, killed = 0;
    uint64_t fallback = 0, postedUnion = 0, issuedOriginalNoFallback = 0;
    uint64_t saved = 0, rawToSaved = 0, lateData = 0, wraps = 0;
    uint64_t collisions = 0, preedgeRead = 0, zeroReads = 0, zeroWrites = 0;
    uint64_t highestReads = 0, uninitializedReads = 0, emptyPoison = 0;
    uint64_t producerRetire = 0, youngerOverwrite = 0, rollbackReuse = 0;
    uint64_t headMoves = 0, loadData = 0, resets = 0, invalidation = 0;
    uint64_t continuousRun = 0, longestRun = 0;
};

Observation read(SResidentMemoryPairGsim& d, bool on) {
    Observation o;
#define READ(S) \
    o.head = d.get_io$$##S##$$head(); \
    o.original = d.get_io$$##S##$$originalMask(); \
    o.preparation = d.get_io$$##S##$$preparationMask(); \
    o.stage.valid = d.get_io$$##S##$$stageValid(); \
    o.stage.tuple = {unsigned(d.get_io$$##S##$$stageIndex()), d.get_io$$##S##$$stageTag(), \
        d.get_io$$##S##$$stageAddress(), d.get_io$$##S##$$stageData(), unsigned(d.get_io$$##S##$$stageSize())}; \
    o.residentLive = d.get_io$$##S##$$residentLive(); \
    o.offer = d.get_io$$##S##$$offer(); o.fire = d.get_io$$##S##$$fire(); \
    o.next.valid = d.get_io$$##S##$$nextValid(); \
    o.next.tuple = {unsigned(d.get_io$$##S##$$nextIndex()), d.get_io$$##S##$$nextTag(), \
        d.get_io$$##S##$$nextAddress(), d.get_io$$##S##$$nextData(), unsigned(d.get_io$$##S##$$nextSize())}; \
    o.freshValid = d.get_io$$##S##$$freshValid(); \
    o.freshIndex = d.get_io$$##S##$$freshIndex(); o.reuse = d.get_io$$##S##$$reuse()
    if (on) { READ(on); } else { READ(off); }
#undef READ
    return o;
}

class Bench {
public:
    // Zero storage before construction. Never clear a constructed GSIM model:
    // the constructor installs scheduling/active state that must survive reset.
    alignas(SResidentMemoryPairGsim) unsigned char modelStorage[sizeof(SResidentMemoryPairGsim)]{};
    SResidentMemoryPairGsim& dut;
    std::array<Row, slots> rows{};
    // The independent PRF model retains both banks, not merely a winning value.
    std::array<std::array<uint64_t, physical>, 2> bank{};
    std::array<bool, physical> initialized{}, owner{};
    std::array<Stage, 2> stages{};
    std::array<std::vector<Accepted>, 2> accepted{};
    unsigned pending = 0, head = 0, mutation = 0;
    uint64_t ready = allReady;
    Coverage cover{};
    std::string phase;
    bool injectMismatch = false, mismatchInjected = false;

    Bench() : dut(*::new (static_cast<void*>(modelStorage)) SResidentMemoryPairGsim()) {}
    ~Bench() { dut.~SResidentMemoryPairGsim(); }
    Bench(const Bench&) = delete;
    Bench& operator=(const Bench&) = delete;

    void require(bool ok, const std::string& why) const {
        if (!ok) throw std::runtime_error(why + " phase=" + phase + " cycle=" + std::to_string(cover.cycles));
    }
    void sameTuple(const Tuple& got, const Tuple& want, const std::string& why) const {
        if (got == want) return;
        std::ostringstream details;
        details << why << std::hex << " got={index:" << got.index << ",tag:" << got.tag
                << ",address:" << got.address << ",data:" << got.data << ",size:" << got.size
                << "} want={index:" << want.index << ",tag:" << want.tag << ",address:" << want.address
                << ",data:" << want.data << ",size:" << want.size << '}';
        require(false, details.str());
    }
    uint64_t word(unsigned address) const {
        if (!address || address >= physical || !initialized[address]) return 0;
        return bank[owner[address] ? 1 : 0][address];
    }
    bool isReady(unsigned address, uint64_t mask) const {
        return address < physical && ((mask >> address) & 1);
    }
    int oldest(unsigned mask, unsigned currentHead) const {
        for (unsigned age = 0; age != slots; ++age) {
            const unsigned index = (currentHead + age) % slots;
            if (mask & bit(index)) return int(index);
        }
        return -1;
    }
    Tuple payload(unsigned index) const {
        const auto& r = rows[index];
        require(r.programmed, "ORACLE selected an unprogrammed row");
        const bool saved = r.store && r.prepared;
        return {index, r.tag, saved ? r.savedAddress : word(r.source1) + r.immediate,
            saved ? r.savedData : word(r.source2), r.size};
    }
    std::array<unsigned, 3> pools(const Input& in) const {
        unsigned original = 0, fallback = 0;
        for (unsigned i = 0; i != slots; ++i) {
            if (!(in.pending & bit(i))) continue;
            const auto& r = rows[i];
            require(r.programmed, "ORACLE pending row is unprogrammed");
            const bool sources = isReady(r.source1, in.readyMask) &&
                (!(r.store || r.atomic) || isReady(r.source2, in.readyMask));
            if ((!r.store || i == head) && (r.prepared || sources)) original |= bit(i);
            if (r.store && !r.atomic && i != head && r.prepared && (in.fallbackQualified & bit(i)))
                fallback |= bit(i);
        }
        // This choice is deliberately made before any accepted-owner exclusion.
        unsigned preparation = original ? original : fallback;
        if (in.postedWindow && original) preparation |= fallback;
        return {original, fallback, preparation & ~in.poolSuppress & 0xffffU};
    }
    Input input(bool startReady = true) const {
        Input in; in.pending = pending; in.head = head; in.readyMask = ready;
        in.startReady = startReady; return in;
    }
    void drive(const Input& in, bool reset) {
        dut.set_reset(reset);
        dut.set_io$$in$$pending(in.pending); dut.set_io$$in$$readyMask(in.readyMask);
        dut.set_io$$in$$kill(in.kill); dut.set_io$$in$$head(in.head); dut.set_io$$in$$commits(in.commits);
        dut.set_io$$in$$fallbackQualified(in.fallbackQualified); dut.set_io$$in$$postedWindow(in.postedWindow);
        dut.set_io$$in$$poolSuppress(in.poolSuppress); dut.set_io$$in$$authority(in.authority);
        dut.set_io$$in$$startReady(in.startReady); dut.set_io$$in$$reserveMask(in.reserveMask);
        dut.set_io$$in$$mutation(mutation);
        dut.set_io$$in$$row$$valid(in.rowValid); dut.set_io$$in$$row$$bits$$index(in.rowIndex);
        dut.set_io$$in$$row$$bits$$tag(in.row.tag); dut.set_io$$in$$row$$bits$$source1(in.row.source1);
        dut.set_io$$in$$row$$bits$$source2(in.row.source2); dut.set_io$$in$$row$$bits$$immediate(in.row.immediate);
        dut.set_io$$in$$row$$bits$$store(in.row.store); dut.set_io$$in$$row$$bits$$atomic(in.row.atomic);
        dut.set_io$$in$$row$$bits$$size(in.row.size);
        dut.set_io$$in$$saved$$valid(in.savedValid); dut.set_io$$in$$saved$$bits$$index(in.savedIndex);
        dut.set_io$$in$$saved$$bits$$prepared(in.prepared); dut.set_io$$in$$saved$$bits$$address(in.savedAddress);
        dut.set_io$$in$$saved$$bits$$data(in.savedData);
#define WRITE(N) \
        dut.set_io$$in$$write##N##$$valid(in.writes[N].valid); \
        dut.set_io$$in$$write##N##$$bits$$address(in.writes[N].address); \
        dut.set_io$$in$$write##N##$$bits$$data(in.writes[N].data)
        WRITE(0); WRITE(1);
#undef WRITE
    }
    void tick(const Input& in, const std::string& label, bool reset = false) {
        phase = label;
        require(in.head == head, "ORACLE host head drift");
        require(in.pending == pending, "ORACLE pending lifecycle drift");
        const auto pool = pools(in);
        drive(in, reset); dut.step();
        std::array<Observation, 2> got{read(dut, false), read(dut, true)};
        if (reset) {
            initialized.fill(false); owner.fill(false); stages = {}; pending = head = 0;
            ready = allReady; ++cover.resets; return;
        }
        if (injectMismatch && !mismatchInjected && got[1].next.valid) {
            got[1].next.tuple.data ^= 1; mismatchInjected = true;
            std::cerr << "RESIDENT_MEMORY_INJECTED_MISMATCH kind=sampled-on-next-data cycle=" << cover.cycles << '\n';
        }
        std::array<Stage, 2> next{};
        std::array<bool, 2> fired{};
        for (unsigned side = 0; side != 2; ++side) {
            const auto& s = stages[side]; const auto& o = got[side];
            const std::string prefix = side ? "RESIDENT_MEMORY_ORACLE ON " : "RESIDENT_MEMORY_ORACLE OFF ";
            const bool live = s.valid && (in.pending & bit(s.tuple.index)) &&
                rows[s.tuple.index].tag == s.tuple.tag;
            const bool offer = live && !(in.kill & bit(s.tuple.index)) && (in.authority & bit(s.tuple.index));
            const bool fire = offer && in.startReady;
            require(o.head == head, prefix + "registered head");
            require(o.original == pool[0], prefix + "original pool before exclusion");
            require(o.preparation == pool[2], prefix + "preparation pool before exclusion");
            require(o.stage.valid == s.valid, prefix + "stage valid");
            if (s.valid) sameTuple(o.stage.tuple, s.tuple, prefix + "complete registered stage tuple");
            require(o.residentLive == live, prefix + "full-token resident liveness");
            require(o.offer == offer && o.fire == fire, prefix + "offer/fire authority");
            fired[side] = o.fire;
            // Each side excludes only its own checked actual fire. Neither side
            // supplies fire or stage state to the other side's oracle.
            unsigned candidates = pool[2];
            if (o.fire) candidates &= ~bit(o.stage.tuple.index);
            const int selected = oldest(candidates, head);
            next[side].valid = selected >= 0;
            if (selected >= 0) next[side].tuple = payload(unsigned(selected));
            require(o.next.valid == next[side].valid, prefix + "next valid");
            if (next[side].valid) sameTuple(o.next.tuple, next[side].tuple,
                prefix + "complete independently recomputed next tuple (including load data)");
            if (side) {
                const int fresh = oldest(pool[2] & ~(live ? bit(s.tuple.index) : 0), head);
                require(o.freshValid == (fresh >= 0), prefix + "fresh validity");
                if (fresh >= 0) require(o.freshIndex == unsigned(fresh), prefix + "fresh circular owner");
                const bool reuse = live && !o.fire && selected == int(s.tuple.index);
                require(o.reuse == reuse, prefix + "resident reuse decision");
            }
            if (o.fire) {
                // Accepted data is the independently predicted prior capture,
                // not a reread of a word that may have changed since that edge.
                sameTuple(o.stage.tuple, s.tuple, prefix + "complete accepted tuple");
                accepted[side].push_back({cover.cycles, o.stage.tuple});
            }
        }
        require(fired[0] == fired[1], "RESIDENT_MEMORY_PAIR accepted-cycle parity");
        require(next[0].valid == next[1].valid && (!next[0].valid || next[0].tuple == next[1].tuple),
            "RESIDENT_MEMORY_PAIR next-tuple parity");
        const auto& o = got[1];
        ++cover.cycles; cover.next += o.next.valid; cover.accepted += o.fire;
        cover.held += o.residentLive && !o.fire; cover.reused += o.reuse;
        cover.absentPoolStart += o.fire && !(pool[2] & bit(o.stage.tuple.index));
        cover.staleTag += o.stage.valid && (in.pending & bit(o.stage.tuple.index)) && !o.residentLive;
        cover.killed += o.residentLive && (in.kill & bit(o.stage.tuple.index));
        cover.fallback += !pool[0] && pool[1];
        cover.postedUnion += in.postedWindow && pool[0] && pool[1];
        cover.issuedOriginalNoFallback += o.fire && pool[0] == bit(o.stage.tuple.index) && pool[1] && !in.postedWindow;
        cover.olderDisplacement += o.residentLive && !o.fire && o.next.valid &&
            o.next.tuple.index != o.stage.tuple.index && (pool[2] & bit(o.stage.tuple.index));
        cover.continuousRun = o.fire ? cover.continuousRun + 1 : 0;
        if (cover.continuousRun > cover.longestRun) cover.longestRun = cover.continuousRun;
        cover.invalidation += o.stage.valid && !o.next.valid;
        cover.headMoves += in.commits != 0;
        if (o.next.valid) {
            const auto& r = rows[o.next.tuple.index];
            cover.wraps += o.next.tuple.index < head;
            cover.saved += r.store && r.prepared; cover.loadData += !r.store && !r.atomic;
            if (!(r.store && r.prepared)) for (const auto source : {r.source1, r.source2}) {
                cover.zeroReads += source == 0; cover.highestReads += source == physical - 1;
                cover.uninitializedReads += source && source < physical && !initialized[source];
                for (const auto& w : in.writes) cover.preedgeRead += w.valid && source && w.address == source;
            }
        }
        cover.collisions += in.writes[0].valid && in.writes[1].valid && in.writes[0].address &&
            in.writes[0].address == in.writes[1].address;
        for (unsigned lane = 0; lane != 2; ++lane) {
            const auto& w = in.writes[lane]; cover.zeroWrites += w.valid && !w.address;
            if (w.valid && w.address && w.address < physical) {
                bank[lane][w.address] = w.data; initialized[w.address] = true; owner[w.address] = lane;
            }
        }
        if (in.rowValid) {
            rows[in.rowIndex] = in.row; rows[in.rowIndex].programmed = true;
            // A new owner has no inherited saved-store authorization.
            rows[in.rowIndex].prepared = false;
        }
        if (in.savedValid) {
            auto& r = rows[in.savedIndex]; r.prepared = in.prepared;
            r.savedAddress = in.savedAddress; r.savedData = in.savedData;
        }
        std::array<unsigned, 2> nextPending{};
        for (unsigned side = 0; side != 2; ++side) {
            const unsigned consumed = fired[side] ? bit(got[side].stage.tuple.index) : 0;
            nextPending[side] = in.pending & ~in.kill & ~consumed;
        }
        require(nextPending[0] == nextPending[1], "PAIR independent pending lifecycle parity");
        pending = nextPending[0];
        head = (head + in.commits) % slots; stages = next;
    }
    void tick(const std::string& label, bool startReady = true) { tick(input(startReady), label); }
    void reset() {
        pending = head = 0; stages = {}; ready = allReady;
        tick(input(), "reset", true); tick(input(), "reset", true); tick("post-reset");
    }
    void quiesce() {
        if (pending) { auto in = input(false); in.kill = pending; tick(in, "phase-cleanup-kill"); }
        tick("phase-cleanup-stage"); tick("phase-cleanup-empty");
    }
    void atHead(unsigned target) {
        quiesce();
        while (head != target) {
            auto in = input(); in.commits = ((target + slots - head) % slots) >= 2 ? 2 : 1;
            tick(in, "retire-advance-registered-head");
        }
    }
    void program(unsigned index, Row row, bool activate = false) {
        auto in = input(false); in.rowValid = true; in.rowIndex = index; in.row = row;
        tick(in, "allocate-row-preedge");
        if (activate) pending |= bit(index);
    }
    void save(unsigned index, uint64_t address, uint64_t data) {
        auto in = input(false); in.savedValid = true; in.savedIndex = index;
        in.prepared = true; in.savedAddress = address; in.savedData = data;
        tick(in, "publish-saved-store-preedge");
    }
    void write(unsigned address, uint64_t value) {
        auto in = input(false); in.writes[0] = {true, address, value}; tick(in, "write-physical-word");
    }
    Row load(unsigned index, unsigned source = 0) const {
        Row r; r.tag = 0x8000000100000000ULL + index; r.source1 = source; r.source2 = 0;
        r.immediate = 0x1000 + index * 17; r.size = index % 4; return r;
    }
    Row store(unsigned index, unsigned base = 7, unsigned data = 47) const {
        Row r = load(index, base); r.store = true; r.source2 = data; return r;
    }
};

void directed(Bench& b) {
    // Invalid issue rows contain out-of-capacity poison. Disabled owners must
    // not authorize any read, stage, or acceptance from these stale fields.
    for (unsigned i = 0; i != slots; ++i) {
        Row r = b.load(i, 48 + i); r.source2 = 63 - i; r.immediate = UINT64_MAX - i;
        b.program(i, r); ++b.cover.emptyPoison;
    }
    b.tick("empty-poisoned-rows");
    // Observe an uninitialized physical47 before any writes initialize banks.
    b.program(0, b.load(0, 47), true); b.tick("uninitialized-physical47"); b.tick("accept-uninitialized");
    b.quiesce();
    for (unsigned address = 0; address != physical; ++address) {
        auto in = b.input();
        in.writes = {{{true, address, 0x1111000000000000ULL + address},
                      {true, address, 0xeeee000000000000ULL + address}}};
        b.tick(in, "initialize-prf-two-bank-collision");
    }
    // A fresh boundary read collides with the write edge, then immediately
    // starts. There is no surviving raw resident on the write edge. This checks
    // the PRF primitive's old-value semantics, not allocator write legality.
    b.program(0, b.load(0, 47), true);
    auto in = b.input(); in.writes = {{{true, 47, 0x123456789abc0001ULL}, {true, 47, 0xfedcba9876540002ULL}}};
    b.tick(in, "fresh-prf-preedge-collision"); b.tick("accept-preedge-payload"); b.quiesce();
    b.program(0, b.load(0, 47), true); b.tick("read-postedge-higher-lane"); b.tick("accept-higher-lane"); b.quiesce();
    b.write(47, 0x2468ace013579bdfULL);
    b.program(0, b.load(0, 47), true); b.tick("read-postedge-lane0-owner"); b.tick("accept-lane0-owner"); b.quiesce();

    for (unsigned i = 0; i != slots; ++i) b.program(i, b.load(i, i + 1));
    b.pending = 0xffff;
    b.tick("continuous-first-prepare");
    for (unsigned i = 0; i != slots; ++i) b.tick("continuous-accepted-starts");
    b.require(!b.pending, "continuous workload failed to drain"); b.quiesce();

    b.program(5, b.load(5, 7), true); b.tick("blocked-resident-prime", false);
    for (unsigned n = 0; n != 5; ++n) b.tick("blocked-resident-reuse", false);
    b.tick("blocked-resident-release"); b.quiesce();

    b.program(2, b.load(2, 9)); b.program(5, b.load(5, 7));
    b.pending = bit(2) | bit(5); b.ready &= ~(uint64_t(1) << 9);
    b.tick("younger-ready-resident-prime", false);
    b.ready |= uint64_t(1) << 9;
    b.tick("older-new-ready-displaces-blocked-resident", false);
    b.tick("accept-newly-ready-older"); b.tick("accept-restaged-younger"); b.quiesce();

    b.program(0, b.load(0, 7)); b.program(1, b.load(1, 9)); b.pending = bit(0) | bit(1);
    b.tick("absent-pool-resident-prime", false);
    in = b.input(); in.poolSuppress = bit(0); b.tick(in, "live-resident-starts-outside-current-E");
    b.tick("accept-independent-fresh"); b.quiesce();

    b.program(5, b.load(5, 7), true); b.tick("stale-fulltag-prime", false);
    Row replacement = b.load(5, 9); replacement.tag ^= uint64_t(1) << 63; replacement.immediate ^= 0x5555;
    b.program(5, replacement);
    b.tick("same-index-new-fulltag-rejects-old-resident", false);
    b.tick("accept-new-fulltag"); b.quiesce();

    b.atHead(14);
    for (const auto index : {14U, 15U, 0U}) b.program(index, b.load(index, 7));
    b.pending = bit(14) | bit(15) | bit(0); b.tick("wrapped-circular-prime");
    b.tick("wrapped-accept14"); b.tick("wrapped-accept15"); b.tick("wrapped-accept0"); b.quiesce();
    b.atHead(0);

    b.program(0, b.store(0), true); b.tick("raw-store-resident-prime", false);
    const auto originalStore = b.payload(0);
    b.save(0, originalStore.address, originalStore.data); ++b.cover.rawToSaved;
    b.ready &= ~((uint64_t(1) << 7) | (uint64_t(1) << 47));
    b.tick("same-token-raw-to-saved-identical-tuple", false);
    b.tick("accept-saved-after-source-ready-removed"); b.quiesce(); b.ready = allReady;

    // Saved younger stores may fill only an empty original pool unless the
    // already-qualified posted window permits the union. Excluding the original
    // on its acceptance edge must not make fallback appear prematurely.
    b.program(0, b.load(0, 7)); b.program(3, b.store(3));
    b.save(3, 0x98765000, 0xc001d00dbeef1234ULL); b.pending = bit(0) | bit(3);
    in = b.input(false); in.fallbackQualified = bit(3); b.tick(in, "original-precludes-fallback-prime");
    in = b.input(); in.fallbackQualified = bit(3); b.tick(in, "issued-original-does-not-expose-fallback");
    in = b.input(false); in.fallbackQualified = bit(3); b.tick(in, "fallback-after-original-pending-clears");
    in = b.input(); in.fallbackQualified = bit(3); b.tick(in, "accept-saved-fallback"); b.quiesce();

    b.program(1, b.store(1)); b.save(1, 0x87654000, 0x1122334455667788ULL);
    b.program(4, b.load(4, 7)); b.pending = bit(1) | bit(4);
    in = b.input(false); in.fallbackQualified = bit(1); in.postedWindow = true;
    b.tick(in, "posted-union-keeps-circular-age");
    in = b.input(); in.fallbackQualified = bit(1); in.postedWindow = true;
    b.tick(in, "posted-union-accept-older-saved"); b.tick("posted-union-accept-load"); b.quiesce();

    b.program(0, b.store(0), true); b.ready &= ~(uint64_t(1) << 47);
    b.tick("late-store-data-ineligible"); ++b.cover.lateData;
    in = b.input(); in.writes[1] = {true, 47, 0xabcdef0123456789ULL};
    b.tick(in, "late-store-data-write-not-ready-until-edge");
    b.ready |= uint64_t(1) << 47; b.tick("late-store-data-registered-ready");
    b.tick("late-store-data-accepted"); b.quiesce();

    b.program(0, b.store(0), true); b.tick("kill-resident-prime", false);
    in = b.input(); in.kill = bit(0); in.writes[0] = {true, 7, 0xfacecafe12340000ULL};
    in.reserveMask = uint64_t(1) << 7;
    b.tick(in, "kill-blocks-start-before-source-reuse"); b.quiesce();

    // Lifecycle witness: retirement of the producer does not release a source
    // with an older pending consumer. A younger architectural overwrite uses a
    // distinct physical word. Rollback permits reuse only after consumer kill.
    b.atHead(0); b.program(5, b.load(5, 7), true); b.tick("lifecycle-consumer-prime", false);
    in = b.input(false); in.commits = 1; b.tick(in, "source-producer-retirement-keeps-physical-source");
    ++b.cover.producerRetire;
    in = b.input(false); in.reserveMask = uint64_t(1) << 33;
    in.writes[1] = {true, 33, 0x9999888877776666ULL};
    b.tick(in, "younger-architectural-overwrite-uses-distinct-physical"); ++b.cover.youngerOverwrite;
    in = b.input(false); in.kill = bit(5); b.tick(in, "rollback-kills-consumer");
    in = b.input(); in.reserveMask = uint64_t(1) << 7; in.writes[0] = {true, 7, 0x1357246800000007ULL};
    b.tick(in, "rollback-reuses-source-after-consumer-death"); ++b.cover.rollbackReuse; b.quiesce();
}

void randomized(Bench& b) {
    std::mt19937_64 rng(0x7265736964656e74ULL);
    // Bounded independent packets: no accepted token is reintroduced, and row
    // contents remain immutable until the prior owner is dead. Random writes
    // never target a surviving source.
    for (unsigned packet = 0; packet != 48; ++packet) {
        b.atHead(rng() % slots); b.ready = allReady;
        const unsigned count = 1 + rng() % 12;
        for (unsigned age = 0; age != count; ++age) {
            const unsigned index = (b.head + age) % slots;
            auto r = b.load(index, 1 + rng() % 30); r.tag = rng(); r.immediate = rng(); r.size = rng() % 4;
            if (age == 0 && packet % 3 == 0) { r.store = true; r.source2 = 47; }
            if (age == 1 && packet % 5 == 0) { r.atomic = true; r.source2 = 31; }
            b.program(index, r);
        }
        for (unsigned age = 0; age != count; ++age) b.pending |= bit((b.head + age) % slots);
        for (unsigned n = 0; n != count * 4 + 8 && b.pending; ++n) {
            auto in = b.input(rng() % 4 != 0);
            in.authority = unsigned(rng()) & 0xffff;
            if (n % 5 == 0) in.poolSuppress = unsigned(rng()) & b.pending;
            if (n == count + 1 && packet % 4 == 0) in.kill = unsigned(rng()) & b.pending;
            if (n % 7 == 0) in.writes[packet % 2] = {true, 40, rng()};
            b.tick(in, "seeded-honest-pending-lifecycle");
        }
        while (b.pending) b.tick("seeded-packet-authorized-drain");
        b.quiesce();
    }
}

void illegal(Bench& b, bool reserve) {
    b.write(7, 0x1234567800000007ULL); b.program(0, b.load(0, 7), true);
    b.tick("illegal-source-resident-prime", false);
    auto in = b.input(false);
    if (reserve) in.reserveMask = uint64_t(1) << 7;
    else in.writes[0] = {true, 7, 0xbadbadbad0000007ULL};
    std::cerr << "RESIDENT_MEMORY_EXPECT_ASSERT kind=" << (reserve ? "reserve" : "write")
              << " source=7 live=1 surviving=1 raw=1\n";
    b.tick(in, reserve ? "illegal-reserve-live-raw-source" : "illegal-write-live-raw-source");
    throw std::runtime_error("RESIDENT_MEMORY_MISSING_INVARIANT_ASSERTION");
}
} // namespace

int main(int argc, char** argv) {
    try {
        Bench b; std::string illegalMode;
        for (int i = 1; i < argc; ++i) {
            const std::string arg = argv[i];
            if (arg == "--inject-mismatch") b.injectMismatch = true;
            else if (arg == "--illegal-reserve" || arg == "--illegal-write") illegalMode = arg;
            else if (arg == "--mutation" && i + 1 < argc) b.mutation = unsigned(std::stoul(argv[++i]));
            else if (arg.rfind("--mutation=", 0) == 0) b.mutation = unsigned(std::stoul(arg.substr(11)));
            else if (arg == "--mutate-index-only") b.mutation = 1;
            else if (arg == "--mutate-retain-issued") b.mutation = 2;
            else if (arg == "--mutate-saved-data") b.mutation = 3;
            else if (arg == "--mutate-issued-before-fallback") b.mutation = 4;
            else throw std::runtime_error("unknown argument: " + arg);
        }
        b.require(b.mutation <= 4, "mutation must be 0..4");
        b.reset();
        if (!illegalMode.empty()) illegal(b, illegalMode == "--illegal-reserve");
        directed(b); randomized(b);
        b.require(b.accepted[0] == b.accepted[1], "PAIR complete accepted tuple/cycle trace differs");
        b.require(!b.pending && !b.stages[0].valid && !b.stages[1].valid, "final stages did not drain");
        b.require(!b.mutation, "requested RTL mutation escaped oracle");
        b.require(!b.injectMismatch || b.mismatchInjected, "requested mismatch was never injected");
        const auto& c = b.cover;
        b.require(c.accepted && c.held && c.reused && c.olderDisplacement && c.absentPoolStart && c.staleTag &&
            c.killed && c.fallback && c.postedUnion && c.issuedOriginalNoFallback && c.saved && c.rawToSaved &&
            c.lateData && c.wraps && c.collisions && c.preedgeRead && c.zeroReads && c.zeroWrites &&
            c.highestReads && c.uninitializedReads && c.emptyPoison == slots && c.producerRetire &&
            c.youngerOverwrite && c.rollbackReuse && c.headMoves && c.loadData && c.longestRun >= slots,
            "directed coverage incomplete");
        std::cout << "RESIDENT_MEMORY_PAIR_PASS rob=16 physical=48 off_reads=4 on_reads=2 cycles=" << c.cycles
                  << " starts=" << c.accepted << " next=" << c.next << " reuse=" << c.reused
                  << " blocked=" << c.held << " longest_start_run=" << c.longestRun
                  << " older_displacement=" << c.olderDisplacement << " absent_E_start=" << c.absentPoolStart
                  << " stale_fulltag=" << c.staleTag << " kill=" << c.killed << " fallback=" << c.fallback
                  << " posted_union=" << c.postedUnion << " issued_before_fallback_guard=" << c.issuedOriginalNoFallback
                  << " saved=" << c.saved << " raw_to_saved=" << c.rawToSaved << " late_data=" << c.lateData
                  << " wrap=" << c.wraps << " prf_collision=" << c.collisions << " preedge_read=" << c.preedgeRead
                  << " x0_read=" << c.zeroReads << " x0_write=" << c.zeroWrites << " physical47=" << c.highestReads
                  << " uninitialized=" << c.uninitializedReads << " poison_empty=" << c.emptyPoison
                  << " producer_retire=" << c.producerRetire << " younger_overwrite=" << c.youngerOverwrite
                  << " rollback_reuse=" << c.rollbackReuse << " full_load_data=" << c.loadData
                  << " head_moves=" << c.headMoves << " resets=" << c.resets << '\n';
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "RESIDENT_MEMORY_PAIR_FAIL " << e.what() << '\n';
        return 1;
    }
}
