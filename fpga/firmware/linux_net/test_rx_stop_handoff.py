#!/usr/bin/env python3
"""Execute the real driver's configuration/arm bodies with scripted MMIO.

This is a narrow host C test, not kernel/NAPI, RTL, or board execution. The
oracle uses ABI numeric addresses independently of the extracted definitions.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def function(source, name):
    start = source.index("static void " + name + "(")
    brace = source.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


STUBS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#define BIT_ULL(n) (1ULL << (n))
#define READ_ONCE(x) (x)
#define container_of(ptr, type, member) ((type *)((char *)(ptr) - offsetof(type, member)))
typedef uint64_t u64;
struct work_struct { int dummy; };
struct delayed_work { struct work_struct work; };
struct napi_struct { int polls; };
struct net_device { bool carrier; int wakes; };
struct vgmac {
    struct delayed_work configure;
    struct net_device *ndev;
    struct napi_struct napi;
    void *mac, *dma;
    int lock;
    uint64_t hw_address;
    bool running, configured, address_set, tx_pending, faulted;
};
static struct net_device dev;
static struct vgmac state;
static int mac_base, dma_base;
static uint64_t mac_regs[32], dma_regs[32];
static struct { bool mac; unsigned int offset; uint64_t value; } writes[16];
static int count, retries, fences;
static struct delayed_work *to_delayed_work(struct work_struct *w) { return container_of(w, struct delayed_work, work); }
static void spin_lock_bh(int *p) { (void)p; }
static void spin_unlock_bh(int *p) { (void)p; }
static bool netif_carrier_ok(struct net_device *p) { return p->carrier; }
static void netif_wake_queue(struct net_device *p) { p->wakes++; }
static unsigned int msecs_to_jiffies(unsigned int v) { return v; }
static void schedule_delayed_work(struct delayed_work *p, unsigned int delay) {
    (void)p; assert(delay == 100); retries++;
}
static void napi_schedule(struct napi_struct *p) { p->polls++; }
static void dma_wmb(void) { fences++; }
static uint64_t vg_read(void *base, unsigned int offset) {
    assert(offset < 256 && offset % 8 == 0);
    return (base == &mac_base ? mac_regs : dma_regs)[offset / 8];
}
static void vg_write(void *base, unsigned int offset, uint64_t value) {
    assert(count < 16 && offset < 256 && offset % 8 == 0);
    writes[count].mac = base == &mac_base;
    writes[count].offset = offset;
    writes[count++].value = value;
    if (base == &dma_base && offset == 0x40) {
        assert(!(dma_regs[0x48 / 8] & 1));
        assert(value == 3 && fences > 0);
        dma_regs[0x48 / 8] = 1;
    }
    if (base == &mac_base && (offset == 0x90 || offset == 0x10)) {
        /* A live consumer must precede either admitting or enabling RX. */
        assert(dma_regs[0x48 / 8] & 1);
    }
    if (base == &mac_base && offset == 0x90)
        assert(mac_regs[0x08 / 8] & (1ULL << 8));
    (base == &mac_base ? mac_regs : dma_regs)[offset / 8] = value;
}
static void reset_case(uint64_t cap) {
    state = (struct vgmac){0}; dev = (struct net_device){ .carrier = true };
    for (int i = 0; i < 32; ++i) mac_regs[i] = dma_regs[i] = 0;
    state.ndev = &dev; state.mac = &mac_base; state.dma = &dma_base;
    state.running = true; state.address_set = true;
    state.hw_address = 0x0256414c0001ULL;
    mac_regs[0x08 / 8] = cap; mac_regs[0x90 / 8] = 3;
    count = retries = fences = 0;
}
static void expect_write(int n, bool mac, unsigned int offset, uint64_t value) {
    assert(writes[n].mac == mac && writes[n].offset == offset && writes[n].value == value);
}
'''

CASES = r'''
int main(void) {
    /* New hardware: DMA start -> admission release -> MAC enable. */
    reset_case(1ULL << 8); vg_configure(&state.configure.work);
    assert(count == 3 && state.configured && dev.wakes == 1 && state.napi.polls == 1);
    expect_write(0, false, 0x40, 3); expect_write(1, true, 0x90, 0); expect_write(2, true, 0x10, 15);
    assert(mac_regs[0x90 / 8] == 0 && retries == 0);
    /* An ordinary zero capability word and unrelated bits both skip RX_STOP. */
    reset_case(0); vg_configure(&state.configure.work);
    assert(count == 2); expect_write(0, false, 0x40, 3); expect_write(1, true, 0x10, 15);
    reset_case(~(1ULL << 8)); vg_configure(&state.configure.work);
    assert(count == 2); expect_write(0, false, 0x40, 3); expect_write(1, true, 0x10, 15);
    /* Do not overwrite an owned descriptor or reopen admission while BUSY. */
    reset_case(1ULL << 8); dma_regs[0x48 / 8] = 1; vg_configure(&state.configure.work);
    assert(count == 0 && retries == 1 && !state.configured);
    /* Without link / while config CDC is busy / after ifdown: no release. */
    reset_case(1ULL << 8); dev.carrier = false; vg_configure(&state.configure.work);
    assert(count == 0 && retries == 1 && !state.configured);
    reset_case(1ULL << 8); mac_regs[0x28 / 8] = 6; vg_configure(&state.configure.work);
    assert(count == 0 && retries == 1 && !state.configured);
    reset_case(1ULL << 8); state.running = false; vg_configure(&state.configure.work);
    assert(count == 0 && retries == 0 && state.napi.polls == 0);
    /* Initial address mailbox gets its acknowledgement before enabling RX. */
    reset_case(1ULL << 8); state.address_set = false; vg_configure(&state.configure.work);
    assert(count == 1 && retries == 1 && !state.configured);
    expect_write(0, true, 0x18, state.hw_address);
    /* Ifup of an already-configured MAC must not replay DMA start or STOP. */
    reset_case(1ULL << 8); state.configured = true; dma_regs[0x48 / 8] = 1;
    vg_configure(&state.configure.work);
    assert(count == 0 && retries == 0 && state.napi.polls == 1);
    puts("PASS_LINUX_GMAC_RX_STOP_HANDOFF cases=9");
    return 0;
}
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--driver", type=Path, default=Path(__file__).with_name("valence_gmac.c"))
    ap.add_argument("--out", type=Path)
    ap.add_argument("--cc", default="cc")
    args = ap.parse_args()
    source = args.driver.read_text()
    definitions = "\n".join(re.findall(r"^#define (?:G_|D_)[^\n]+", source, re.M))
    bodies = function(source, "vg_arm_rx") + "\n" + function(source, "vg_configure")
    c = STUBS + definitions + "\n" + bodies + "\n" + CASES
    controls = {
        "omit_admission_release": c.replace("vg_write(p->mac, G_RX_STOP, 0);", "(void)0;"),
        "omit_rx_consumer": c.replace("vg_arm_rx(p);", "if (0) vg_arm_rx(p);"),
    }
    outputs = {}
    with tempfile.TemporaryDirectory(prefix="valence-gmac-handoff-") as tmp:
        root = Path(tmp)
        for name, code in {"positive": c, **controls}.items():
            assert name == "positive" or code != c, "Negative control did not mutate the test"
            path = root / (name + ".c")
            binary = root / name
            path.write_text(code)
            subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                            str(path), "-o", str(binary)], check=True)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            outputs[name] = dict(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
            if name == "positive":
                assert result.returncode == 0 and "PASS_LINUX_GMAC_RX_STOP_HANDOFF cases=9" in result.stdout, outputs[name]
            else:
                assert result.returncode != 0 and "Assertion" in result.stderr, outputs[name]
    receipt = dict(status="PASS_LINUX_GMAC_RX_STOP_HANDOFF_SCRIPTED_MMIO", cases=9,
                   negative_controls=2, driver_sha256=hashlib.sha256(args.driver.read_bytes()).hexdigest(),
                   compiler=subprocess.check_output([args.cc, "--version"], text=True).splitlines()[0],
                   scope="Actual vg_configure/vg_arm_rx C bodies, scripted MMIO and kernel API stubs; not full kernel, RTL, or board runtime",
                   outputs=outputs)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        assert not (args.out / "receipt.json").exists(), "Preserve prior result"
        (args.out / "harness.c").write_text(c)
        shutil.copy2(args.driver, args.out / "valence_gmac.c")
        (args.out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(receipt["status"])


if __name__ == "__main__":
    main()
