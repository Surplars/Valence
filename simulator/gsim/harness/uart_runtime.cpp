// Independent wire/FIFO/interrupt exercise for the upstream 16550 runtime ABI.
// No CPU model, Linux execution, cycle-performance or board claim.
#include "UartConsole.h"
#include <cstdint>
#include <deque>
#include <iostream>
#include <stdexcept>
#include <vector>

static void check(bool ok, const char *message) {
    if (!ok) throw std::runtime_error(message);
}
struct Test {
    SUartConsole d;
    unsigned cycle = 0, reads = 0, interrupts = 0, txBatches = 0;
    unsigned phase = 0, timer = 0, txByte = 0, ier = 0;
    unsigned rxStart = 0;
    std::vector<unsigned> wireTx, wireRx, received;
    std::deque<unsigned> pending;
    void tick() {
        bool rx = true;
        if (cycle >= rxStart && cycle - rxStart < wireRx.size() * 160) {
            const auto at = cycle - rxStart;
            const unsigned bit = (at % 160) / 16;
            rx = bit == 0 ? false : bit == 9 ? true : (wireRx[at / 160] >> (bit - 1)) & 1;
        }
        d.set_io$$rx(rx);
        d.step(); ++cycle;
        const bool tx = d.get_io$$tx();
        if (!phase) { if (!tx) { phase = 1; timer = 23; txByte = 0; } }
        else if (timer) --timer;
        else if (phase <= 8) { txByte |= unsigned(tx) << (phase - 1); ++phase; timer = 15; }
        else { check(tx, "invalid TX stop bit"); wireTx.push_back(txByte); phase = 0; }
    }
    Test() {
        d.set_io$$mmio$$request$$valid(0); d.set_io$$mmio$$response$$ready(0);
        d.set_io$$mmio$$request$$bits$$size(0); d.set_io$$mmio$$request$$bits$$byteEnable(1);
        d.set_reset(1); tick(); tick(); d.set_reset(0);
    }
    unsigned access(unsigned offset, bool write = false, unsigned value = 0) {
        if (!write) ++reads;
        d.set_io$$mmio$$request$$bits$$address(0x10000000ULL + offset);
        d.set_io$$mmio$$request$$bits$$write(write); d.set_io$$mmio$$request$$bits$$data(value);
        d.set_io$$mmio$$request$$valid(1); d.set_io$$mmio$$response$$ready(0);
        unsigned wait = 0;
        do { tick(); check(++wait < 64, "FIFO handler performed blocking MMIO write"); }
        while (!d.get_io$$mmio$$request$$ready());
        d.set_io$$mmio$$request$$valid(0); tick();
        check(d.get_io$$mmio$$response$$valid() && !d.get_io$$mmio$$response$$bits$$error(), "MMIO failed");
        const unsigned result = d.get_io$$mmio$$response$$bits$$data();
        d.set_io$$mmio$$response$$ready(1); tick(); d.set_io$$mmio$$response$$ready(0);
        return result;
    }
    void service() {
        check(d.get_io$$irq(), "handler called without interrupt");
        ++interrupts;
        const unsigned iir = access(2);
        check(!(iir & 1), "IRQ without a pending IIR cause");
        unsigned lsr = access(5), budget = 256;
        while (lsr & 1) {
            check(!(lsr & 0x1e), "unexpected RX data loss/error");
            received.push_back(access(0));
            if (!--budget) break;
            lsr = access(5);
        }
        if ((lsr & 0x20) && (ier & 2)) {
            unsigned count = 16;
            ++txBatches;
            while (count-- && !pending.empty()) {
                access(0, true, pending.front()); pending.pop_front();
            }
            if (pending.empty()) { ier &= ~2U; access(1, true, ier); }
        }
    }
    void advance(unsigned count) {
        const auto until = cycle + count;
        while (cycle < until) { tick(); if (d.get_io$$irq()) service(); }
    }
};
int main(int argc, char **) { try {
    Test t;
    // Linux startup THRE tests: a second 0 -> THRI transition must reassert,
    // otherwise upstream 8250 silently falls back to a periodic backup timer.
    for (unsigned n = 0; n < 3; ++n) {
        t.access(1, true, 2);
        check(t.access(2) == 2, "THRE did not reassert after IER enable");
        check(t.access(2) == 1, "THRE IIR acknowledgement did not clear");
        t.access(1, true, 0);
    }
    t.access(2, true, 0x87); // FIFO enable/clear, RX trigger 8.
    t.ier = 7; t.access(1, true, t.ier);
    std::vector<unsigned> expectedTx;
    for (unsigned n = 0; n < 257; ++n) { expectedTx.push_back((n * 73 + 11) & 255); t.pending.push_back(expectedTx.back()); }
    for (unsigned n = 0; n < 137; ++n) t.wireRx.push_back((n * 29 + 7) & 255);
    t.rxStart = t.cycle + 200;
    t.advance(50000);
    if (argc > 1) expectedTx[17] ^= 1; // oracle mutation must fail.
    check(t.wireTx == expectedTx, "TX wire differs from independent software queue");
    check(t.received == t.wireRx, "full duplex RX FIFO drain lost/reordered input");
    check(t.pending.empty() && !(t.access(1) & 2), "TX-empty interrupt left enabled without queued output");
    check(t.txBatches <= 18, "TX did not batch the 16-byte FIFO");
    const auto idleReads = t.reads, idleIrqs = t.interrupts;
    t.advance(10000);
    check(t.reads == idleReads && t.interrupts == idleIrqs, "idle UART was polled or generated an IRQ storm");
    // One interactive byte below threshold must arrive through the four-char
    // timeout IRQ; no periodic software poll is allowed to discover it.
    t.wireRx = {0x5a}; t.rxStart = t.cycle + 20;
    const auto before = t.received.size();
    t.advance(1000);
    check(t.received.size() == before + 1 && t.received.back() == 0x5a, "short input timeout IRQ lost");
    check(!t.d.get_io$$irq(), "drained RX left level IRQ asserted");
    std::cout << "GSIM IRQ UART runtime PASS: tx=257 rx=138 batch<=16 idle_mmio=0 THRE_reassert=3 timeout=1 interrupts="
              << t.interrupts << " tx_batches=" << t.txBatches << '\n';
    return 0;
} catch (const std::exception &e) { std::cerr << "GSIM IRQ UART runtime FAIL: " << e.what() << '\n'; return 1; } }
