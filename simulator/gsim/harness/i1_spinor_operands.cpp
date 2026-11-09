#include "SpinorScalarOperandsFixture.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
using Wide = unsigned _BitInt(128);
struct Form { uint32_t instruction; unsigned scalar; bool second, avl, x0, f0; };
// Independent native ABI examples: scalar 0=GPR, 1=FPR, 2=zimm7, 3=zimm0, 4=unused.
static constexpr std::array<Form, 12> forms{{
    {0x0220c0d7,0,false,false,false,false}, // vadd.vx
    {0x022040d7,0,false,false,true,false},  // vadd.vx x0
    {0x9620e0d7,0,false,false,false,false}, // vmul.vx
    {0x0220d0d7,1,false,false,false,false}, // vfadd.vf f1
    {0x420051d7,1,false,false,true,true},   // vfmv.s.f f0
    {0x0000f1d7,4,false,true,false,false},  // vsetvli: AVL is architectural rs1
    {0x8020f1d7,4,true,true,false,false},   // vsetvl: rs2 is vtype
    {0xcd02f1d7,4,false,false,true,false},  // vsetivli: immediate remains in instruction
    {0x0200e087,0,false,false,false,false}, // vle32.v physical base
    {0x0a20f0a7,0,true,false,false,false},  // vsse64.v signed byte stride
    {0x00809073,0,false,false,false,false}, // csrrw vstart, x1
    {0x0083d173,2,false,false,false,false}  // csrrwi vstart, 7
}};
static void need(bool value) {
    if (!value) throw std::runtime_error("independent Spinor scalar operand ABI oracle mismatch");
}
int main(int argc, char **argv) { try {
    SSpinorScalarOperandsFixture dut;
    const std::string mutation = argc == 2 ? argv[1] : "";
    std::mt19937_64 random(0x5343414c41523830ULL);
    uint64_t checks = 0, floatingZero = 0;
    for (const auto &form : forms) for (unsigned sample = 0; sample < 4096; ++sample) {
        const uint64_t left = form.x0 ? 0 : random(), right = random(), floating = random() | 1;
        const Wide token = (Wide(random() & 0xffff) << 64) | random();
        dut.set_io$$instruction(form.instruction);dut.set_io$$integerLeft(left);dut.set_io$$integerRight(right);
        dut.set_io$$floatingLeft(floating);dut.set_io$$token(token);dut.step();
        const Wide expectedToken = token ^ (mutation == "--truncate-token" ? Wide(1) << 79 : 0);
        need(dut.get_io$$command$$instruction() == form.instruction && dut.get_io$$command$$token() == expectedToken);
        if (form.scalar < 4) {
            uint64_t expected = form.scalar == 0 ? left : form.scalar == 1 ? floating : form.scalar == 2 ? 7 : 0;
            if (mutation == "--zero-f0" && form.f0) expected = 0;
            need(dut.get_io$$command$$scalar() == expected);
        }
        if (form.second) need(dut.get_io$$command$$scalar2() == right);
        if (form.avl) need(dut.get_io$$command$$avl() == left);
        floatingZero += form.f0; ++checks;
    }
    // Zero zimm must not read an unrelated GPR value.
    dut.set_io$$instruction(0x00f06173);dut.set_io$$integerLeft(UINT64_MAX);dut.step();
    need(dut.get_io$$command$$scalar() == 0);
    std::cout << "I1_SPINOR_OPERANDS_PASS cases=" << checks+1 << " f0_values=" << floatingZero
        << " full_80bit_token_GPR_FPR_f0_CSR_zimm_AVL_stride=PASS\n";
    return 0;
} catch(const std::exception &error) {std::cerr << error.what() << '\n'; return 1;} }
