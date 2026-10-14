#include "RobCompletionPayloadGsim.h"
#include "rob_completion_payload_oracle.h"
#include "rob_payload_ram_oracle.h"
#include <cstdlib>
#include <iostream>
#include <new>
#include <stdexcept>
#include <string>

int main(int argc, char **argv) {
    try {
        if (argc > 2 || (argc == 2 && std::string(argv[1]) != "--payload-only"))
            throw std::runtime_error("usage: rob_completion_payload [--payload-only]");
        // Match existing GSIM initialization. Only public inputs are driven;
        // generated internal state is never modified after construction.
        void *storage = std::calloc(1, sizeof(SRobCompletionPayloadGsim));
        if (!storage) throw std::runtime_error("model allocation failed");
        auto *model = new (storage) SRobCompletionPayloadGsim;
        rob_payload_ram::run(*model);
        rob_completion_payload::run(*model);
        if (argc == 1) run_retirement_rob(*model);
        model->~SRobCompletionPayloadGsim();
        std::free(storage);
        std::cout << (argc == 1 ? "ROB_COMPLETION_PAYLOAD_PAIR_PASS\n" : "ROB_COMPLETION_PAYLOAD_DIRECTED_PASS\n");
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
