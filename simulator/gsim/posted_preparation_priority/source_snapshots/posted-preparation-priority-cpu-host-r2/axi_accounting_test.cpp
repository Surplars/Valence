#include "axi_accounting.h"
#include <functional>
#include <iostream>
#include <sstream>
#include <utility>

using posted_board::AxiAccounting;
using posted_board::AxiSample;
using posted_board::ChannelCycles;
using posted_board::Window;

static unsigned positives = 0, negatives = 0;
static void check(bool ok, const std::string &message) {
    if (!ok) throw std::runtime_error(message);
}
static AxiSample ar(unsigned id, unsigned len, unsigned size, bool ready = true) {
    AxiSample s; s.arValid = true; s.arReady = ready; s.arId = id; s.arLen = len; s.arSize = size; return s;
}
static AxiSample aw(unsigned id, unsigned len, unsigned size, bool ready = true) {
    AxiSample s; s.awValid = true; s.awReady = ready; s.awId = id; s.awLen = len; s.awSize = size; return s;
}
static AxiSample r(unsigned id, bool last, bool ready = true) {
    AxiSample s; s.rValid = true; s.rReady = ready; s.rId = id; s.rLast = last; return s;
}
static AxiSample w(bool last, unsigned strobe, bool ready = true) {
    AxiSample s; s.wValid = true; s.wReady = ready; s.wLast = last; s.wStrobe = strobe; return s;
}
static AxiSample b(unsigned id, bool ready = true) {
    AxiSample s; s.bValid = true; s.bReady = ready; s.bId = id; return s;
}
// Combine independent channel offers, not accounting results or expected values.
static AxiSample operator|(AxiSample left, const AxiSample &right) {
    if (right.arValid) {
        left.arValid = true; left.arReady = right.arReady; left.arId = right.arId;
        left.arLen = right.arLen; left.arSize = right.arSize;
    }
    if (right.awValid) {
        left.awValid = true; left.awReady = right.awReady; left.awId = right.awId;
        left.awLen = right.awLen; left.awSize = right.awSize;
    }
    if (right.rValid) { left.rValid = true; left.rReady = right.rReady; left.rId = right.rId; left.rLast = right.rLast; }
    if (right.wValid) { left.wValid = true; left.wReady = right.wReady; left.wLast = right.wLast; left.wStrobe = right.wStrobe; }
    if (right.bValid) { left.bValid = true; left.bReady = right.bReady; left.bId = right.bId; }
    return left;
}
static void bucket(const ChannelCycles &actual, unsigned fire, unsigned held, unsigned absent) {
    check(actual.fire == fire && actual.backpressured == held && actual.noOffer == absent,
        "manual channel partition differs");
}
static void quietFinish(AxiAccounting &ledger) {
    ledger.sample({}, Window::Kernel);
    ledger.sample({}, Window::Flush);
    ledger.sample({}, Window::None);
    ledger.finish();
}
static void reject(const char *name, const char *diagnostic, const std::function<void(AxiAccounting &)> &body) {
    AxiAccounting ledger;
    try { body(ledger); }
    catch (const std::runtime_error &error) {
        check(std::string(error.what()).find(diagnostic) != std::string::npos,
            std::string(name) + " rejected for an unrelated reason: " + error.what());
        ++negatives;
        return;
    }
    throw std::runtime_error(std::string(name) + " mutation was not rejected");
}

