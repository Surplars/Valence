// Directed public-interface schedules reuse the independent ISA and byte-store
// oracle. No expected result or PC is derived from DUT internal state.
#define main i1_integer_core_main
#include "five_stage.cpp"
#undef main

static_assert(DUT_HAS_C && DUT_HAS_M && DUT_XLEN == 64,
    "frontend recovery gate requires the RV64 MC bare core");

enum class FrontendCase { IrqAccept, IrqLength, HeldAtFlush, HeldAcrossFlush };

struct FrontendRecovery : FiveStageObserver {
    const FrontendCase kind;
    const std::vector<uint32_t> &code;
    const bool injectPc;
    const uint64_t marker, target = BASE + 0x80;
    uint64_t expectedFetch = BASE, edge = 0, pulseAt = 0, flushAt = 0;
    std::optional<uint64_t> fetchPc, dataPc;
    FiveStageService inputs{};
    bool boundaryAccepted = false, heldSeen = false, pulseDone = false;
    bool flushSeen = false, resumed = false, targetSeen = false, checkingFetch = false;
    unsigned setupAccepts = 0, setupBranchFlushes = 0, irqHighEdges = 0, irqCommitEdges = 0;
    unsigned accepts = 0, pulseAccepts = 0, pulseRepairs = 0, stoppedEdges = 0;
    unsigned heldEdges = 0, flushHeld = 0, flushAccepts = 0, drainedWithTarget = 0, stores = 0;
    bool isIrq() const { return kind == FrontendCase::IrqAccept || kind == FrontendCase::IrqLength; }
    FrontendRecovery(FrontendCase k, const std::vector<uint32_t> &p, bool inject)
        : kind(k), code(p), injectPc(inject), marker(BASE + (isIrq() ? 0x88 : 12)) {
        checkingFetch = !isIrq();
    }

    void service(uint64_t cycle, const std::optional<MemoryReply> &fetch,
                 const std::optional<MemoryReply> &data, FiveStageService &s) override {
        edge = cycle;
        fetchPc = fetch ? std::optional<uint64_t>(fetch->address) : std::nullopt;
        dataPc = data ? std::optional<uint64_t>(data->address) : std::nullopt;
        if (kind == FrontendCase::IrqAccept && boundaryAccepted && !pulseDone) {
            // First expose and hold the ordinary offer. IRQ is then pulsed on
            // its real acceptance while an older load cannot yet complete.
            s.fetchReady = false;
            if (heldSeen && data) {
                need(!data->write && data->address == DATA + 512 && data->due > cycle + 8,
                    "ordinary IRQ pulse lacks a long-lived older load");
                // Eligibility is registered in the FPGA profile. Keep the
                // offered PC held for this edge; accept it on the next edge.
                s.externalIrq = true; pulseDone = true; pulseAt = cycle;
            }
        }
        if (kind == FrontendCase::IrqLength && fetch && fetch->address == marker && !pulseDone) {
            // Do not expose VALID before this event; once released the normal
            // harness holds the same response until the core accepts it.
            s.fetchValid = false;
            if (data && fetch->due <= cycle) {
                need(!data->write && data->address == DATA + 512 && data->due > cycle + 8,
                    "C IRQ pulse lacks a long-lived older load");
                // Release the C response one edge after the external pulse,
                // when the registered IRQ eligibility closes the next offer.
                s.externalIrq = true; pulseDone = true; pulseAt = cycle;
            }
        }
        if (!isIrq() && boundaryAccepted && !targetSeen) {
            s.fetchReady = false;
            if (kind == FrontendCase::HeldAtFlush) {
                // In this established bare-core service law, the old load
                // response releases the ADDR branch at the same edge.
                if ((heldSeen && s.dataValid) || flushSeen) s.fetchReady = true;
            } else if (flushSeen && cycle >= flushAt + 2) s.fetchReady = true;
        }
        inputs = s;
    }

