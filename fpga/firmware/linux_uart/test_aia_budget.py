#!/usr/bin/env python3
"""Exercise the actual parent-handler C body with independent claim sequences."""
from pathlib import Path
import subprocess
import tempfile
import unittest

NET = Path(__file__).resolve().parents[1] / 'linux_net'


class AiaBudgetTests(unittest.TestCase):
    def test_actual_handler_yields_without_losing_next_claim(self):
        source = (NET / 'valence_aia.c').read_text()
        body = source[source.index('static void va_parent('):source.index('static irqreturn_t va_test_irq(')]
        fixture = r'''
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include "valence_irq_policy.h"
#define CSR_STOPEI 0
#define I_DELIVERY 0x70
struct vaia {
    void *dev, *domain;
    unsigned long parent_calls, claims, budget_yields;
    bool faulted;
};
struct irq_desc { struct vaia *data; };
struct irq_chip { int unused; };
static unsigned long pending[256];
static unsigned int position, length, delivery_disables, handled;
static int handle_failure;
static struct vaia *irq_desc_get_handler_data(struct irq_desc *d) { return d->data; }
static struct irq_chip *irq_desc_get_chip(struct irq_desc *d) { (void)d; return NULL; }
static void chained_irq_enter(struct irq_chip *c, struct irq_desc *d) { (void)c; (void)d; }
static void chained_irq_exit(struct irq_chip *c, struct irq_desc *d) { (void)c; (void)d; }
static unsigned long csr_swap(int csr, int value) {
    (void)csr; (void)value;
    return position < length ? pending[position++] : 0;
}
static int generic_handle_domain_irq(void *domain, unsigned int id) {
    (void)domain;
    if (id == 0 || id > 31) abort();
    ++handled;
    return handle_failure;
}
static void va_reg_write(int reg, int value) {
    if (reg != I_DELIVERY || value != 0) abort();
    ++delivery_disables;
}
#define dev_err_ratelimited(...) ((void)0)
'''
        fixture += body + r'''
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "line %d\n", __LINE__); return 1; } } while (0)
int main(void) {
    struct vaia p = {0};
    struct irq_desc d = { &p };
    // More than a budget of valid independent identities, including UART3
    // and DMA6. Exactly 64 must be consumed; the 65th remains pending.
    length = 130;
    for (unsigned int i = 0; i < length; ++i) {
        unsigned long id = 1 + i % 31;
        pending[i] = (id << 16) | id;
    }
    va_parent(&d);
    CHECK(position == 64 && handled == 64 && p.claims == 64);
    CHECK(p.budget_yields == 1 && !p.faulted && !delivery_disables);
    va_parent(&d);
    CHECK(position == 128 && handled == 128 && p.claims == 128);
    CHECK(p.budget_yields == 2 && !p.faulted && !delivery_disables);
    va_parent(&d);
    CHECK(position == 130 && handled == 130 && p.claims == 130);
    CHECK(p.budget_yields == 2 && !p.faulted && !delivery_disables);
    // Invalid identity is a real fault, unlike the busy-but-valid boundary.
    position = 0; length = 1; pending[0] = (32UL << 16) | 32;
    va_parent(&d);
    CHECK(p.faulted && delivery_disables == 1 && handled == 130);
    p.faulted = false; position = 0; pending[0] = (3UL << 16) | 3;
    handle_failure = 1;
    va_parent(&d);
    CHECK(p.faulted && delivery_disables == 2 && handled == 131);
    puts("AIA real parent handler PASS: 130 valid claims in 64/64/2, invalid/domain failures closed");
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'test.c').write_text(fixture)
            subprocess.run(['gcc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-I' + str(NET),
                            path / 'test.c', '-o', path / 'test'], check=True)
            subprocess.run([path / 'test'], check=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
