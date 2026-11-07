#include "DualFsPreparationGsim.h"
#include <array>
#include <cstdint>
#include <initializer_list>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>

// Independent state/event oracle. No arithmetic or guest program is executed:
// all producer responses below are explicitly synthetic component stimulation.
struct Token {
    unsigned index = 0;
    uint64_t tag = 0;
    bool operator==(const Token&) const = default;
};
struct Command {
    Token token{};
    uint32_t instruction = 0x02000053;
    std::array<unsigned, 3> source{};
    std::array<bool, 3> boxed{};
    uint64_t integer = 0;
    unsigned destination = 0, rm = 0;
    bool single = false, writes = true, flags = true, rounding = false;
};
struct Result {
    Token token{};
    uint64_t value = 0, tval = 0;
    unsigned flags = 0, cause = 0;
    bool fault = false;
};
struct Input {
    bool head = true, flush = false, issue = false, executeReady = true;
    bool result = false, retire = false, csr = false, csrWrite = false;
    bool status = false, mret = false, sret = false;
    unsigned csrAddress = 3, csrOperation = 0, statusAddress = 0x100, readAddress = 0x100;
    uint64_t csrValue = 0, statusData = 0;
    Command command{};
    Result response{};
    Token retireToken{};
};
struct Image {
    std::array<uint64_t, 32> regs{};
    unsigned fcsr = 0, hostFs = 2, guestFs = 2;
};

class Oracle {
public:
    SDualFsPreparationGsim dut;
    std::array<uint64_t, 32> regs{};
    std::array<uint64_t, 3> operands{}, observedOperands{};
    unsigned hostFs = 0, guestFs = 0, frm = 0, flags = 0, state = 0, rm = 0;
    bool virtualized = false, spv = false, pendingGuest = false;
    unsigned pendingDenial = 0; // 1=host Off, 2=guest Off, 3=rounding
    Command pending{};
    Result response{};
    std::string negative;
    bool guestStatusBoundary = false, guestDirtyBoundary = false;
    unsigned cycles = 0, issued = 0, retired = 0, producerRequests = 0;
    unsigned hostOff = 0, guestOff = 0, roundingIllegal = 0, staleResults = 0;
    unsigned heldCompletions = 0, wrongRetireTags = 0, wrongRetireIndices = 0;
    unsigned deniedHeadRetires = 0, blockedContext = 0, boxedOperands = 0;
    unsigned csrHostEvents = 0, csrGuestEvents = 0, retireHostEvents = 0, retireGuestEvents = 0;
    unsigned faultRetirements = 0, hostStatusWrites = 0, guestStatusWrites = 0;
    unsigned liveOwnerChanges = 0, flagsOnly = 0, fpOnly = 0, readOnly = 0;
    unsigned permissionRows = 0, permissionDenied = 0, csrMatrixAccesses = 0, csrMatrixDenied = 0;
    unsigned forwardingChecks = 0, olderCommitFlushChecks = 0, imageSaves = 0, imageRestores = 0;
    uint64_t sequence = 1;

