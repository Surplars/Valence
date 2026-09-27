/* Runs before interrupts are enabled; all state lives in the platform's ordinary RAM. */
unsigned long boot_workload(void) {
    volatile unsigned *values = (volatile unsigned *)0x80010100UL;
#ifdef TILELINK_SPLIT_BOOT
    volatile unsigned *highValues = (volatile unsigned *)0x80010900UL;
#endif
    unsigned long sum = 0;
    for (unsigned i = 0; i < 16; ++i) {
#ifdef TILELINK_SPLIT_BOOT
        if (i >= 8) highValues[i - 8] = i * 3 + 1;
        else values[i] = i * 3 + 1;
#else
        values[i] = i * 3 + 1;
#endif
    }
#ifdef LATENCY_BOOT
    /* Drain initialization writes before measuring independent external reads. */
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    for (unsigned repeat = 0; repeat < 16; ++repeat) {
        unsigned v0 = values[0], v1 = values[1], v2 = values[2], v3 = values[3];
        unsigned v4 = values[4], v5 = values[5], v6 = values[6], v7 = values[7];
        unsigned v8 = values[8], v9 = values[9], v10 = values[10], v11 = values[11];
        unsigned v12 = values[12], v13 = values[13], v14 = values[14], v15 = values[15];
        sum += v0 + v1 + v2 + v3 + v4 + v5 + v6 + v7 + v8 + v9 + v10 + v11 + v12 + v13 + v14 + v15;
    }
    sum /= 16;
#else
    for (unsigned i = 0; i < 16; ++i) {
#ifdef TILELINK_SPLIT_BOOT
        sum += i >= 8 ? highValues[i - 8] : values[i];
#else
        sum += values[i];
#endif
    }
#endif
    return sum;
}
