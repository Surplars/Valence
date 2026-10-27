    // Standalone raw-invalid requests are intentionally newly rejected. They
    // are outside the integrated CPU producer's accepted alignment domain.
    for (unsigned route = 0; route < 6; ++route) {
        Bench b;
        if (route == 2) { b.context = 0; b.maintenance(); }
        if (route == 1) b.run(b.raw(va, false)); // warm raw hit, not only cold walking
        const auto beforePhysical = b.physical, beforeFaults = b.faults;
        for (unsigned size = 1; size <= 3; ++size) {
            for (bool write : {false, true}) {
                auto r = b.raw((route == 0 ? ram : va) + 1, write, size);
                if (route == 0) { r.virt = false; r.origin = false; }
                if (route == 2) r.descriptor.virtualAddress = ram + 1;
                if (route == 3) { r.uncached = true; r.origin = false; }
                if (route == 4) { r.atomic = true; r.atomicOp = write ? 3 : 2; r.origin = false; }
                b.run(r);
            }
        }
        b.check(b.physical - beforePhysical == (GUARDED_NATURAL_DTA ? 0u : 6u) &&
            b.faults - beforeFaults == (GUARDED_NATURAL_DTA ? 6u : 0u),
            "raw-invalid strict boundary did not preserve exact rejection count");
        b.report("guarded_raw_route_" + std::to_string(route));
    }
    {
        Bench b; b.blockPhysical = b.cycle + 100; b.blockResponse = b.cycle + 160;
        auto seed = b.raw(ram, false); seed.virt = false; b.send(seed);
        for (unsigned n = 0; n < 24; ++n) {
            auto r = b.raw(ram + 1 + 8 * (n % 8), n % 2, 3);
            r.virt = false; r.origin = false; b.send(r);
        }
        b.drain();
        b.check(b.accepted == 25 && b.returned == 25 && !b.certificates &&
            b.physical == (GUARDED_NATURAL_DTA ? 1u : 25u) &&
            b.faults == (GUARDED_NATURAL_DTA ? 24u : 0u) &&
            b.translatedPushes && b.identityPasses && b.heldResponses,
            "raw-invalid identity spill lost its guard, owner, or response ordering");
        b.report("guarded_identity_spill");
    }
    {
        Bench b;
        auto r = b.raw(va + 9 * 4096 + 1, false); b.run(r);
        r = b.raw(va + 9 * 4096 + 1, true); b.run(r);
        b.check(b.accepted == 2 && b.faults == 2 && !b.physical && !b.certificates,
            "raw-invalid page fault must retain pageFault priority and no authority");
        b.report("guarded_page_fault_priority");
    }
