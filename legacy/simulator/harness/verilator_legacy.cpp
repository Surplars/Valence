#include <cstdio>
#include <cstring>
#include <sys/stat.h>
#include <filesystem>
#include <elf.h>
#include <verilated.h>
#include <verilated_vcd_c.h>
#include "VSoc.h"
#include "VSoc___024root.h"

#include <queue>
#include <unistd.h>
#include <fcntl.h>
#include <termios.h>
#include <signal.h>

#define RED "\033[31m"
#define GREEN "\033[32m"
#define YELLOW "\033[33m"
#define CEND "\033[0m"

#define BROM_BASE 0x00000000
#define ROM_SIZE 0x1000
// #define SRAM_BASE 0x20000000
#define SRAM_BASE 0x1000
#define SRAM_SIZE 0x4000

#define MAX_SIM_CYCLES 10000
vluint64_t sim_time = 0;
static struct termios orig_termios;

static volatile sig_atomic_t esc_requested = 0;

void load_elf(VSoc *dut, const char *path);
void ram_init(VSoc *dut);

// run_one_test now reuses a provided dut & tracer and returns (doesn't delete dut)
// if esc_requested is set, the function will abort the simulation loop and return false.
bool run_one_test(VSoc *dut, VerilatedVcdC *tfp,
                  const std::string &bin_path,
                  const std::string &test_name,
                  bool trace_en,
                  bool &trace_opened);

// helper to make stdin non-blocking (sets O_NONBLOCK)
static void configure_stdin_nonblocking() {
    int flags = fcntl(STDIN_FILENO, F_GETFL, 0);
    if (flags == -1) flags = 0;
    fcntl(STDIN_FILENO, F_SETFL, flags | O_NONBLOCK);
}

// set terminal to raw-ish (non-canonical, no-echo), save orig state in orig_termios
void uart_terminal_init()
{
    if (tcgetattr(STDIN_FILENO, &orig_termios) != 0) {
        perror("tcgetattr");
    } else {
        struct termios raw = orig_termios;
        raw.c_lflag &= ~(ICANON | ECHO);
        raw.c_cc[VMIN]  = 0;
        raw.c_cc[VTIME] = 0;

        if (tcsetattr(STDIN_FILENO, TCSANOW, &raw) != 0) {
            perror("tcsetattr");
        }
    }

    configure_stdin_nonblocking();
}

// restore terminal attributes saved in orig_termios
void uart_terminal_restore()
{
    if (tcsetattr(STDIN_FILENO, TCSANOW, &orig_termios) != 0) {
        // often when terminal already restored by user, this might fail; still try
        // but do not abort
        // perror("tcsetattr restore");
    }
}

// signal handler: restore terminal then exit cleanly
static void handle_exit_signal(int signo)
{
    // mark esc_requested so any ongoing run_one_test can observe
    esc_requested = 1;
    // restore terminal immediately
    uart_terminal_restore();
    // exit with signal code
    _exit(128 + signo);
}

int main(int argc, char **argv, char **env)
{
    printf("\n");

    // register atexit to restore terminal on normal exit
    // but call uart_terminal_init first to ensure orig_termios is valid
    // prepare test list like you had
    std::vector<std::string> tests;
    bool testAll = false;

    if (argc < 2)
    {
        tests.push_back("simulator/build/payload/payload.elf");
    }
    else
    {
        for (int i = 1; i < argc; ++i)
        {
            if (std::string(argv[i]) == "all")
            {
                testAll = true;
                break;
            }
            tests.emplace_back(argv[i]);
        }

        const std::string base_dir = "simulator/generated/";

        if (testAll)
        {
            tests.clear();
            for (auto &p : std::filesystem::directory_iterator(base_dir))
            {
                if (p.path().extension() == "")
                {
                    std::string bin = p.path().string();
                    tests.push_back(bin);
                }
            }
        } else {
            // translate user supplied short names to actual file paths like earlier behavior
            std::vector<std::string> resolved;
            for (auto &t : tests) {
                std::string bin_ui = base_dir + "rv32ui-p-" + t;
                std::string bin_um = base_dir + "rv32um-p-" + t;
                if (std::filesystem::exists(bin_ui)) resolved.push_back(bin_ui);
                else if (std::filesystem::exists(bin_um)) resolved.push_back(bin_um);
                else {
                    printf("Test binary for %s not found.\n", t.c_str());
                }
            }
            tests.swap(resolved);
        }
    }

    // init terminal and ensure restore on exit
    uart_terminal_init();
    if (atexit(uart_terminal_restore) != 0) {
        fprintf(stderr, "Warning: atexit registration failed\n");
    }

    // install signal handlers to restore terminal on SIGINT / SIGTERM
    signal(SIGINT, handle_exit_signal);
    signal(SIGTERM, handle_exit_signal);

    // Create DUT and trace once (will be reused across tests)
    VSoc *dut = new VSoc;
    VerilatedVcdC *tfp = new VerilatedVcdC;
    bool trace_opened = false;

    // We will call run_one_test repeatedly, which will re-init RAM, load ELF, pulse reset, run sim, etc.
    for (size_t i = 0; i < tests.size(); ++i) {
        if (esc_requested) {
            printf("ESC requested: aborting remaining tests.\n");
            break;
        }
        std::string bin = tests[i];
        // make a short name for printing
        std::string name = std::filesystem::path(bin).stem().string();
        // decide whether to enable trace for this run (simple policy: enable trace if single test requested)
        bool trace_en = (tests.size() == 1); // only enable trace if single test requested
        bool ok = run_one_test(dut, tfp, bin, name, trace_en, trace_opened);
        if (!ok) {
            printf("[%s] simulation reported failure or was aborted\n", name.c_str());
        }
    }

    // close trace if opened
    if (trace_opened) {
        tfp->close();
    }

    dut->final();
    delete dut;
    delete tfp;

    printf("All simulations finished.\n");
    // restore terminal before exit (atexit will also do it)
    uart_terminal_restore();
    return 0;
}

