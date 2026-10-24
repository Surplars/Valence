#include "M2TranslationBufferGsim.h"
#include <algorithm>
#include <cstdint>
#include <deque>
#include <iomanip>
#include <iostream>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>

// Complete FullCandidate descriptor ABI. These are host-authored inputs, not
// values learned from a DUT output, a mirrored FIFO, or an internal occupancy.
#define M2_DESCRIPTOR_FIELDS(X) \
    X(atomic, Atomic, "request.atomic") \
    X(atomicOp, AtomicOp, "request.atomicOp") \
    X(address, Address, "request.address") \
    X(write, Write, "request.write") \
    X(size, Size, "request.size") \
    X(data, Data, "request.data") \
    X(mask, Mask, "request.mask") \
    X(virtualized, Virtualized, "request.virtualized") \
    X(precheckedLoad, PrecheckedLoad, "request.precheckedLoad") \
    X(translationEpoch, TranslationEpoch, "request.translationEpoch") \
    X(prefetchNextAllowed, PrefetchNextAllowed, "request.prefetchNextAllowed") \
    X(uncached, Uncached, "request.uncached") \
    X(canonicalValid, CanonicalValid, "canonicalStoreOrigin.valid") \
    X(canonicalIndex, CanonicalIndex, "canonicalStoreOrigin.token.index") \
    X(canonicalTag, CanonicalTag, "canonicalStoreOrigin.token.tag") \
    X(canonicalEpoch, CanonicalEpoch, "canonicalStoreOrigin.epoch") \
    X(originalVirtualAddress, OriginalVirtualAddress, "originalVirtualAddress") \
    X(privilege, Privilege, "privilege") \
    X(checkPhysical, CheckPhysical, "checkPhysical") \
    X(pageFault, PageFault, "pageFault") \
    X(accessFault, AccessFault, "accessFault")

struct Descriptor {
#define FIELD(member, port, label) uint64_t member = 0;
    M2_DESCRIPTOR_FIELDS(FIELD)
#undef FIELD
};

static void check(bool ok, const std::string &why) {
    if (!ok) throw std::runtime_error(why);
}