static void manualWindows() {
    AxiAccounting ledger;
    // Pre-edge (read,write) occupancy by hand:
    // Kernel: (1,1),(1,1),(2,2),(2,2); Flush: (1,2),(0,2),(1,1),(0,0).
    // ID2 returns before ID1; W has no ID and therefore follows AW4 then AW5.
    ledger.sample(ar(1, 1, 3) | aw(4, 1, 3), Window::None);
    ledger.sample(ar(2, 0, 2, false) | aw(5, 0, 2, false) |
        r(1, false, false) | w(false, 0x0f, false), Window::Kernel);
    ledger.sample(ar(2, 0, 2) | aw(5, 0, 2) | r(1, false) | w(false, 0x0f), Window::Kernel);
    ledger.sample({}, Window::Kernel);
    ledger.sample(r(2, true) | w(true, 0x03), Window::Kernel);
    ledger.sample(r(1, true) | w(true, 0x0f) | b(4, false), Window::Flush);
    ledger.sample(ar(3, 0, 0) | b(4), Window::Flush);
    ledger.sample(r(3, true) | b(5), Window::Flush);
    ledger.sample({}, Window::Flush);
    ledger.sample({}, Window::None);
    ledger.finish();

    const auto &k = ledger.kernel;
    check(k.cycles == 4 && k.rBytes == 12 && k.wBytes == 6, "manual kernel cycle/byte totals");
    check(k.rWireBytes == 16 && k.wWireBytes == 16, "manual kernel wire bytes differ from payload/strobes");
    check(k.readOutstandingCycles == 6 && k.writeOutstandingCycles == 6 && k.readPeak == 2 && k.writePeak == 2,
        "manual kernel occupancy totals");
    check(k.readCarryIn == 1 && k.writeCarryIn == 1 && k.readCarryOut == 1 && k.writeCarryOut == 2,
        "manual kernel carry boundaries");
    check(k.readHistogram == std::map<unsigned, uint64_t>{{1, 2}, {2, 2}} &&
        k.writeHistogram == std::map<unsigned, uint64_t>{{1, 2}, {2, 2}}, "manual kernel histograms");
    check(k.bothOutstandingCycles == 4 && k.simultaneousRwFire == 2 && k.outstandingWithoutRValid == 1 &&
        k.rBackpressure == 1 && k.readWindowEmpty == 0 && k.wholeBusEmpty == 0, "manual kernel classifications");
    bucket(k.channel[0], 1, 1, 2); bucket(k.channel[1], 1, 1, 2);
    bucket(k.channel[2], 2, 1, 1); bucket(k.channel[3], 2, 1, 1);

    const auto &f = ledger.flush;
    check(f.cycles == 4 && f.rBytes == 9 && f.wBytes == 4, "manual flush cycle/byte totals");
    check(f.rWireBytes == 16 && f.wWireBytes == 8, "manual flush wire bytes differ from payload/strobes");
    check(f.readOutstandingCycles == 2 && f.writeOutstandingCycles == 5 && f.readPeak == 1 && f.writePeak == 2,
        "manual flush occupancy totals");
    check(f.readCarryIn == 1 && f.writeCarryIn == 2 && f.readCarryOut == 0 && f.writeCarryOut == 0,
        "manual flush carry boundaries");
    check(f.readHistogram == std::map<unsigned, uint64_t>{{0, 2}, {1, 2}} &&
        f.writeHistogram == std::map<unsigned, uint64_t>{{0, 1}, {1, 1}, {2, 2}}, "manual flush histograms");
    check(f.bothOutstandingCycles == 2 && f.simultaneousRwFire == 1 && f.outstandingWithoutRValid == 0 &&
        f.rBackpressure == 0 && f.readWindowEmpty == 1 && f.wholeBusEmpty == 1, "manual flush classifications");
    bucket(f.channel[0], 1, 0, 3); bucket(f.channel[1], 0, 0, 4);
    bucket(f.channel[2], 2, 0, 2); bucket(f.channel[3], 1, 0, 3);

    std::ostringstream json;
    k.json(json, "kernel"); json << '\n'; f.json(json, "flush");
    check(json.str().find("\"read_outstanding_mean\":1.5") != std::string::npos &&
        json.str().find("\"write_outstanding_mean\":1.25") != std::string::npos &&
        json.str().find("\"accepted_w_strobe_bytes\":6") != std::string::npos &&
        json.str().find("\"accepted_r_wire_bytes\":16") != std::string::npos &&
        json.str().find("\"accepted_r_requested_payload_bytes\":12") != std::string::npos &&
        json.str().find("\"accepted_w_wire_bytes\":16") != std::string::npos &&
        json.str().find("\"outstanding_sample\":\"pre_edge_accepted_owners\"") != std::string::npos &&
        json.str().find("\"no_offer\":2") != std::string::npos,
        "JSON lost manually checked means/bytes");
    ++positives;
}

