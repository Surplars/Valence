#include "branch_isa.h"
#include "branch_gold.h"
#include <functional>
int main(int argc, char** argv) {
    try {
        matched::require(argc == 3, "usage: gold-check ELF SYMBOLS");
        matched::Image image(argv[1], argv[2]);
        branch_isa::Oracle reference(image);
        reference.run(image);
        branch_gold::check_reference(reference);
        unsigned rejected = 0;
        auto reject = [&](const std::function<void()>& fn) {
            bool caught = false;
            try { fn(); } catch (const std::runtime_error&) { caught = true; }
            matched::require(caught, "gold checker accepted deliberate mismatch");
            ++rejected;
        };
        auto e = reference.events.at(3);
        auto altered = e; altered.pc ^= 4; reject([&] { branch_gold::check_event(altered, 3); });
        altered = e; altered.instruction ^= 1; reject([&] { branch_gold::check_event(altered, 3); });
        altered = e; altered.nextPc ^= 4; reject([&] { branch_gold::check_event(altered, 3); });
        altered = e; altered.rd ^= 1; reject([&] { branch_gold::check_event(altered, 3); });
        altered = e; altered.writes = !altered.writes; reject([&] { branch_gold::check_event(altered, 3); });
        altered = e; altered.data ^= 1; reject([&] { branch_gold::check_event(altered, 3); });
        reject([&] { branch_gold::check_event(e, reference.events.size()); });
        auto bad = reference; bad.events.pop_back(); reject([&] { branch_gold::check_reference(bad); });
        bad = reference; bad.events.push_back(e); reject([&] { branch_gold::check_reference(bad); });
        bad = reference; bad.regs[10] ^= 1; reject([&] { branch_gold::check_reference(bad); });
        bad = reference; ++bad.beginCount; reject([&] { branch_gold::check_reference(bad); });
        bad = reference; ++bad.endCount; reject([&] { branch_gold::check_reference(bad); });
        bad = reference; ++bad.retired; reject([&] { branch_gold::check_reference(bad); });
        bad = reference; bad.pc ^= 4; reject([&] { branch_gold::check_reference(bad); });
        std::cout << "BRANCH_SOURCE_GOLD_CHECK_PASS retired=" << reference.retired
            << " roi=" << reference.endCount - reference.beginCount << " rejected=" << rejected << '\n';
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
