#include "I1OperandSingletonFixture.h"
#include <array>
#include <cstdint>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <type_traits>

using Values = std::array<uint64_t, 20>;
constexpr std::array<unsigned, 11> counts = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20};
static uint64_t operandChecks = 0, overrideChecks = 0;

// Independent bit-level truth table: no grouping, Chisel helper, or DUT-derived masks.
static uint64_t oracle(unsigned count, uint32_t masks, const Values &values) {
    uint64_t result = 0;
    for (unsigned bit = 0; bit < 64; ++bit) {
        bool selectedBit = false;
        for (unsigned lane = 0; lane < count; ++lane)
            selectedBit = selectedBit || (((masks >> lane) & 1U) && ((values[lane] >> bit) & 1U));
        if (selectedBit) result |= uint64_t(1) << bit;
    }
    return result;
}

static void drive(SI1OperandSingletonFixture &dut, uint32_t masks, const Values &values,
                  bool overrideEnable = false, bool registerEnable = true, uint64_t overrideValue = 0) {
    dut.set_io$$masks(masks);
#define SET_VALUE(i) dut.set_io$$value##i(values[i])
    SET_VALUE(0); SET_VALUE(1); SET_VALUE(2); SET_VALUE(3); SET_VALUE(4);
    SET_VALUE(5); SET_VALUE(6); SET_VALUE(7); SET_VALUE(8); SET_VALUE(9);
    SET_VALUE(10); SET_VALUE(11); SET_VALUE(12); SET_VALUE(13); SET_VALUE(14);
    SET_VALUE(15); SET_VALUE(16); SET_VALUE(17); SET_VALUE(18); SET_VALUE(19);
#undef SET_VALUE
    dut.set_io$$overrideEnable(overrideEnable);
    dut.set_io$$registerEnable(registerEnable);
    dut.set_io$$overrideValue(overrideValue);
    dut.step();
}

static uint64_t observe(SI1OperandSingletonFixture &dut, unsigned count, bool legacy) {
#define OUTPUT(n) case n: return legacy ? dut.get_io$$legacyResult##n() : dut.get_io$$result##n()
    switch (count) {
        OUTPUT(1); OUTPUT(2); OUTPUT(3); OUTPUT(4); OUTPUT(5); OUTPUT(6);
        OUTPUT(7); OUTPUT(8); OUTPUT(9); OUTPUT(10); OUTPUT(20);
        default: throw std::runtime_error("invalid fixture count");
    }
#undef OUTPUT
}

static void compare(uint64_t actual, uint64_t expected, unsigned count, uint32_t masks,
                    const std::string &label) {
    if (actual != expected) {
        std::cerr << "I1_OPERAND_MASKED_OR_MISMATCH case=" << label << " n=" << count
                  << " masks=0x" << std::hex << masks << " expected=0x" << expected
                  << " actual=0x" << actual << std::dec << '\n';
        throw std::runtime_error("independent bitwise masked-OR oracle rejected output");
    }
}

static void checkOperand(SI1OperandSingletonFixture &dut, unsigned count, uint32_t masks,
                         const Values &values, const std::string &label, bool legacy = false) {
    drive(dut, masks, values);
    compare(observe(dut, count, legacy), oracle(count, masks, values), count, masks, label);
    ++operandChecks;
}

static void checkOverride(SI1OperandSingletonFixture &dut, uint32_t masks, const Values &values,
                          bool overrideEnable, bool registerEnable, uint64_t overrideValue,
                          const std::string &label, bool legacy = false) {
    drive(dut, masks, values, overrideEnable, registerEnable, overrideValue);
    const uint64_t expected = overrideEnable ? overrideValue :
                              (registerEnable ? oracle(4, masks, values) : 0);
    compare(legacy ? dut.get_io$$legacyOverridden() : dut.get_io$$overridden(),
            expected, 4, masks, label);
    ++overrideChecks;
}

static Values poisonValues(unsigned count) {
    Values values{};
    for (unsigned lane = 0; lane < values.size(); ++lane)
        values[lane] = (uint64_t(1) << (lane % 32)) | (uint64_t(1) << (32 + lane % 32));
    values[count - 1] = 0x8000000000000040ULL;
    return values;
}