static void permittedTurnover() {
    AxiAccounting ledger;
    ledger.sample(aw(7, 0, 3) | w(true, 0), Window::None); // Zero strobe still completes a W beat.
    ledger.sample(b(7) | aw(7, 0, 3) | w(true, 0xff), Window::None); // B belongs to prior edge's owner.
    ledger.sample(b(7), Window::None);
    ledger.sample(ar(3, 0, 1), Window::None);
    ledger.sample(r(3, true) | ar(3, 1, 3), Window::None); // Old RLAST retires before same-ID AR reuse.
    ledger.sample(r(3, false), Window::None);
    ledger.sample(r(3, true), Window::None);
    // Preserve the existing read-side same-edge observation contract. This
    // ledger-only allowance is not a claim about real DDR minimum latency.
    ledger.sample(ar(9, 0, 2) | r(9, true), Window::None);
    quietFinish(ledger);
    ++positives;
}

static void carryOutsideWindows() {
    AxiAccounting ledger;
    ledger.sample(ar(1, 0, 3) | aw(2, 0, 3), Window::Kernel);
    ledger.sample(w(true, 0xff), Window::Flush);
    ledger.sample(r(1, true) | b(2), Window::None); // Drain is outside measured intervals, but remains owned.
    ledger.finish();
    check(ledger.kernel.readCarryOut == 1 && ledger.kernel.writeCarryOut == 1 &&
        ledger.flush.readCarryIn == 1 && ledger.flush.writeCarryIn == 1 &&
        ledger.flush.readCarryOut == 1 && ledger.flush.writeCarryOut == 1,
        "outside-window drain erased carry-out responsibility");
    check(ledger.kernel.rBytes == 0 && ledger.flush.rBytes == 0 && ledger.flush.wBytes == 8,
        "outside-window R bytes leaked into ROI");
    ++positives;
}

static void zeroStrobeStillUsesWire() {
    AxiAccounting ledger;
    ledger.sample(aw(7, 0, 3) | w(true, 0), Window::Kernel);
    ledger.sample(b(7) | ar(9, 0, 0) | r(9, true), Window::Flush);
    ledger.sample({}, Window::None);
    ledger.finish();
    check(ledger.kernel.wWireBytes == 8 && ledger.kernel.wBytes == 0 &&
        ledger.flush.rWireBytes == 8 && ledger.flush.rBytes == 1,
        "zero-strobe/narrow read wire bytes conflated with useful byte count");
    ++positives;
}