// load_elf and ram_init: mostly your original code with small cleanup
void load_elf(VSoc *dut, const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f) { perror("fopen"); exit(1); }

    // Read ELF header
    Elf32_Ehdr ehdr;
    if (fread(&ehdr, 1, sizeof(Elf32_Ehdr), f) != sizeof(Elf32_Ehdr)) {
        fprintf(stderr, "Read ELF header failed: %s\n", path);
        fclose(f); exit(1);
    }

    // Check ELF magic & basic sanity
    if (ehdr.e_ident[EI_MAG0] != ELFMAG0 || ehdr.e_ident[EI_MAG1] != ELFMAG1 ||
        ehdr.e_ident[EI_MAG2] != ELFMAG2 || ehdr.e_ident[EI_MAG3] != ELFMAG3) {
        fprintf(stderr, "Not an ELF file: %s\n", path);
        fclose(f); exit(1);
    }
    if (ehdr.e_ident[EI_CLASS] != ELFCLASS32) {
        fprintf(stderr, "Unsupported ELF class (not 32-bit): %s\n", path);
        fclose(f); exit(1);
    }
    if (ehdr.e_ident[EI_DATA] != ELFDATA2LSB) {
        fprintf(stderr, "Unsupported ELF endianness (not little-endian): %s\n", path);
        fclose(f); exit(1);
    }

    if (ehdr.e_phoff == 0 || ehdr.e_phnum == 0) {
        fprintf(stderr, "No program headers in ELF: %s\n", path);
        fclose(f); exit(1);
    }

    // read program headers
    if (fseek(f, ehdr.e_phoff, SEEK_SET) != 0) {
        perror("fseek phoff");
        fclose(f); exit(1);
    }
    Elf32_Phdr *phdrs = new Elf32_Phdr[ehdr.e_phnum];
    if (fread(phdrs, sizeof(Elf32_Phdr), ehdr.e_phnum, f) != (size_t)ehdr.e_phnum) {
        fprintf(stderr, "Read program headers failed\n");
        delete[] phdrs; fclose(f); exit(1);
    }

    // memory pointers: treat DUT mem[] as word array but also provide byte view
    uint32_t *rom_words = (uint32_t*)&(dut->rootp->SoC__DOT__rom__DOT__mem[0]);
    uint32_t *sram_words = (uint32_t*)&(dut->rootp->SoC__DOT__ram__DOT__ram_inst__DOT__mem[0]);
    uint8_t *rom_bytes = (uint8_t*)rom_words;
    uint8_t *sram_bytes = (uint8_t*)sram_words;

    const size_t rom_bytes_size = (size_t)ROM_SIZE;
    const size_t sram_bytes_size = (size_t)SRAM_SIZE;

    auto write_bytes_to_region = [&](uint8_t *target_bytes, size_t region_bytes,
                                    uint32_t offset_byte, uint32_t file_off, uint32_t filesz) {
        if (filesz == 0) return;
        if ((uint64_t)offset_byte + (uint64_t)filesz > region_bytes) {
            size_t can = (offset_byte < region_bytes) ? (region_bytes - offset_byte) : 0;
            fprintf(stderr, "Warning: truncating write: offset 0x%x filesz %u -> %zu available\n",
                    offset_byte, filesz, can);
            filesz = (uint32_t)can;
            if (filesz == 0) return;
        }

        if ((offset_byte % 4 == 0) && (filesz % 4 == 0)) {
            size_t word_idx = offset_byte / 4;
            size_t words = filesz / 4;
            if (fseek(f, file_off, SEEK_SET) != 0) { perror("fseek file_off"); return; }
            for (size_t w = 0; w < words; ++w) {
                uint8_t buf[4];
                size_t r = fread(buf, 1, 4, f);
                if (r != 4) { fprintf(stderr, "Warning: short read in word copy (%zu/%zu)\n", r, (size_t)4); break; }
                uint32_t word = (uint32_t)buf[0] | ((uint32_t)buf[1] << 8) | ((uint32_t)buf[2] << 16) | ((uint32_t)buf[3] << 24);
                ((uint32_t*)target_bytes)[word_idx + w] = word;
            }
        } else {
            if (fseek(f, file_off, SEEK_SET) != 0) { perror("fseek file_off"); return; }
            size_t to_copy = filesz;
            size_t dest = offset_byte;
            const size_t CHUNK = 1024;
            uint8_t tmp[CHUNK];
            while (to_copy > 0) {
                size_t c = (to_copy > CHUNK) ? CHUNK : to_copy;
                size_t r = fread(tmp, 1, c, f);
                if (r == 0) break;
                memcpy(target_bytes + dest, tmp, r);
                dest += r;
                to_copy -= r;
            }
        }
    };

    for (int i = 0; i < ehdr.e_phnum; ++i) {
        Elf32_Phdr &ph = phdrs[i];
        printf("PHDR %d: type=%u vaddr=0x%08x off=0x%08x filesz=%u memsz=%u\n",
               i, ph.p_type, ph.p_vaddr, ph.p_offset, ph.p_filesz, ph.p_memsz);

        if (ph.p_type != PT_LOAD) continue;

        uint32_t vaddr = ph.p_vaddr;
        uint32_t filesz = ph.p_filesz;
        uint32_t memsz = ph.p_memsz;

        uint8_t *target_bytes = nullptr;
        size_t region_bytes = 0;
        uint32_t offset_in_region = 0;
        const char *region_name = nullptr;

        if ( (uint64_t)vaddr >= (uint64_t)BROM_BASE && (uint64_t)vaddr < (uint64_t)BROM_BASE + ROM_SIZE ) {
            target_bytes = rom_bytes;
            region_bytes = rom_bytes_size;
            offset_in_region = (uint32_t)((uint64_t)vaddr - (uint64_t)BROM_BASE);
            region_name = "ROM";
        } else if ( (uint64_t)vaddr >= (uint64_t)SRAM_BASE && (uint64_t)vaddr < (uint64_t)SRAM_BASE + SRAM_SIZE ) {
            target_bytes = sram_bytes;
            region_bytes = sram_bytes_size;
            offset_in_region = (uint32_t)((uint64_t)vaddr - (uint64_t)SRAM_BASE);
            region_name = "SRAM";
        } else {
            printf("Warning: PT_LOAD at vaddr 0x%08x (filesz=%u) outside ROM/SRAM -> skip\n", vaddr, filesz);
            continue;
        }

        if (filesz > 0) {
            write_bytes_to_region(target_bytes, region_bytes, offset_in_region, ph.p_offset, filesz);
            printf("  -> wrote %u bytes to %s @ offset 0x%x\n", filesz, region_name, offset_in_region);
        }

        if (memsz > filesz) {
            uint32_t zero_start = offset_in_region + filesz;
            uint32_t zero_len = memsz - filesz;
            if ((uint64_t)zero_start < region_bytes) {
                if ((uint64_t)zero_start + (uint64_t)zero_len > region_bytes) {
                    zero_len = (uint32_t)(region_bytes - zero_start);
                }
                if (zero_len > 0) {
                    memset(target_bytes + zero_start, 0, zero_len);
                    printf("  -> zeroed %u bytes in %s @ offset 0x%x\n", zero_len, region_name, zero_start);
                }
            }
        }
    }

    delete[] phdrs;
    fclose(f);
}