    void cycle(SFiveStageCore &d, uint64_t) override {
        const bool offered = d.get_io$$instructionRequest$$valid();
        const uint64_t pc = d.get_io$$instructionRequest$$bits();
        const bool accept = offered && inputs.fetchReady;
        const bool reply = inputs.fetchValid && d.get_io$$instructionResponse$$ready();
        const bool branchFlush = d.get_io$$branchMispredict();
        if (offered && !inputs.fetchReady && pc == marker) { heldSeen = true; ++heldEdges; }
        if (isIrq()) {
            irqHighEdges += inputs.externalIrq;
            irqCommitEdges += d.get_io$$trapTaken() && !d.get_io$$retire$$valid();
            if (checkingFetch && !resumed)
                need(!d.get_io$$clearReservation(), "transient IRQ body required an older flush to resume");
            need(!branchFlush || !checkingFetch, "transient IRQ body unexpectedly redirected a branch");
            if (branchFlush) ++setupBranchFlushes;
            if (inputs.externalIrq) {
                need(dataPc == DATA + 512 && !inputs.dataValid && !d.get_io$$trapTaken(),
                    "transient IRQ committed or lost its older outstanding load");
            }
            if (pulseDone && edge == pulseAt + 1) {
                need(!inputs.externalIrq && dataPc == DATA + 512 && !inputs.dataValid,
                    "registered IRQ event lacks its older load or pulse was not withdrawn");
                if (kind == FrontendCase::IrqAccept) {
                    need(accept && pc == marker, "ordinary IRQ did not overlap request acceptance");
                    ++pulseAccepts;
                } else {
                    need(reply && fetchPc == marker && !offered,
                        "C IRQ did not overlap the live short-response length repair");
                    ++pulseRepairs;
                }
            }
            if (pulseDone && edge == pulseAt + 2) {
                need(!offered && !inputs.externalIrq, "IRQ did not close the offer for one edge");
                ++stoppedEdges;
            }
            if (pulseDone && edge > pulseAt + 1 && accept && !resumed) {
                const uint64_t resumePc = marker + (kind == FrontendCase::IrqLength ? 2 : 4);
                need(pc == (injectPc ? resumePc ^ 4 : resumePc),
                    "frontend recovery independent resume-PC mismatch");
                need(dataPc == DATA + 512 && !inputs.dataValid && !d.get_io$$trapTaken(),
                    "transient IRQ resumed only after backend completion or a trap");
                resumed = true;
            }
        } else {
            if (branchFlush) {
                need(!flushSeen && heldSeen && offered && pc == marker,
                    "branch flush did not encounter the scheduled held offer");
                flushSeen = true; flushAt = edge;
                if (accept) ++flushAccepts; else ++flushHeld;
            }
            if (accept && pc == target) {
                need(flushSeen && reply && fetchPc == marker,
                    "redirect target did not coincide with draining the killed fetch response");
                ++drainedWithTarget; targetSeen = true;
            }
        }
        if (accept) {
            if (!checkingFetch) {
                // The setup mstatus CSR causes a legal recovery/re-fetch. Its
                // retirement is checked by the ISA oracle. A literal JAL then
                // starts the independently checked perturbation window.
                if (pc == target) { checkingFetch = true; expectedFetch = target; }
                else {
                    need(pc >= BASE && pc < target && !(pc & 3), "IRQ setup fetched outside its literal region");
                    ++setupAccepts;
                    return;
                }
            }
            const uint64_t expected = injectPc && !isIrq() && expectedFetch == target ? target ^ 4 : expectedFetch;
            need(pc == expected, "frontend recovery independent accepted-PC mismatch expected=" +
                std::to_string(expected) + " got=" + std::to_string(pc));
            need(pc >= BASE && pc + 4 <= BASE + code.size() * 4, "frontend test fetch escaped literal image");
            uint16_t half; std::memcpy(&half, reinterpret_cast<const uint8_t *>(code.data()) + pc - BASE, 2);
            expectedFetch = pc + ((half & 3) == 3 ? 4 : 2);
            if (!isIrq() && pc == marker) expectedFetch = target;
            if (pc == marker - 4) boundaryAccepted = true;
            ++accepts;
        }
    }

    void retire(SFiveStageCore &, uint64_t, uint64_t, uint32_t ins, uint64_t, bool trap,
                unsigned = 4) override {
        if (!trap && (ins & 127) == 0x23) ++stores;
    }

