// Independent owner-ticket and byte-interval oracle. DUT outputs never choose
// future inputs, expected owners, permissions, service responses, or issue time.
#include "ElasticLoadProofGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <map>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {
constexpr uint64_t Ram = 0x80000000ULL, RamBytes = 0x400000ULL, Va = 0x40000000ULL;
struct Token { unsigned index = 0; uint64_t tag = 0; bool operator==(const Token &) const = default; };
struct Key {
    Token token; uint64_t address = 0; unsigned size = 0, epoch = 7;
    bool operator==(const Key &) const = default;
};
struct Row {
    bool valid = false; Key key; uint64_t physical = 0; bool normal = false, allowed = false;
    uint64_t queried = 0;
};
struct Ticket { Token token; unsigned size = 0; bool pending = true, ordinary = true; };
struct Response { bool valid = true; uint64_t physical = Ram; unsigned pbmt = 0, epoch = 7; };
struct Inputs {
    std::optional<Key> current, lookahead;
    std::optional<Token> issued;
    unsigned epoch = 7, privilege = 1;
    bool stable = true, flush = false;
    std::optional<Response> response;
};
struct Plan {
    bool resultSpace = false, advance = false, translatedSpace = false;
    bool offer = false, accept = false, fromD = false, transfer = false, capture = false;
    bool preemptT = false, preemptR = false;
    std::optional<Key> query;
    Response response;
    std::array<bool, 3> live{}, fresh{}, conflict{};
};
struct Coverage {
    uint64_t cycles = 0, queries = 0, advances = 0, captures = 0, issued = 0;
    uint64_t heldD = 0, heldT = 0, heldR = 0, rawConsumeBlocked = 0, noDRefill = 0;
    uint64_t turnover = 0, queryCaptureDedup = 0, negatives = 0, staleResponses = 0;
    uint64_t preemptT = 0, preemptR = 0, transferredCancel = 0, issuedIncoming = 0;
    uint64_t dead = 0, inconsistent = 0, flushes = 0, unstable = 0, epochKills = 0;
    uint64_t pmpCases = 0, warmIssues = 0, warmQueries = 0;
    uint64_t discardDHit = 0, discardDMiss = 0, discardDStale = 0, discardDIssue = 0;
    uint64_t badDGoodT = 0, badTGoodD = 0;
};

class Oracle {
    SElasticLoadProofGsim dut;
    std::array<Row, 3> rows{}; // descriptor, translated, prepared
    std::array<bool, 3> heldPayload{};
    std::array<std::optional<Ticket>, 16> ledger{};
    std::map<uint64_t, Response> translations;
    std::array<unsigned, 16> cfg{};
    std::array<uint64_t, 16> addr{};
    Coverage cov;
    std::string injection;
    bool injected = false;
    std::optional<Token> forbiddenPublication;
    std::string scenario = "reset";
    uint64_t sequence = 1;

