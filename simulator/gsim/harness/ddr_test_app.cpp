// Reuse the independent serial-pin and sparse AXI model, not the long boot regression.
#define main board_boot_regression_main
#include "board_boot.cpp"
#undef main

int main(int argc, char **argv) {
    try {
        check(argc == 3, "usage: run bootrom.bin ddr_test.bin");
        Test test(readFile(argv[1]));
        test.expect("Valence Bootrom V0.1\r\n");
        test.downloadMode();
        test.download(readFile(argv[2]));
        test.send('g');
        test.expect("Valence DDR test V0.1");
        test.expect("DDR SMOKE PASS errors=0");
        test.expect("[x] return to Bootrom\r\n");
        // Check actual backing memory, not just CPU cache-visible reads.
        for (uint32_t base : {0x80400000U, 0x90000000U, 0xa01f7f00U}) {
            for (uint32_t offset = 0; offset < 256; offset += 8) {
                uint32_t address = base + offset;
                uint64_t expected = ~((uint64_t(address) << 32) | uint32_t(~address));
                auto found = test.ddr.memory.find(address - ramBase);
                check(found != test.ddr.memory.end() && found->second == expected,
                      "DDR test writes did not reach backing AXI memory");
            }
        }
        test.send('x');
        test.expect("APP RETURN\r\n");
        test.ready();
        std::cout << "GSIM DDR test application: PASS cycles=" << test.cycles
                  << " readBursts=" << test.ddr.readBursts
                  << " writeBursts=" << test.ddr.writeBursts << "\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "GSIM DDR test application: FAIL " << error.what() << "\n";
        return 1;
    }
}
