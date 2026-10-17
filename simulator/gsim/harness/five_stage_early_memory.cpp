// Reuse the independent software ISA/byte/intent oracle, never the DUT control tables.
#define main FoundationOriginalMain
#include "five_stage.cpp"
#undef main

int main(int argc, char **argv) {
    int foundation = FoundationOriginalMain(argc, argv);
    if (foundation) return foundation;
    try {
        unsigned cases = 0;
        for (unsigned latency : {1U, 9U}) {
            auto prefix = std::vector<uint32_t>{0x00002a17, ri(0x13, 1, 0, 0, -31)};
            auto checkFault = [&](const std::string &name, uint32_t old, std::optional<uint64_t> error) {
                auto code = prefix;
                code.push_back(old); code.push_back(st(2, 20, 1, 16));
                code.push_back(ri(0x13, 31, 0, 0, 77)); code.push_back(0x00100073);
                execute(name, code, latency, {}, error); ++cases;
            };
            // No younger store may become visible behind a faulting ALU or late memory error.
            checkFault("early-old-illegal-before-store", 0xffffffff, {});
            checkFault("early-old-load-error-before-store", ri(0x03, 2, 2, 20, 128), DATA + 128);
            checkFault("early-old-store-error-before-store", st(2, 20, 1, 128), DATA + 128);
            auto forwarding = prefix;
            forwarding.push_back(ri(0x13, 20, 0, 20, 64));
            forwarding.push_back(ri(0x13, 1, 0, 1, 7));
            forwarding.push_back(st(2, 20, 1, 0));
            forwarding.push_back(ri(0x03, 2, 2, 20, 0));
            forwarding.push_back(rr(0x33, 3, 0, 2, 1));
            forwarding.push_back(0x00100073);
            execute("early-old-alu-forwarded-address-data", forwarding, latency); ++cases;
            auto serial = prefix;
            serial.push_back(ri(0x73, 2, 1, 1, 0x340));
            serial.push_back(0x0000100f); serial.push_back(st(2, 20, 1, 64));
            serial.push_back(0x00100073);
            execute("early-old-csr-fence-before-store", serial, latency); ++cases;
            auto youngest = prefix;
            youngest.push_back(ri(0x13, 5, 0, 0, 21));
            youngest.push_back(st(2, 20, 5, 64));
            youngest.push_back(ri(0x13, 5, 0, 0, 7));
            youngest.push_back(ri(0x03, 5, 2, 20, 64));
            youngest.push_back(rr(0x33, 6, 0, 5, 1));
            youngest.push_back(st(2, 20, 6, 68));
            youngest.push_back(0x00100073);
            execute("youngest-same-rd-load-wins-older-alu", youngest, latency); ++cases;
            auto retained = prefix;
            retained.push_back(ri(0x13, 5, 0, 0, 63));
            retained.push_back(ri(0x03, 2, 2, 20, 64));
            retained.push_back(rr(0x33, 6, 0, 5, 2));
            retained.push_back(ri(0x13, 5, 0, 0, 11));
            retained.push_back(rr(0x33, 7, 0, 5, 6));
            retained.push_back(st(2, 20, 7, 72));
            retained.push_back(0x00100073);
            execute("held-rf-operand-snoops-wb-while-load-stalls", retained, latency); ++cases;
        }
        std::cout << "FIVE_STAGE_EARLY_MEMORY_PASS xlen=" << N << " M=" << DUT_HAS_M
            << " prefix_cases=" << cases << " late_errors_older_faults_alu_forwarding_serial_hold_store_ledger=PASS\n";
        return 0;
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
