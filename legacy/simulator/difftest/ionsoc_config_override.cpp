#include <cstdint>

extern uint64_t PMEM_BASE;
extern uint64_t FIRST_INST_ADDRESS;

#ifndef DIFFTEST_PMEM_BASE
#define DIFFTEST_PMEM_BASE 0x10000000UL
#endif

#ifndef DIFFTEST_FIRST_INST_ADDRESS
#define DIFFTEST_FIRST_INST_ADDRESS 0x80000000UL
#endif

// OpenXiangShan DiffTest exposes these as runtime globals, but its default
// config initializes both for a different platform. Override them before main
// so one integration can build independent bare-metal and Linux profiles.
__attribute__((constructor)) static void ionsoc_config_override() {
    PMEM_BASE = DIFFTEST_PMEM_BASE;
    FIRST_INST_ADDRESS = DIFFTEST_FIRST_INST_ADDRESS;
}
