#define FIVE_STAGE_BASE 0x80200000ULL
#define FIVE_STAGE_SOC_MEMORY_ONLY
#include "five_stage_soc.cpp"
#include "five_stage_coherent_readback.h"

int main(int argc, char **argv) { try {
    const bool smoke = argc == 3 && std::string(argv[2]) == "--smoke";
    need(smoke || argc == 7 || argc == 8, "CoreMark SoC image/errors/crcs/phase/validated/duration symbols required");
    std::ifstream file(argv[1], std::ios::binary);
    need(bool(file), "missing SoC CoreMark image");
    std::vector<uint8_t> image((std::istreambuf_iterator<char>(file)), {});
    need(image.size() < 65536, "CoreMark code exceeds fixed64KiB linker region");
    const uint64_t errors = smoke ? 0 : std::stoull(argv[2], nullptr, 0);
    const uint64_t crcs = smoke ? 0 : std::stoull(argv[3], nullptr, 0);
    const uint64_t phase = smoke ? UINT64_MAX : std::stoull(argv[4], nullptr, 0);
    const uint64_t validated = smoke ? 0 : std::stoull(argv[5], nullptr, 0);
    const uint64_t duration = smoke ? 0 : std::stoull(argv[6], nullptr, 0);
    const bool mutate = argc == 8 && std::string(argv[7]) == "--inject";
    SFiveStageSoc d; AxiMemory memory(d, image, false, false);
    image.resize(0x12000); Oracle oracle(image);
    d.set_reset(1); d.set_io$$uartRx(1); d.set_io$$externalIrq(0);
    d.set_io$$clockLocked(1); d.set_io$$ddrReady(1); d.set_io$$jtagLinkUp(0);
    d.set_io$$jtagDmi$$request$$valid(0); d.set_io$$jtagDmi$$response$$ready(0);
    i1CoherentHostIdle(d); memory.inputs(0); d.step(); d.step(); d.set_reset(0);
    uint64_t retired = 0, roiStartCycle = 0, roiEndCycle = 0, roiStartRetired = 0, roiInstructions = 0;
    uint64_t trace = 1469598103934665603ULL, cycle = 0;
    bool finished = false, started = false, ended = false;
    for (; cycle < 8000000 && !finished; ++cycle) {
        memory.inputs(cycle); d.step(); memory.outputs(cycle);
        if (!d.get_io$$retire$$valid()) continue;
        const uint64_t pc = d.get_io$$retire$$bits$$pc();
        const uint32_t ins = d.get_io$$retire$$bits$$instruction();
        need(pc == oracle.pc && ins == oracle.load(pc, 4), "CoreMark independent retired PC/instruction mismatch");
        if ((ins & 127) == 0x23) {
            const unsigned rs1 = ins >> 15 & 31, rs2 = ins >> 20 & 31;
            const uint64_t imm = signExtend(((ins >> 25) << 5) | (ins >> 7 & 31), 12);
            if (oracle.r[rs1] + imm == phase) {
                if (oracle.r[rs2] == 1) {
                    need(!started && !ended, "duplicate CoreMark ROI start");
                    started = true; roiStartCycle = cycle; roiStartRetired = retired;
                } else if (oracle.r[rs2] == 2) {
                    need(started && !ended, "CoreMark ROI end without start");
                    ended = true; roiEndCycle = cycle; roiInstructions = retired - roiStartRetired;
                }
            }
        }
        auto expected = oracle.evaluate(ins, false, false);
        if (mutate && retired == 2) expected.value ^= 1;
        const bool trap = d.get_io$$retire$$bits$$trap();
        need(trap == expected.trap && (!trap || d.get_io$$retire$$bits$$cause() == expected.cause),
             "CoreMark independent exception mismatch");
        if (trap) {
            need(ins == 0x00100073 && expected.cause == 3 && oracle.r[10] == 0,
                 "CoreMark guest validation failed");
            finished = true; break;
        }
        need(bool(d.get_io$$retire$$bits$$writesRd() && d.get_io$$retire$$bits$$rd() != 0) == expected.write,
             "CoreMark independent write-enable mismatch");
        if (expected.write)
            need(d.get_io$$retire$$bits$$rd() == expected.rd && d.get_io$$retire$$bits$$data() == expected.value,
                 "CoreMark independent register oracle mismatch");
        need(d.get_io$$retire$$bits$$nextPc() == expected.next, "CoreMark independent next-PC mismatch");
        trace ^= pc; trace *= 1099511628211ULL; trace ^= ins; trace *= 1099511628211ULL;
        oracle.commit(expected); ++retired;
    }
    need(finished && (smoke || (started && ended && roiEndCycle > roiStartCycle && roiInstructions > 10000)),
         "CoreMark bounded ROI/completion missing");
    const auto reads = memory.readCount, writes = memory.writeCount;
    uint64_t drainCycle = cycle + 1;
    for (unsigned offset = smoke ? 0 : 0x10000; offset < 0x12000; offset += 64)
        coherentRead(d, memory, drainCycle, offset);
    for (unsigned offset = smoke ? 0 : 0x10000; offset < 0x12000; ++offset)
        need(memory.bytes[offset] == oracle.memory[offset], "CoreMark final coherent RAM/ISA oracle mismatch");
    if (smoke) {
        need(memory.bytes.find(0x12000) == memory.bytes.end(), "wrong-path store reached physical memory");
        std::cout << "I1_FETCH_CONTROL_CPU_PASS cycles=" << cycle << " retired=" << retired
            << " actual_CPU_self_modify_FENCEI_branch_JALR_wrongpath_full_byte_oracle=PASS\n";
        return 0;
    }
    auto u32 = [&](uint64_t a) { return uint32_t(memory.load(a - BASE)); };
    // The real official program MUST reject a <10-second formal score. Never
    // falsify time_in_secs to obtain its validation banner. This is an
    // independently checked CRC/retirement short test, not a reportable score.
    need(u32(errors) == 0 && u32(validated) == 0 && u32(duration) == 1 && u32(phase) == 2,
         "CoreMark short-run duration/result ledger mismatch");
    const std::array<uint32_t, 4> known{0xe9f5, 0xe714, 0x1fd7, 0x8e3a};
    for (unsigned n = 0; n < known.size(); ++n)
        need(u32(crcs + n * 4) == known[n], "CoreMark independent standard2000 CRC mismatch");
    std::cout << "I1_SOC_COREMARK_PASS {\"cycles\":" << cycle << ",\"roi_ticks\":"
        << roiEndCycle - roiStartCycle << ",\"roi_instructions\":" << roiInstructions
        << ",\"retired\":" << retired << ",\"trace_fnv64\":\"" << std::hex << trace << std::dec
        << "\",\"crcfinal\":" << u32(crcs + 16) << ",\"axi_reads\":" << reads
        << ",\"axi_writes\":" << writes
        << ",\"official_duration_warning\":true,\"independent_crc_validated\":true,\"formal_score\":false}\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