    void check(bool ok, const char* name, const char* detail) const {
        if (!ok) throw std::runtime_error(std::string("DUAL_FS_CHECK[") + name + "]: " + detail);
    }
    static uint64_t statusBits(unsigned fs) {
        return (uint64_t(fs) << 13) | (fs == 3 ? (uint64_t(1) << 63) : 0);
    }
    unsigned fcsr() const { return (frm << 5) | flags; }
    Command command(unsigned rd, bool writes = true, bool writesFlags = true) {
        Command c;
        // Nontrivial high tag bits are essential: index-only or truncated-token
        // comparisons must not pass the stale-result and retirement checks.
        c.token = {unsigned(sequence % 16), 0x1456000000000000ULL | sequence++};
        c.destination = rd;
        c.source = {rd, (rd + 1) % 32, (rd + 31) % 32};
        c.integer = 0x9850000000000000ULL ^ c.token.tag;
        c.writes = writes;
        c.flags = writesFlags;
        return c;
    }
    void drive(const Input& x) {
        dut.set_io$$headAuthorized(x.head);
        dut.set_io$$flush(x.flush);
        dut.set_io$$issue$$valid(x.issue);
        dut.set_io$$issue$$bits$$token$$index(x.command.token.index);
        dut.set_io$$issue$$bits$$token$$tag(x.command.token.tag);
        dut.set_io$$issue$$bits$$instruction(x.command.instruction);
#define SOURCE(n) \
        dut.set_io$$issue$$bits$$sources_##n(x.command.source[n]); \
        dut.set_io$$issue$$bits$$checkSingleBox_##n(x.command.boxed[n])
        SOURCE(0); SOURCE(1); SOURCE(2);
#undef SOURCE
        dut.set_io$$issue$$bits$$integerSource(x.command.integer);
        dut.set_io$$issue$$bits$$destination(x.command.destination);
        dut.set_io$$issue$$bits$$singleResult(x.command.single);
        dut.set_io$$issue$$bits$$writesFp(x.command.writes);
        dut.set_io$$issue$$bits$$writesFlags(x.command.flags);
        dut.set_io$$issue$$bits$$usesRounding(x.command.rounding);
        dut.set_io$$issue$$bits$$rounding(x.command.rm);
        dut.set_io$$execute$$ready(x.executeReady);
        dut.set_io$$result$$valid(x.result);
        dut.set_io$$result$$bits$$token$$index(x.response.token.index);
        dut.set_io$$result$$bits$$token$$tag(x.response.token.tag);
        dut.set_io$$result$$bits$$value(x.response.value);
        dut.set_io$$result$$bits$$flags(x.response.flags);
        dut.set_io$$result$$bits$$exception(x.response.fault);
        dut.set_io$$result$$bits$$cause(x.response.cause);
        dut.set_io$$result$$bits$$tval(x.response.tval);
        dut.set_io$$retire$$valid(x.retire);
        dut.set_io$$retire$$bits$$index(x.retireToken.index);
        dut.set_io$$retire$$bits$$tag(x.retireToken.tag);
        dut.set_io$$csr$$valid(x.csr);
        dut.set_io$$csr$$bits$$address(x.csrAddress);
        dut.set_io$$csr$$bits$$operation(x.csrOperation);
        dut.set_io$$csr$$bits$$write(x.csrWrite);
        dut.set_io$$csr$$bits$$value(x.csrValue);
        dut.set_io$$status$$valid(x.status);
        dut.set_io$$status$$bits$$address(x.statusAddress);
        dut.set_io$$status$$bits$$data(x.statusData);
        dut.set_io$$statusReadAddress(x.readAddress);
        dut.set_io$$mret(x.mret);
        dut.set_io$$sret(x.sret);
    }
    void reset() {
        drive({}); dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
        regs.fill(0);
        hostFs = guestFs = frm = flags = state = 0;
        virtualized = spv = false;
    }
    void tick(const Input& x = {}) {
        drive(x); dut.step();
        check(cycles < 20000, "trace_bound", "component cycle budget exceeded");
        // Audit rows contain only raw stimulus and unmodified DUT observations,
        // before negative-control corruption or any expected-state calculation.
        // Array orders are the named bundle fields, documented below each group.
        std::cout << "DUAL_FS_TRACE {\"cycle\":" << cycles << ",\"in\":{\"head\":" << x.head
            << ",\"flush\":" << x.flush << ",\"status\":[" << x.status << ',' << x.statusAddress << ',' << x.statusData
            << "],\"csr\":[" << x.csr << ',' << x.csrAddress << ',' << x.csrOperation << ',' << x.csrWrite << ',' << x.csrValue
            // issue: valid,index,tag,destination,writesFp,writesFlags,singleResult,usesRounding,rounding,instruction
            << "],\"issue\":[" << x.issue << ',' << x.command.token.index << ',' << x.command.token.tag << ','
            << x.command.destination << ',' << x.command.writes << ',' << x.command.flags << ',' << x.command.single
            << ',' << x.command.rounding << ',' << x.command.rm << ',' << x.command.instruction
            << "],\"execute_ready\":" << x.executeReady
            // result: valid,index,tag,value,flags,exception,cause,tval
            << ",\"result\":[" << x.result << ',' << x.response.token.index << ',' << x.response.token.tag << ','
            << x.response.value << ',' << x.response.flags << ',' << x.response.fault << ',' << x.response.cause << ','
            << x.response.tval << "],\"retire\":[" << x.retire << ',' << x.retireToken.index << ',' << x.retireToken.tag
            << "],\"mret\":" << x.mret << ",\"sret\":" << x.sret << ",\"read_address\":" << x.readAddress
            << "},\"out\":{\"host_fs\":" << unsigned(dut.get_io$$hostFs())
            << ",\"guest_fs\":" << unsigned(dut.get_io$$guestFs())
            << ",\"host_sd\":" << bool(dut.get_io$$hostSd()) << ",\"guest_sd\":" << bool(dut.get_io$$guestSd())
            << ",\"v\":" << bool(dut.get_io$$virtualized()) << ",\"fcsr\":" << unsigned(dut.get_io$$fcsr())
            << ",\"status_ready\":" << bool(dut.get_io$$status$$ready())
            << ",\"status_read\":" << dut.get_io$$statusReadData()
            << ",\"status_shadow\":" << bool(dut.get_io$$statusShadow())
            << ",\"csr_ready\":" << bool(dut.get_io$$csr$$ready()) << ",\"csr_read\":" << dut.get_io$$csrRead()
            << ",\"csr_illegal\":" << bool(dut.get_io$$csrIllegal())
            << ",\"issue_ready\":" << bool(dut.get_io$$issue$$ready())
            << ",\"busy\":" << bool(dut.get_io$$busy())
            // execute: valid,index,tag; complete: valid,index,tag,exception,cause,tval,value,flags
            << ",\"execute\":[" << bool(dut.get_io$$execute$$valid()) << ','
            << unsigned(dut.get_io$$execute$$bits$$command$$token$$index()) << ','
            << dut.get_io$$execute$$bits$$command$$token$$tag()
            << "],\"complete\":[" << bool(dut.get_io$$complete$$valid()) << ','
            << unsigned(dut.get_io$$complete$$bits$$token$$index()) << ','
            << dut.get_io$$complete$$bits$$token$$tag() << ',' << bool(dut.get_io$$complete$$bits$$exception()) << ','
            << unsigned(dut.get_io$$complete$$bits$$cause()) << ',' << dut.get_io$$complete$$bits$$tval() << ','
            << dut.get_io$$complete$$bits$$value() << ',' << unsigned(dut.get_io$$complete$$bits$$flags())
            << "],\"retire_accepted\":" << bool(dut.get_io$$retireAccepted())
            // Invalid event payload has no meaning; use JSON null rather than
            // interpreting the intentionally unreset pending-owner register.
            << ",\"mutation_valid\":" << bool(dut.get_io$$mutation$$valid()) << ",\"mutation_guest\":";
        if (dut.get_io$$mutation$$valid()) std::cout << bool(dut.get_io$$mutation$$bits$$guest());
        else std::cout << "null";
        std::cout << "}}\n";
        const bool idle = state == 0 && x.head && !x.flush;
        const bool csrReady = idle && !x.status;
        const bool issueReady = csrReady && !x.csr;
        const bool executing = state == 1 && !x.flush;
        const bool complete = state == 3 && !x.flush;
        const bool retire = complete && x.retire && x.head && x.retireToken == pending.token;
        // This permission is derived only from the software-owned status image
        // and context, never from DUT FS, status read data, or a DUT predicate.
        const bool allowed = hostFs != 0 && (!virtualized || guestFs != 0);
        const bool csrIllegal = !allowed || x.csrAddress < 1 || x.csrAddress > 3 || x.csrOperation == 3;
        const uint64_t csrRead = x.csrAddress == 1 ? flags : x.csrAddress == 2 ? frm :
            x.csrAddress == 3 ? fcsr() : 0;
        const bool csrMutation = x.csr && csrReady && x.csrWrite && !csrIllegal;
        const bool retireMutation = retire && !response.fault && (pending.writes || pending.flags);
        const bool mutation = csrMutation || retireMutation;
        const bool mutationGuest = csrMutation ? virtualized : pendingGuest;

        bool observedExecute = dut.get_io$$execute$$valid();
        bool observedMutation = dut.get_io$$mutation$$valid();
        unsigned observedHostFs = dut.get_io$$hostFs();
        unsigned observedGuestFs = dut.get_io$$guestFs();
        // Named negatives corrupt a captured observation at a real boundary.
        // They prove checker sensitivity, not RTL-mutation coverage. The expected
        // algorithm, stimulus, and every positive DUT observation stay unchanged.
        if (negative == "host-permission" && complete && pendingDenial == 1) observedExecute = true;
        if (negative == "guest-permission" && complete && pendingDenial == 2) observedExecute = true;
        if (negative == "status-target" && guestStatusBoundary) observedHostFs = guestFs;
        if (negative == "guest-dirty" && guestDirtyBoundary) observedGuestFs = 2;
        if (negative == "fault-mutation" && retire && response.fault && response.cause == 13)
            observedMutation = true;
        if (complete && pendingDenial == 1)
            check(!observedExecute, "host_permission", "FP request with host FS Off");
        if (complete && pendingDenial == 2)
            check(!observedExecute, "guest_permission", "FP request with guest FS Off");
        if (guestStatusBoundary)
            check(observedHostFs == hostFs, "status_target", "guest sstatus changed host FS");
        if (guestDirtyBoundary)
            check(observedGuestFs == 3, "guest_dirty", "guest mutation did not dirty VS FS");
        if (retire && response.fault)
            check(!observedMutation, "fault_mutation", "fault retirement emitted mutation");
        check(observedHostFs == hostFs && observedGuestFs == guestFs, "status_state", "FS owner state");
        check(bool(dut.get_io$$hostSd()) == (hostFs == 3) &&
            bool(dut.get_io$$guestSd()) == (guestFs == 3), "sd", "independent derived SD");
        check(bool(dut.get_io$$virtualized()) == virtualized, "context", "production V state");
        check(dut.get_io$$fcsr() == fcsr(), "fcsr", "architectural flags/rounding state");
        check(dut.get_io$$csrRead() == csrRead && bool(dut.get_io$$csrIllegal()) == csrIllegal,
            "csr", "FCSR alias read/permission");
        check(bool(dut.get_io$$status$$ready()) == idle && bool(dut.get_io$$csr$$ready()) == csrReady,
            "serialization", "status/CSR acceptance");
        check(bool(dut.get_io$$issue$$ready()) == issueReady && bool(dut.get_io$$busy()) == (state != 0),
            "issue", "head acceptance/occupancy");
        check(observedExecute == executing && bool(dut.get_io$$complete$$valid()) == complete,
            "lifecycle", "producer/completion boundary");
        check(dut.get_io$$result$$ready() && bool(dut.get_io$$retireAccepted()) == retire,
            "retirement", "full-token/head authorization");
        check(observedMutation == mutation, "mutation", "accepted architectural event");
        if (mutation)
            check(bool(dut.get_io$$mutation$$bits$$guest()) == mutationGuest,
                "mutation_owner", "captured guest owner");
        if (x.readAddress == 0x100 || x.readAddress == 0x200 || x.readAddress == 0x300) {
            const bool guestRead = x.readAddress == 0x200 || (x.readAddress == 0x100 && virtualized);
            const uint64_t mask = (uint64_t(3) << 13) | (uint64_t(1) << 63);
            check((dut.get_io$$statusReadData() & mask) == statusBits(guestRead ? guestFs : hostFs),
                "status_alias", "FS/SD read target");
            check(bool(dut.get_io$$statusShadow()) == (x.readAddress == 0x100 && virtualized),
                "status_alias", "guest sstatus substitution");
        }
        if (executing) {
            check(dut.get_io$$execute$$bits$$command$$token$$index() == pending.token.index &&
                dut.get_io$$execute$$bits$$command$$token$$tag() == pending.token.tag,
                "producer_owner", "full command token");
            check(dut.get_io$$execute$$bits$$command$$instruction() == pending.instruction &&
                dut.get_io$$execute$$bits$$command$$integerSource() == pending.integer &&
                dut.get_io$$execute$$bits$$command$$destination() == pending.destination &&
                bool(dut.get_io$$execute$$bits$$command$$writesFp()) == pending.writes &&
                bool(dut.get_io$$execute$$bits$$command$$writesFlags()) == pending.flags &&
                bool(dut.get_io$$execute$$bits$$command$$singleResult()) == pending.single,
                "producer_payload", "held command fields");
            check(dut.get_io$$execute$$bits$$rounding() == rm, "rounding", "captured effective frm/rm");
#define OPERAND(n) \
            observedOperands[n] = dut.get_io$$execute$$bits$$operands_##n(); \
            check(observedOperands[n] == operands[n], "fpr", "raw/boxed/forwarded operand")
            OPERAND(0); OPERAND(1); OPERAND(2);
#undef OPERAND
        }
        if (complete) {
            check(dut.get_io$$complete$$bits$$token$$index() == response.token.index &&
                dut.get_io$$complete$$bits$$token$$tag() == response.token.tag,
                "completion_owner", "full response token");
            check(dut.get_io$$complete$$bits$$value() == response.value &&
                dut.get_io$$complete$$bits$$flags() == response.flags &&
                bool(dut.get_io$$complete$$bits$$exception()) == response.fault &&
                dut.get_io$$complete$$bits$$cause() == response.cause &&
                dut.get_io$$complete$$bits$$tval() == response.tval,
                "completion_payload", "held result/flags/fault metadata");
            if (!retire) ++heldCompletions;
            if (x.retire && x.retireToken.index == pending.token.index && x.retireToken.tag != pending.token.tag)
                ++wrongRetireTags;
            if (x.retire && x.retireToken.index != pending.token.index && x.retireToken.tag == pending.token.tag)
                ++wrongRetireIndices;
            if (x.retire && x.retireToken == pending.token && !x.head) ++deniedHeadRetires;
        }

        const unsigned oldState = state;
        const bool oldV = virtualized;
        guestStatusBoundary = false;
        guestDirtyBoundary = mutation && mutationGuest && guestFs != 3;
        if (x.status && idle) {
            const unsigned fs = (x.statusData >> 13) & 3;
            if (x.statusAddress == 0x300 || (x.statusAddress == 0x100 && !oldV)) {
                hostFs = fs; ++hostStatusWrites;
            }
            if (x.statusAddress == 0x200 || (x.statusAddress == 0x100 && oldV)) {
                guestFs = fs; ++guestStatusWrites;
                guestStatusBoundary = x.statusAddress == 0x100 && oldV && hostFs != guestFs;
            }
            if (x.statusAddress == 0x600) spv = (x.statusData >> 7) & 1;
        }
        if (csrMutation) {
            const uint64_t value = x.csrOperation == 0 ? x.csrValue :
                x.csrOperation == 1 ? (csrRead | x.csrValue) : (csrRead & ~x.csrValue);
            if (x.csrAddress == 1) flags = value & 31;
            if (x.csrAddress == 2) frm = value & 7;
            if (x.csrAddress == 3) { flags = value & 31; frm = (value >> 5) & 7; }
            hostFs = 3;
            if (oldV) { guestFs = 3; ++csrGuestEvents; } else ++csrHostEvents;
        }
        if ((x.status || x.csr) && !idle) ++blockedContext;
        if (x.issue && issueReady) {
            pending = x.command; pendingGuest = oldV;
            rm = pending.rm == 7 ? frm : pending.rm;
            for (unsigned lane = 0; lane < 3; ++lane) {
                operands[lane] = regs[pending.source[lane]];
                if (pending.boxed[lane] && (operands[lane] >> 32) != 0xffffffffULL) {
                    operands[lane] = 0xffffffff7fc00000ULL; ++boxedOperands;
                }
            }
            pendingDenial = hostFs == 0 ? 1 : (oldV && guestFs == 0) ? 2 :
                (pending.rounding && rm > 4) ? 3 : 0;
            response = {}; response.token = pending.token;
            response.fault = pendingDenial != 0;
            if (response.fault) { response.cause = 2; response.tval = pending.instruction; }
            state = response.fault ? 3 : 1;
            if (pendingDenial == 1) ++hostOff;
            if (pendingDenial == 2) ++guestOff;
            if (pendingDenial == 3) ++roundingIllegal;
            ++issued;
        }
        if (executing && x.executeReady) { state = 2; ++producerRequests; }
        if (x.result) {
            if (oldState == 2 && !x.flush && x.response.token == pending.token) {
                response = x.response; state = 3;
            } else ++staleResults;
        }
        if (retire) {
            if (!response.fault) {
                if (pending.writes)
                    regs[pending.destination] = pending.single ?
                        (0xffffffff00000000ULL | uint32_t(response.value)) : response.value;
                if (pending.flags) flags |= response.flags;
                if (retireMutation) {
                    hostFs = 3;
                    if (pendingGuest) { guestFs = 3; ++retireGuestEvents; } else ++retireHostEvents;
                }
                if (pending.flags && !pending.writes) ++flagsOnly;
                if (pending.writes && !pending.flags) ++fpOnly;
                if (!pending.writes && !pending.flags) ++readOnly;
            } else ++faultRetirements;
            state = 0; ++retired;
        }
        if (x.mret) virtualized = false; // fixture mpp=3, independent of MPV
        if (x.sret && !oldV) { virtualized = spv; spv = false; }
        if (oldState != 0 && virtualized != oldV) ++liveOwnerChanges;
        if (x.flush) state = 0;
        ++cycles;
    }
    void status(unsigned address, uint64_t data) {
        Input x; x.status = true; x.statusAddress = address; x.statusData = data;
        tick(x); tick();
    }
    void leaveGuest() {
        if (virtualized) { Input x; x.mret = true; tick(x); tick(); }
    }
    void enterGuest() {
        check(!virtualized, "stimulus", "enterGuest requires host context");
        status(0x600, 1U << 7);
        Input x; x.sret = true; tick(x); tick();
    }
    void context(unsigned host, unsigned guest, bool inGuest) {
        leaveGuest(); status(0x300, uint64_t(host) << 13); status(0x200, uint64_t(guest) << 13);
        if (inGuest) enterGuest();
    }
    void csr(unsigned address, uint64_t value, unsigned operation = 0, bool write = true) {
        Input x; x.csr = true; x.csrWrite = write; x.csrAddress = address;
        x.csrValue = value; x.csrOperation = operation; tick(x); tick();
    }
    // ownerChange: 1 leaves a guest while pending, 2 enters a pre-armed guest.
    void transaction(Command c, uint64_t syntheticValue, unsigned resultFlags = 0,
        bool fault = false, bool rigorous = false, unsigned ownerChange = 0, bool drain = true) {
        Input x; x.issue = true; x.command = c; tick(x);
        if (state == 1) {
            x = {}; x.executeReady = false;
            x.mret = ownerChange == 1; x.sret = ownerChange == 2;
            tick(x);
            x = {}; x.executeReady = false; tick(x);
            x = {}; tick(x);
            if (rigorous) {
                x = {}; x.result = true; x.response.token = {c.token.index, c.token.tag ^ (uint64_t(1) << 48)};
                x.response.value = ~uint64_t(0); x.response.flags = 31; tick(x);
                x.response.token = {(c.token.index + 1) % 16, c.token.tag}; tick(x);
                x = {}; x.status = true; x.statusAddress = virtualized ? 0x100 : 0x300;
                x.statusData = 0; x.csr = true; x.csrWrite = true; x.csrValue = 255; tick(x);
            }
            x = {}; x.result = true;
            x.response = {c.token, syntheticValue, fault ? 0x12345000ULL : 0, resultFlags, fault ? 13U : 0, fault};
            tick(x);
        }
        // Also inspect forbidden producer offers while its ready is low.
        x = {}; x.executeReady = false; tick(x); // unretired completion cannot mutate state
        if (rigorous) {
            x = {}; x.retire = true; x.retireToken = {c.token.index, c.token.tag ^ (uint64_t(1) << 48)}; tick(x);
            x.retireToken = {(c.token.index + 1) % 16, c.token.tag}; tick(x);
            x.retireToken = c.token; x.head = false; tick(x);
        }
        x = {}; x.retire = true; x.retireToken = c.token; tick(x);
        if (drain) tick();
    }
    std::array<uint64_t, 32> readAll() {
        std::array<uint64_t, 32> captured{};
        for (unsigned reg = 0; reg < 32; ++reg) {
            auto c = command(reg, false, false);
            c.source = {reg, reg, reg}; c.boxed = {false, true, false};
            transaction(c, 0);
            captured[reg] = observedOperands[0];
        }
        return captured;
    }
    void loadImage(const Image& image, bool inGuest) {
        context(2, 2, inGuest);
        for (unsigned reg = 0; reg < 32; ++reg)
            transaction(command(reg, true, false), image.regs[reg]);
        csr(3, image.fcsr);
        // Explicit metadata restoration is separate from shared-data transport.
        context(image.hostFs, image.guestFs, inGuest);
        ++imageRestores;
    }
    Image saveImage(const Image& expected) {
        Image captured;
        captured.regs = readAll();
        Input x; x.csr = true; x.csrAddress = 3; x.csrOperation = 1; tick(x);
        captured.fcsr = dut.get_io$$csrRead(); tick();
        captured.hostFs = dut.get_io$$hostFs(); captured.guestFs = dut.get_io$$guestFs();
        check(captured.regs == expected.regs && captured.fcsr == expected.fcsr &&
            captured.hostFs == expected.hostFs && captured.guestFs == expected.guestFs,
            "context_image", "32 raw FPRs/fcsr/FS image");
        ++imageSaves;
        return captured;
    }
};

