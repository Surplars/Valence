int main(int argc, char **argv) { try {
    const std::string mode = argc > 1 ? argv[1] : "";
    require(argc <= 2 && (mode.empty() || mode == "--inject-pa" || mode == "--inject-data" ||
        mode == "--inject-fault" || mode == "--inject-canonical" || mode == "--inject-hint" ||
        mode == "--force-undrained-flush" || mode == "--force-invalid-sidecar"), "unknown option");
    {
        Bench b(mode);
        for (unsigned size = 0; size < 4; ++size)
            for (unsigned offset = 0; offset < 8; offset += (1u << size)) {
                const auto ph = b.physical; b.run(b.certified(ram + offset, size));
                b.check(b.physicalLatencies.at(ph) == (CERTIFIED_LOAD_INGRESS ? 1u : 2u),
                    "empty direct versus registered fallback fixed latency mismatch");
            }
        b.check(b.physical == 15 && !b.faults && b.ingressDirect == (CERTIFIED_LOAD_INGRESS ? 15u : 0u),
            "empty certified byte/half/word/double route coverage missing");
        b.report("empty_certified_shapes");
    }
    {
        Bench b(mode); b.run(b.raw()); // real walker then warm write/read reuse
        b.blockPhysical = b.cycle + 90; b.blockResponse = b.cycle + 150;
        b.periodic = true; b.latency = 5; b.pteLatency = 7;
        for (unsigned n = 0; n < 96; ++n) {
            auto r = n % 2 ? b.certified(ram + (n % 16) * 8) : b.raw(va + (n % 16) * 8, n % 4 == 0);
            if (n % 11 == 3) --r.translationEpoch;
            if (n == 12 || n == 36) r.descriptor.virtualAddress = va + 9 * 4096;
            if (n == 16 || n == 40) r.descriptor.virtualAddress = va + 4096;
            if (n == 22) { r.descriptor.virtualAddress = va + 4 * 4096; r.write = false; r.origin = false; }
            if (n == 24) { r.uncached = true; r.origin = false; }
            if (n == 26) { r.atomic = true; r.atomicOp = 2; r.write = false; r.origin = false; }
            if (n == 28) { r.origin = false; r.lateError = true; }
            b.send(r);
        }
        b.drain();
        b.check(b.faults && b.lateErrors && b.walks >= 3 && b.certificates && b.acceptedMissWaiting &&
            b.heldPhysical && b.heldResponses && b.heldUpstream && b.olderPopNewSpill &&
            b.checkedFull && b.translatedFull && b.fullCheckedDequeue,
            "mixed older ingress/translated/walker/full dequeue/held/fault witnesses missing");
        b.report("mixed_order_congestion_and_errors");
    }
    {
        Bench b;
        b.context = (b.context & ~(15ULL << 60)) | (1ULL << 60); b.maintenance();
        // A reserved mode is not a valid integrated certificate producer. At
        // this defensive PA boundary legacy final permission allows it: direct
        // conservatism MUST NOT turn that rejection into a new sticky fault.
        b.run(b.certified());
        b.check(b.physical == 1 && !b.faults && !b.ingressDirect && b.incomingFires == 1 &&
            b.physicalLatencies.front() == 2, "qualifier-only rejection became fallback fault or direct capture");
        b.report("qualifier_false_final_permission_true");
    }
    {
        Bench b(mode);
        for (unsigned kind = 0; kind < 12; ++kind) {
            auto r = b.certified();
            if (kind == 0) --r.translationEpoch;
            if (kind == 1) r.descriptor.virtualAddress = 0x10000000ULL;
            if (kind == 2) r.descriptor.virtualAddress = ram + ramBytes;
            if (kind == 3) r.write = true;
            if (kind == 4) { r.atomic = true; r.atomicOp = 2; }
            if (kind == 5) r.virt = true;
            if (kind == 6) r.uncached = true;
            if (kind == 7) r.descriptor.virtualAddress = ram + ramBytes - 4;
            if (kind == 8) r.descriptor.virtualAddress = ram | (1ULL << 48);
            if (kind == 9) r.descriptor.virtualAddress = ~3ULL;
            if (kind == 10) r.descriptor.mask = 0x7f;
            if (kind == 11) r.descriptor.virtualAddress = ram + 1;
            b.run(r);
        }
        b.check(!b.physical && b.faults == 12 && !b.ingressDirect, "forged certified permission escaped fallback refusal");
        b.report("stale_shape_original_range_wrap_faults");
    }
    {
        Bench b;
        // Lowest-address entry wins, even when a later entry allows all.
        b.cfg = 0x18; b.pmpAddress = ram >> 2;
        b.cfg1 = 0x1f; b.pmpAddress1 = virtual_load_test::allPmp; b.maintenance(false);
        b.run(b.certified()); b.run(b.certified(ram + 8));
        b.check(b.faults == 1 && b.physical == 1, "first matching deny lost priority");
        // Lowest match allows 4 bytes only: later full allow cannot repair partial.
        b.cfg = 0x11; b.maintenance(false); b.run(b.certified());
        b.check(b.faults == 2, "partial NA4 match borrowed later full coverage");
        b.run(b.certified(ram, 2));
        // OFF entry address defines following TOR lower bound.
        b.cfg = 0; b.pmpAddress = ram >> 2;
        b.cfg1 = 0x09; b.pmpAddress1 = (ram + 8) >> 2;
        b.cfg2 = 0x18; b.pmpAddress2 = virtual_load_test::allPmp; b.maintenance(false);
        b.run(b.certified()); b.run(b.certified(ram + 8));
        b.check(b.faults == 3 && b.physical == 3, "TOR/OFF predecessor or later deny mismatch");
        // M-mode unlocked PMP permits; locked matching entry denies ordinary
        // Bare demand access. Certified M-mode is independently forbidden.
        b.cfg = 0x18; b.pmpAddress = virtual_load_test::allPmp; b.cfg1 = b.cfg2 = 0;
        b.privilege = 3; b.context = 0; b.maintenance(); b.run(b.raw(ram, false));
        b.cfg = 0x98; b.maintenance(false); b.run(b.raw(ram, false));
        b.check(b.faults == 4 && b.physical == 4, "locked versus unlocked M-mode PMP mismatch");
        b.report("pmp_priority_partial_tor_locked");
    }
    {
        Bench b;
        for (unsigned change = 0; change < 8; ++change) {
            auto stale = b.certified();
            if (change == 1) b.context ^= 1ULL << 44;
            if (change == 2) b.context ^= 1ULL;
            if (change == 3) b.sum = !b.sum;
            if (change == 4) b.mxr = !b.mxr;
            if (change == 5) b.privilege = 0;
            if (change == 6) b.cfg = 0x18;
            if (change == 7) b.pmpAddress ^= 8;
            b.maintenance(change == 0); b.run(stale); b.run(b.certified(ram + 32));
        }
        b.report("drained_epoch_context_acceptance");
    }
    for (bool superpage : {false, true}) {
        Bench b; b.superpage = superpage;
        b.run(b.raw(va, false)); // warm actual 4KiB or 2MiB TLB mapping
        const auto ph = b.physical, hits = b.hits, walks = b.walks;
        b.run(b.raw(va | (1ULL << 39), false));
        b.run(b.raw(va | (1ULL << 38), false));
        b.check(b.physical == ph && b.faults == 2 && b.hits == hits && b.walks == walks + 2,
            "warm low-VPN alias bypassed real noncanonical translation fault");
        b.report(superpage ? "noncanonical_warm_superpage" : "noncanonical_warm_4k");
    }
    if (mode == "--force-invalid-sidecar") {
        Bench b;
        auto r = b.certified(); r.origin = true;
        // This violates the unchanged producer contract: origin.valid requires
        // an ordinary virtual write. It is not a legal fallback request.
        std::cout << "INJECT CERTIFIED_INGRESS invalid canonical sidecar on certified load\n" << std::flush;
        b.send(r);
        throw std::runtime_error("invalid sidecar producer assertion did not fire");
    }
    if (mode == "--force-undrained-flush") {
        Bench b; b.blockPhysical = b.cycle + 100; b.send(b.certified());
        for (unsigned n = 0; n < 10; ++n) b.tick();
        std::cout << "INJECT REGISTERED_RAW_CERTIFIED_FLOW undrained flush\n" << std::flush;
        b.flush = true; b.tick(); throw std::runtime_error("undrained flush assertion did not fire");
    }
    std::cout << "CERTIFIED_INGRESS_DTA_PASS enabled=" << CERTIFIED_LOAD_INGRESS << '\n'; return 0;
} catch (const std::exception &e) {
    std::cerr << "CERTIFIED_INGRESS_DTA_FAIL " << e.what() << '\n'; return 1;
} }
