// Directed architectural expectations are literal ISA encodings and IEEE values.
// The production cached CPU and the unchanged CoreMark burst service are reused.
#define I1_COREMARK_MEMORY_ONLY
#include "five_stage_coremark.cpp"

struct ExpectedInstruction {
    uint64_t pc, next, value; uint32_t instruction;
    unsigned rd, flags; bool integer, floating, trap;
};
struct Program {
    std::vector<uint8_t> image = std::vector<uint8_t>(0x12000);
    std::vector<ExpectedInstruction> expected;
    unsigned cursor = 0;
    void bytes(uint64_t offset, uint64_t value, unsigned size) {
        for (unsigned n = 0; n < size; ++n) image.at(offset + n) = value >> (8*n);
    }
    void emit(uint32_t instruction, unsigned rd = 0, uint64_t value = 0,
              bool floating = false, unsigned flags = 0, unsigned length = 4,
              bool trap = false, unsigned advance = 0) {
        expected.push_back({BASE+cursor, BASE+cursor+(advance?advance:length), value,
            instruction, rd, flags, rd != 0 && !floating, floating, trap});
        bytes(cursor, instruction, length); cursor += length;
    }
    void fp(unsigned function, unsigned rd, unsigned a, unsigned b, uint64_t value, unsigned flags = 0) {
        emit(function<<25 | b<<20 | a<<15 | rd<<7 | 0x53, rd, value, true, flags);
    }
    Program() {
        bytes(0x1000, 5, 8);
        bytes(0x1010, 0x400000003fc00000ULL, 8); // 1.5f, 2.0f
        bytes(0x1018, 0x40800000, 8);             // 4.0f, +0.0f
        bytes(0x1028, 0x3ff8000000000000ULL, 8); // 1.5
        bytes(0x1030, 0x4000000000000000ULL, 8); // 2.0
        bytes(0x1038, 0x4010000000000000ULL, 8); // 4.0
        emit(0x00001097, 1, BASE+0x1000); // AUIPC x1,1
        emit(0x00700113, 2, 7);
#ifdef I1_WITH_A
        auto amo = [&](unsigned operation, unsigned rd, unsigned source, uint64_t value) {
            emit(operation<<27 | 3<<25 | source<<20 | 1<<15 | 3<<12 | rd<<7 | 0x2f, rd, value);
        };
        amo(0, 3, 2, 5);  // AMOADD.D.aqrl: 5 -> 12
        amo(2, 4, 0, 12); // LR.D
        emit(0x00d00113, 2, 13);
        amo(3, 5, 2, 0);  // successful SC.D, RAM -> 13
        amo(3, 6, 2, 1);  // consumed reservation, failed SC.D
        emit(0x0000b383, 7, 13); // LD readback
#endif
#ifdef I1_WITH_C
        emit(0x4415, 8, 5, false, 0, 2);  // C.LI
        emit(0x0405, 8, 6, false, 0, 2);  // C.ADDI
        emit(0x9422, 8, 12, false, 0, 2); // C.ADD
        emit(0x84a2, 9, 12, false, 0, 2); // C.MV
        emit(0x0001, 0, 0, false, 0, 2);  // C.NOP; next word straddles an XLEN word
        emit(0x00148493, 9, 13);
        emit(0xa011, 0, 0, false, 0, 2, false, 4); // C.J +4 kills the next parcel
        bytes(cursor, 0x447d, 2); cursor += 2;
        emit(0x0405, 8, 13, false, 0, 2);
#endif
#ifdef I1_WITH_F
        emit(0x00006537, 10, 0x6000);
        emit(0x30052073); // CSRRS mstatus, x10: enable architectural FP state
        emit(0x0100a087, 1, 0xffffffff3fc00000ULL, true);
        emit(0x0140a107, 2, 0xffffffff40000000ULL, true);
        fp(0x00, 3, 1, 2, 0xffffffff40600000ULL); // 1.5 + 2 = 3.5
        fp(0x08, 4, 1, 2, 0xffffffff40400000ULL); // 1.5 * 2 = 3
        fp(0x0c, 5, 4, 1, 0xffffffff40000000ULL); // 3 / 1.5 = 2
        emit(0x0180a387, 7, 0xffffffff40800000ULL, true);
        fp(0x2c, 6, 7, 0, 0xffffffff40000000ULL); // sqrt(4) = 2
        emit(1<<27 | 2<<20 | 1<<15 | 8<<7 | 0x43, 8, 0xffffffff40900000ULL, true); // FMA = 4.5
        emit(0xc00415d3, 11, 4, false, 1); // FCVT.W.S RTZ, NX
        emit(0xe0018653, 12, 0x40600000); // FMV.X.W f3
        emit(0x0230a027); // FSW f3,32(x1)
        emit(0x0200a683, 13, 0x40600000);
        emit(0x01c0a007, 0, 0xffffffff00000000ULL, true);
        fp(0x0c, 9, 1, 0, 0xffffffff7f800000ULL, 8); // division by zero
        emit(0x00102773, 14, 9); // accumulated fflags = NX | DZ
#ifdef I1_WITH_D
        emit(0x0280b507, 10, 0x3ff8000000000000ULL, true);
        emit(0x0300b587, 11, 0x4000000000000000ULL, true);
        fp(0x01, 12, 10, 11, 0x400c000000000000ULL);
        fp(0x09, 13, 10, 11, 0x4008000000000000ULL);
        emit(0x0380b707, 14, 0x4010000000000000ULL, true);
        fp(0x2d, 14, 14, 0, 0x4000000000000000ULL);
        fp(0x21, 15, 3, 0, 0x400c000000000000ULL); // FCVT.D.S
        fp(0x20, 16, 10, 1, 0xffffffff3fc00000ULL); // FCVT.S.D
        emit(0x04c0b027); // FSD f12,64(x1)
        emit(0x0400b783, 15, 0x400c000000000000ULL);
#endif
#endif
        emit(0x00100073, 0, 0, false, 0, 4, true);
    }
};
int main(int argc, char **argv) { try {
    const bool inject = argc > 1 && std::string(argv[1]) == "--inject";
    for (unsigned latency : {1U, 12U}) {
        Program p; Model d; Memory memory(d, p.image, latency);
        d.set_reset(1); d.set_io$$time(0); d.set_io$$externalIrq(0);
        d.set_io$$timerIrq(0); d.set_io$$softwareIrq(0);
#ifdef I1_WITH_A
        d.set_io$$invalidateReservation(0);
#endif
        memory.inputs(0); d.step(); d.step(); d.set_reset(0);
        unsigned checked = 0, fpWrites = 0;
        for (uint64_t cycle = 0; cycle < 30000 && checked < p.expected.size(); ++cycle) {
            memory.inputs(cycle); d.set_io$$time(cycle); d.step(); memory.outputs(cycle);
            if (!d.get_io$$retire$$valid()) continue;
            auto e = p.expected.at(checked);
            if (inject && checked == 1) e.value ^= 1;
            const uint64_t pc = d.get_io$$retire$$bits$$pc();
            const uint32_t ins = d.get_io$$retire$$bits$$instruction();
            need(pc == e.pc && ins == e.instruction, "extension independent PC/instruction oracle index="+std::to_string(checked));
            need(bool(d.get_io$$retire$$bits$$trap()) == e.trap &&
                (!e.trap || d.get_io$$retire$$bits$$cause() == 3), "extension independent exception oracle index="+std::to_string(checked));
            need(bool(d.get_io$$retire$$bits$$writesRd()) == e.integer,
                "extension independent integer write-enable oracle index="+std::to_string(checked));
            if (e.integer) need(d.get_io$$retire$$bits$$rd() == e.rd && d.get_io$$retire$$bits$$data() == e.value,
                "extension independent integer value oracle index="+std::to_string(checked));
#ifdef I1_WITH_F
            need(bool(d.get_io$$retire$$bits$$floating$$write()) == e.floating,
                "extension independent FP write-enable oracle index="+std::to_string(checked));
            if (e.floating) {
                need(d.get_io$$retire$$bits$$rd() == e.rd && d.get_io$$retire$$bits$$floating$$data() == e.value,
                    "extension independent IEEE value oracle index="+std::to_string(checked));
                ++fpWrites;
            }
            need(d.get_io$$retire$$bits$$floating$$flags() == e.flags,
                "extension independent IEEE flags oracle index="+std::to_string(checked));
#endif
            if (!e.trap) need(d.get_io$$retire$$bits$$nextPc() == e.next, "extension independent next-PC oracle");
            ++checked;
        }
        need(checked == p.expected.size(), "extension program bounded completion");
#ifdef I1_WITH_A
        need(memory.load(BASE+0x1000) == 13, "extension atomic final RAM oracle");
#endif
#ifdef I1_WITH_F
        need(memory.load(BASE+0x1020,4) == 0x40600000, "extension FP store RAM oracle");
#endif
        std::cout << "I1_EXTENSIONS_PASS latency=" << latency << " instructions=" << checked
            << " fp_writes=" << fpWrites << " precise_retire_integer_FP_flags_memory=PASS\n";
    }
    return 0;
} catch (const std::exception &error) { std::cerr << error.what() << '\n'; return 1; } }
