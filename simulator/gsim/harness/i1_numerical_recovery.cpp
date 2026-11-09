// Independent architectural recovery scenarios on the production cached CPU.
// Literal results/IEEE bits and retire order are separate from pipeline control.
#define I1_COREMARK_MEMORY_ONLY
#include "five_stage_coremark.cpp"

struct RecoveryExpected {
    uint64_t pc, next, value, cause, tval;
    uint32_t instruction;
    unsigned rd;
    bool floating, trap;
};
struct RecoveryProgram {
    std::vector<uint8_t> image = std::vector<uint8_t>(0x12000);
    std::vector<RecoveryExpected> expected;
    unsigned cursor = 0;
    bool architectural = true;
    void bytes(unsigned offset, uint64_t value, unsigned size = 8) {
        for (unsigned n = 0; n < size; ++n) image.at(offset+n) = value >> (8*n);
    }
    void emit(uint32_t instruction, unsigned rd = 0, uint64_t value = 0,
              bool floating = false, unsigned advance = 4, unsigned cause = 0, uint64_t tval = 0) {
        if (architectural) expected.push_back({BASE+cursor, BASE+cursor+advance, value, cause, tval,
            instruction, rd, floating, cause != 0});
        bytes(cursor, instruction, 4); cursor += 4;
    }
    void complete() {
        emit(rr(0x33, 8, 0, 1, 2, 1), 8, 651); // a new real MUL owner
        emit(rr(0x33, 9, 4, 1, 2, 1), 9, 13);  // a new real DIV owner
        emit(rr(0x53, 3, 0, 1, 2, 1), 3, 0x400c000000000000ULL, true); // FADD.D = 3.5
        emit(rr(0x53, 4, 0, 3, 2, 0x0d), 4, 0x3ffc000000000000ULL, true); // FDIV.D = 1.75
        // The waiting younger integer ID changes continuous FPR read addresses.
        emit(rr(0x33, 13, 0, 2, 2), 13, 14);
        emit(rr(0x53, 14, 0, 4, 0, 0x71), 14, 0x3ffc000000000000ULL);
        emit(rr(0x53, 11, 0, 3, 0, 0x71), 11, 0x400c000000000000ULL); // FMV.X.D
        emit(ri(0x73, 12, 2, 0, 1), 12, 0); // wrong-path FDIV must not set fflags
        emit(st(3, 20, 8, 0x188));
        emit(0x00100073, 0, 0, false, 4, 3, BASE+cursor);
    }
    RecoveryProgram(unsigned wrongKind, bool error) {
        bytes(0x1000, 0x3ff8000000000000ULL); // 1.5
        bytes(0x1008, 0x4000000000000000ULL); // 2.0
        bytes(0x1100, 93);
        bytes(0x1180, 0x123456789abcdef0ULL);
        emit(0x00001a17, 20, BASE+0x1000); // AUIPC x20,1
        emit(0x00000297, 5, BASE+4);
        emit(ri(0x13, 5, 0, 5, 0x1fc), 5, BASE+0x200);
        emit(ri(0x73, 0, 1, 5, 0x305)); // mtvec = independent handler
        emit(ri(0x13, 1, 0, 0, 93), 1, 93);
        emit(ri(0x13, 2, 0, 0, 7), 2, 7);
        emit(0x00006537, 10, 0x6000);
        emit(0x30052073); // enable FP architectural state
        emit(ri(0x07, 1, 3, 20, 0), 1, 0x3ff8000000000000ULL, true);
        emit(ri(0x07, 2, 3, 20, 8), 2, 0x4000000000000000ULL, true);
        emit(ri(0x73, 0, 1, 0, 1)); // clear fflags
        emit(ri(0x03, 4, 3, 20, 0x100), error ? 0 : 4, 93, false, 4,
             error ? 5 : 0, error ? BASE+0x1100 : 0);
        architectural = !error;
        emit(br(0, 0, 0, 16), 0, 0, false, 16);
        architectural = false;
        const uint32_t wrong = wrongKind == 0 ? rr(0x33, 7, 0, 1, 2, 1) :
            wrongKind == 1 ? rr(0x33, 7, 4, 1, 2, 1) : rr(0x53, 7, 0, 2, 0, 0x0d);
        emit(wrong); // MUL, DIV, or FDIV.D by architectural zero
        emit(st(3, 20, 7, 0x180));
        emit(ri(0x13, 31, 0, 0, 88));
        architectural = !error;
        complete();
        cursor = 0x200;
        architectural = error;
        complete();
    }
};

