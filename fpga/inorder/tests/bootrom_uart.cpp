// Real CPU BootROM execution and an independent, bit-level UART receiver.
// GSIM's single-clock model is intentional: physical UART50 CDC is separately audited.
#define FIVE_STAGE_SOC_MEMORY_ONLY
#define I1_HAS_ROM 1
#include "five_stage_soc.cpp"
#include "five_stage_rom_host.h"

struct BootUartReceiver {
    bool previous = true, busy = false;
    double sample = 0;
    unsigned bit = 0, value = 0;
    std::string text;
    void tick(uint64_t cycle, bool line) {
        constexpr double period = 300000000.0 / 460800.0;
        if (!busy && previous && !line) {
            busy = true; sample = cycle + period * 0.5; bit = 0; value = 0;
        }
        if (busy && double(cycle) >= sample) {
            if (bit == 0) need(!line, "UART start-bit mismatch");
            else if (bit <= 8) value |= unsigned(line) << (bit - 1);
            else {
                need(line, "UART stop-bit mismatch");
                text += char(value); busy = false;
            }
            ++bit; sample += period;
        }
        previous = line;
    }
};

int main(int argc, char **argv) { try {
    need(argc == 2 || argc == 3, "ROM hex and optional --wrong-banner required");
    const bool wrong = argc == 3 && std::string(argv[2]) == "--wrong-banner";
    std::ifstream rom(argv[1]); need(bool(rom), "ROM missing");
    std::vector<uint8_t> bytes;
    uint64_t word;
    while (rom >> std::hex >> word)
        for (unsigned n = 0; n < 8; ++n) bytes.push_back(word >> (8 * n));
    need(bytes.size() == 4096, "ROM geometry mismatch");
    SFiveStageSoc d; AxiMemory memory(d, {}, false, false);
    d.set_reset(1); d.set_io$$uartRx(1); d.set_io$$externalIrq(0);
    d.set_io$$clockLocked(0); d.set_io$$ddrReady(0); d.set_io$$jtagLinkUp(0);
    d.set_io$$jtagDmi$$request$$valid(0); d.set_io$$jtagDmi$$response$$ready(1);
    d.set_io$$networkMemory$$request$$valid(0); d.set_io$$networkMemory$$response$$ready(1);
    i1InitializeRom(d, memory, argv[1]);
    for (unsigned n = 0; n < 16; ++n) { memory.inputs(0); d.step(); }
    d.set_reset(0);
    BootUartReceiver uart;
    const std::string expected = wrong ? "Xalence Orbital-I1 BootROM V0.1\r\n" :
        "Valence Orbital-I1 BootROM V0.1\r\n";
    uint64_t retired = 0, firstPc = 0, lastPc = 0, completed = 0;
    for (uint64_t cycle = 0; cycle < 350000; ++cycle) {
        if (cycle == 17) d.set_io$$clockLocked(1);
        if (cycle == 1000) d.set_io$$ddrReady(1);
        memory.inputs(cycle); d.step(); memory.outputs(cycle);
        need(!d.get_io$$resetFault(), "unexpected reset fault");
        need(!d.get_io$$trapTaken(), "BootROM execution trap");
        uart.tick(cycle, d.get_io$$uartTx());
        if (cycle < 17) need(!d.get_io$$retire$$valid(), "CPU escaped unlocked reset");
        if (d.get_io$$retire$$valid()) {
            lastPc = d.get_io$$retire$$bits$$pc();
            if (!retired++) firstPc = lastPc;
            need(lastPc >= 0x10000 && lastPc + 4 <= 0x11000, "execution escaped BootROM without JTAG commit");
            uint32_t instruction = 0;
            for (unsigned n = 0; n < 4; ++n) instruction |= uint32_t(bytes[lastPc - 0x10000 + n]) << (8*n);
            need(d.get_io$$retire$$bits$$instruction() == instruction, "independent retired ROM bytes mismatch");
            need(!d.get_io$$retire$$bits$$trap(), "retired BootROM trap");
        }
        need(memory.readCount == 0 && memory.writeCount == 0, "DDR accessed before verified JTAG handoff");
        need(uart.text.size() <= expected.size() &&
            uart.text == expected.substr(0, uart.text.size()), "independent UART banner mismatch");
        if (uart.text == expected && !completed) completed = cycle;
        if (completed && cycle >= completed + 2000) {
            need(firstPc == 0x10000 && retired > 100, "reset-vector/retirement coverage missing");
            need(!d.get_io$$resetHeld(), "startup reset did not release");
            std::cout << uart.text << "I1_BOOTROM_UART_PASS cycles=" << cycle << " retired=" << retired
                << " UART_bytes=" << uart.text.size() << " baud=460800 model_clock=300000000"
                << " JTAG_wait_no_DDR=PASS PC=0x" << std::hex << lastPc << std::dec << '\n';
            return 0;
        }
    }
    std::cerr << "BOOT_STALL retired=" << retired << " pc=0x" << std::hex << lastPc << std::dec
        << " uart_bytes=" << uart.text.size() << '\n';
    throw std::runtime_error("bounded BootROM UART startup failed");
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