static Image makeImage(unsigned identity) {
    Image image;
    const std::array<uint64_t, 8> patterns = {
        0, 0x8000000000000000ULL, 0x7ff0000000000000ULL, 0xfff0000000000000ULL,
        0x7ff0000000000001ULL, 0x7ff8123456789000ULL, 1, 0x000fffffffffffffULL};
    for (unsigned reg = 0; reg < 32; ++reg) {
        image.regs[reg] = patterns[reg % patterns.size()] ^
            (uint64_t(identity) << 44) ^ (0x0102040808102041ULL * reg);
        if (reg % 3 == 0) image.regs[reg] = 0xffffffff00000000ULL | uint32_t(image.regs[reg]);
    }
    image.fcsr = (identity << 5) | (identity * 7);
    image.hostFs = identity == 1 ? 1 : 2;
    image.guestFs = identity == 3 ? 1 : 2;
    return image;
}

int main(int argc, char** argv) {
    try {
        Oracle m;
        if (argc == 2) {
            const std::string_view option(argv[1]);
            const std::string_view prefix = "--negative=";
            if (!option.starts_with(prefix)) throw std::runtime_error("DUAL_FS_USAGE: expected --negative=NAME");
            m.negative = option.substr(prefix.size());
            if (m.negative != "host-permission" && m.negative != "guest-permission" &&
                m.negative != "status-target" && m.negative != "guest-dirty" && m.negative != "fault-mutation")
                throw std::runtime_error("DUAL_FS_USAGE: unknown negative control");
        } else if (argc != 1) throw std::runtime_error("DUAL_FS_USAGE: expected zero or one option");
        m.reset(); m.tick();

        // Every permission row is established independently for every access,
        // because an accepted CSR write changes FS to Dirty in that very row.
        for (unsigned v = 0; v < 2; ++v) for (unsigned host = 0; host < 4; ++host)
            for (unsigned guest = 0; guest < 4; ++guest) {
                const bool allowed = host != 0 && (!v || guest != 0);
                for (unsigned address = 1; address <= 3; ++address) for (unsigned write = 0; write < 2; ++write) {
                    m.context(host, guest, v);
                    m.csr(address, 0xa5, write ? 0 : 1, write);
                    ++m.csrMatrixAccesses;
                    if (!allowed) ++m.csrMatrixDenied;
                }
                m.context(host, guest, v);
                m.transaction(m.command((host * 4 + guest) % 32, false, false), 0, 0, false, true);
                ++m.permissionRows;
                if (!allowed) ++m.permissionDenied;
            }
        m.check(m.permissionRows == 32 && m.permissionDenied == 11 &&
            m.csrMatrixAccesses == 192 && m.csrMatrixDenied == 66,
            "coverage", "complete dual-FS command/CSR matrix");

        // All status write targets and independent, read-only SD. SD writes use
        // the opposite value from that derived by FS and must have no effect.
        for (unsigned host = 0; host < 4; ++host) for (unsigned guest = 0; guest < 4; ++guest) {
            m.context(host, guest, false);
            const uint64_t oppositeSd = host == 3 ? 0 : uint64_t(1) << 63;
            m.status(0x100, (uint64_t(host) << 13) | oppositeSd);
            for (unsigned address : {0x300U, 0x100U, 0x200U}) {
                Input x; x.readAddress = address; m.tick(x);
            }
            m.enterGuest();
            m.status(0x100, (uint64_t(guest) << 13) | (guest == 3 ? 0 : uint64_t(1) << 63));
            Input x; x.readAddress = 0x100; m.tick(x);
        }
        m.context(2, 2, true);
        m.transaction(m.command(3), 0x7ff8123456789001ULL, 17, false, true);
        m.status(0x100, uint64_t(1) << 13); // guest clears only its own Dirty
        m.check(m.hostFs == 3 && m.guestFs == 1, "status_target", "guest clear preserves host Dirty");

        // CSR write-intent, including unchanged writes, is distinct from reads.
        // Both immediate and register forms have already reduced to this decoded
        // operation/write contract; no ISA decode is claimed by this fixture.
        for (unsigned v = 0; v < 2; ++v) for (unsigned address = 1; address <= 3; ++address) {
            m.context(2, 2, v);
            const unsigned same = address == 1 ? m.flags : address == 2 ? m.frm : m.fcsr();
            m.csr(address, same); // CSRRW write intent, even unchanged
            m.context(2, 2, v); m.csr(address, 0, 1, false); // CSRRS/CSRRSI zero-source read
            m.csr(address, 0, 2, false); // CSRRC/CSRRCI zero-source read
            m.csr(address, 0, 0, true); // CSRRW zero still writes
            m.context(2, 2, v); m.csr(address, 3, 1, true);
            m.context(2, 2, v); m.csr(address, 1, 2, true);
            m.context(2, 2, v); m.csr(address, ~uint64_t(0), 3, true); // illegal operation
        }
        m.context(2, 2, true); m.csr(0x300, ~uint64_t(0)); // not an FP CSR alias

        // Successful FP-only, flags-only and neither-modifying commands; fault
        // payloads contain nonzero flags/data that must never become committed.
        for (unsigned v = 0; v < 2; ++v) {
            m.context(2, 2, v); m.csr(3, 0); m.context(2, 2, v);
            m.transaction(m.command(4, true, false), 0xabcdef0123456789ULL, 31, false, true);
            m.context(2, 2, v);
            m.transaction(m.command(4, false, true), ~uint64_t(0), 0x15, false, true);
            m.context(2, 2, v);
            m.transaction(m.command(4, false, false), 0, 31, false, true);
            m.context(2, 2, v);
            m.transaction(m.command(4), ~uint64_t(0), 31, true, true);
            auto read = m.command(4, false, false); read.source = {4, 4, 4};
            m.transaction(read, 0);
        }

        // The retiring owner comes from accepted issue, never live V. These
        // deliberate component-context perturbations are not a core program.
        m.context(2, 2, true);
        m.transaction(m.command(5), 0x5511223344556677ULL, 2, false, true, 1);
        m.context(2, 2, false); m.status(0x600, 1U << 7);
        m.transaction(m.command(6), 0x6611223344556677ULL, 4, false, true, 2);
        m.check(m.hostFs == 3 && m.guestFs == 2, "mutation_owner", "host owner must not dirty live guest");

        // Focused effective rounding and flag accrual, not numerical arithmetic.
        for (unsigned v = 0; v < 2; ++v) {
            m.context(2, 2, v); m.csr(2, 4); m.context(2, 2, v);
            auto c = m.command(7, false, true); c.rounding = true; c.rm = 7;
            m.transaction(c, 0, 0x1b, false, true);
            for (unsigned reserved = 5; reserved <= 7; ++reserved) {
                m.csr(2, reserved); m.context(2, 2, v);
                c = m.command(7); c.rounding = true; c.rm = 7; m.transaction(c, 0, 31);
                c = m.command(7, false, false); c.rm = reserved; m.transaction(c, 0);
            }
            m.csr(2, 0);
        }

        // All 32 writable FPRs, boxed S writes and raw/boxed source views. Both
        // paths retain the older committed value when the physical Mem write is
        // delayed: immediate next issue, or the inherited younger-flush case.
        const std::array<uint32_t, 8> singleBits = {
            0, 0x80000000U, 0x7f800000U, 0xff800000U, 0x7f800001U, 0x7fc12345U, 1, 0x007fffffU};
        for (unsigned reg = 0; reg < 32; ++reg) for (unsigned youngerFlush = 0; youngerFlush < 2; ++youngerFlush) {
            m.context(2, 2, reg % 2);
            auto write = m.command(reg, true, false); write.single = youngerFlush;
            const uint64_t data = youngerFlush ? singleBits[reg % 8] :
                (0x1234567800000000ULL | (uint64_t(reg) << 24) | (0x800001U + reg));
            m.transaction(write, data, 0, false, false, 0, false);
            if (youngerFlush) { Input x; x.flush = true; m.tick(x); ++m.olderCommitFlushChecks; }
            auto read = m.command(reg, false, false); read.source = {reg, reg, reg}; read.boxed = {false, true, false};
            m.transaction(read, 0); ++m.forwardingChecks;
        }

        // Denied head prevents even idle accepted CSR/status/issue changes.
        Input blocked; blocked.head = false; blocked.status = true; blocked.statusAddress = 0x100;
        blocked.statusData = 0; blocked.csr = true; blocked.csrWrite = true; blocked.csrValue = 255;
        blocked.issue = true; blocked.command = m.command(0); m.tick(blocked); m.tick();
        blocked.status = false; blocked.issue = false; m.tick(blocked); // CSR alone, denied head
        blocked.csr = false; blocked.issue = true; m.tick(blocked); // command alone, denied head
        blocked.issue = false; blocked.status = true; m.tick(blocked); m.tick();

        // Three explicitly transported images share one physical FPR/fcsr bank.
        // Save uses checked DUT observations, restore uses synthetic full-width
        // result inputs. This is component transport, not memory/software proof.
        const std::array<Image, 3> expected = {makeImage(1), makeImage(2), makeImage(3)};
        std::array<Image, 3> saved{};
        for (unsigned identity = 0; identity < 3; ++identity) {
            m.loadImage(expected[identity], identity != 0);
            saved[identity] = m.saveImage(expected[identity]);
        }
        for (unsigned identity : {1U, 0U}) {
            m.loadImage(saved[identity], identity != 0);
            m.saveImage(expected[identity]);
        }
        // Initial is metadata, not implicit zeroing or automatic isolation.
        m.context(1, 1, true);
        const auto retained = m.readAll();
        m.check(retained == expected[0].regs && m.fcsr() == expected[0].fcsr,
            "initial_retention", "FS Initial must retain all FPR/fcsr data");
        m.context(0, 0, false); m.context(1, 1, false);
        m.check(m.readAll() == expected[0].regs && m.fcsr() == expected[0].fcsr,
            "initial_retention", "Off to Initial must not initialize data");

        m.check(m.liveOwnerChanges == 2 && m.forwardingChecks == 64 && m.olderCommitFlushChecks == 32 &&
            m.imageSaves == 5 && m.imageRestores == 5 && m.roundingIllegal == 6,
            "coverage", "ownership/transport/forwarding/rounding cases");
        m.check(m.hostOff == 8 && m.guestOff == 3 && m.staleResults > 40 && m.heldCompletions > 50 &&
            m.wrongRetireTags > 30 && m.wrongRetireIndices > 30 && m.deniedHeadRetires > 30 &&
            m.blockedContext > 30 && m.boxedOperands > 50 && m.flagsOnly >= 4 && m.fpOnly > 100 &&
            m.readOnly > 100 && m.csrHostEvents > 0 && m.csrGuestEvents > 0 &&
            m.retireHostEvents > 0 && m.retireGuestEvents > 0,
            "coverage", "event/state boundary coverage");
        m.check(m.negative.empty(), "negative_not_triggered", "named checker control did not fail");
        std::cout << "DUAL_FS_PREPARATION_PASS {\"schema\":1,\"evidence\":\"component_only\","
            "\"synthetic_results\":true,\"guest_fd_execution\":false,\"cycles\":" << m.cycles
            << ",\"permission_rows\":" << m.permissionRows << ",\"command_denials\":" << m.permissionDenied
            << ",\"csr_matrix_accesses\":" << m.csrMatrixAccesses << ",\"csr_matrix_denials\":" << m.csrMatrixDenied
            << ",\"issued\":" << m.issued << ",\"retired\":" << m.retired
            << ",\"producer_requests\":" << m.producerRequests << ",\"host_off\":" << m.hostOff
            << ",\"guest_off\":" << m.guestOff << ",\"stale_results\":" << m.staleResults
            << ",\"held_completions\":" << m.heldCompletions << ",\"wrong_retire_tags\":" << m.wrongRetireTags
            << ",\"wrong_retire_indices\":" << m.wrongRetireIndices
            << ",\"denied_head_retires\":" << m.deniedHeadRetires << ",\"blocked_context\":" << m.blockedContext
            << ",\"csr_host_events\":" << m.csrHostEvents << ",\"csr_guest_events\":" << m.csrGuestEvents
            << ",\"retire_host_events\":" << m.retireHostEvents << ",\"retire_guest_events\":" << m.retireGuestEvents
            << ",\"fault_retirements\":" << m.faultRetirements << ",\"live_owner_changes\":" << m.liveOwnerChanges
            << ",\"fpr_registers\":32,\"forwarding_checks\":" << m.forwardingChecks
            << ",\"older_commit_younger_flush\":" << m.olderCommitFlushChecks
            << ",\"image_saves\":" << m.imageSaves << ",\"image_restores\":" << m.imageRestores
            << ",\"initial_retention_contexts\":2,\"status_alias_pairs\":16,\"rounding_denials\":"
            << m.roundingIllegal << "}\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
