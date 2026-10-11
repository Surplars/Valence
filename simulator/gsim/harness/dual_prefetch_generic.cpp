// Additive entry points for exactly two approved generic-flag checks.
// The original ten-case main is compiled under another name and never called.
#define main dual_prefetch_tracking_original_main
#include "dual_prefetch_tracking.cpp"
#undef main

int main(int argc, char** argv) {
    using namespace dual_prefetch;
    try {
        std::string selected;
        for (int i = 1; i < argc; ++i) {
            const std::string arg = argv[i];
            if (arg.rfind("--case=", 0) == 0) selected = arg.substr(7);
            else if (arg.rfind("--images=", 0) == 0) imageDirectory = arg.substr(9);
            else if (arg == "--inject-mismatch") injectMismatch = true;
            else if (arg == "--inject-token-address") mutation = "token-address";
            else if (arg == "--inject-victim") mutation = "victim";
            else throw std::runtime_error("unknown generic gate option: " + arg);
        }
        check(split, "generic flag gate requires actual split tracking ON");
        check(unsigned(injectMismatch) + unsigned(!mutation.empty()) <= 1,
            "run generic negative controls separately");
        if (selected == "one-way") {
            check(CACHE_WAYS == 1 && mutation != "victim", "one-way case/model/negative mismatch");
            one_way_veto();
        } else if (selected == "lru-protected") {
            check(CACHE_WAYS == 2 && lru, "protected LRU case requires actual two-way/LRU-ON model");
            protected_dirty_release();
        } else throw std::runtime_error("explicit --case=one-way|lru-protected required");
        check(mutation.empty(), "requested generic negative control did not fail");
        check(completedCases == 1, "generic invocation ran more than its selected focused case");
        std::cout << "DUAL_PREFETCH_GENERIC_PASS case=" << selected << " split=1 store_lru=" << lru
            << " ways=" << CACHE_WAYS << " lifetime=" << PF_CANDIDATE_CYCLES
            << " cases=1 actual_cache_home=1 full_flush=1 executing_cpu=0 performance_qualification=0\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "DUAL_PREFETCH_GENERIC_FAIL " << error.what() << '\n'; return 1;
    }
}
