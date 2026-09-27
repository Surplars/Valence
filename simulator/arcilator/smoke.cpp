#include "GsimSmoke_arc.h"

#include <cstdint>
#include <iostream>
#include <stdexcept>

static void require(bool value, const char *message) {
    if (!value) throw std::runtime_error(message);
}

static void tick(GsimSmoke &model) {
    model.view.clock = 0;
    model.eval();
    model.view.clock = 1;
    model.eval();
    model.view.clock = 0;
    model.eval();
}

int main() {
    GsimSmoke model;
    auto &port = model.view;
    port.reset = 1;
    port.io_enable = 0;
    port.io_lhs = 0;
    port.io_rhs = 0;
    port.io_write = 0;
    port.io_address = 0;
    port.io_writeData = 0;
    port.io_mask = 0;
    port.io_read = 0;
    tick(model);
    require(port.io_count == 0, "reset failed");

    port.reset = 0;
    port.io_enable = 1;
    port.io_lhs = UINT64_MAX;
    port.io_rhs = 2;
    tick(model);
    require(port.io_sum == 1, "64-bit wraparound failed");
    require(port.io_count == 1, "counter enable failed");

    port.io_enable = 0;
    port.io_write = 1;
    port.io_mask = 15;
    port.io_address = 3;
    port.io_writeData = 0x12345678;
    tick(model);
    port.io_write = 0;
    port.io_read = 1;
    tick(model);
    port.io_read = 0;
    tick(model);
    require(port.io_readData == 0x12345678, "synchronous memory failed");
    std::cout << "Arcilator Windows smoke: PASS\n";
}