static void negativeCases() {
    constexpr auto N = Window::None;
    const char *earlyB = "BVALID has no prior-edge completed AW/W owner";
    reject("orphan B fire", earlyB, [&](auto &a) { a.sample(b(1), N); });
    reject("orphan held B", earlyB, [&](auto &a) { a.sample(b(1, false), N); });
    reject("new AW/W/B same edge", earlyB, [&](auto &a) { a.sample(aw(1, 0, 3) | w(true, 0xff) | b(1), N); });
    reject("new AW/W/held-B same edge", earlyB, [&](auto &a) { a.sample(aw(1, 0, 3) | w(true, 0xff) | b(1, false), N); });
    reject("old AW final W/B same edge", earlyB, [&](auto &a) {
        a.sample(aw(1, 0, 3), N); a.sample(w(true, 0xff) | b(1), N);
    });
    reject("B before remaining W", earlyB, [&](auto &a) {
        a.sample(aw(1, 1, 3), N); a.sample(w(false, 0xff), N); a.sample(b(1), N);
    });
    reject("B wrong accepted ID", earlyB, [&](auto &a) { a.sample(aw(1, 0, 3) | w(true, 0xff), N); a.sample(b(2), N); });
    reject("held B ID mutation", "held B ID changed", [&](auto &a) {
        a.sample(aw(1, 0, 3) | w(true, 0xff), N); a.sample(aw(2, 0, 3) | w(true, 0xff), N);
        a.sample(b(1, false), N); a.sample(b(2), N);
    });
    reject("held B withdrawn", "held B ID changed", [&](auto &a) {
        a.sample(aw(1, 0, 3) | w(true, 0xff), N); a.sample(b(1, false), N); a.sample({}, N);
    });
    reject("orphan R fire", "R has no accepted AR owner", [&](auto &a) { a.sample(r(1, true), N); });
    reject("orphan held R", "R has no accepted AR owner", [&](auto &a) { a.sample(r(1, true, false), N); });
    reject("R wrong accepted ID", "R has no accepted AR owner", [&](auto &a) { a.sample(ar(1, 0, 3), N); a.sample(r(2, true), N); });
    reject("early RLAST", "RLAST does not complete", [&](auto &a) { a.sample(ar(1, 1, 3), N); a.sample(r(1, true), N); });
    reject("missing RLAST", "RLAST does not complete", [&](auto &a) { a.sample(ar(1, 0, 3), N); a.sample(r(1, false), N); });
    reject("held R ID mutation", "held R ID/LAST changed", [&](auto &a) {
        a.sample(ar(1, 0, 3), N); a.sample(ar(2, 0, 3), N); a.sample(r(1, true, false), N); a.sample(r(2, true), N);
    });
    reject("held RLAST mutation", "held R ID/LAST changed", [&](auto &a) {
        a.sample(ar(1, 1, 3), N); a.sample(r(1, false, false), N); a.sample(r(1, true), N);
    });
    reject("orphan W", "W has no accepted AW owner", [&](auto &a) { a.sample(w(true, 0xff), N); });
    reject("early WLAST", "WLAST does not complete", [&](auto &a) { a.sample(aw(1, 1, 3), N); a.sample(w(true, 0xff), N); });
    reject("missing WLAST", "WLAST does not complete", [&](auto &a) { a.sample(aw(1, 0, 3), N); a.sample(w(false, 0xff), N); });
    reject("held WLAST mutation", "held W LAST/strobe changed", [&](auto &a) {
        a.sample(aw(1, 1, 3), N); a.sample(w(false, 0xff, false), N); a.sample(w(true, 0xff), N);
    });
    reject("held W strobe mutation", "held W LAST/strobe changed", [&](auto &a) {
        a.sample(aw(1, 0, 3), N); a.sample(w(true, 0x0f, false), N); a.sample(w(true, 0xff), N);
    });
    reject("strobe outside bus", "W has no accepted AW owner or invalid strobe", [&](auto &a) {
        a.sample(aw(1, 0, 3), N); a.sample(w(true, 256), N);
    });
    reject("strobe wider than transfer", "strobe exceeds original AW transfer size", [&](auto &a) {
        a.sample(aw(1, 0, 0), N); a.sample(w(true, 3), N);
    });
    reject("live AR ID reuse", "AR reused a live ID", [&](auto &a) { a.sample(ar(1, 0, 3), N); a.sample(ar(1, 0, 3), N); });
    reject("live AW ID reuse", "AW reused a live ID", [&](auto &a) { a.sample(aw(1, 0, 3), N); a.sample(aw(1, 0, 3), N); });
    reject("held AR ID mutation", "held AR metadata changed", [&](auto &a) { a.sample(ar(1, 0, 3, false), N); a.sample(ar(2, 0, 3), N); });
    reject("held AW length mutation", "held AW metadata changed", [&](auto &a) { a.sample(aw(1, 0, 3, false), N); a.sample(aw(1, 1, 3), N); });
    reject("final read owner lost", "final drain lost accepted", [&](auto &a) { a.sample(ar(1, 0, 3), N); quietFinish(a); });
    reject("final completed write owner lost", "final drain lost accepted", [&](auto &a) { a.sample(aw(1, 0, 3) | w(true, 0xff), N); quietFinish(a); });
    reject("window reentered", "window reentered", [&](auto &a) {
        a.sample({}, Window::Kernel); a.sample({}, Window::Flush); a.sample({}, Window::Kernel);
    });
    reject("window never entered", "window was not completely sampled", [&](auto &a) { a.sample({}, Window::Kernel); a.finish(); });
}

int main() {
    try {
        manualWindows(); permittedTurnover(); carryOutsideWindows(); zeroStrobeStillUsesWire(); negativeCases();
        std::cout << "PASS passive AXI accounting host-only positives=" << positives << " mutation_rejections=" << negatives << '\n';
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "FAIL passive AXI accounting host-only: " << error.what() << '\n';
        return 1;
    }
}