int main(int argc, char **argv) { try {
    const bool inject = argc > 1 && std::string(argv[1]) == "--inject";
    uint64_t totalOverlap = 0;
    unsigned cases = 0;
    for (unsigned kind = 0; kind < 3; ++kind) for (unsigned scenario = 0; scenario < 4; ++scenario) {
        const unsigned latency = scenario == 0 ? 1 : scenario == 1 ? 12 : 80;
        const bool error = scenario == 3;
        RecoveryProgram p(kind, error); Model d; Memory memory(d, p.image, latency);
        d.set_reset(1); d.set_io$$time(0); d.set_io$$externalIrq(0);
        d.set_io$$timerIrq(0); d.set_io$$softwareIrq(0); d.set_io$$invalidateReservation(0);
        memory.inputs(0); d.step(); d.step(); d.set_reset(0);
        unsigned checked = 0, redirects = 0, injectedBeats = 0;
        uint64_t overlap = 0, cycle;
        for (cycle = 0; cycle < 20000 && checked < p.expected.size(); ++cycle) {
            memory.inputs(cycle);
            if (error && memory.active == 1 && memory.owners[1]->prepared &&
                memory.owners[1]->address == BASE+0x1100) {
                memory.owners[1]->error = true;
                d.set_io$$dataMemory$$response$$bits$$error(1);
                ++injectedBeats;
            }
            d.set_io$$time(cycle); d.step(); memory.outputs(cycle);
            redirects += d.get_io$$branchMispredict();
            if (checked == 11 && d.get_io$$stallMemory() && d.get_io$$stallMulDiv()) ++overlap;
            if (!d.get_io$$retire$$valid()) continue;
            auto e = p.expected.at(checked);
            if (inject && checked == 4) e.value ^= 1;
            const std::string where = " recovery scenario="+std::to_string(scenario)+
                " kind="+std::to_string(kind)+" index="+std::to_string(checked);
            need(d.get_io$$retire$$bits$$pc() == e.pc &&
                 d.get_io$$retire$$bits$$instruction() == e.instruction, "recovery independent retire order"+where);
            need(bool(d.get_io$$retire$$bits$$trap()) == e.trap && (!e.trap ||
                 (d.get_io$$retire$$bits$$cause() == e.cause && d.get_io$$retire$$bits$$tval() == e.tval)),
                 "recovery independent precise trap"+where);
            need(bool(d.get_io$$retire$$bits$$writesRd()) == (e.rd != 0 && !e.floating && !e.trap),
                 "recovery independent integer write-enable"+where);
            need(bool(d.get_io$$retire$$bits$$floating$$write()) == e.floating &&
                 d.get_io$$retire$$bits$$floating$$flags() == 0, "recovery independent FP side effects"+where);
            if (e.rd && !e.trap) need(d.get_io$$retire$$bits$$rd() == e.rd &&
                (e.floating ? d.get_io$$retire$$bits$$floating$$data() : d.get_io$$retire$$bits$$data()) == e.value,
                "recovery independent value"+where);
            if (!e.trap) need(d.get_io$$retire$$bits$$nextPc() == e.next, "recovery independent next PC"+where);
            ++checked;
        }
        need(checked == p.expected.size(), "recovery bounded completion");
        need(memory.load(BASE+0x1180) == 0x123456789abcdef0ULL && memory.load(BASE+0x1188) == 651 &&
             memory.writes == 1, "recovery independent store ledger");
        need(error ? injectedBeats > 0 : redirects > 0, "recovery stimulus coverage");
        if (kind < 2 && latency == 80) need(overlap > 0, "wrong-path MDU EX did not overlap older pending load");
        totalOverlap += overlap; ++cases;
        std::cout << "I1_NUMERICAL_RECOVERY_PASS kind=" << kind << " latency=" << latency << " load_error=" << error
            << " cycles=" << cycle << " retired=" << checked << " wrong_path_mdu_ex_overlap=" << overlap
            << " redirects=" << redirects << " error_beats=" << injectedBeats << '\n';
    }
    std::cout << "I1_NUMERICAL_RECOVERY_SUITE_PASS cases=" << cases << " overlap=" << totalOverlap
        << " literal_retire_IEEE_flags_traps_store_new_owner=PASS fp_wrongpath_serial_suppression=PASS\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