static void negative(SI1OperandSingletonFixture &dut, const std::string &flag) {
    for (const unsigned count : {1U, 4U, 7U, 10U}) {
        const std::string zero = "--legacy-zero-n" + std::to_string(count);
        const std::string first = "--legacy-first-n" + std::to_string(count);
        if (flag == zero || (count != 1 && flag == first)) {
            std::cout << "REACHED " << flag << " test-only exact legacy helper" << std::endl;
            checkOperand(dut, count, flag == zero ? 0 : 1, poisonValues(count), flag, true);
            throw std::runtime_error("NEGATIVE_CONTROL_ESCAPED");
        }
    }
    if (flag == "--legacy-override-enabled" || flag == "--legacy-register-disabled") {
        std::cout << "REACHED " << flag << " test-only exact legacy helper" << std::endl;
        checkOverride(dut, 0xf, poisonValues(4), flag == "--legacy-override-enabled", false,
                      0x0102030405060708ULL, flag, true);
        throw std::runtime_error("NEGATIVE_CONTROL_ESCAPED");
    }
    throw std::runtime_error("unknown negative-control flag");
}

int main(int argc, char **argv) {
    try {
        SI1OperandSingletonFixture dut;
        static_assert(std::is_trivially_copyable_v<SI1OperandSingletonFixture>);
        std::memset(&dut, 0, sizeof(dut));
        dut.LOG_START = 1;
        dut.activateAll();
        dut.set_reset(1);
        drive(dut, 0, Values{});
        drive(dut, 0, Values{});
        dut.set_reset(0);
        if (argc > 2) throw std::runtime_error("expected at most one mode flag");
        const std::string flag = argc == 2 ? argv[1] : "";
        const bool legacyControls = flag == "--legacy-controls";
        if (!flag.empty() && !legacyControls) negative(dut, flag);

        std::mt19937_64 rng(0x49314f504552414eULL);
        for (const unsigned count : counts) {
            if (legacyControls && count % 3 == 1) continue;
            Values values = poisonValues(count);
            const uint32_t all = (uint32_t(1) << count) - 1;
            checkOperand(dut, count, 0, values, "zero-mask-tail-poison", legacyControls);
            checkOperand(dut, count, 1, values, "first-only-tail-poison", legacyControls);
            checkOperand(dut, count, uint32_t(1) << (count - 1), values, "last-only", legacyControls);
            checkOperand(dut, count, all, values, "all-selected-or", legacyControls);
            for (unsigned lane = 0; lane < count; ++lane)
                checkOperand(dut, count, uint32_t(1) << lane, values, "every-single-selection", legacyControls);

            // Every payload bit in every lane, both selected and suppressed.
            for (unsigned lane = 0; lane < count; ++lane) {
                for (unsigned bit = 0; bit < 64; ++bit) {
                    values = {};
                    values[lane] = uint64_t(1) << bit;
                    checkOperand(dut, count, uint32_t(1) << lane, values, "walking-selected-bit", legacyControls);
                    checkOperand(dut, count, 0, values, "walking-suppressed-bit", legacyControls);
                }
            }
            // Exhaust masks through n=10; n=20 uses bounded random masks below.
            values = poisonValues(count);
            if (count <= 10) {
                for (uint32_t masks = 0; masks <= all; ++masks)
                    checkOperand(dut, count, masks, values, "exhaustive-mask-or", legacyControls);
            }
            for (unsigned trial = 0; trial < 1024; ++trial) {
                for (auto &value : values) value = rng();
                const uint32_t masks = uint32_t(rng()) & all;
                checkOperand(dut, count, masks, values, "seeded-random-or", legacyControls);
            }
        }
        if (!legacyControls) {
            const Values poison = poisonValues(4);
            checkOverride(dut, 0xf, poison, true, true, 0x0102030405060708ULL, "override-enabled-poison");
            checkOverride(dut, 0xf, poison, false, false, 0, "register-disabled-poison");
            for (unsigned mode = 0; mode < 4; ++mode) {
                for (uint32_t masks = 0; masks < 16; ++masks) {
                    for (unsigned trial = 0; trial < 64; ++trial) {
                        Values values{};
                        for (auto &value : values) value = rng();
                        checkOverride(dut, masks, values, mode & 1, mode & 2, rng(), "override-control-matrix");
                    }
                }
            }
        }
        if (operandChecks < 10000 || (!legacyControls && overrideChecks != 4098))
            throw std::runtime_error("COVERAGE_LOW");
        std::cout << (legacyControls ? "I1_OPERAND_LEGACY_CONTROLS_PASS" : "I1_OPERAND_SINGLETON_PASS")
                  << " widths=64 counts=" << (legacyControls ? "2,3,5,6,8,9,20" : "1,2,3,4,5,6,7,8,9,10,20")
                  << " operand_checks=" << operandChecks << " override_checks=" << overrideChecks << '\n';
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "I1 operand singleton rejection: " << error.what() << '\n';
        return 1;
    }
}
