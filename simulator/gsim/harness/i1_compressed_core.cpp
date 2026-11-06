// Reuse the independent ISA, memory, IRQ and store ledgers; C expectations come
// from the separately exhaustively checked software halfword decoder.
#define main i1_integer_core_main
#include "five_stage.cpp"
#undef main

static_assert(DUT_HAS_C && DUT_XLEN == 64, "this gate requires the RV64 C bare core");

static std::vector<uint32_t> packed(std::initializer_list<std::pair<uint32_t, unsigned>> instructions) {
    std::vector<uint8_t> bytes;
    for (auto [value, size] : instructions)
        for (unsigned j=0; j<size; ++j) bytes.push_back(value >> (8*j));
    bytes.resize((bytes.size()+3) & ~size_t(3));
    std::vector<uint32_t> words(bytes.size()/4);
    std::memcpy(words.data(), bytes.data(), bytes.size());
    return words;
}

int main(int argc, char **argv) { try {
    const bool injectC = argc == 2 && std::string(argv[1]) == "--inject-compressed-result";
    if (!injectC) {
        const int result = i1_integer_core_main(argc, argv);
        if (result) return result;
    }
    // LI/ADDI/ADD/MV/J/EBREAK halfwords mix with memory and FENCE.I words.
    // C.J skips both a write and a trap; later instructions begin at pc[1]=1.
    const auto program = packed({
        {0x00002a17,4}, {0x409d,2}, {0x0085,2}, {0x410d,2}, {0x908a,2},
        {st(0,20,1,0),4}, {ri(0x03,3,0,20,0),4}, {0x820e,2}, {0x127d,2}, {0x0000100f,4},
        {0xa019,2}, {0x0f85,2}, {0x9002,2}, {0x0205,2}, {ri(0x13,31,0,0,77),4}, {0x9002,2}
    });
    for (unsigned latency : {1U,7U,12U}) {
        const auto result = execute("mixed-c-no-predictor-"+std::to_string(latency), program,
            latency, {}, {}, false, injectC);
        need(result.compressedRetires == 9, "C program did not retire all expected halfwords");
        std::cout << "I1_COMPRESSED_CORE_CASE_PASS latency=" << latency << " cycles=" << result.cycles
            << " compressed_retired=" << result.compressedRetires << '\n';
    }
    execute("c-fetch-error", program, 8, BASE+6);
    execute("c-store-error", program, 7, {}, DATA);
    execute("c-illegal", packed({{0x00002a17,4}, {0x0000,2}}), 7);
    // Interrupt the real busy divider, then return to a halfword-aligned PC.
    // The handler reads and writes MEPC, proving that C preserves its bit 1.
    const auto irq = packed({
        {0x00002a17,4}, {ri(0x13,1,0,0,8),4}, {ri(0x73,0,1,1,0x300),4},
        {ri(0x13,1,0,0,-2048),4}, {ri(0x73,0,1,1,0x304),4}, {0x0001,2},
        {ri(0x03,2,3,20,512),4}, {rr(0x33,3,4,2,1,1),4}, {0x0001,2},
        {ri(0x13,31,0,0,77),4}, {0x9002,2}
    });
    execute("mixed-c-interrupt-return", irq, 7, {}, {}, true, false, true);
    std::cout << "I1_COMPRESSED_CORE_PASS independent_ISA_raw_C_IRQ_MRET_backpressure_faults_fence=PASS\n";
    return 0;
} catch (const std::exception &error) { std::cerr << error.what() << '\n'; return 1; } }
