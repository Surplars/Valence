// Link against the same completed BoardSocGsim objects as the fixed COPY run.
#define main unused_board_boot_main
#include "board_boot.cpp"
#undef main
#include "pmp_trap_symbols.h"

struct PreciseTrapObserver {
    bool shortInstruction = false;
    unsigned traps = 0, targetCommits = 0;
    uint64_t firstPc = 0, firstCause = 0, firstTval = 0;
    static void observe(SBoardSocGsim &d, void *context) {
        static_cast<PreciseTrapObserver *>(context)->sample(d);
    }
    void sample(SBoardSocGsim &d) {
        for (unsigned lane = 0; lane < 2; ++lane) {
            const bool valid = lane ? d.get_io$$commit1() : d.get_io$$commit0();
            if (!valid) continue;
            const uint64_t pc = lane ? d.get_io$$commit1Pc() : d.get_io$$commit0Pc();
            if (pc == PMP_TARGET_PC) ++targetCommits;
            check(pc != PMP_TARGET_PC + 2, "denied next parcel retired");
        }
        if (!d.get_io$$trap$$valid()) return;
        const auto pc = d.get_io$$trap$$bits$$pc();
        const auto cause = d.get_io$$trap$$bits$$cause();
        const auto tval = d.get_io$$trap$$bits$$tval();
        if (traps == 0) {
            firstPc = pc; firstCause = cause; firstTval = tval;
            check(cause == 1, "expected instruction access fault");
            check(pc == PMP_TARGET_PC + (shortInstruction ? 2 : 0), "precise trap PC mismatch");
            check(tval == PMP_TARGET_PC + 2, "precise trap tval mismatch");
        } else {
            check(traps == 1 && cause == 11 && pc == PMP_FINISHED_ECALL,
                  "unexpected handler trap or terminal event");
        }
        ++traps;
    }
};
int main(int argc, char **argv) {
    try {
        check(argc == 3, "image short|word");
        const std::string mode = argv[2];
        check(mode == "short" || mode == "word", "unknown parcel case");
        const Bytes image = readFile(argv[1]);
        Bytes rom; word(rom, 0x00200297); word(rom, 0x00028067);
        Test test(rom); test.running = false;
        for (size_t offset = 0; offset < image.size(); offset += 8) {
            uint64_t value = 0;
            for (unsigned b = 0; b < 8 && offset + b < image.size(); ++b)
                value |= uint64_t(image[offset + b]) << (8 * b);
            test.ddr.memory[uint32_t(offset)] = value;
        }
        for (unsigned i = 0; i < 4; ++i)
            test.ddr.memory[uint32_t(0x80210000ULL + 8 * i - ramBase)] = 0;
        PreciseTrapObserver observer; observer.shortInstruction = mode == "short";
        test.observer = PreciseTrapObserver::observe; test.observerContext = &observer;
        const auto deadline = test.cycles + 20000;
        while (test.cycles < deadline && observer.traps < 2) test.tick();
        check(observer.traps == 2, "precise trap guest timeout");
        check(observer.targetCommits == (observer.shortInstruction ? 1U : 0U), "target retirement count mismatch");
        // The handler reads the architectural CSRs and fence.i publishes the mailbox.
        // No internal register names or invalid payload bits are observed.
        const auto mailbox = [&](unsigned wordIndex) {
            return test.ddr.memory.at(uint32_t(0x80210000ULL + 8 * wordIndex - ramBase));
        };
        check(mailbox(0) == 1, "architectural mcause mailbox mismatch");
        check(mailbox(1) == observer.firstPc, "architectural mepc mailbox mismatch");
        check(mailbox(2) == observer.firstTval, "architectural mtval mailbox mismatch");
        check(mailbox(3) == 0x504d50, "architectural mailbox incomplete");
        test.idle(128);
        check(observer.traps == 2, "unexpected third trap while draining");
        check(test.ddr.pendingReads.empty() && test.ddr.pendingWrites.empty() && test.ddr.pendingB.empty(),
              "terminal guest retained AXI owners");
        test.fabric.finish();
        std::cout << "PMP_PRECISE_CPU_PASS mode=" << mode << " cause=" << observer.firstCause
                  << " mepc=" << observer.firstPc << " mtval=" << observer.firstTval
                  << " target_commits=" << observer.targetCommits << " cycles=" << test.cycles << "\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "PMP_PRECISE_CPU_FAIL " << error.what() << "\n";
        return 1;
    }
}
