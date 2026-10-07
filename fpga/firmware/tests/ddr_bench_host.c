/* Independent reference checks for benchmark kernels, ring and units.
 * Runs on the host, NOT a replacement for board or hardware GSIM coverage.
 */
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#define DDR_BENCH_HOST_TEST 1
#define main ddr_bench_firmware_main
#include "../ddr_bench.c"
#undef main

static char output[2048];
static size_t length;
void ddr_bench_host_putc(char c) {
    assert(length + 1 < sizeof(output));
    output[length++] = c;
    output[length] = 0;
}
int main(void) {
    for (size_t bytes = 1024; bytes <= 8 * 1024 * 1024; bytes *= 2) {
        size_t words = bytes / 8;
        uint64_t *src = calloc(words, sizeof(uint64_t));
        uint64_t *dst = calloc(words, sizeof(uint64_t));
        uint8_t *ring = calloc(bytes, 1);
        assert(src && dst && ring);
        stream_write(src, words, 2);
        uint64_t expected = 0;
        for (size_t i = 0; i < words; ++i) {
            assert(src[i] == 0x10203040ULL + i);
            expected += 0x10203040ULL + i;
            dst[i] = ~src[i];
        }
        assert(stream_read(src, words, 3) == expected * 3);
        assert(expected_sum(words, 3) == expected * 3);
        stream_copy(dst, src, words, 2);
        assert(memcmp(dst, src, bytes) == 0);
        assert(verify(dst, words));

        size_t nodes = bytes / 64;
        build_chain((uintptr_t)ring, bytes);
        uintptr_t p = (uintptr_t)ring;
        unsigned char *seen = calloc(nodes, 1);
        assert(seen);
        for (size_t step = 0; step < nodes; ++step) {
            size_t i = (p - (uintptr_t)ring) / 64;
            assert(i < nodes && !seen[i]);
            seen[i] = 1;
            uintptr_t expected_link = (uintptr_t)ring + ((i + 257) % nodes) * 64;
            assert(*(uintptr_t *)p == expected_link);
            p = *(uintptr_t *)p;
        }
        assert(p == (uintptr_t)ring);
        assert(walk_chain((uintptr_t)ring, nodes) == (uintptr_t)ring);
        free(seen);
        free(ring);
        free(dst);
        free(src);
    }
    assert(rate_milli_mib(1048576, 50000000) == 1000); /* 1 MiB in 1 second */
    assert(rate_milli_mib(8388608, 25000000) == 16000);
    assert(rate_milli_mib(1048576, 100000000) == 500);
    assert(rate_milli_mib(0, 50000000) == 0);
    assert(rate_milli_mib(1048576, 0) == 0);
    fixed3(12034);
    assert(strcmp(output, "12.034") == 0);
    length = 0; output[0] = 0;
    uint64_t bad[8];
    stream_write(bad, 8, 1);
    bad[3] ^= 1;
    assert(!verify(bad, 8) && errors == 1); /* Negative corruption must fail. */
    assert(strstr(output, "VERIFY FAIL") != NULL);
    length = 0; output[0] = 0;
    assert(!report("zero-timer", 4096, 0, 1, 0) && errors == 2);
    assert(strstr(output, "FAIL") != NULL);
    puts("DDR benchmark host kernels/ring/units/corruption/zero-timer: PASS");
    return 0;
}
