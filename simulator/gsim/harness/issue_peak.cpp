#include "CoremarkPlatformGsim.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>

static void drive(SCoremarkPlatformGsim &d) {
    d.set_io$$hold(0); d.set_io$$romWrite(0); d.set_io$$romIndex(0);
    d.set_io$$romData(0); d.set_io$$inspectRegister(0);
}
static void run(bool writes) {
    constexpr unsigned instructions = 2048;
    SCoremarkPlatformGsim d;
    drive(d); d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    for (unsigned i = 0; i <= instructions; ++i) {
        const unsigned rd = writes ? 1 + i % 31 : 0;
        const uint32_t inst = i == instructions ? 0x00100073u :
            ((i & 2047u) << 20) | (rd << 7) | 0x13u;
        drive(d); d.set_io$$hold(1); d.set_io$$romWrite(1);
        d.set_io$$romIndex(i); d.set_io$$romData(inst); d.step();
    }
    drive(d); d.set_io$$hold(1); d.step();
    uint64_t retired = 0, cycles = 0, commits[5] = {}, issues[5] = {};
    uint64_t fetchGets = 0, fetchWaits = 0;
    for (cycles = 1; cycles < 20000; ++cycles) {
        drive(d); d.step();
        unsigned n = d.get_io$$commit0() + d.get_io$$commit1() +
            d.get_io$$commit2() + d.get_io$$commit3();
        if (n > 4 || d.get_io$$issueCount() > 4) throw std::runtime_error("width mismatch");
        commits[n]++; issues[d.get_io$$issueCount()]++; retired += n;
        fetchGets += d.get_io$$fetchGetFire();
        fetchWaits += d.get_io$$fetchWait();
        if (d.get_io$$trap()) {
            if (d.get_io$$trapCause() != 3 || retired != instructions)
                throw std::runtime_error("wrong completion or trap");
            if (double(retired) / cycles < 1.9)
                throw std::runtime_error("independent stream throughput regressed: cycles=" +
                    std::to_string(cycles) + " retired=" + std::to_string(retired) +
                    " ipc=" + std::to_string(double(retired) / cycles) +
                    " commit4=" + std::to_string(commits[4]) +
                    " issue4=" + std::to_string(issues[4]) +
                    " fetchGets=" + std::to_string(fetchGets) +
                    " fetchWaits=" + std::to_string(fetchWaits));
            std::cout << (writes ? "independent-register-writes" : "independent-nop")
                      << " cycles=" << cycles << " retired=" << retired
                      << " ipc=" << double(retired) / cycles
                      << " commit4=" << commits[4] << " issue4=" << issues[4] << '\n';
            return;
        }
    }
    throw std::runtime_error("timeout");
}
static uint32_t jal(int offset) {
    const uint32_t imm = uint32_t(offset) & 0x1fffffu;
    return (((imm >> 20) & 1u) << 31) | (((imm >> 1) & 0x3ffu) << 21) |
           (((imm >> 11) & 1u) << 20) | (((imm >> 12) & 0xffu) << 12) | 0x6fu;
}
static void hotLoop() {
    SCoremarkPlatformGsim d;
    drive(d); d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    for (unsigned i = 0; i <= 32; ++i) {
        const uint32_t inst = i == 32 ? jal(-128) : ((i & 2047u) << 20) | 0x13u;
        drive(d); d.set_io$$hold(1); d.set_io$$romWrite(1);
        d.set_io$$romIndex(i); d.set_io$$romData(inst); d.step();
    }
    drive(d); d.set_io$$hold(1); d.step();
    uint64_t retired = 0, commit4 = 0, issue4 = 0;
    for (unsigned cycle = 0; cycle < 12000; ++cycle) {
        drive(d); d.step();
        if (d.get_io$$trap()) throw std::runtime_error("hot loop trapped");
        if (cycle >= 2000) {
            retired += d.get_io$$commit0() + d.get_io$$commit1() +
                d.get_io$$commit2() + d.get_io$$commit3();
            commit4 += d.get_io$$commit3(); issue4 += d.get_io$$issueCount() == 4;
        }
    }
    if (double(retired) / 10000 < 3.2)
        throw std::runtime_error("four-issue cached loop throughput regressed");
    std::cout << "hot-independent-loop cycles=10000 retired=" << retired
              << " ipc=" << double(retired) / 10000
              << " commit4=" << commit4 << " issue4=" << issue4 << '\n';
}
int main() { run(false); run(true); hotLoop(); }