void ram_init(VSoc *dut)
{
    const size_t WORDS = SRAM_SIZE / 4;
    for (size_t i = 0; i < WORDS; ++i)
    {
        dut->rootp->SoC__DOT__ram__DOT__ram_inst__DOT__mem[i] = 0;
    }
}

bool run_one_test(VSoc *dut, VerilatedVcdC *tfp,
                  const std::string &bin_path,
                  const std::string &test_name,
                  bool trace_en,
                  bool &trace_opened)
{
    printf("=== run test: %s (elf: %s) ===\n", test_name.c_str(), bin_path.c_str());

    // initialize sim_time for this test
    sim_time = 0;

    // re-init RAM and load elf
    ram_init(dut);
    load_elf(dut, bin_path.c_str());
    printf("===============SIMULATION OUTPUT===============\n");

    // optionally enable tracing (only once)
    if (trace_en && !trace_opened) {
        Verilated::traceEverOn(true);
        dut->trace(tfp, 99);
        tfp->open("simulator/build/wave.vcd");
        trace_opened = true;
    }

    // Ensure top-level inputs are in known state
    dut->clk = 0;
    dut->rst_n = 0;

    // ----- initialize uart rx/tx signals at rootp side (make sure names match your RTL) -----
    dut->rootp->uart_rx_valid = 0;
    dut->rootp->uart_rx_byte = 0;

    // reset pulse (6 toggles like original)
    for (int i = 0; i < 6; ++i)
    {
        dut->clk ^= 1;
        dut->eval();
        if (trace_opened) tfp->dump(sim_time);
        sim_time++;
    }
    dut->rst_n = 1;

    // simulation loop
    std::queue<uint8_t> rx_fifo;
    bool rx_asserted = false; // whether we asserted uart_rx_valid in previous cycle (to clear next)
    char inbuf[32];

    // we're going to sample & inject at same eval granularity as your previous code
    while (sim_time < MAX_SIM_CYCLES)
    {
        // if ESC requested externally, abort this run
        if (esc_requested) {
            printf("ESC requested: aborting simulation of %s\n", test_name.c_str());
            return false;
        }

        // toggle clock
        dut->clk ^= 1;
        dut->eval();

        // record waveform
        if (trace_opened) tfp->dump(sim_time);

        // ---------- UART TX: DUT -> host ----------
        if (dut->rootp->uart_tx_valid && dut->clk) {
            uint8_t ch = (uint8_t)(dut->rootp->uart_tx_byte & 0xFF);
            putchar((char)ch);
            fflush(stdout);
        }

        // ---------- read stdin non-blocking and push to rx_fifo ----------
        ssize_t r = read(STDIN_FILENO, inbuf, sizeof(inbuf));
        if (r > 0) {
            for (ssize_t k = 0; k < r; ++k) {
                uint8_t c = (uint8_t)inbuf[k];
                if (c == 27) { // ESC
                    esc_requested = 1;
                    // don't push ESC into fifo; ESC is control for host to abort simulation
                    break;
                } else {
                    rx_fifo.push(c);
                }
            }
            if (esc_requested) {
                // detected ESC during read: abort quickly after DUT evaluation cleanup
                printf("ESC pressed on stdin. Will abort current test.\n");
                return false;
            }
        }

        // ---------- DUT RX injection logic ----------
        if (rx_asserted) {
            // clear the signal (one-cycle pulse)
            dut->rootp->uart_rx_valid = 0;
            rx_asserted = false;
        } else {
            // if there's pending char and DUT isn't currently asserting rx_valid, inject one
            if (!rx_fifo.empty() && dut->rootp->uart_rx_valid == 0) {
                uint8_t b = rx_fifo.front(); rx_fifo.pop();
                dut->rootp->uart_rx_byte = b;
                dut->rootp->uart_rx_valid = 1;
                rx_asserted = true;
            }
        }

        sim_time++;

        // if (dut->rootp->SoC__DOT__dbg_exit) break;
    }

    printf("\n===============SIMULATION OUTPUT===============\n");

    int x3 = dut->rootp->SoC__DOT__hart0__DOT__register__DOT__regs[3];
    int x26 = dut->rootp->SoC__DOT__hart0__DOT__register__DOT__regs[26];
    int x27 = dut->rootp->SoC__DOT__hart0__DOT__register__DOT__regs[27];

    bool pass = (x26 == 1 && x27 == 1);
    if (x26 == 1 && x27 == 1)
        printf("[%s]: x3=%d, x26=%d, x27=%d, test %ssuccess%s\n", test_name.c_str(), x3, x26, x27, GREEN, CEND);
    else if (x26 == 1 && x27 == 0)
        printf("[%s]: x3=%d, x26=%d, x27=%d, test %sfailed%s\n", test_name.c_str(), x3, x26, x27, RED, CEND);
    else
        printf("[%s]: x3=%d, x26=%d, x27=%d, test %sunknown%s\n", test_name.c_str(), x3, x26, x27, YELLOW, CEND);

    return pass;
}