    void require(bool ok, const std::string &message) const {
        if (!ok) throw std::runtime_error("case=" + scenario + " cycle=" + std::to_string(cov.cycles) + " " + message);
    }
    static bool sameNumerical(const Key &a, const Key &b) {
        return a.token == b.token && a.address == b.address && a.size == b.size;
    }
    static bool tokenConflict(const Key &a, const Key &b) {
        return a.token == b.token && !sameNumerical(a, b);
    }
    bool live(const Row &r) const {
        if (!r.valid) return false;
        const auto &t = ledger.at(r.key.token.index);
        return t && t->pending && t->ordinary && t->token == r.key.token && t->size == r.key.size;
    }
    // Decode PMP into mathematical half-open byte intervals, then visit each
    // access byte. No copied hardware range/alignment/priority helpers are used.
    bool readPermission(uint64_t pa, unsigned size, unsigned privilege) const {
        using Wide = unsigned __int128;
        const Wide begin = pa, end = begin + (Wide(1) << size);
        for (unsigned i = 0; i < 16; ++i) {
            const unsigned mode = (cfg[i] >> 3) & 3;
            if (!mode) continue;
            Wide low = 0, high = 0;
            if (mode == 1) { low = i ? Wide(addr[i - 1]) * 4 : 0; high = Wide(addr[i]) * 4; }
            if (mode == 2) { low = Wide(addr[i]) * 4; high = low + 4; }
            if (mode == 3) {
                unsigned ones = 0;
                while (ones < 54 && ((addr[i] >> ones) & 1)) ++ones;
                const unsigned exponent = ones + 3 > 56 ? 56 : ones + 3;
                const Wide length = Wide(1) << exponent;
                low = (Wide(addr[i]) * 4) & ~(length - 1); high = low + length;
            }
            bool touches = false, contains = true;
            for (Wide byte = begin; byte < end; ++byte) {
                const bool inside = byte >= low && byte < high;
                touches |= inside; contains &= inside;
            }
            if (touches) return contains && ((privilege == 3 && !(cfg[i] & 0x80)) || (cfg[i] & 1));
        }
        return privilege == 3;
    }
    bool permission(const Row &r, unsigned privilege) const {
        const uint64_t bytes = uint64_t(1) << r.key.size;
        bool insideRam = true;
        for (unsigned b = 0; b < bytes; ++b) {
            const unsigned __int128 address = static_cast<unsigned __int128>(r.physical) + b;
            insideRam &= address >= Ram && address < static_cast<unsigned __int128>(Ram) + RamBytes;
        }
        return r.normal && r.key.address % bytes == 0 && insideRam &&
            (r.key.address % 4096 == r.physical % 4096) && readPermission(r.physical, r.key.size, privilege);
    }
    Plan plan(const Inputs &in) const {
        Plan p;
        const bool active = in.stable && !in.flush;
        for (unsigned i = 0; i < 3; ++i) {
            p.live[i] = live(rows[i]);
            p.fresh[i] = p.live[i] && rows[i].key.epoch == in.epoch;
            p.conflict[i] = rows[i].valid &&
                ((in.current && tokenConflict(rows[i].key, *in.current)) ||
                 (in.lookahead && tokenConflict(rows[i].key, *in.lookahead)));
        }
        std::array<bool, 3> currentIn{};
        bool currentConflict = false;
        for (unsigned i = 0; i < 3; ++i) {
            currentIn[i] = in.current && p.fresh[i] && rows[i].key == *in.current;
            currentConflict |= in.current && rows[i].valid && tokenConflict(rows[i].key, *in.current);
        }
        const bool reserved = currentIn[0] || currentIn[1] || currentIn[2];
        p.resultSpace = !rows[2].valid;
        p.advance = rows[1].valid && p.fresh[1] && p.resultSpace && active;
        p.translatedSpace = !rows[1].valid || p.advance;
        if (in.current && !reserved && !currentConflict) p.query = in.current;
        // An immutable, live D snapshot may perform a discard-only hit peek
        // despite a new numerical-key disagreement. This is not an accepted
        // memory demand or page-walk request: token cancellation still removes
        // D and every tentative copy before any resulting proof can publish.
        else if ((currentIn[0] || !in.current || reserved) && p.fresh[0]) {
            p.query = rows[0].key; p.fromD = true;
        }
        p.offer = p.query && p.translatedSpace && active;
        if (in.response) p.response = *in.response;
        else if (p.query && translations.contains(p.query->address)) p.response = translations.at(p.query->address);
        else p.response = {.valid = false, .epoch = in.epoch};
        p.accept = p.offer && (!p.response.valid || p.response.epoch == in.epoch);
        p.transfer = p.accept && p.fromD;
        bool tokenResident = false;
        if (in.lookahead) for (const Row &r : rows)
            tokenResident |= r.valid && r.key.token == in.lookahead->token;
        const bool queryDuplicate = in.lookahead && p.accept && p.query->token == in.lookahead->token;
        const bool sourceDisagrees = in.lookahead && in.current && tokenConflict(*in.lookahead, *in.current);
        p.capture = !rows[0].valid && in.lookahead && !tokenResident && !queryDuplicate && !sourceDisagrees && active;
        if (in.current) {
            const bool needQuery = !currentIn[1] && !currentIn[2];
            p.preemptT = needQuery && rows[1].valid && !(in.current->token == rows[1].key.token);
            p.preemptR = !currentIn[2] && rows[2].valid && !(in.current->token == rows[2].key.token);
        }
        return p;
    }
    void drive(const Inputs &in, const Plan &p) {
        const Key c = in.current.value_or(Key{}), l = in.lookahead.value_or(Key{});
        const Token issued = in.issued.value_or(Token{});
        dut.set_io$$current$$valid(in.current.has_value());
        dut.set_io$$current$$bits$$token$$index(c.token.index); dut.set_io$$current$$bits$$token$$tag(c.token.tag);
        dut.set_io$$current$$bits$$address(c.address); dut.set_io$$current$$bits$$size(c.size);
        dut.set_io$$lookahead$$valid(in.lookahead.has_value());
        dut.set_io$$lookahead$$bits$$token$$index(l.token.index); dut.set_io$$lookahead$$bits$$token$$tag(l.token.tag);
        dut.set_io$$lookahead$$bits$$address(l.address); dut.set_io$$lookahead$$bits$$size(l.size);
        dut.set_io$$issued$$valid(in.issued.has_value());
        dut.set_io$$issued$$bits$$index(issued.index); dut.set_io$$issued$$bits$$tag(issued.tag);
        dut.set_io$$descriptorOwnerLive(p.live[0]); dut.set_io$$translatedOwnerLive(p.live[1]);
        dut.set_io$$preparedOwnerLive(p.live[2]);
        dut.set_io$$precheck$$response$$valid(p.response.valid);
        dut.set_io$$precheck$$response$$bits$$physicalAddress(p.response.physical);
        dut.set_io$$precheck$$response$$bits$$pbmt(p.response.pbmt);
        dut.set_io$$precheck$$response$$bits$$epoch(p.response.epoch);
        dut.set_io$$precheck$$epoch(in.epoch); dut.set_io$$precheck$$stable(in.stable);
        dut.set_io$$flush(in.flush); dut.set_io$$privilege(in.privilege);
#define PMP_PIN(N) dut.set_io$$cfg##N(cfg[N]); dut.set_io$$addr##N(addr[N]);
        PMP_PIN(0) PMP_PIN(1) PMP_PIN(2) PMP_PIN(3) PMP_PIN(4) PMP_PIN(5) PMP_PIN(6) PMP_PIN(7)
        PMP_PIN(8) PMP_PIN(9) PMP_PIN(10) PMP_PIN(11) PMP_PIN(12) PMP_PIN(13) PMP_PIN(14) PMP_PIN(15)
#undef PMP_PIN
    }
    void observe(const Inputs &in, const Plan &p) {
#define OWNER_ROW(NAME) Row{bool(dut.get_io$$##NAME##$$valid()), \
        {{unsigned(dut.get_io$$##NAME##$$bits$$token$$index()), uint64_t(dut.get_io$$##NAME##$$bits$$token$$tag())}, \
         uint64_t(dut.get_io$$##NAME##$$bits$$address()), unsigned(dut.get_io$$##NAME##$$bits$$size()), \
         unsigned(dut.get_io$$##NAME##$$bits$$epoch())}}
        std::array<Row, 3> actual{OWNER_ROW(descriptorOwner), OWNER_ROW(translatedOwner), OWNER_ROW(preparedOwner)};
#undef OWNER_ROW
        actual[1].physical = dut.get_io$$translatedPayload$$physicalAddress();
        actual[1].allowed = dut.get_io$$translatedPayload$$allowed();
        actual[1].normal = dut.get_io$$translatedNormal();
        actual[2].physical = dut.get_io$$preparedPayload$$physicalAddress();
        actual[2].allowed = dut.get_io$$preparedPayload$$allowed();
        bool resultSpace = dut.get_io$$resultSpace();
        if (!injected && injection == "owner" && actual[1].valid) {
            injected = true; actual[1].key.token.tag ^= UINT64_C(1) << 40;
            std::cerr << "ELASTIC_LOAD_PROOF_INJECTION_REACHED kind=owner mutation=sampled_high_tag\n";
        }
        if (!injected && injection == "permission" && actual[2].valid) {
            injected = true; actual[2].allowed = !actual[2].allowed;
            std::cerr << "ELASTIC_LOAD_PROOF_INJECTION_REACHED kind=permission mutation=sampled_allowed\n";
        }
        if (!injected && injection == "credit" && rows[2].valid && in.issued) {
            injected = true; resultSpace = true;
            std::cerr << "ELASTIC_LOAD_PROOF_INJECTION_REACHED kind=credit mutation=borrow_same_edge_issue\n";
        }
        for (unsigned i = 0; i < 3; ++i) {
            require(actual[i].valid == rows[i].valid, "independent raw validity mismatch slot=" + std::to_string(i));
            if (rows[i].valid || heldPayload[i]) {
                require(actual[i].key == rows[i].key, "independent full owner key mismatch slot=" + std::to_string(i));
                if (i) require(actual[i].physical == rows[i].physical,
                    "independent physical payload mismatch slot=" + std::to_string(i));
                if (i == 1) require(actual[i].normal == rows[i].normal && !actual[i].allowed,
                    "independent translated response mismatch");
                if (i == 2) require(actual[i].allowed == rows[i].allowed, "independent byte permission mismatch");
            }
        }
        require(resultSpace == p.resultSpace, "independent raw pre-edge R credit mismatch");
        require(bool(dut.get_io$$translatedAdvance()) == p.advance, "independent T-to-R advance mismatch");
        require(bool(dut.get_io$$translatedSpace()) == p.translatedSpace, "independent raw pre-edge T credit mismatch");
        require(bool(dut.get_io$$queryOffer()) == p.offer && bool(dut.get_io$$precheck$$request$$valid()) == p.offer,
            "independent query offer mismatch");
        require(bool(dut.get_io$$queryAccept()) == p.accept, "independent response-epoch query acceptance mismatch");
        require(bool(dut.get_io$$descriptorTransfer()) == p.transfer, "independent descriptor transfer mismatch");
        require(bool(dut.get_io$$descriptorCapture()) == p.capture, "independent raw-empty descriptor capture mismatch");
        require(!dut.get_io$$descriptorPreempt() && bool(dut.get_io$$translatedPreempt()) == p.preemptT &&
            bool(dut.get_io$$preparedPreempt()) == p.preemptR, "independent token-specific advisory preemption mismatch");
        require(bool(dut.get_io$$queryFromDescriptor()) == p.fromD, "independent early query source mismatch");
        require(bool(dut.get_io$$negativeExpire()) == (rows[2].valid && !rows[2].allowed),
            "independent negative publication expiration mismatch");
        require(bool(dut.get_io$$hit()) == (p.offer && p.response.valid && in.stable),
            "independent raw hit observation mismatch");
        if (p.offer) require(dut.get_io$$precheck$$request$$bits$$address() == p.query->address &&
            dut.get_io$$precheck$$request$$bits$$size() == p.query->size && !dut.get_io$$precheck$$request$$bits$$write(),
            "independent query numerical ownership mismatch");
        // Actual issue is deliberately not a combinational prepared-valid veto.
        const bool publication = rows[2].valid && p.fresh[2] && in.stable && !in.flush;
        require(bool(dut.get_io$$prepared$$valid()) == publication, "independent prepared publication mismatch");
        if (forbiddenPublication && dut.get_io$$prepared$$valid())
            require(dut.get_io$$prepared$$bits$$token$$index() != forbiddenPublication->index ||
                dut.get_io$$prepared$$bits$$token$$tag() != forbiddenPublication->tag,
                "discard-only peek or canceled transfer published its rejected full-token owner");
        if (publication) require(dut.get_io$$prepared$$bits$$allowed() == rows[2].allowed &&
            dut.get_io$$prepared$$bits$$token$$index() == rows[2].key.token.index &&
            dut.get_io$$prepared$$bits$$token$$tag() == rows[2].key.token.tag &&
            dut.get_io$$prepared$$bits$$address() == rows[2].key.address &&
            dut.get_io$$prepared$$bits$$size() == rows[2].key.size &&
            dut.get_io$$prepared$$bits$$epoch() == rows[2].key.epoch &&
            dut.get_io$$prepared$$bits$$physicalAddress() == rows[2].physical,
            "independent externally usable certificate mismatch");
        require(dut.get_io$$descriptorBits() == 167 && dut.get_io$$translatedBits() == 233 &&
            dut.get_io$$preparedBits() == 232, "current-shape declared state count mismatch");
    }
    void advance(const Inputs &in, const Plan &p) {
        const auto old = rows;
        heldPayload = {old[0].valid, old[1].valid && !p.advance, old[2].valid};
        if (p.transfer) rows[0].valid = false;
        if (p.capture) rows[0] = {.valid = true, .key = *in.lookahead};
        if (p.advance) {
            rows[1].valid = false; rows[2] = old[1]; rows[2].allowed = permission(old[1], in.privilege);
        }
        if (p.accept) rows[1] = {.valid = true, .key = *p.query,
            .physical = p.response.valid ? p.response.physical : 0,
            .normal = p.response.valid && p.response.pbmt == 0, .allowed = false, .queried = cov.cycles};
        std::vector<Token> cancelled;
        for (unsigned i = 0; i < 3; ++i) if (old[i].valid &&
            (!p.fresh[i] || p.conflict[i] || (i == 1 && p.preemptT) || (i == 2 && p.preemptR)))
            cancelled.push_back(old[i].key.token);
        if (in.issued) cancelled.push_back(*in.issued);
        for (Row &r : rows) {
            for (const Token &token : cancelled) if (r.key.token == token) r.valid = false;
            if (old[2].valid && !old[2].allowed && r.key == old[2].key) r.valid = false;
            if (in.flush || !in.stable || r.key.epoch != in.epoch) r.valid = false;
        }
        cov.queries += p.accept; cov.advances += p.advance; cov.captures += p.capture;
        cov.issued += in.issued.has_value();
        cov.heldD += old[0].valid && rows[0].valid && !p.transfer;
        cov.heldT += old[1].valid && rows[1].valid && !p.advance && !p.accept;
        cov.heldR += old[2].valid && rows[2].valid;
        cov.rawConsumeBlocked += old[2].valid && in.issued && *in.issued == old[2].key.token && !p.advance;
        cov.noDRefill += p.transfer && in.lookahead.has_value() && !p.capture;
        cov.turnover += p.advance && p.accept;
        cov.queryCaptureDedup += in.lookahead && p.accept && p.query->token == in.lookahead->token && !p.capture;
        cov.negatives += old[2].valid && !old[2].allowed;
        cov.staleResponses += p.offer && p.response.valid && p.response.epoch != in.epoch && !p.accept;
        // Count advisory disposals only while the context is enabled, not when
        // a coincident global flush/unstable boundary already clears all state.
        cov.preemptT += p.preemptT && in.stable && !in.flush;
        cov.preemptR += p.preemptR && in.stable && !in.flush;
        cov.transferredCancel += p.advance && p.preemptT && !rows[2].valid;
        cov.issuedIncoming += p.accept && in.issued && *in.issued == p.query->token && !rows[1].valid;
        const bool discardPeek = old[0].valid && p.conflict[0] && p.fromD && p.offer;
        cov.discardDHit += discardPeek && p.accept && p.response.valid;
        cov.discardDMiss += discardPeek && p.accept && !p.response.valid;
        cov.discardDStale += discardPeek && !p.accept && p.response.valid && p.response.epoch != in.epoch;
        cov.discardDIssue += discardPeek && in.issued && *in.issued == old[0].key.token;
        cov.badDGoodT += p.transfer && p.conflict[0] && p.advance && !p.conflict[1] && !p.preemptT &&
            rows[2].valid && rows[2].key == old[1].key && !rows[1].valid;
        cov.badTGoodD += p.transfer && !p.conflict[0] && p.advance && p.conflict[1] &&
            rows[1].valid && rows[1].key == old[0].key && !rows[2].valid;
        for (unsigned i = 0; i < 3; ++i) {
            cov.dead += old[i].valid && !p.live[i]; cov.inconsistent += p.conflict[i];
            cov.epochKills += old[i].valid && old[i].key.epoch != in.epoch;
        }
        cov.flushes += in.flush; cov.unstable += !in.stable; ++cov.cycles;
    }
public:
    explicit Oracle(std::string mutate) : injection(std::move(mutate)) {
        allowAll(); const Inputs in; const auto p = plan(in);
        dut.LOG_START = 1; dut.activateAll(); drive(in, p);
        dut.set_reset(true); dut.step(); dut.step(); dut.set_reset(false);
    }
    void allowAll() { cfg.fill(0); addr.fill(0); cfg[0] = 0x1f; addr[0] = (UINT64_C(1) << 54) - 1; }
    Key make(unsigned size = 3, std::optional<uint64_t> address = {}, std::optional<unsigned> index = {}) {
        const uint64_t id = sequence++;
        Key k{{index.value_or(unsigned(id & 15)), UINT64_C(0x8fed000000000000) + id},
            address.value_or(Va + (id * 16) % 0x100000), size, 7};
        ledger[k.token.index] = Ticket{k.token, size};
        translations[k.address] = {.physical = Ram + (k.address - Va), .epoch = k.epoch};
        return k;
    }
    Plan tick(Inputs in = {}) {
        if (in.current) in.current->epoch = in.epoch;
        if (in.lookahead) in.lookahead->epoch = in.epoch;
        const Plan p = plan(in); drive(in, p); dut.step(); observe(in, p); advance(in, p); return p;
    }
    void clean(const std::string &name) {
        forbiddenPublication.reset();
        scenario = name; tick({.flush = true}); tick(); ledger.fill({}); translations.clear(); allowAll();
        require(!rows[0].valid && !rows[1].valid && !rows[2].valid, "flush cleanup did not release reservations");
    }
    void checkDiscarded(Token token) {
        forbiddenPublication = token;
        // Observe every subsequent register boundary without offering a retry.
        // Three quiet cycles cover D -> T -> R, including a delayed ghost copy;
        // a later explicit retry is a new reservation and is checked separately.
        for (unsigned n = 0; n < 3; ++n) {
            for (const Row &r : rows)
                require(!r.valid || !(r.key.token == token), "rejected full-token owner retained a reservation");
            tick();
        }
        forbiddenPublication.reset();
    }
    void waitProof(Key key, bool allowed, Inputs settings = {}) {
        settings.current = key;
        const uint64_t start = cov.cycles;
        auto p = tick(settings); require(p.accept, "direct current query was not accepted");
        require(rows[1].valid && !rows[2].valid, "query bypassed translated register");
        tick(settings); require(rows[2].valid && rows[2].key == key && rows[2].allowed == allowed,
            "independent direct proof expected after two accepted edges");
        require(cov.cycles - start == 2, "minimum direct latency must be two");
        const auto pub = tick(settings);
        require(!pub.accept, "positive or negative publication must reserve exact current for entire cycle");
        if (!allowed) { require(!rows[2].valid, "negative result did not expire at publication edge");
            require(tick(settings).accept, "same-epoch negative retry did not reopen next cycle"); }
    }
    void warm() {
        clean("continuous-ready-current-and-second");
        constexpr unsigned Count = 48;
        std::vector<Key> work; work.reserve(Count);
        // At most two ranks are exposed. Tickets are installed only when an owner
        // becomes visible, so ROB-index reuse cannot overwrite a live generation.
        for (unsigned n = 0; n < Count; ++n) {
            Key k{{n & 15, UINT64_C(0xfedc000000000000) + n}, Va + 0x10000 + 16 * n, 3, 7};
            work.push_back(k); translations[k.address] = {.physical = Ram + 0x10000 + 16 * n};
        }
        std::vector<uint64_t> issues;
        unsigned head = 0;
        const auto beginQueries = cov.queries, beginT = cov.preemptT, beginR = cov.preemptR;
        while (head < Count && issues.size() < Count && cov.cycles < 500) {
            const Key c = work[head]; ledger[c.token.index] = Ticket{c.token, c.size};
            Inputs in{.current = c};
            if (head + 1 < Count) { const Key l = work[head + 1]; in.lookahead = l;
                ledger[l.token.index] = Ticket{l.token, l.size}; }
            if (rows[2].valid && rows[2].key == c && rows[2].allowed) in.issued = c.token;
            const uint64_t time = cov.cycles;
            tick(in);
            if (in.issued) { issues.push_back(time); ledger[c.token.index]->pending = false; ++head; }
        }
        require(issues.size() == Count, "continuous ready supply failed to drain bounded work");
        for (unsigned i = 1; i < issues.size(); ++i)
            require(issues[i] - issues[i - 1] == 2, "ideal continuous distinct-owner issue interval is not two");
        require(cov.queries - beginQueries == Count, "warm stream duplicated a full owner query");
        require(cov.preemptT == beginT && cov.preemptR == beginR, "warm stream unexpectedly used advisory preemption");
        cov.warmIssues = issues.size(); cov.warmQueries = cov.queries - beginQueries;
        std::cout << "ELASTIC_LOAD_PROOF_IDEAL issues=" << issues.size() << " unique_queries=" << cov.warmQueries
            << " steady_issue_interval=2 first_to_last=" << issues.back() - issues.front()
            << " cpu_performance_claim=false\n";
    }
    void directed() {
        clean("minimum-current-latency"); auto a = make(); waitProof(a, true);
        clean("minimum-descriptor-latency"); a = make();
        tick({.lookahead = a}); require(rows[0].valid && !rows[1].valid, "descriptor bypassed first register");
        tick(); require(rows[1].valid && !rows[2].valid, "descriptor query bypassed translated register");
        tick(); require(rows[2].valid && rows[2].key == a, "descriptor minimum three-edge proof missing"); tick();

        clean("full-hold-and-no-late-consume-credit"); a = make(); auto b = make(); auto c = make(); auto d = make();
        tick({.current = a, .lookahead = b}); tick({.current = a});
        tick({.current = a, .lookahead = c});
        require(rows[0].valid && rows[1].valid && rows[2].valid, "failed to fill independent D/T/R positions");
        for (unsigned i = 0; i < 7; ++i) tick({.current = a, .lookahead = d});
        auto p = tick({.current = a, .lookahead = d, .issued = a.token});
        require(!p.advance && !p.accept, "same-edge result issue borrowed raw credit");
        p = tick({.current = b, .lookahead = d});
        require(p.advance && p.transfer && !p.capture, "T turnover or no-same-edge D refill contract failed");
        require(rows[1].key == c && rows[2].key == b, "legal turnover lost either distinct owner");
        tick({.current = b, .lookahead = d}); require(rows[0].key == d, "following-edge D capture did not resume");

        clean("accepted-query-descriptor-dedup"); a = make();
        p = tick({.current = a, .lookahead = a}); require(p.accept && !p.capture, "query/D same-edge token duplicated");
        tick({.current = a, .lookahead = a}); tick({.current = a, .lookahead = a});

        clean("stale-response-keeps-descriptor"); a = make(); tick({.lookahead = a});
        p = tick({.response = Response{.physical = Ram, .epoch = 6}});
        require(p.offer && !p.accept && rows[0].valid && !rows[1].valid, "stale response consumed descriptor");
        tick(); tick(); tick();

        clean("miss-negative-fill-retry"); a = make(); translations.erase(a.address);
        tick({.current = a}); tick({.current = a});
        require(rows[2].valid && !rows[2].allowed, "miss did not make a negative reservation");
        translations[a.address] = {.physical = Ram + (a.address - Va)};
        p = tick({.current = a, .lookahead = a});
        require(!p.offer && !p.capture && !rows[2].valid, "negative publication did not reserve full cycle");
        require(tick({.current = a}).accept, "same-epoch filled translation was not retried");
        tick({.current = a}); require(rows[2].valid && rows[2].allowed, "fill did not produce usable positive proof");
        tick({.current = a, .issued = a.token});

        clean("current-priority-transferred-owner-cancel"); a = make(); b = make();
        tick({.current = b}); p = tick({.current = a});
        require(p.advance && p.accept && p.preemptT && !rows[2].valid && rows[1].key == a,
            "preempted transferred B resurrected or erased unrelated incoming A");
        tick({.current = a}); require(rows[2].valid && rows[2].key == a, "replacement current did not reach result");
        for (unsigned i = 0; i < 4; ++i) tick({.current = a, .lookahead = b});

        clean("current-missing-preempts-full-advisory"); a = make(); b = make(); c = make(); d = make();
        tick({.current = b, .lookahead = c}); tick({.current = b}); tick({.current = b, .lookahead = d});
        p = tick({.current = a}); require(!p.accept && !p.advance && p.preemptT && p.preemptR,
            "full advisory preemption borrowed same-edge space");
        require(rows[0].valid && !rows[1].valid && !rows[2].valid, "preemption canceled wrong owner positions");
        require(tick({.current = a}).accept, "stable new current did not gain next-edge query priority");
        tick({.current = a}); tick({.current = a, .issued = a.token});

        clean("current-in-T-preempts-blocking-R"); a = make(); b = make();
        tick({.current = b, .lookahead = a}); tick({.current = b});
        p = tick({.current = a}); require(!p.advance && p.preemptR && !rows[2].valid && rows[1].key == a,
            "current T did not preserve owner while discarding only blocker R");
        tick({.current = a}); tick({.current = a, .issued = a.token});

        clean("fallback-cancels-incoming-direct-query"); a = make();
        p = tick({.current = a, .issued = a.token});
        require(p.accept && !rows[1].valid, "raw fallback suppressed early query or failed incoming cancellation");
        tick();
        clean("fallback-cancels-new-descriptor"); a = make();
        p = tick({.lookahead = a, .issued = a.token});
        require(p.capture && !rows[0].valid, "actual issue failed new descriptor cancellation or changed early capture");
        tick();
        clean("fallback-while-negative-published"); a = make(); translations.erase(a.address);
        tick({.current = a}); tick({.current = a});
        require(rows[2].valid && !rows[2].allowed, "negative fallback setup missing");
        p = tick({.current = a, .issued = a.token});
        require(!p.accept && !rows[2].valid, "fallback could not release negative reservation after full publication");
        tick();
        clean("fallback-cancels-transferred-result"); a = make(); tick({.current = a});
        p = tick({.current = a, .issued = a.token});
        require(p.advance && !rows[2].valid, "actual fallback resurrected incoming result"); tick();
        clean("fallback-cancels-old-T-not-distinct-replacement"); a = make(); b = make();
        tick({.current = a, .lookahead = b});
        p = tick({.current = a, .issued = a.token});
        require(p.advance && p.transfer && !rows[2].valid && rows[1].valid && rows[1].key == b,
            "old-T actual issue canceled distinct incoming T owner or resurrected outgoing R owner");
        tick({.current = b}); tick({.current = b, .issued = b.token});
        clean("fallback-cancels-descriptor-query"); a = make(); tick({.lookahead = a});
        p = tick({.current = a, .issued = a.token});
        require(p.transfer && !rows[0].valid && !rows[1].valid, "actual issue failed exact descriptor/transferred cancellation");
        tick();
        clean("same-index-different-generation-is-not-consume"); a = make(); waitProof(a, true);
        auto wrong = a.token; wrong.tag ^= UINT64_C(1) << 47;
        tick({.current = a, .issued = wrong}); require(rows[2].valid, "index-only issue consumed wrong generation");
        tick({.current = a, .issued = a.token}); require(!rows[2].valid, "exact full token failed consume");

        for (unsigned slot = 0; slot < 3; ++slot) {
            clean("dead-owner-raw-credit-slot-" + std::to_string(slot)); a = make(); b = make();
            if (slot == 0) tick({.lookahead = a});
            else { tick({.current = a}); if (slot == 2) tick({.current = a}); }
            ledger[a.token.index]->pending = false;
            p = tick({.current = b, .lookahead = b});
            if (slot == 0) require(!p.capture, "dead raw D was treated as empty before cleanup");
            if (slot == 1) require(!p.accept, "dead raw T was treated as empty before cleanup");
            if (slot == 2) require(!p.resultSpace, "dead raw R was treated as empty before cleanup");
            tick({.current = b}); tick({.current = b}); tick({.current = b});
        }
        clean("ROB-index-reuse-full-generation"); a = make(3, {}, 6); tick({.lookahead = a});
        b = make(3, {}, 6); tick({.current = b});
        require(!rows[0].valid && rows[1].valid && rows[1].key == b, "ROB reuse retained old-generation descriptor");
        tick({.current = b}); tick({.current = b});

        for (unsigned slot = 0; slot < 3; ++slot) for (unsigned mismatch = 0; mismatch < 3; ++mismatch) {
            clean("full-key-mismatch-" + std::to_string(slot) + "-" + std::to_string(mismatch)); a = make();
            if (slot == 0) tick({.lookahead = a});
            else { tick({.current = a}); if (slot == 2) tick({.current = a}); }
            b = a;
            if (mismatch == 0) b.address += UINT64_C(1) << 33;
            else if (mismatch == 1) b.size ^= 1;
            else b.address += 8;
            p = mismatch == 2 ? tick({.lookahead = b}) : tick({.current = b});
            const bool discardedPeek = slot == 0 && mismatch == 2;
            require(p.accept == discardedPeek && p.transfer == discardedPeek && !p.capture &&
                !rows[0].valid && !rows[1].valid && !rows[2].valid,
                "same-token differing full VA/size created a surviving reservation instead of discard/cleanup");
            if (discardedPeek) require(p.fromD && p.query == a,
                "discard-only peek did not use the immutable old D snapshot");
            checkDiscarded(a.token);
            ledger[b.token.index] = Ticket{b.token, b.size};
            translations[b.address] = {.physical = Ram + (b.address & 4095)};
            require(tick({.current = b}).accept, "cleaned inconsistent owner could not retry"); tick(); tick();
        }
        clean("current-lookahead-disagree-without-resident"); a = make(); b = a; b.address += 8;
        p = tick({.current = a, .lookahead = b}); require(p.accept && !p.capture, "lookahead overruled staged current");
        tick({.current = a}); tick({.current = a});

        // Cancellation follows the source owner's full token, not the slot it
        // leaves or enters. Both transfers happen using already-empty R credit.
        clean("bad-D-peek-preserves-good-T-result"); a = make(); b = make();
        tick({.current = b, .lookahead = a}); c = a; c.address += 8;
        p = tick({.current = b, .lookahead = c});
        require(p.offer && p.accept && p.transfer && p.advance && p.query == a &&
            p.conflict[0] && !p.conflict[1] && !p.preemptT && !p.capture &&
            !rows[0].valid && !rows[1].valid && rows[2].valid && rows[2].key == b && rows[2].allowed,
            "bad D discard erased distinct good T-to-R result or retained bad D in T");
        checkDiscarded(a.token);
        require(rows[2].valid && rows[2].key == b && rows[2].allowed,
            "good T owner did not retain its positive proof after distinct D cancellation");
        tick({.current = b, .issued = b.token});

        clean("bad-T-result-preserves-good-D-query"); a = make(); b = make();
        tick({.current = b, .lookahead = a}); c = b; c.address += 8;
        p = tick({.current = b, .lookahead = c});
        require(p.accept && p.transfer && p.advance && p.query == a && !p.conflict[0] &&
            p.conflict[1] && !p.preemptT && !rows[0].valid && !rows[2].valid &&
            rows[1].valid && rows[1].key == a,
            "bad old T cancellation erased distinct incoming D owner or resurrected bad T in R");
        checkDiscarded(b.token);
        require(rows[2].valid && rows[2].key == a && rows[2].allowed,
            "good D query did not reach a positive proof after distinct old-T cancellation");
        tick({.current = a, .issued = a.token});

        for (unsigned responseKind = 0; responseKind < 3; ++responseKind)
            for (bool issueAlso : {false, true}) {
                clean("bad-D-discard-response-" + std::to_string(responseKind) + "-issue-" +
                    std::to_string(issueAlso));
                a = make(); tick({.lookahead = a}); b = a; b.address += 8;
                Inputs in{.current = a, .lookahead = b};
                if (responseKind == 1) in.response = Response{.valid = false};
                if (responseKind == 2) in.response = Response{.physical = Ram + (a.address - Va), .epoch = 6};
                if (issueAlso) in.issued = a.token;
                p = tick(in);
                const bool acceptedPeek = responseKind != 2;
                require(p.fromD && p.offer && p.query == a && p.conflict[0] &&
                    p.accept == acceptedPeek && p.transfer == acceptedPeek && !p.capture &&
                    !rows[0].valid && !rows[1].valid && !rows[2].valid,
                    "bad D hit/miss/stale/issue overlap changed early peek or escaped exact-owner cancellation");
                checkDiscarded(a.token);
            }

        for (unsigned cut = 0; cut < 3; ++cut) for (unsigned kind = 0; kind < 3; ++kind) {
            clean("context-cut-" + std::to_string(cut) + "-" + std::to_string(kind)); a = make();
            if (cut == 0) tick({.lookahead = a});
            else { tick({.current = a}); if (cut == 2) tick({.current = a}); }
            Inputs in{.current = a, .lookahead = a};
            if (kind == 0) in.flush = true;
            if (kind == 1) in.stable = false;
            if (kind == 2) { in.epoch = 8; in.response = Response{.epoch = 7}; }
            tick(in);
            require(!rows[0].valid && !rows[1].valid && !rows[2].valid, "context change retained stale preparation owner");
            tick({.epoch = kind == 2 ? 8U : 7U});
        }
    }
    void permissions() {
        auto run = [&](const std::string &name, unsigned size, uint64_t va, Response response,
                       bool expected, unsigned privilege = 1) {
            scenario = name; Key a = make(size, va); translations[a.address] = response;
            waitProof(a, expected, {.privilege = privilege}); ++cov.pmpCases;
        };
        for (unsigned size = 0; size < 4; ++size) {
            clean("alignment"); run("aligned-size-" + std::to_string(size), size, Va + 32,
                {.physical = Ram + 32}, true);
            if (size) { clean("VA-misaligned"); run("VA-misaligned", size, Va + 33, {.physical = Ram + 33}, false); }
        }
        for (unsigned pbmt : {1U, 2U, 3U}) { clean("PBMT-denial");
            run("PBMT-denial", 3, Va + 32, {.physical = Ram + 32, .pbmt = pbmt}, false); }
        for (uint64_t pa : {Ram - 8, Ram + RamBytes, UINT64_MAX - 7, Ram + 33, Ram + 40}) {
            clean("range-offset-denial"); run("range-offset-denial", 3, Va + 32, {.physical = pa}, false);
        }
        clean("last-RAM-byte"); run("last-RAM-byte", 0, Va + 4095, {.physical = Ram + RamBytes - 1}, true);
        clean("last-RAM-doubleword"); run("last-RAM-doubleword", 3, Va + 4088,
            {.physical = Ram + RamBytes - 8}, true);
        // Every raw PMP entry gets an independent positive/negative test. Empty
        // lower entries cannot silently mask cfg15/addr15 wiring mistakes.
        for (unsigned entry = 0; entry < 16; ++entry) for (bool allow : {false, true}) {
            clean("PMP-entry-" + std::to_string(entry)); cfg.fill(0); addr.fill(0);
            cfg[entry] = allow ? 0x19 : 0x18; addr[entry] = (Ram + 32) >> 2;
            run("PMP-NAPOT-entry-" + std::to_string(entry), 3, Va + 32, {.physical = Ram + 32}, allow);
        }
        clean("PMP-first-overlap-wins"); cfg[0] = 0x18; addr[0] = (Ram + 32) >> 2;
        cfg[15] = 0x1f; addr[15] = (UINT64_C(1) << 54) - 1;
        run("PMP-first-overlap-wins", 3, Va + 32, {.physical = Ram + 32}, false);
        clean("PMP-NA4-partial-overlap"); cfg.fill(0); addr.fill(0); cfg[3] = 0x11; addr[3] = (Ram + 36) >> 2;
        cfg[15] = 0x1f; addr[15] = (UINT64_C(1) << 54) - 1;
        run("PMP-NA4-partial-overlap", 3, Va + 32, {.physical = Ram + 32}, false);
        clean("PMP-TOR-cover"); cfg.fill(0); addr.fill(0); addr[6] = (Ram + 32) >> 2;
        addr[7] = (Ram + 40) >> 2; cfg[7] = 0x09;
        run("PMP-TOR-cover", 3, Va + 32, {.physical = Ram + 32}, true);
        clean("PMP-reversed-TOR"); cfg.fill(0); addr.fill(0); addr[6] = (Ram + 40) >> 2;
        addr[7] = (Ram + 32) >> 2; cfg[7] = 0x09;
        run("PMP-reversed-TOR", 3, Va + 32, {.physical = Ram + 32}, false);
        for (unsigned privilege : {1U, 3U}) for (bool locked : {false, true}) {
            clean("PMP-lock-and-privilege"); cfg[0] = locked ? 0x98 : 0x18;
            run("PMP-lock-and-privilege", 3, Va + 32, {.physical = Ram + 32}, privilege == 3 && !locked, privilege);
        }
        for (unsigned privilege : {1U, 3U}) {
            clean("PMP-unmatched"); cfg.fill(0); addr.fill(0);
            run("PMP-unmatched", 3, Va + 32, {.physical = Ram + 32}, privilege == 3, privilege);
        }
    }
    void finish() {
        clean("final-drain");
        require(cov.heldD && cov.heldT && cov.heldR && cov.rawConsumeBlocked && cov.noDRefill && cov.turnover &&
            cov.queryCaptureDedup && cov.negatives && cov.staleResponses && cov.preemptT && cov.preemptR &&
            cov.transferredCancel && cov.issuedIncoming && cov.dead && cov.inconsistent && cov.flushes &&
            cov.unstable && cov.epochKills && cov.pmpCases >= 50 && cov.warmIssues == 48 && cov.warmQueries == 48,
            "required independent contract coverage missing");
        require(cov.discardDHit >= 2 && cov.discardDMiss >= 2 && cov.discardDStale >= 2 &&
            cov.discardDIssue >= 3 && cov.badDGoodT && cov.badTGoodD,
            "discard-only descriptor peek or distinct-owner transfer coverage missing");
        require(injection.empty() || injected, "requested observation injection was not reached");
        std::cout << "ELASTIC_LOAD_PROOF_PASS cycles=" << cov.cycles << " queries=" << cov.queries
            << " advances=" << cov.advances << " captures=" << cov.captures << " issued=" << cov.issued
            << " held_D=" << cov.heldD << " held_T=" << cov.heldT << " held_R=" << cov.heldR
            << " raw_consume_blocked=" << cov.rawConsumeBlocked << " no_D_refill=" << cov.noDRefill
            << " T_turnover=" << cov.turnover << " query_D_dedup=" << cov.queryCaptureDedup
            << " negative_publications=" << cov.negatives << " stale_responses=" << cov.staleResponses
            << " preempt_T=" << cov.preemptT << " preempt_R=" << cov.preemptR
            << " transferred_cancel=" << cov.transferredCancel << " issued_incoming=" << cov.issuedIncoming
            << " dead_owner=" << cov.dead << " inconsistent=" << cov.inconsistent
            << " epoch_kills=" << cov.epochKills << " pmp_cases=" << cov.pmpCases
            << " discard_D_hit=" << cov.discardDHit << " discard_D_miss=" << cov.discardDMiss
            << " discard_D_stale=" << cov.discardDStale << " discard_D_issue=" << cov.discardDIssue
            << " bad_D_good_T=" << cov.badDGoodT << " bad_T_good_D=" << cov.badTGoodD
            << " D_bits=167 T_bits=233 R_bits=232 extra_bits=167 raw_PMP_entries=16"
            << " cpu_performance=UNVERIFIED timing=UNVERIFIED\n";
    }
};
}
int main(int argc, char **argv) {
    try {
        std::string injection;
        if (argc == 2) {
            const std::string flag = argv[1];
            if (flag == "--inject-owner") injection = "owner";
            else if (flag == "--inject-permission") injection = "permission";
            else if (flag == "--inject-credit") injection = "credit";
            else throw std::runtime_error("unknown negative injection: " + flag);
        } else if (argc != 1) throw std::runtime_error("expected zero or one negative injection flag");
        Oracle oracle(injection); oracle.warm(); oracle.directed(); oracle.permissions(); oracle.finish(); return 0;
    } catch (const std::exception &error) {
        std::cerr << "ELASTIC_LOAD_PROOF_FAIL " << error.what() << '\n'; return 1;
    }
}
