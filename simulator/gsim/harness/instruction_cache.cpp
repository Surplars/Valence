#include "FpgaFetchGsim.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>

static constexpr uint64_t base = 0x80000000;
static void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}
static uint32_t instruction(unsigned n) { return 0x00000013U | ((n & 0xfffU) << 20); }
static uint64_t packet(unsigned n) {
    return uint64_t(instruction(2 * n)) | (uint64_t(instruction(2 * n + 1)) << 32);
}
static void init(SFpgaFetchGsim &dut) {
    dut.set_io$$write(0);
    dut.set_io$$writeIndex(0);
    dut.set_io$$writeData(0);
    dut.set_io$$rom$$request$$valid(0);
    dut.set_io$$rom$$request$$bits(base);
    dut.set_io$$rom$$requestMask(3);
    dut.set_io$$rom$$response$$ready(1);
    dut.set_io$$pc(base);
    dut.set_io$$enable(0);
    dut.set_io$$invalidate(0);
    dut.set_io$$pmpCfg0(0);
    dut.set_io$$pmpAddr0(0);
    dut.set_io$$privilege(3);
    dut.set_io$$pause(1);
    dut.set_io$$fetch$$request$$ready(1);
    dut.set_io$$fetch$$response$$valid(0);
    dut.set_io$$fetch$$response$$bits(0);
    dut.set_io$$fetch$$responseError(0);
    dut.set_io$$fetch$$responsePageFault(0);
    dut.set_io$$bootHold(1);
    dut.set_io$$commitEnable(0);
    dut.set_reset(1);
    dut.step();
    dut.step();
    dut.set_reset(0);
}
static void fill(SFpgaFetchGsim &dut, unsigned n, uint64_t value) {
    dut.set_io$$pc(base + 8 * n);
    dut.set_io$$enable(1);
    dut.set_io$$pause(0);
    dut.step();
    check(dut.get_io$$fetch$$request$$valid() &&
          dut.get_io$$fetch$$request$$bits() == base + 8 * n &&
          dut.get_io$$fetch$$requestMask() == 3, "missing aligned packet fetch");
    dut.set_io$$pause(1);
    dut.set_io$$fetch$$response$$valid(1);
    dut.set_io$$fetch$$response$$bits(value);
    dut.step();
    check(dut.get_io$$instruction0$$valid() &&
          dut.get_io$$instruction0$$bits() == uint32_t(value), "response bypass mismatch");
    dut.set_io$$fetch$$response$$valid(0);
    dut.step();
    check(dut.get_io$$instruction0$$valid() &&
          dut.get_io$$instruction0$$bits() == uint32_t(value), "cached packet mismatch");
    dut.set_io$$enable(0);
    dut.step();
}
int main() {
    try {
        SFpgaFetchGsim dut;
        init(dut);
        for (unsigned n = 0; n < 5; ++n) fill(dut, n, packet(n));
        for (unsigned n = 0; n < 5; ++n) {
            dut.set_io$$pc(base + 8 * n);
            dut.set_io$$enable(1);
            dut.step();
            check(!dut.get_io$$fetch$$request$$valid() &&
                  dut.get_io$$instruction0$$valid() &&
                  dut.get_io$$instruction0$$bits() == instruction(2 * n) &&
                  dut.get_io$$instruction1$$valid() &&
                  dut.get_io$$instruction1$$bits() == instruction(2 * n + 1),
                  "multi-line instruction cache lost a resident packet");
        }
        dut.set_io$$invalidate(1);
        dut.step();
        check(!dut.get_io$$instruction0$$valid(), "invalidate exposed stale instruction");
        dut.set_io$$invalidate(0);
        fill(dut, 0, packet(17));
        std::cout << "GSIM multi-line instruction cache + invalidate: PASS packets=5\n";
    } catch (const std::exception &error) {
        std::cerr << "GSIM instruction cache: FAIL " << error.what() << '\n';
        return 1;
    }
}
