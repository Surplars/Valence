#define FIVE_STAGE_SOC_MEMORY_ONLY
#include "five_stage_soc.cpp"
#include "five_stage_rom_host.h"
#include "five_stage_coherent_readback.h"

int main(int argc, char **argv) { try {
    need(argc >= 3, "FP SoC binary and expected case count required");
    const unsigned expected = std::stoul(argv[2]);
    bool jtag = false, retry = false, mutate = false, faults = false;
    for (int n = 3; n < argc; ++n) {
        const std::string option = argv[n];
        if (option == "--jtag") jtag = true;
        else if (option == "--retry") { jtag = true; retry = true; }
        else if (option == "--wrong-result") mutate = true;
        else if (option == "--faults") faults = true;
        else throw std::runtime_error("unknown FP SoC option");
    }
    std::ifstream file(argv[1], std::ios::binary); need(bool(file), "missing FP CPU image");
    std::vector<uint8_t> image((std::istreambuf_iterator<char>(file)), {});
    SFiveStageSoc d; AxiMemory memory(d, jtag ? std::vector<uint8_t>{} : image, false, faults);
    I1JtagHost host(d, image, false, retry);
    d.set_reset(1); d.set_io$$uartRx(1); d.set_io$$externalIrq(0);
    d.set_io$$clockLocked(1); d.set_io$$ddrReady(1); d.set_io$$jtagLinkUp(jtag);
    d.set_io$$jtagDmi$$request$$valid(0); d.set_io$$jtagDmi$$response$$ready(0);
    i1CoherentHostIdle(d);
    i1InitializeRom(d, memory, "src/main/resources/inorder/bootrom.hex");
    memory.inputs(0); d.step(); d.step(); d.set_reset(0);
    uint64_t retired = 0, fpWrites = 0, flags = 0, traps = 0, lastPc = 0, lastA0 = 0;
    for (uint64_t cycle = 0; cycle < 12000000; ++cycle) {
        memory.inputs(cycle);
        if (jtag) host.inputs();
        d.step(); memory.outputs(cycle);
        if (jtag) host.outputs();
        if (d.get_io$$trapTaken()) ++traps;
        if (!d.get_io$$retire$$valid()) continue;
        ++retired; lastPc = d.get_io$$retire$$bits$$pc();
        bool fault = d.get_io$$retire$$bits$$trap();
        bool fpWrite = d.get_io$$retire$$bits$$floating$$write();
        need(!fpWrite || !fault, "faulted floating instruction wrote architectural FP state");
        fpWrites += fpWrite;
        flags |= d.get_io$$retire$$bits$$floating$$flags();
        if (d.get_io$$retire$$bits$$writesRd() && d.get_io$$retire$$bits$$rd() == 10)
            lastA0 = d.get_io$$retire$$bits$$data();
        if (fault && d.get_io$$retire$$bits$$cause() == 3) {
            need(lastA0 == 0, "actual FP CPU guest fail path");
#ifdef I1_COHERENT_READBACK
            // The guest parks after this completion trap. No forced flush or
            // reset: a real coherent DMA request must obtain dirty ledger data.
            uint64_t drainCycle = cycle + 1;
            coherentRead(d, memory, drainCycle, 0x800000);
#endif
            need(memory.load(0x800000) == 0x46504450415353ULL &&
                memory.load(0x800008) == (mutate ? expected + 1 : expected),
                "independent FP actual CPU result/flags/context ledger oracle");
            need(fpWrites > 20, "floating architectural write coverage missing");
            if (jtag) {
                need(host.done && host.acceptedRequests > 20 && (!retry || host.rejected),
                    "logical JTAG did not finish download/claim/CRC retry");
                for (size_t n = 0; n < image.size(); ++n)
                    need(memory.bytes[n] == image[n], "JTAG download changed executable bytes");
            }
            std::cout << "I1_FP_CPU_PASS cases=" << expected << " cycles=" << cycle << " retired=" << retired
                << " fp_writes=" << fpWrites << " flags_seen=" << flags << " traps=" << traps
                << " jtag=" << jtag << " retry=" << retry << " numerical_CSR_memory_precise_commit=PASS\n";
            return 0;
        }
        if (memory.load(0x800000) == 0xbad) {
            std::cerr << "FP_GUEST_FAIL case=" << memory.load(0x800008) << " pc=0x" << std::hex << lastPc
                << std::dec << " retired=" << retired << " traps=" << traps << '\n';
            throw std::runtime_error("actual FP CPU guest fail path");
        }
    }
    std::cerr << "FP_CPU_STALL pc=0x" << std::hex << lastPc << std::dec << " retired=" << retired << '\n';
    throw std::runtime_error("FP CPU bounded completion failed");
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
