// Real OoO -> APLIC -> IMSIC guest-file qualification, single clock only.
// Reuse the unchanged platform's image loader and native bus snapshots, not its
// architectural oracle. The program and set-based oracle below are independent.
#define main existing_hypervisor_platform_main
#include "hypervisor_platform.cpp"
#undef main
#include <set>
#include <string>
#include <vector>

namespace guest_claims {
constexpr uint64_t Boot = 0x80000000, Host = Boot + 0x1000;
constexpr uint64_t Guest = Boot + 0x2000, Handler = Boot + 0x3000;
constexpr uint64_t Ram = 0x80200000, Datum = 0x0123456789abcdefULL;
constexpr uint32_t Mret = 0x30200073, Sret = 0x10200073, Ecall = 0x00000073;

uint32_t addImmediate(unsigned rd, unsigned rs1, unsigned value) {
    return (value & 0xfff) << 20 | rs1 << 15 | rd << 7 | 0x13;
}
uint32_t shiftLeft(unsigned rd, unsigned rs1, unsigned amount) {
    return amount << 20 | rs1 << 15 | 1 << 12 | rd << 7 | 0x13;
}
uint32_t loadDouble(unsigned rd, unsigned rs1) {
    return rs1 << 15 | 3 << 12 | rd << 7 | 0x03;
}

uint32_t csrInstruction(unsigned address, unsigned operation, unsigned rd, unsigned source) {
    return address << 20 | source << 15 | operation << 12 | rd << 7 | 0x73;
}
struct Observation {
    uint64_t value;
    std::string label;
    bool isolation = false;
};
struct Image {
    std::map<uint64_t, uint32_t> code;
    std::map<uint64_t, Observation> observations;
    uint64_t pc = Boot, armPc = 0, firstObservation = 0, ecallPc = 0, donePc = 0;
    void emit(uint32_t instruction) { code.emplace(pc, instruction); pc += 4; }
    void immediate(unsigned reg, uint64_t value) {
        emit(addImmediate(reg, 0, 0));
        bool started = false;
        for (int byte = 7; byte >= 0; --byte) {
            unsigned part = (value >> (byte * 8)) & 255;
            if (!started && !part) continue;
            if (started) emit(shiftLeft(reg, reg, 8));
            emit(addImmediate(reg, reg, part));
            started = true;
        }
    }
    void write(unsigned address, uint64_t value) {
        immediate(1, value);
        emit(csrInstruction(address, 1, 0, 1));
    }
    void mmio(uint64_t address, uint32_t value) {
        immediate(4, address); immediate(5, value);
        emit(5 << 20 | 4 << 15 | 2 << 12 | 0x23); // SW x5, 0(x4).
    }
    void expect(unsigned address, uint64_t value, const std::string& label,
                unsigned operation = 2, unsigned source = 0, bool isolation = false) {
        observations.emplace(pc, Observation{value, label, isolation});
        emit(csrInstruction(address, operation, 10, source));
    }
    void indirect(bool shadow, unsigned selector, uint64_t value, const std::string& label,
                  bool isolation = false) {
        write(shadow ? 0x150 : 0x250, selector);
        expect(shadow ? 0x151 : 0x251, value, label, 2, 0, isolation);
    }
    void pending(bool shadow, uint64_t low, uint64_t high, const std::string& label) {
        indirect(shadow, 0x80, low, label + " EIP[63:0]");
        indirect(shadow, 0x82, high, label + " EIP[127:64]");
    }
    void threshold(unsigned value, uint64_t top, uint64_t low, uint64_t high) {
        write(0x150, 0x72); write(0x151, value);
        expect(0x151, value, "VS threshold " + std::to_string(value));
        expect(0x15c, top, "VS threshold " + std::to_string(value) + " TOPEI");
        pending(true, low, high, "VS threshold " + std::to_string(value));
    }
    void observeHost(unsigned file, uint64_t low, uint64_t high, uint64_t top,
                     const std::string& label, bool isolation = false, unsigned limit = 0) {
        write(0x600, uint64_t(file) << 12);
        expect(0x600, (2ULL << 32) | uint64_t(file) << 12, label + " HSTATUS");
        indirect(false, 0x80, low, label + " EIP[63:0]", isolation);
        indirect(false, 0x82, high, label + " EIP[127:64]");
        indirect(false, 0xc0, file == 1 ? 0x28 : 0x20, label + " EIE[63:0]");
        indirect(false, 0xc2, file == 1 ? 2 : 0, label + " EIE[127:64]");
        indirect(false, 0x70, 1, label + " eidelivery");
        indirect(false, 0x72, limit, label + " eithreshold");
        expect(0x25c, top, label + " TOPEI CSRRS x0");
        expect(0x25c, top, label + " TOPEI CSRRC x0", 3);
    }
    Image() {
        // M-only platform setup. Per-source physical rising edges are the only
        // source of set EIP bits. Software only initializes EIP to zero before
        // arming; it never injects pending bits, and no genmsi is used.
        const unsigned files[] = {1, 1, 1, 3}, identities[] = {3, 5, 65, 5};
        for (unsigned source = 1; source <= 4; ++source) {
            mmio(0x0c000000 + 4 * source, 0x400);
            mmio(0x0c004000 + 4 * source, 4);
            mmio(0x0c007000 + 4 * source, (files[source - 1] << 12) | identities[source - 1]);
            mmio(0x0c005edc, source);
        }
        mmio(0x0c004000, 0x100);
        write(0x3b0, ~0ULL); write(0x3a0, 31);
        write(0x305, Boot + 0x3f00); write(0x105, Handler);
        write(0x302, 1 << 10); write(0x602, 0); // VS ECALL -> HS only.
        write(0x304, 0); write(0x604, 0); write(0x607, 0); write(0x645, 0);
        write(0x603, 0); write(0x104, 0); write(0x204, 0); write(0x200, 0);
        write(0x180, 0); write(0x280, 0); write(0x680, 0); // Explicit Bare paths.
        expect(0x304, 0, "M interrupt enables disabled");
        for (unsigned file : {1U, 3U}) {
            write(0x600, uint64_t(file) << 12);
            write(0x250, 0x80); write(0x251, 0);
            write(0x250, 0x82); write(0x251, 0);
            write(0x250, 0x70); write(0x251, 1);
            write(0x250, 0xc0); write(0x251, file == 1 ? 0x28 : 0x20);
            write(0x250, 0xc2); write(0x251, file == 1 ? 2 : 0);
            write(0x250, 0x72); write(0x251, 0);
        }
        write(0x600, 1 << 12); write(0x341, Host); write(0x300, 1 << 11);
        immediate(29, 0);
        armPc = pc; emit(Mret);
        if (pc >= Host) throw std::runtime_error("boot image overlaps HS entry");

        pc = Host;
        // MRET is head-only and serializing. Retirement is paused immediately
        // after it, before this block retires. The 32 ordinary instructions also
        // exceed this platform's 16-entry ROB, excluding observational CSR issue
        // during the pause independently of fetch/dispatch timing.
        for (unsigned n = 0; n < 32; ++n) emit(addImmediate(29, 29, 1));
        firstObservation = pc;
        expect(0x604, 0, "HS HIE stays disabled");
        expect(0x607, 0, "HS HGEIE stays disabled");
        expect(0x645, 0, "HS HVIP stays zero");
        expect(0x204, 0, "HS VSIE stays disabled");
        expect(0x200, 2ULL << 32, "HS VS SIE stays disabled");
        observeHost(1, 0x28, 2, 0x30003, "HS A initial");
        observeHost(3, 0x20, 0, 0x50005, "HS B initial", true);
        observeHost(1, 0x28, 2, 0x30003, "HS A restored");
        write(0x141, Guest); write(0x600, (1 << 12) | 0x80); write(0x100, 0x100);
        emit(Sret);
        if (pc >= Guest) throw std::runtime_error("HS image overlaps VS entry");

        pc = Guest;
        expect(0x100, 2ULL << 32, "VS shadow SIE disabled");
        expect(0x104, 0, "VS shadow interrupt enables disabled");
        immediate(6, Ram); emit(loadDouble(20, 6)); // Actual Bare guest data path.
        immediate(2, 0); // Encoded nonzero rs1, despite its zero runtime value.
        pending(true, 0x28, 2, "VS initial");
        indirect(true, 0xc0, 0x28, "VS initial EIE[63:0]");
        indirect(true, 0xc2, 2, "VS initial EIE[127:64]");
        indirect(true, 0x70, 1, "VS eidelivery remains enabled");
        expect(0x15c, 0x30003, "VS CSRRS x0 is read-only");
        expect(0x15c, 0x30003, "VS CSRRC x0 is read-only", 3);
        expect(0x15c, 0x30003, "VS CSRRSI zimm0 is read-only", 6);
        expect(0x15c, 0x30003, "VS CSRRCI zimm0 is read-only", 7);
        pending(true, 0x28, 2, "VS after read-only encodings");
        threshold(3, 0, 0x28, 2); threshold(4, 0x30003, 0x28, 2);
        // Leave every pending identity eligible during these claims. An extra
        // destructive claim must lose a visible EIP bit and the next TOPEI.
        write(0x150, 0x72); write(0x151, 0);
        expect(0x151, 0, "VS threshold0 before claim ID3");
        expect(0x15c, 0x30003, "VS ID3 eligible with threshold0");
        expect(0x15c, 0x30003, "VS claim ID3 with CSRRS x2=0", 2, 2);
        pending(true, 0x20, 2, "VS after claim ID3");
        expect(0x15c, 0x50005, "VS ID5 survives claim ID3 and is next");
        write(0x150, 0x72); write(0x151, 4);
        expect(0x151, 4, "VS threshold4 restored after claim ID3");
        expect(0x15c, 0, "VS ID5 masked by threshold4");
        threshold(5, 0, 0x20, 2); threshold(6, 0x50005, 0x20, 2);
        write(0x150, 0x72); write(0x151, 0);
        expect(0x151, 0, "VS threshold0 before claim ID5");
        expect(0x15c, 0x50005, "VS ID5 eligible with threshold0");
        expect(0x15c, 0x50005, "VS claim ID5 with CSRRC x2=0", 3, 2);
        pending(true, 0, 2, "VS after claim ID5");
        expect(0x15c, 0x410041, "VS ID65 survives claim ID5 and is next");
        write(0x150, 0x72); write(0x151, 6);
        expect(0x151, 6, "VS threshold6 restored after claim ID5");
        expect(0x15c, 0, "VS ID65 masked by threshold6");
        threshold(65, 0, 0, 2); threshold(66, 0x410041, 0, 2);
        expect(0x15c, 0x410041, "VS claim ID65 with CSRRWI zimm0", 5, 0);
        pending(true, 0, 0, "VS after claim ID65");
        expect(0x15c, 0, "VS A empty");
        ecallPc = pc; emit(Ecall);
        if (pc >= Handler) throw std::runtime_error("VS image overlaps HS handler");

        pc = Handler;
        expect(0x142, 10, "HS ECALL cause");
        expect(0x141, ecallPc, "HS precise ECALL SEPC");
        expect(0x143, 0, "HS ECALL STVAL");
        expect(0x643, 0, "HS ECALL HTVAL");
        expect(0x64a, 0, "HS ECALL HTINST");
        expect(0x600, (2ULL << 32) | (1 << 12) | 0x180, "HS ECALL SPV/SPVP");
        expect(0x604, 0, "HS HIE disabled after ECALL");
        expect(0x607, 0, "HS HGEIE disabled after ECALL");
        expect(0x645, 0, "HS HVIP zero after ECALL");
        observeHost(3, 0x20, 0, 0x50005, "HS B survives A claims", true);
        expect(0x25c, 0x50005, "HS claim B ID5 with CSRRW x0", 1);
        pending(false, 0, 0, "HS B after claim");
        expect(0x25c, 0, "HS B empty");
        observeHost(1, 0, 0, 0, "HS A remains empty", false, 66);
        immediate(1, 99); donePc = pc; emit(csrInstruction(0x140, 1, 0, 1));
        emit(0x6f);
        if (pc >= Boot + 0x3f00) throw std::runtime_error("handler exceeds ROM image");
        pc = Boot + 0x3f00; emit(0x6f); // Any M trap is independently rejected.
    }
    void load(Memory& memory) const {
        for (unsigned n = 0; n < 4; ++n) memory.page(Boot + n * 4096);
        for (unsigned n = 0; n < 16; ++n) memory.page(Ram + n * 4096);
        memory.put(Ram, Datum, 8);
        for (auto [address, instruction] : code) memory.put(address, instruction, 4);
    }
};

// An architectural file is a set of pending and enabled interrupt identities.
// Priority is an ascending identity search, not the DUT's bank encoder/mux.
struct File {
    std::set<unsigned> pending, enabled;
    uint64_t threshold = 0, delivery = 0;
    unsigned top() const {
        for (unsigned id : pending)
            if (enabled.count(id) && (!threshold || id < threshold)) return id;
        return 0;
    }
    uint64_t bitmap(const std::set<unsigned>& values, unsigned bank) const {
        uint64_t result = 0;
        for (unsigned id : values) if (id / 64 == bank) result |= 1ULL << (id % 64);
        return result;
    }
};
struct Model {
    uint64_t r[32]{}, pc = Boot, checks = 0, commits = 0, csrReads = 0;
    std::map<unsigned, uint64_t> local;
    std::map<unsigned, File> files;
    unsigned privilege = 3, selected = 0, selector = 0, claims = 0, traps = 0, returns = 0;
    bool virtualized = false, armRetired = false, done = false, wrongClaim, wrongFile;
    Model(bool claimControl, bool fileControl) : wrongClaim(claimControl), wrongFile(fileControl) {}
    void check(uint64_t actual, uint64_t expected, const char* name) {
        ++checks;
        if (actual != expected) {
            std::cerr << name << " pc=0x" << std::hex << pc << " actual=0x" << actual
                      << " expected=0x" << expected << std::dec << '\n';
            throw std::runtime_error(name);
        }
    }
    unsigned canonical(unsigned address) const {
        if (virtualized && (address == 0x100 || address == 0x104 || address == 0x150 ||
                            address == 0x151 || address == 0x15c)) return address + 0x100;
        return address;
    }
    uint64_t read(unsigned address) {
        address = canonical(address);
        if (address == 0x600) return (2ULL << 32) | local[address];
        if (address == 0x200) return (2ULL << 32) | local[address];
        if (address == 0x250) return selector;
        if (address == 0x25c) { uint64_t id = files.at(selected).top(); return id << 16 | id; }
        if (address == 0x251) {
            const File& f = files.at(selected);
            switch (selector) {
            case 0x70: return f.delivery;
            case 0x72: return f.threshold;
            case 0x80: return f.bitmap(f.pending, 0);
            case 0x82: return f.bitmap(f.pending, 1);
            case 0xc0: return f.bitmap(f.enabled, 0);
            case 0xc2: return f.bitmap(f.enabled, 1);
            default: throw std::runtime_error("oracle unsupported indirect selector");
            }
        }
        return local[address];
    }
    void write(unsigned address, uint64_t value) {
        address = canonical(address);
        if (address == 0x600) { selected = (value >> 12) & 63; files.try_emplace(selected); }
        if (address == 0x250) selector = value;
        else if (address == 0x251) {
            File& f = files[selected];
            if (selector == 0x80 || selector == 0x82) {
                check(privilege == 3 && !armRetired, 1, "EIP initialization only before MRET arming");
                check(value, 0, "software may only initialize EIP to zero");
                unsigned bank = selector == 0x80 ? 0 : 1;
                for (unsigned id = bank * 64; id < (bank + 1) * 64; ++id) f.pending.erase(id);
            } else if (selector == 0x70) f.delivery = value;
            else if (selector == 0x72) f.threshold = value;
            else if (selector == 0xc0 || selector == 0xc2) {
                unsigned base = selector == 0xc0 ? 0 : 64;
                for (unsigned bit = 0; bit < 64; ++bit) {
                    f.enabled.erase(base + bit);
                    if ((value >> bit) & 1) f.enabled.insert(base + bit);
                }
            } else throw std::runtime_error("software EIP modification is out of scope");
        }
        local[address] = value;
    }
    void commit(uint64_t actualPc, uint32_t instruction, unsigned rd, uint64_t data,
                uint64_t nextPc, bool writesRd, const Image& image, unsigned msiReplies) {
        check(actualPc, pc, "independent retired PC");
        check(instruction, image.code.at(pc), "independent retired instruction");
        if (pc >= Host && pc < Boot + 0x3f00)
            check(msiReplies, 4, "all MSI replies precede observational program");
        unsigned opcode = instruction & 127, dest = (instruction >> 7) & 31;
        unsigned rs1 = (instruction >> 15) & 31, rs2 = (instruction >> 20) & 31;
        unsigned funct3 = (instruction >> 12) & 7;
        bool writes = dest != 0;
        uint64_t value = 0, next = pc + 4;
        if (opcode == 0x13) {
            if (funct3 == 0) value = r[rs1] + int64_t(int32_t(instruction) >> 20);
            else if (funct3 == 1) value = r[rs1] << ((instruction >> 20) & 63);
            else throw std::runtime_error("oracle unexpected OP-IMM");
        } else if (opcode == 0x23) {
            writes = false; check(privilege, 3, "APLIC setup remains M-only");
            check(virtualized, 0, "APLIC setup not virtualized");
            check(funct3, 2, "APLIC setup uses SW");
            check(rs1, 4, "APLIC address register"); check(rs2, 5, "APLIC value register");
        } else if (opcode == 3) {
            check(virtualized, 1, "real data load executes in VS");
            check(funct3, 3, "guest data load is LD");
            check(r[rs1] + int64_t(int32_t(instruction) >> 20), Ram, "independent guest data address");
            value = Datum;
        } else if (opcode == 0x73 && funct3) {
            unsigned address = instruction >> 20, mapped = canonical(address);
            // Zicsr write suppression depends on the ENCODED source, never its
            // runtime contents. CSRRW/I always writes, including uimm=0.
            unsigned operation = funct3 & 3;
            bool writesCsr = operation == 1 || rs1 != 0;
            uint64_t source = funct3 >= 5 ? rs1 : r[rs1];
            value = read(address);
            bool claim = mapped == 0x25c && writesCsr;
            auto observation = image.observations.find(pc);
            if (dest) {
                ++csrReads;
                check(observation != image.observations.end(), 1, "each CSR result has explicit expectation");
                check(value, observation->second.value, "independent program CSR expectation");
                uint64_t comparison = value;
                const char* name = "independent guest CSR result";
                if (claim) {
                    name = "independent guest claim result";
                    if (wrongClaim && claims == 0) comparison ^= 0x10001;
                } else if (observation->second.isolation) {
                    name = "independent guest file isolation";
                    if (wrongFile) comparison ^= 8;
                }
                check(data, comparison, name);
                std::cout << "CSR " << (virtualized ? "VS" : privilege == 3 ? "M" : "HS")
                          << " pc=0x" << std::hex << pc << " csr=0x" << address
                          << " value=0x" << value << std::dec << " file=" << selected
                          << " " << observation->second.label << '\n';
            }
            if (claim) {
                check(msiReplies, 4, "no claim before all MSI replies");
                const unsigned expectedFiles[] = {1, 1, 1, 3}, expectedIds[] = {3, 5, 65, 5};
                const unsigned expectedForms[] = {2, 3, 5, 1}, expectedSources[] = {2, 2, 0, 0};
                check(claims < 4, 1, "exactly four guest claims");
                check(selected, expectedFiles[claims], "independent claim file sequence");
                check(value & 0xffff, expectedIds[claims], "independent claim ID sequence");
                check(funct3, expectedForms[claims], "independent claim encoding sequence");
                check(rs1, expectedSources[claims], "independent claim encoded source");
                check(source, 0, "claim source runtime value zero");
                check(virtualized, claims < 3, "three shadow claims then one direct HS claim");
                files.at(selected).pending.erase(unsigned(value & 0xffff));
                ++claims;
                std::cout << "CLAIM file=" << selected << " id=" << (value & 0xffff)
                          << " form=" << funct3 << " encodedSource=" << rs1
                          << " operand=" << source << '\n';
            } else if (writesCsr) {
                uint64_t updated = operation == 1 ? source : operation == 2 ? value | source : value & ~source;
                write(address, updated);
            }
        } else if (opcode == 0x6f) {
            check(done, 1, "only terminal loop may retire JAL");
            check(instruction, 0x6f, "terminal JAL x0,0");
            writes = false; next = pc;
        } else if (instruction == Mret) {
            writes = false; check(pc, image.armPc, "serializing MRET arming marker");
            check(privilege, 3, "MRET starts in M"); check((local[0x300] >> 11) & 3, 1, "MRET targets HS");
            check((local[0x300] >> 39) & 1, 0, "MRET keeps V clear");
            next = local[0x341]; privilege = 1; armRetired = true;
        } else if (instruction == Sret) {
            writes = false; check(privilege, 1, "SRET starts in HS"); check(virtualized, 0, "one HS to VS entry");
            check(local[0x600] & 0x80, 0x80, "retired HSTATUS SPV authorizes VS");
            check(local[0x100] & 0x100, 0x100, "retired SSTATUS SPP selects VS supervisor");
            next = local[0x141]; virtualized = true; local[0x600] &= ~0x80ULL; ++returns;
        } else throw std::runtime_error("oracle unexpected retired instruction");
        check(writesRd, writes, "independent retirement write-enable");
        check(nextPc, next, "independent retired next PC");
        check(rd, dest, "independent architectural RD");
        if (writes) { check(data, value, "independent retired value"); r[dest] = value; }
        if (pc == image.donePc) done = true;
        pc = next; ++commits;
    }
    void trap(uint64_t actualPc, uint64_t cause, uint64_t tval, uint64_t gpa,
              bool pageFault, bool guestAddress, bool implicit, const Image& image) {
        check(actualPc, pc, "independent precise ECALL PC"); check(pc, image.ecallPc, "only ordinary VS ECALL may trap");
        check(image.code.at(pc), Ecall, "precise ECALL instruction");
        check(virtualized, 1, "ECALL originates in VS"); check(privilege, 1, "ECALL originates in supervisor mode");
        check(cause, 10, "no interrupt or guest-memory-fault trap");
        check(tval, 0, "ECALL trap tval zero"); check(gpa, 0, "ECALL GPA metadata zero");
        check(pageFault || guestAddress || implicit, 0, "ECALL has no guest-fault metadata");
        check(traps++, 0, "exactly one ordinary VS ECALL"); check(claims, 3, "VS claims precede ECALL");
        local[0x141] = pc; local[0x142] = 10; local[0x143] = local[0x643] = local[0x64a] = 0;
        local[0x600] |= 0x180; virtualized = false; pc = Handler;
        std::cout << "ECALL cause=10 sepc=0x" << std::hex << actualPc << std::dec << " target=HS\n";
    }
};

// These expected physical writes are independent of instruction generation.
const std::array<std::pair<uint64_t, uint32_t>, 17> Configuration{{
    {0x0c000004, 0x400}, {0x0c004004, 4}, {0x0c007004, 0x1003}, {0x0c005edc, 1},
    {0x0c000008, 0x400}, {0x0c004008, 4}, {0x0c007008, 0x1005}, {0x0c005edc, 2},
    {0x0c00000c, 0x400}, {0x0c00400c, 4}, {0x0c00700c, 0x1041}, {0x0c005edc, 3},
    {0x0c000010, 0x400}, {0x0c004010, 4}, {0x0c007010, 0x3005}, {0x0c005edc, 4},
    {0x0c004000, 0x100}
}};

void run(bool stalled, bool wrongClaim, bool wrongFile) {
    const char* schedule = stalled ? "stalled" : "open";
    Image program; Memory memory; program.load(memory); Model model(wrongClaim, wrongFile);
    auto allocation = std::make_unique<SHypervisorPlatformGsim>(); auto& dut = *allocation;
    static_assert(std::is_trivially_copyable_v<SHypervisorPlatformGsim>);
    std::memset(&dut, 0, sizeof(dut)); dut.LOG_START = 1; dut.activateAll(); initialize(dut, memory);
    std::deque<Request> owners[2]; Request lastRequest[2]; Response lastResponse[2];
    bool requestHeld[2]{}, responseHeld[2]{};
    unsigned nextOwner[2]{}, requests[2]{}, replies[2]{}, requestHolds[2]{}, responseHolds[2]{};
    unsigned mmioWrites = 0, dataReads = 0, fetchParcels = 0, parcelOffsets = 0, clears = 0;
    unsigned msiRequests = 0, msiReplies = 0, msiHolds = 0, msiReplyHolds = 0, sourceCycle = 0;
    unsigned pauseCycles = 0, terminalCycles = 0;
    std::set<std::pair<unsigned, unsigned>> observedMsis;
    bool sources = false, lastMsiHeld = false, lastMsiReplyHeld = false, resumeLogged = false;
    std::array<uint64_t, 5> lastMsi{};
    std::array<uint64_t, 2> lastMsiReply{};
    std::cout << "BEGIN guest claims schedule=" << schedule << " Bare instruction/data paths, single clock\n";
    for (unsigned cycle = 0; cycle < 200000; ++cycle) {
        bool pause = model.armRetired && msiReplies != 4;
        if (model.armRetired && !sources) {
            model.check(mmioWrites, Configuration.size(), "all CPU APLIC setup precedes source edges");
            sources = true; sourceCycle = cycle;
            std::cout << "ARM retired MRET; pause retirement; physical sources 1,2,3,4 rise\n";
        }
        if (model.armRetired && !pause && !resumeLogged) {
            resumeLogged = true;
            std::cout << "RESUME all four actual IMSIC replies complete; no earlier observation or claim\n";
        }
        // enable is a cold-start gate: never lower it after startup. The
        // terminal loop remains live; fetch owners are reported, not drained.
        dut.set_io$$enable(1);
        dut.set_io$$commitEnable(!pause && (!stalled || cycle % 11 != 3));
        dut.set_io$$sources(sources ? 15 : 0);
        dut.set_io$$allowRequest(stalled ? (cycle % 5 == 1 ? 0 : 1) | (cycle % 7 == 2 ? 0 : 2) : 3);
        dut.set_io$$allowResponse(stalled ? (cycle % 7 < 3 ? 0 : 1) | (cycle % 9 < 4 ? 0 : 2) : 3);
        dut.set_io$$allowMsi(!stalled || (sources && cycle >= sourceCycle + 8 && cycle % 9 == 0));
        dut.set_io$$allowMsiResponse(!stalled || (msiRequests && cycle % 11 == 0));
        dut.set_io$$allowDrain(1);
        dut.step();
        if (pause) {
            ++pauseCycles;
            model.check(dut.get_io$$commit0$$valid() || dut.get_io$$commit1$$valid(), 0, "no retirement while MSI phase is paused");
            model.check(dut.get_io$$trap$$valid(), 0, "no trap while MSI phase is paused");
        }
        for (unsigned lane = 0; lane < 2; ++lane) {
            Request q = request(dut, lane); Response r = response(dut, lane);
            bool qr = (dut.get_io$$scalarRequestReady() >> lane) & 1;
            bool rr = (dut.get_io$$scalarResponseReady() >> lane) & 1;
            if (requestHeld[lane]) model.check(q == lastRequest[lane], 1, "native request hold stability");
            if (responseHeld[lane]) model.check(r == lastResponse[lane], 1, "native response hold stability");
            requestHeld[lane] = q.valid && !qr; responseHeld[lane] = r.valid && !rr;
            requestHolds[lane] += requestHeld[lane]; responseHolds[lane] += responseHeld[lane];
            lastRequest[lane] = q; lastResponse[lane] = r;
            if (r.valid && rr) {
                model.check(!owners[lane].empty(), 1, "native response owns a request");
                Request prior = owners[lane].front(); owners[lane].pop_front();
                model.check(r.owner, prior.owner, "physical scalar response owner");
                model.check(r.clear, prior.clear, "physical scalar clear identity");
                model.check(r.error || r.pageFault, 0, "physical scalar response has no errors");
                if (!prior.clear && !prior.write)
                    model.check(r.data, memory.get(prior.address & ~7ULL, 8), "independent physical scalar read beat");
                ++replies[lane];
            }
            if (q.valid && qr) {
                model.check(q.owner, nextOwner[lane]++ & 15, "monotonic physical scalar owner");
                model.check(q.lookup, 1, "native uncached coherence lookup");
                if (q.clear) {
                    ++clears; model.check(lane, 0, "reservation clear uses data lane");
                    model.check(model.traps + unsigned(dut.get_io$$trap$$valid()), 1, "reservation clear belongs to sole ECALL");
                    model.check(owners[0].empty() && owners[1].empty(), 1, "reservation clear follows older native replies");
                } else {
                    model.check(q.virtualized || q.prechecked || q.epoch || q.prefetch || q.atomic, 0,
                                "virtual metadata consumed before physical fabric");
                    if (q.write) {
                        model.check(lane, 0, "only native data lane may write");
                        model.check(mmioWrites < Configuration.size(), 1, "no unexpected physical writes");
                        const auto expected = Configuration.at(mmioWrites++);
                        model.check(q.address, expected.first, "independent CPU APLIC MMIO address");
                        model.check(q.data >> ((q.address & 7) * 8), expected.second, "independent CPU APLIC MMIO data");
                        model.check(q.size, 2, "APLIC physical SW size");
                        model.check(q.mask, 15U << (q.address & 7), "APLIC physical SW byte mask");
                        model.check(q.uncached, 1, "APLIC physical MMIO uncached");
                    } else if (lane == 1) {
                        ++fetchParcels; parcelOffsets |= 1U << (q.address & 7);
                        model.check(q.size, 1, "Bare fetch uses halfword parcels, no PTE reads");
                        model.check(q.address >= Boot && q.address < Boot + 16384, 1, "actual physical ROM fetch address");
                        model.check(q.mask, 3U << (q.address & 7), "physical fetch halfword byte mask");
                    } else {
                        ++dataReads; model.check(q.address, Ram, "actual physical guest data address");
                        model.check(q.size, 3, "actual physical guest LD size");
                        model.check(q.mask, 255, "actual physical guest LD byte mask");
                    }
                }
                owners[lane].push_back(q); ++requests[lane];
            }
        }
        bool msiValid = dut.get_io$$msiRequest$$valid();
        std::array<uint64_t, 5> msi{dut.get_io$$msiRequest$$bits$$address(), dut.get_io$$msiRequest$$bits$$data(),
            dut.get_io$$msiRequest$$bits$$size(), dut.get_io$$msiRequest$$bits$$byteEnable(), dut.get_io$$msiRequest$$bits$$write()};
        if (lastMsiHeld) {
            model.check(msiValid, 1, "held MSI request cannot withdraw");
            model.check(msi == lastMsi, 1, "MSI request hold stability");
        }
        lastMsiHeld = msiValid && !dut.get_io$$msiRequestReady(); lastMsi = msi; msiHolds += lastMsiHeld;
        if (msiValid && dut.get_io$$msiRequestReady()) {
            const std::array<std::pair<unsigned, unsigned>, 4> planned{{{1, 3}, {1, 5}, {1, 65}, {3, 5}}};
            model.check(sources && pause, 1, "all real MSIs occur in paused arming phase");
            model.check(msiRequests < 4, 1, "exactly four physical-source MSIs");
            unsigned matched = 4;
            for (unsigned event = 0; event < planned.size(); ++event)
                if (msi[0] == 0x28000000 + 4096 * planned[event].first && msi[1] == planned[event].second)
                    matched = event;
            model.check(matched < planned.size(), 1, "independent planned MSI destination and identity");
            auto [file, id] = planned.at(matched);
            model.check(observedMsis.insert({file, id}).second, 1, "no duplicate physical-source MSI");
            model.check(msi[2], 2, "actual MSI 32-bit size"); model.check(msi[3], 15, "actual MSI byte lanes");
            model.check(msi[4], 1, "actual MSI is a write");
            model.files.at(file).pending.insert(id); ++msiRequests;
            std::cout << "MSI source=" << matched + 1 << " guest=" << file << " id=" << id
                      << " address=0x" << std::hex << msi[0] << std::dec << '\n';
        }
        bool msiReplyValid = dut.get_io$$msiResponse$$valid();
        std::array<uint64_t, 2> msiReply{dut.get_io$$msiResponse$$bits$$data(), dut.get_io$$msiResponse$$bits$$error()};
        if (lastMsiReplyHeld) {
            model.check(msiReplyValid, 1, "held MSI reply cannot withdraw");
            model.check(msiReply == lastMsiReply, 1, "MSI reply hold stability");
        }
        lastMsiReplyHeld = msiReplyValid && !dut.get_io$$msiResponseReady();
        lastMsiReply = msiReply; msiReplyHolds += lastMsiReplyHeld;
        if (msiReplyValid) {
            model.check(msiReply[0], 0, "actual IMSIC reply data"); model.check(msiReply[1], 0, "actual IMSIC reply error");
            if (dut.get_io$$msiResponseReady()) {
                model.check(msiReplies < msiRequests, 1, "MSI reply owns an outstanding request"); ++msiReplies;
            }
        }
        model.check(dut.get_io$$maintenance$$valid() || dut.get_io$$drained$$valid(), 0, "no unexpected FENCE.I maintenance");
        model.check(dut.get_io$$msiError(), 0, "APLIC reports every MSI successful");
#define CLAIM_COMMIT(N) \
        if (dut.get_io$$commit##N##$$valid()) \
            model.commit(dut.get_io$$commit##N##$$bits$$pc(), dut.get_io$$commit##N##$$bits$$instruction(), \
                dut.get_io$$commit##N##$$bits$$rd(), dut.get_io$$commit##N##$$bits$$data(), \
                dut.get_io$$commit##N##$$bits$$nextPc(), dut.get_io$$commit##N##$$bits$$writesRd(), program, msiReplies)
        CLAIM_COMMIT(0); CLAIM_COMMIT(1);
#undef CLAIM_COMMIT
        if (dut.get_io$$trap$$valid())
            model.trap(dut.get_io$$trap$$bits$$pc(), dut.get_io$$trap$$bits$$cause(), dut.get_io$$trap$$bits$$tval(),
                dut.get_io$$trap$$bits$$guestFault$$guestPhysicalAddress(), dut.get_io$$trap$$bits$$guestFault$$guestPageFault(),
                dut.get_io$$trap$$bits$$guestFault$$guestAddress(), dut.get_io$$trap$$bits$$guestFault$$implicitPte(), program);
        if (model.done) ++terminalCycles;
        if (terminalCycles >= 64 && owners[0].empty() && !request(dut, 0).valid && !msiValid && !msiReplyValid) {
            model.check(msiRequests, 4, "final exact MSI request count"); model.check(msiReplies, 4, "final exact MSI reply count");
            model.check(model.claims, 4, "final exact guest claim count"); model.check(model.traps, 1, "final exact ECALL count");
            model.check(model.returns, 1, "one legal HS SRET enters VS");
            model.check(model.csrReads, program.observations.size(), "every expected CSR observation retired");
            model.check(mmioWrites, 17, "all CPU APLIC writes observed"); model.check(dataReads, 1, "one actual guest data load");
            model.check(model.r[20], Datum, "independent guest LD retirement"); model.check(model.r[29], 32, "arming separator fully retired");
            model.check(clears, 1, "sole ECALL reservation clear"); model.check(parcelOffsets, 0x55, "all physical halfword lanes used");
            model.check(model.files.at(1).pending.empty() && model.files.at(3).pending.empty(), 1, "final independent pending files empty");
            model.check(pauseCycles > 0 && resumeLogged, 1, "bounded MSI arming pause completed");
            model.check(requests[0], replies[0], "all native data owners drained");
            model.check(requests[1], replies[1] + owners[1].size(), "live fetch owner accounting remains exact");
            if (stalled) {
                model.check(requestHolds[0] > 0 && requestHolds[1] > 0, 1, "both native request lanes backpressured");
                model.check(responseHolds[0] > 0 && responseHolds[1] > 0, 1, "both native response lanes backpressured");
                model.check(msiHolds > 0 && msiReplyHolds > 0, 1, "both MSI directions held under backpressure");
            }
            std::cout << "AIA_GUEST_CLAIMS_PASS schedule=" << schedule << " cycles=" << cycle + 1
                      << " commits=" << model.commits << " checks=" << model.checks << " csrReads=" << model.csrReads
                      << " claims=" << model.claims << " sources=4 msiRequests=" << msiRequests << " msiReplies=" << msiReplies
                      << " ecalls=" << model.traps << " nativeRequests=" << requests[0] << ',' << requests[1]
                      << " nativeReplies=" << replies[0] << ',' << replies[1]
                      << " requestHeld=" << requestHolds[0] << ',' << requestHolds[1]
                      << " responseHeld=" << responseHolds[0] << ',' << responseHolds[1]
                      << " msiHeld=" << msiHolds << " msiReplyHeld=" << msiReplyHolds
                      << " pauseCycles=" << pauseCycles << " fetchParcels=" << fetchParcels
                      << " terminalCycles=" << terminalCycles << " outstandingFetchOwners=" << owners[1].size()
                      << " finalPendingA=0 finalPendingB=0\n";
            return;
        }
    }
    throw std::runtime_error("guest claims finite guard exhausted pc=" + std::to_string(model.pc));
}
} // namespace guest_claims

int main(int argc, char** argv) {
    try {
        bool wrongClaim = false, wrongFile = false;
        if (argc == 2 && std::string(argv[1]) == "--wrong-claim") wrongClaim = true;
        else if (argc == 2 && std::string(argv[1]) == "--wrong-file") wrongFile = true;
        else if (argc != 1) throw std::runtime_error("usage: aia_guest_claims [--wrong-claim|--wrong-file]");
        guest_claims::run(false, wrongClaim, wrongFile);
        if (wrongClaim || wrongFile) throw std::runtime_error("negative control was not rejected");
        guest_claims::run(true, false, false);
        std::cout << "AIA_GUEST_CLAIMS_ALL_PASS cases=2\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "FAIL " << error.what() << '\n';
        return 1;
    }
}
