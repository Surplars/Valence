// Same exact downloadable image, independent AXI backing/latency/backpressure.
// Short CRC/tick comparison only: duration is intentionally <10 seconds, NOT a score.
#define main board_boot_regression_main
#include "board_boot.cpp"
#undef main

int main(int argc, char **argv) {
    try {
        check(argc == 2, "usage: run coremark_board.bin");
        const auto image = readFile(argv[1]);
        check(!image.empty() && image.size() < 992 * 1024, "CoreMark image bounds");
        Bytes rom;
        word(rom, 0x00200297); // auipc t0,0x200 -> entry 0x80200000
        word(rom, 0x10000337); // lui t1,0x10000 -> UART
        word(rom, 0x00700393); // addi t2,zero,7
        word(rom, 0x00730123); // sb t2,2(t1) -> FCR=7
        word(rom, 0x000280e7); // jalr ra,0(t0)
        Bytes returned = instructionFixture('R');
        returned.resize(returned.size() - 4);
        word(returned, 0x0000006f);
        rom.insert(rom.end(), returned.begin(), returned.end());
        Test test(rom);
        for (size_t offset = 0; offset < image.size(); offset += 8) {
            uint64_t value = 0;
            for (unsigned lane = 0; lane < 8 && offset + lane < image.size(); ++lane)
                value |= uint64_t(image[offset + lane]) << (8 * lane);
            test.ddr.memory[uint32_t(offset)] = value;
        }
        test.expect("VALENCE CoreMark 2K started");
        const size_t tickBegin = test.expect("Total ticks      : ");
        test.expect("\r\n");
        const auto ticks = std::stoull(std::string(
            test.received.begin() + tickBegin + std::string("Total ticks      : ").size(),
            test.received.begin() + test.consumed));
        check(ticks > 0 && ticks < 10ULL * BOARD_CPU_HZ, "short regression duration");
        test.expect("Iterations       : 1\r\n");
        test.expect("seedcrc          : 0xe9f5\r\n");
        // Fixed reference CRCs from the pinned unmodified EEMBC source, not DUT output.
        test.expect("[0]crclist       : 0xe714\r\n");
        test.expect("[0]crcmatrix     : 0x1fd7\r\n");
        test.expect("[0]crcstate      : 0x8e3a\r\n");
        test.expect("Errors detected\r\n"); // sole expected error is the <10 second run
        test.expect("FENCE R\r\n");
        const std::string output(test.received.begin(), test.received.end());
        const std::string durationError =
            "ERROR! Must execute for at least 10 secs for a valid result!";
        const size_t error = output.find("ERROR!");
        check(error != std::string::npos &&
              output.compare(error, durationError.size(), durationError) == 0 &&
              output.find("ERROR!", error + durationError.size()) == std::string::npos,
              "unexpected CoreMark validation error");
        check(output.find("Cannot validate") == std::string::npos, "unknown CoreMark seed");
        check(test.ddr.readBursts && test.ddr.writeBursts && test.ddr.stalls,
              "no DDR bursts/backpressure exercised");
        std::cout << output;
        std::cout << "GSIM compact board CoreMark: PASS ticks=" << ticks
                  << " imageBytes=" << image.size() << " cyclesWithUart=" << test.cycles
                  << " readBursts=" << test.ddr.readBursts
                  << " writeBursts=" << test.ddr.writeBursts << "\n";
        std::cout << "One iteration CRC/tick regression; NOT a valid CoreMark score or FPGA measurement.\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "GSIM compact board CoreMark: FAIL " << error.what() << "\n";
        return 1;
    }
}
