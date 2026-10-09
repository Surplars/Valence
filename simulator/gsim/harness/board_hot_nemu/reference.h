#pragma once
// Shared audited NEMU ABI/client. Includer defines base, dataBase, Memory and check.
// ABI reviewed against pinned NEMU isa-def.h: FPU_NONE, no RVH/RVV or extra diff CSR fields.
struct ReferenceState {
    uint64_t gpr[32];
    uint64_t mode, mstatus, sstatus, mepc, sepc, mtval, stval, mtvec, stvec;
    uint64_t mcause, scause, satp, mip, mie, mscratch, sscratch, mideleg, medeleg, pc;
};
static_assert(sizeof(ReferenceState) == 51 * sizeof(uint64_t));
class Reference {
    void *handle;
    void (*copyRegisters)(void *, bool);
    void (*copyMemory)(uint64_t, void *, size_t, bool);
    void (*step)(uint64_t);
    ReferenceState initial{};
    template <typename T> T symbol(const char *name) {
        auto result = reinterpret_cast<T>(dlsym(handle, name));
        check(result != nullptr, std::string("NEMU missing symbol: ") + name);
        return result;
    }
public:
    explicit Reference(const char *path) {
        handle = dlopen(path, RTLD_NOW | RTLD_LOCAL);
        if (!handle) throw std::runtime_error(std::string("NEMU dlopen: ") + dlerror());
        const auto size = symbol<const unsigned *>("DIFFTEST_REG_SIZE");
        check(*size == sizeof(ReferenceState), "NEMU register ABI size mismatch");
        symbol<void (*)(unsigned)>("difftest_init_v2")(sizeof(ReferenceState));
        copyRegisters = symbol<void (*)(void *, bool)>("difftest_regcpy");
        copyMemory = symbol<void (*)(uint64_t, void *, size_t, bool)>("difftest_memcpy");
        step = symbol<void (*)(uint64_t)>("difftest_exec");
        copyRegisters(&initial, false);
        std::fill(std::begin(initial.gpr), std::end(initial.gpr), 0);
        initial.pc = base;
    }
    ~Reference() { dlclose(handle); }
    // Test initialization only, before executing system programs; never used to repair a mismatch.
    void machineReset() {
        initial.mode = 3; initial.mstatus = UINT64_C(0xa00000000); initial.sstatus = UINT64_C(0x200000000);
        initial.mtvec = initial.mepc = initial.mcause = initial.mtval = initial.mscratch = 0;
        initial.mie = initial.mip = initial.medeleg = initial.mideleg = 0;
    }
    // Fixed ROM semantics only. Never receives any DUT-derived register state.
    void initializeAfterBoardRom() {
        machineReset();
        initial.gpr[1] = 0x80000014ULL;
        initial.gpr[5] = 0x80200000ULL;
        initial.gpr[6] = 0x10000000ULL;
        initial.gpr[7] = 7;
    }
    ReferenceState executeOne() {
        step(1);
        return inspectState();
    }
    Memory inspectMemory() {
        Memory bytes(memoryBytes, 0);
        copyMemory(dataBase, bytes.data(), bytes.size(), false);
        return bytes;
    }
    ReferenceState inspectState() {
        ReferenceState state{}; copyRegisters(&state, false); return state;
    }
    void load(const std::vector<uint32_t> &program) {
        std::vector<uint8_t> bytes;
        for (uint32_t inst : program) for (unsigned byte = 0; byte < 4; ++byte) bytes.push_back(inst >> (8 * byte));
        copyMemory(base, bytes.data(), bytes.size(), true);
        // NEMU memcpy/regcpy do not invalidate its decoded-instruction cache. Execute FENCE.I at a
        // reserved reference-only bootstrap address before resetting state for each new program.
        // This is initialization between test cases, never resynchronization after a mismatch.
        constexpr uint64_t bootstrap = 0x80ffff00; // Fits pinned 16 MiB RAM with guest at 0x80200000.
        std::array<uint8_t, 4> fence{0x0f, 0x10, 0, 0};
        copyMemory(bootstrap, fence.data(), fence.size(), true);
        auto state = initial;
        state.pc = bootstrap;
        copyRegisters(&state, true);
        step(1);
        copyRegisters(&state, false);
        check(state.pc == bootstrap + 4, "NEMU initialization FENCE.I failed");
        state = initial;
        copyRegisters(&state, true);
    }
    void initializeMemory(const Memory &memory) {
        auto bytes = memory;
        copyMemory(dataBase, bytes.data(), bytes.size(), true);
    }
    // Model an independently specified external writer, never a DUT mismatch repair.
    void externalWrite64(uint64_t address, uint64_t value) {
        std::array<uint8_t, 8> bytes{};
        for (unsigned i = 0; i < bytes.size(); ++i) bytes[i] = value >> (8 * i);
        copyMemory(address, bytes.data(), bytes.size(), true);
    }
    void compareMemory(const Memory &memory) {
        Memory actual{};
        copyMemory(dataBase, actual.data(), actual.size(), false);
        check(actual == memory, "NEMU memory mismatch");
    }
    void compare(const std::array<uint64_t, 32> &registers, uint64_t expectedPc) {
        step(1);
        ReferenceState state{};
        copyRegisters(&state, false);
        check(state.pc == expectedPc, "NEMU PC mismatch at " + std::to_string(expectedPc - 4));
        for (unsigned r = 0; r < 32; ++r)
            check(state.gpr[r] == registers[r], "NEMU register mismatch x" + std::to_string(r) +
                  " at PC " + std::to_string(expectedPc - 4) + " reference=" + std::to_string(state.gpr[r]) +
                  " dut=" + std::to_string(registers[r]));
    }
};