    void finish(const Stats &s) {
        need(stores == 1, "frontend recovery did not commit exactly the intended store");
        if (isIrq()) {
            need(pulseDone && resumed && stoppedEdges == 1 && s.retires == 12 &&
                setupAccepts > 0 && setupBranchFlushes == 1 && irqHighEdges == 1 && irqCommitEdges == 0,
                "transient IRQ acceptance/stop/resume/retirement coverage missing");
            need(pulseAccepts == unsigned(kind == FrontendCase::IrqAccept) &&
                pulseRepairs == unsigned(kind == FrontendCase::IrqLength),
                "transient IRQ trigger coverage missing");
        } else {
            need(flushSeen && targetSeen && drainedWithTarget == 1 && heldEdges > 0 && s.retires == 6,
                "held fetch flush/drain/redirect/retirement coverage missing");
            need(flushAccepts == unsigned(kind == FrontendCase::HeldAtFlush) &&
                flushHeld == unsigned(kind == FrontendCase::HeldAcrossFlush),
                "held fetch acceptance timing coverage missing");
        }
        std::cout << "I1_FRONTEND_RECOVERY_PASS case=" << unsigned(kind) << " cycles=" << s.cycles
            << " retired=" << s.retires << " accepted_fetches=" << accepts
            << " irq_accept=" << pulseAccepts << " irq_length_repair=" << pulseRepairs
            << " irq_stopped_edges=" << stoppedEdges << " irq_input_edges=" << irqHighEdges
            << " irq_commit_edges=" << irqCommitEdges << " held_edges=" << heldEdges
            << " flush_held=" << flushHeld << " flush_accept=" << flushAccepts
            << " killed_reply_target_overlap=" << drainedWithTarget << " committed_stores=" << stores
            << " independent_fetch_PC_ISA_store=PASS\n";
    }
};

static std::vector<uint32_t> frontendProgram(bool irq, bool compressed) {
    std::vector<uint32_t> code(128, 0x00000013);
    auto put = [&](unsigned offset, uint32_t value, unsigned size = 4) {
        std::memcpy(reinterpret_cast<uint8_t *>(code.data()) + offset, &value, size);
    };
    put(0, 0x00002a17);
    if (irq) {
        put(4, ri(0x13,1,0,0,8)); put(8, ri(0x73,0,1,1,0x300));
        put(12, ri(0x13,1,0,0,-2048)); put(16, ri(0x73,0,1,1,0x304));
        put(20, jal(0,0x6c)); // Leave the setup CSR recovery region before arming.
        put(0x80, ri(0x03,4,3,20,512)); put(0x84, rr(0x33,5,4,4,1,1));
        put(0x88, compressed ? 0x0505 : ri(0x13,10,0,0,9), compressed ? 2 : 4);
        const unsigned next = compressed ? 0x8a : 0x8c;
        put(next, ri(0x13,31,0,0,77)); put(next + 4, st(3,20,31,0)); put(next + 8, 0x00100073);
    } else {
        put(4, ri(0x03,4,3,20,512)); put(8, br(0,0,0,0x78));
        put(12, st(3,20,4,8)); // This visible but killed owner must never write.
        put(0x80, ri(0x13,31,0,0,77)); put(0x84, st(3,20,31,0)); put(0x88, 0x00100073);
    }
    return code;
}

int main(int argc, char **argv) { try {
    const std::string option = argc > 1 ? argv[1] : "";
    const bool inject = option.starts_with("--inject-");
    for (auto kind : {FrontendCase::IrqAccept, FrontendCase::IrqLength,
                      FrontendCase::HeldAtFlush, FrontendCase::HeldAcrossFlush}) {
        if (option == "--inject-c-resume-pc" && kind != FrontendCase::IrqLength) continue;
        if (option == "--inject-redirect-pc" && kind != FrontendCase::HeldAcrossFlush) continue;
        const bool irq = kind == FrontendCase::IrqAccept || kind == FrontendCase::IrqLength;
        const auto code = frontendProgram(irq, kind == FrontendCase::IrqLength);
        FrontendRecovery observer(kind, code, inject);
        const auto result = execute("mixed-frontend-recovery-" + std::to_string(unsigned(kind)), code, 1,
            {}, {}, false, false, false, false, 128, &observer, true);
        observer.finish(result);
    }
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