// Independently vary bits, including high token/VA/epoch bits. Reuse the same
// ROB index with unrelated full tags; neither epoch is reconstructed from PA.
static uint64_t mix(uint64_t n) {
    n += UINT64_C(0x9e3779b97f4a7c15);
    n = (n ^ (n >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
    n = (n ^ (n >> 27)) * UINT64_C(0x94d049bb133111eb);
    return n ^ (n >> 31);
}

static Descriptor stimulus(uint64_t sequence) {
    Descriptor d;
    unsigned lane = 0;
#define RANDOM_FIELD(member, port, label) d.member = mix(sequence * 32 + lane++);
    M2_DESCRIPTOR_FIELDS(RANDOM_FIELD)
#undef RANDOM_FIELD
    d.atomic &= 1;
    d.atomicOp &= 31;
    d.write &= 1;
    d.size &= 3;
    d.mask &= 255;
    d.virtualized &= 1;
    d.precheckedLoad &= 1;
    d.translationEpoch &= UINT32_MAX;
    d.prefetchNextAllowed &= 1;
    d.uncached &= 1;
    d.canonicalValid &= 1;
    d.canonicalIndex = sequence % 16;
    d.canonicalEpoch &= UINT32_MAX;
    d.privilege &= 3;
    d.checkPhysical &= 1;
    d.pageFault &= 1;
    d.accessFault &= 1;
    // A transport buffer must preserve even invalid/fault descriptor payloads.
    // Deliberately do not make address, token, epoch and fault fields agree.
    return d;
}

static void drive(SM2TranslationBufferGsim &dut, const Descriptor &d) {
#define DRIVE(member, port, label) dut.set_io$$in##port(d.member);
    M2_DESCRIPTOR_FIELDS(DRIVE)
#undef DRIVE
}

static Descriptor observe(SM2TranslationBufferGsim &dut) {
    Descriptor d;
#define OBSERVE(member, port, label) d.member = dut.get_io$$out##port();
    M2_DESCRIPTOR_FIELDS(OBSERVE)
#undef OBSERVE
    return d;
}

static void compare(const Descriptor &got, const Descriptor &expected, uint64_t cycle,
                    uint64_t sequence, const char *phase) {
#define COMPARE(member, port, label) \
    if (got.member != expected.member) { \
        std::ostringstream error; \
        error << "descriptor mismatch field=" << label << " cycle=" << cycle \
              << " accepted_sequence=" << sequence << " phase=" << phase \
              << " expected=0x" << std::hex << expected.member << " observed=0x" << got.member; \
        throw std::runtime_error(error.str()); \
    }
    M2_DESCRIPTOR_FIELDS(COMPARE)
#undef COMPARE
}

struct Accepted {
    Descriptor descriptor;
    uint64_t sequence;
    uint64_t cycle;
};

struct Cycle {
    bool push;
    bool pop;
    unsigned occupancy;
};

class Oracle {
    SM2TranslationBufferGsim dut;
    std::deque<Accepted> acceptedInputs;
    std::optional<Descriptor> heldInput;
    bool injectPayload;
    bool injected = false;

public:
    uint64_t cycle = 0;
    unsigned accepted = 0;
    unsigned retired = 0;
    unsigned maximum = 0;
    unsigned heldOutputCycles = 0;
    unsigned heldInputCycles = 0;
    unsigned simultaneous = 0;
    unsigned fullPopNoCredit = 0;
    unsigned descriptorChecks = 0;
    unsigned firstCycleVisible = 0;

    explicit Oracle(bool inject) : injectPayload(inject) {
        drive(dut, Descriptor{});
        dut.set_io$$inValid(0);
        dut.set_io$$outReady(0);
        dut.set_reset(1);
        dut.step();
        dut.step();
        dut.set_reset(0);
    }

    Cycle tick(bool offer, bool ready, const char *phase) {
        // A stalled source retains both valid and its original full descriptor.
        const bool valid = offer || heldInput.has_value();
        const Descriptor input = heldInput.value_or(stimulus(accepted));
        const unsigned occupancy = acceptedInputs.size();
        const bool expectedReady = occupancy < 8; // Never borrow same-cycle pop.
        const bool expectedValid = occupancy != 0; // Never flow an empty enqueue.
        drive(dut, input);
        dut.set_io$$inValid(valid);
        dut.set_io$$outReady(ready);
        dut.step(); // GSIM exposes this edge's pre-update combinational outputs.

        const std::string where = std::string(" phase=") + phase + " cycle=" + std::to_string(cycle);
        check(bool(dut.get_io$$inReady()) == expectedReady, "occupancy-only enqueue credit mismatch" + where);
        check(bool(dut.get_io$$outValid()) == expectedValid, "non-flow valid/latency mismatch" + where);
        check(dut.get_io$$count() == occupancy, "accepted-input ledger occupancy mismatch" + where);
        const bool push = valid && bool(dut.get_io$$inReady());
        const bool pop = ready && bool(dut.get_io$$outValid());
        if (expectedValid) {
            const auto &owner = acceptedInputs.front();
            check(cycle >= owner.cycle + 1, "descriptor bypassed the registered boundary" + where);
            firstCycleVisible += cycle == owner.cycle + 1;
            auto actual = observe(dut);
            if (injectPayload && !injected && std::string(phase) == "full-hold") {
                injected = true;
                actual.data ^= UINT64_C(1) << 37;
                std::cerr << "INJECT M2_TRANSLATION_BUFFER field=request.data bit=37 phase=" << phase
                          << " cycle=" << cycle << " accepted_sequence=" << owner.sequence << '\n';
            }
            compare(actual, owner.descriptor, cycle, owner.sequence, phase);
            ++descriptorChecks;
            heldOutputCycles += !ready;
        }
        heldInputCycles += valid && !expectedReady;
        simultaneous += push && pop;
        fullPopNoCredit += occupancy == 8 && valid && pop && !push;

        // The only expected-payload source is the independently driven input at
        // an observed accepted handshake. Output values never seed this ledger.
        if (pop) {
            acceptedInputs.pop_front();
            ++retired;
        }
        if (push) {
            acceptedInputs.push_back({input, accepted, cycle});
            ++accepted;
            heldInput.reset();
        } else if (valid) {
            heldInput = input;
        }
        maximum = std::max(maximum, unsigned(acceptedInputs.size()));
        check(acceptedInputs.size() <= 8 && accepted - retired == acceptedInputs.size(),
              "accepted-descriptor conservation mismatch" + where);
        ++cycle;
        return {push, pop, occupancy};
    }

    void drain(const char *phase) {
        for (unsigned i = 0; i < 10 && (!acceptedInputs.empty() || heldInput); ++i)
            tick(false, true, phase);
        check(acceptedInputs.empty() && !heldInput, std::string("bounded drain failed phase=") + phase);
        for (unsigned i = 0; i < 3; ++i) {
            const auto edge = tick(false, true, phase);
            check(!edge.push && !edge.pop && edge.occupancy == 0, "duplicate descriptor after drain");
        }
    }

    void finish() const {
        check(!injectPayload || injected, "requested payload mutation was never exercised");
        check(!injectPayload, "injected payload mismatch was not rejected");
        check(acceptedInputs.empty() && !heldInput && accepted == retired,
              "final accepted-descriptor ledger did not drain");
    }
};

int main(int argc, char **argv) {
    try {
        const bool inject = argc == 2 && std::string(argv[1]) == "--inject-payload";
        check(argc == 1 || inject, "usage: buffer [--inject-payload]");
        Oracle oracle(inject);

        for (unsigned i = 0; i < 3; ++i) oracle.tick(false, true, "empty");
        // Exact latency-one witness, then a held descriptor without a consumer.
        auto edge = oracle.tick(true, true, "latency-accept");
        check(edge.push && !edge.pop && edge.occupancy == 0, "empty enqueue must not flow");
        edge = oracle.tick(false, false, "latency-visible");
        check(!edge.push && !edge.pop && edge.occupancy == 1, "one-cycle visibility witness missing");
        for (unsigned i = 0; i < 9; ++i) oracle.tick(false, false, "held-single");
        oracle.drain("single-drain");

        // Check every individual cycle, not an average or unrelated activity
        // counter: II=2 would fail on the first missing accepted transfer.
        const auto steadyStart = oracle.cycle;
        const unsigned steadyAcceptedStart = oracle.accepted;
        const unsigned steadyRetiredStart = oracle.retired;
        for (unsigned i = 0; i < 512; ++i) {
            edge = oracle.tick(true, true, "continuous-512");
            check(edge.push && edge.pop == (i != 0), "continuous supplied stream had an acceptance/output bubble");
        }
        edge = oracle.tick(false, true, "continuous-tail");
        check(!edge.push && edge.pop, "continuous stream lost its registered tail");
        const uint64_t steadyTotalCycles = oracle.cycle - steadyStart;
        check(steadyTotalCycles == 513 && oracle.accepted - steadyAcceptedStart == 512 &&
              oracle.retired - steadyRetiredStart == 512, "continuous stream end-to-end cycle cost mismatch");
        oracle.drain("continuous-drain");

        for (unsigned i = 0; i < 8; ++i) {
            edge = oracle.tick(true, false, "fill-eight");
            check(edge.push && !edge.pop && edge.occupancy == i, "buffer capacity is not exactly eight");
        }
        for (unsigned i = 0; i < 5; ++i) {
            edge = oracle.tick(true, false, "full-hold");
            check(!edge.push && !edge.pop && edge.occupancy == 8, "full held descriptor was overwritten");
        }
        edge = oracle.tick(true, true, "full-pop-no-credit");
        check(!edge.push && edge.pop && edge.occupancy == 8, "full pop illegally lent same-cycle credit");

        // Exactly the full-pop cycle above has no enqueue credit. Beginning on
        // the next cycle, every supplied request must be accepted, with every
        // old descriptor returned in order; no alternate-cycle recovery bubbles.
        const unsigned recoveryAcceptedStart = oracle.accepted;
        const unsigned recoveryRetiredStart = oracle.retired;
        for (unsigned i = 0; i < 512; ++i) {
            edge = oracle.tick(true, true, "recovery-512");
            check(edge.push && edge.pop && edge.occupancy == 7,
                  "full recovery failed sustained same-cycle pop/push II=1");
        }
        check(oracle.accepted - recoveryAcceptedStart == 512 && oracle.retired - recoveryRetiredStart == 512,
              "post-full continuous acceptance/output count mismatch");
        oracle.drain("recovery-drain");

        // Repeated congestion plus independent source gaps. A prior blocked
        // source remains valid despite the source schedule requesting a gap.
        for (unsigned i = 0; i < 384; ++i)
            oracle.tick(i % 13 != 2 && i % 13 != 3, i % 17 >= 6 && i % 5 != 1, "congested");
        oracle.drain("final-drain");
        oracle.finish();
        check(oracle.maximum == 8 && oracle.fullPopNoCredit > 1 && oracle.heldInputCycles > 20 &&
              oracle.heldOutputCycles > 20 && oracle.simultaneous >= 1023 &&
              oracle.firstCycleVisible >= 512 && oracle.descriptorChecks > oracle.retired,
              "capacity/held/recovery/turnover/latency coverage incomplete");
        std::cout << "M2_TRANSLATION_BUFFER_PASS accepted=" << oracle.accepted << " retired=" << oracle.retired
                  << " capacity=" << oracle.maximum << " descriptor_fields=21 descriptor_bits=351"
                  << " continuous_accepts=512 continuous_cycles=512 continuous_total_cycles=" << steadyTotalCycles
                  << " recovery_accepts=512 recovery_cycles=512 latency=1 steady_ii=1"
                  << " full_pop_no_credit=" << oracle.fullPopNoCredit
                  << " held_input_cycles=" << oracle.heldInputCycles
                  << " held_output_cycles=" << oracle.heldOutputCycles
                  << " simultaneous=" << oracle.simultaneous << " checks=" << oracle.descriptorChecks
                  << " cycles=" << oracle.cycle << " cpu_executed=0\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "M2_TRANSLATION_BUFFER_FAIL " << error.what() << '\n';
        return 1;
    }
}
