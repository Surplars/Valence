#define FIVE_STAGE_SOC_MEMORY_ONLY
#include "five_stage_soc.cpp"
#include "five_stage_rom_host.h"
#include "five_stage_coherent_readback.h"

int main(int argc, char **argv) { try {
    need(argc >= 2, "privilege SoC binary required");
    std::ifstream file(argv[1], std::ios::binary); need(bool(file), "missing privilege SoC binary");
    std::vector<uint8_t> image((std::istreambuf_iterator<char>(file)), {});
    bool mutate = argc > 2 && std::string(argv[2]) == "--wrong-result";
    bool throughput = argc > 2 && (std::string(argv[2]) == "--bare-throughput" ||
                                  std::string(argv[2]) == "--sv39-throughput");
    bool paging = argc > 2 && std::string(argv[2]) == "--sv39-throughput";
    bool largeStream = false, wrongStream = false;
    unsigned memoryLatency = 3;
    for (int i = 3; i < argc; ++i) {
        largeStream |= std::string(argv[i]) == "--large-stream";
        wrongStream |= std::string(argv[i]) == "--wrong-stream";
        const std::string argument(argv[i]), prefix("--memory-latency=");
        if (argument.starts_with(prefix)) memoryLatency = std::stoul(argument.substr(prefix.size()));
    }
    need(memoryLatency >= 3 && memoryLatency <= 128, "bounded matched AXI latency required");
    const unsigned streamWords = largeStream ? 8192 : 1024;
    const uint64_t streamDestination = largeStream ? 0x80000 : 0x34000;
    SFiveStageSoc d; AxiMemory memory(d, image, false);
    memory.readLatency = memoryLatency; memory.writeLatency = memoryLatency - 1;
    if (throughput) memory.bytes[0xf000] = paging;
    d.set_reset(1); d.set_io$$uartRx(1); d.set_io$$externalIrq(0);
    d.set_io$$clockLocked(1); d.set_io$$ddrReady(1); d.set_io$$jtagLinkUp(0);
    d.set_io$$jtagDmi$$request$$valid(0); d.set_io$$jtagDmi$$response$$ready(0);
    i1CoherentHostIdle(d);
    i1InitializeRom(d,memory,"src/main/resources/inorder/bootrom.hex");
    memory.inputs(0); d.step(); d.step(); d.set_reset(0);
    uint64_t retired = 0, lastA0 = 0, traps = 0, lastPc = 0;
    for (uint64_t cycle = 0; cycle < 1500000ULL + uint64_t(memoryLatency - 3) * 16000; ++cycle) {
        memory.inputs(cycle); d.step(); memory.outputs(cycle);
        if (d.get_io$$trapTaken()) ++traps;
        if (!d.get_io$$retire$$valid()) continue;
        ++retired; uint64_t pc = d.get_io$$retire$$bits$$pc(); lastPc = pc;
        if(pc>=0x10000 && pc<0x11000) {
            need(!d.get_io$$retire$$bits$$trap(),"privilege BootROM fault"); continue;
        }
        if (d.get_io$$retire$$bits$$writesRd() && d.get_io$$retire$$bits$$rd() == 10)
            lastA0 = d.get_io$$retire$$bits$$data();
        if (d.get_io$$retire$$bits$$trap()) {
            auto cause = d.get_io$$retire$$bits$$cause();
            if (cause == 3) {
                need(lastA0 == 0, "privileged SoC guest fail path");
                if (throughput) {
                    const auto guestReads = memory.readCount, guestWrites = memory.writeCount;
                    const auto readBeats = memory.readBeats, writeBeats = memory.writtenBeats;
                    const auto overlapCycles = memory.overlapOwnerCycles;
                    const auto readWithWritePending = memory.readWithWritePending;
#ifdef I1_COHERENT_READBACK
                    uint64_t drainCycle = cycle + 1;
                    // One word/line revokes the complete 64-byte line. The
                    // original full-buffer backing byte checks remain below.
                    for (unsigned i = 0; i < streamWords; i += 8) {
                        const uint64_t value = 0x123400000000ULL + i;
                        need(coherentRead(d, memory, drainCycle, 0x30000 + i * 8) == value &&
                             coherentRead(d, memory, drainCycle, streamDestination + i * 8) == value,
                             "independent coherent DMA streaming oracle");
                    }
                    coherentRead(d, memory, drainCycle, 0x10000);
#endif
                    uint64_t sum = 0;
                    for (unsigned i = 0; i < streamWords; ++i) {
                        uint64_t expected = 0x123400000000ULL + i; sum += expected;
                        need(memory.load(0x30000 + i * 8) == expected &&
                            memory.load(streamDestination + i * 8) == expected, "independent S-mode streaming byte oracle");
                    }
                    need(memory.load(0x10018) == (wrongStream ? sum ^ 1 : sum),
                         "independent streaming READ checksum");
                    std::cout << "I1_PRIVILEGED_STREAM_PASS {\"mode\":\"" << (paging ? "Sv39" : "Bare")
                        << "\",\"bytes\":" << streamWords * 8 << ",\"read_ticks\":" << memory.load(0x10000)
                        << ",\"write_ticks\":" << memory.load(0x10008)
                        << ",\"copy_ticks\":" << memory.load(0x10010)
                        << ",\"cycles\":" << cycle << ",\"retired\":" << retired
                        << ",\"axi_reads\":" << guestReads << ",\"axi_writes\":" << guestWrites
                        << ",\"axi_read_beats\":" << readBeats << ",\"axi_write_beats\":" << writeBeats
                        << ",\"axi_overlap_owner_cycles\":" << overlapCycles
                        << ",\"axi_reads_while_write_pending\":" << readWithWritePending
                        << ",\"axi_read_latency_floor\":" << memoryLatency
                        << ",\"axi_write_latency_floor\":" << memoryLatency - 1
                        << ",\"formal_benchmark\":false}\n";
                    return 0;
                }
                const std::map<unsigned, uint64_t> expected{{2,4}, {5,1}, {8,1}, {12,1}, {13,4}, {15,2},
                    {21,1}, {25,1}, {30,2}, {31, mutate ? 0x564c101ULL : 0x564c100ULL}};
#ifdef I1_COHERENT_READBACK
                uint64_t drainCycle = cycle + 1;
                for (unsigned i = 0; i < 256; i += 64) coherentRead(d, memory, drainCycle, 0x10000 + i);
                coherentRead(d, memory, drainCycle, 0x33000);
                coherentRead(d, memory, drainCycle, 0x30000);
#endif
                for (auto [index, value] : expected) {
                    if (memory.load(0x10000 + index * 8) != value) {
                        std::cerr << "bad ledger index=" << index << " got=" << memory.load(0x10000 + index * 8)
                            << " expected=" << value << '\n';
                        throw std::runtime_error("independent privileged SoC result ledger oracle");
                    }
                }
                need(memory.load(0x33008) == 0xabc, "U-mode virtual store did not reach remapped physical page");
                need(memory.load(0x30000) == 0x112233, "old data mapping changed after SFENCE");
                need(memory.load(0x33000) == 0xbeef, "faulting A/D access changed payload");
                for (unsigned i = 0; i < image.size() - 0x2000; ++i)
                    need(memory.bytes[0x2000 + i] == image[0x2000 + i], "denied virtual store changed U code");
                need(memory.bytes.find(0x40000) == memory.bytes.end(), "PMP denied demand reached AXI");
                std::cout << "FIVE_STAGE_PRIVILEGED_SOC_PASS cycles=" << cycle << " retired=" << retired
                    << " traps=" << traps << " axi_reads=" << memory.readCount << " axi_writes=" << memory.writeCount
                    << " actual_CPU_M_S_U_Sv39_4K_1G_Svade_MPRV_SUM_MXR_SFENCE_PLIC_S_UART_SBI_timer=PASS\n";
                return 0;
            }
        } else {
            uint64_t physicalPc = pc >= 0x40000000 && pc < 0x40001000 ? 0x80202000 + pc - 0x40000000 : pc;
            need(physicalPc >= 0x80200000 && physicalPc + 4 <= 0x80200000 + image.size(),
                "privileged CPU retired outside physical/virtual text");
            auto word = memory.load((physicalPc - 0x80200000) & ~7ULL);
            uint32_t ins = word >> ((physicalPc & 7) * 8);
            need(ins == d.get_io$$retire$$bits$$instruction(), "physical/virtual retired instruction byte oracle");
        }
    }
    std::cerr << "PRIV_SOC_STALL retired=" << retired << " traps=" << traps << " last_pc=0x"
        << std::hex << lastPc << std::dec << " reads=" << memory.readCount << " writes=" << memory.writeCount << '\n';
    throw std::runtime_error("privileged SoC bounded completion failed");
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
