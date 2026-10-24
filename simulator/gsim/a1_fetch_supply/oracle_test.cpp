#include "oracle.h"
#include <iostream>
#include <functional>
using namespace a1_fetch_oracle;
static void rejects(const std::function<void()> &test) {
    bool rejected = false;
    try { test(); } catch (const std::runtime_error &) { rejected = true; }
    require(rejected, "host negative was not rejected");
}
int main() {
    Image image; image.pattern = Pattern::mixed;
    require(image.length(image.virtualBase) == 2 && image.length(image.virtualBase + 2) == 4 &&
            image.length(image.virtualBase + 6) == 4 && image.length(image.virtualBase + 10) == 2,
            "independent image length schedule");
    for (auto offset : {6ULL, 62ULL, 4094ULL}) {
        const auto pc = image.virtualBase + offset;
        require(image.length(pc) == 4, "directed boundary must start a full instruction");
        const auto first = image.beat((pc - image.virtualBase + image.physicalBase) & ~7ULL);
        const auto second = image.beat(((pc - image.virtualBase + image.physicalBase) & ~7ULL) + 8);
        require(uint32_t(first >> 48) + (uint32_t(second & 65535) << 16) == image.instruction(pc),
                "byte oracle boundary reconstruction");
    }
    OrderedOwners ordered;
    ordered.request(8, 0, 0); ordered.request(16, 1, 1);
    require(ordered.response(5, 1).address == 8 && ordered.staleReplies == 1,
            "old generation reply ownership");
    require(ordered.response(6, 1).address == 16 && ordered.maximum == 2,
            "two ordered owners");
    rejects([&] { ordered.response(7, 1); });
    TlOwners tl;
    tl.request(3, 64, 6, 255, 0);
    for (unsigned i = 1; i <= 7; ++i) tl.response(3, 6, i);
    rejects([&] { tl.request(3, 128, 6, 255, 8); });
    tl.response(3, 6, 8); tl.request(3, 128, 6, 255, 8);
    rejects([&] { tl.response(2, 6, 9); });
    rejects([&] { tl.response(3, 3, 9); });
    rejects([&] { tl.request(4, 67, 3, 255, 9); });
    Counters counters;
    counters.sample(2, 2, 0, 0, 1); counters.sample(2, 2, 2, 2, 2); counters.validate();
    rejects([&] { counters.sample(0, 0, 0, 0, 3); });
    counters.consume[0]++; rejects([&] { counters.validate(); });
    std::cout << "PASS A1_FETCH_HOST_ORACLE byte boundaries, ordered generations, TL ownership, histogram negatives\n";
}
