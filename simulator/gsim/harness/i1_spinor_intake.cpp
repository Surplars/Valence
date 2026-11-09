// Reuse the pinned Spinor independent host/memory oracle without editing it.
// Add Valence-toolchain vector arithmetic and active oracle negative controls.
#define main spinor_upstream_main
#include "m61_isolated_driver.cc"
#undef main

int main(int argc, char **argv) {
    try {
        Driver driver;
        const std::string mode = argc == 2 ? argv[1] : "";
        driver.reset();
        if (mode == "--wrong-grant") {
            driver.negative = "wrong-grant";
            driver.directed();
        } else if (mode == "--wrong-rf" || mode == "--wrong-csr") {
            driver.negative = mode.substr(2);
            for (unsigned word = 0; word < 64; ++word) driver.context(word, true, 0);
            const std::array<uint64_t, 64> zero{};
            driver.command("0 f1d7 0 0 4 0 0 0 1 4 4 0 0 0 0 0 0", zero);
        } else {
            driver.directed();
            driver.config(32, 4);
            driver.context(4, true, 0x0000000200000001ULL);
            driver.context(5, true, 0x0000000400000003ULL);
            const auto result = driver.operation(0x0221b0d7); // vadd.vi v1,v2,3
            driver.check(!result[4] && !result[8], "vadd.vi rejected");
            driver.check(driver.context(2, false, 0) == 0x0000000500000004ULL &&
                driver.context(3, false, 0) == 0x0000000700000006ULL,
                "independent vector add values");
            std::cout << "I1_SPINOR_NATIVE_INTAKE_PASS full_80bit_token=1 preview_grant_done=1 "
                << "context_backpressure=1 load_store_stop_prefix_retry=1 denied=1 host_fcsr=1 vector_add=1"
                << " cycles=" << driver.cycles << " commands=" << driver.commands << '\n';
        }
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
