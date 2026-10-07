#include <stdint.h>
#include <stddef.h>
#include "crc32.h"
#ifdef BOARD_NETBOOT
#include "netboot.h"
#endif

#ifndef UART_DIVISOR
#define UART_DIVISOR 1
#endif
#ifndef CPU_HZ
#define CPU_HZ 40000000ULL
#endif

#include "board_memory.h"
#define CHUNK_MAX 256U
#define HEADER_SEQ 0xffffffffU
#define UART ((volatile uint8_t *)0x10000000UL)
enum { OK, BAD_HEADER, BAD_RANGE, BAD_CRC, BAD_SEQUENCE, TIMEOUT };
static uint8_t packet[CHUNK_MAX];
static uint32_t image_entry, image_length;
static unsigned image_valid;
static unsigned image_network;
extern void run_image(uintptr_t entry);

#ifdef BOOTROM_TEST
extern uint64_t boot_test_now(void);
extern int boot_test_getc(uint64_t);
extern void boot_test_putc(uint8_t);
extern uint8_t *boot_test_ram(void);
#endif
static uint8_t *image_memory(unsigned offset) {
#ifdef BOOTROM_TEST
    return boot_test_ram()+offset;
#else
    return (uint8_t *)(RAM_BASE+offset);
#endif
}
static uint64_t cycles(void) {
#ifdef BOOTROM_TEST
    return boot_test_now();
#else
    uint64_t n;
    /* Board timerTick is one per clock; this core exposes time, not cycle CSR. */
    __asm__ volatile ("rdtime %0" : "=r"(n) :: "memory");
    return n;
#endif
}

static void uart_init(void) {
#ifndef BOOTROM_TEST
    while (!(UART[5] & 0x40)) {}
    UART[3] = 0x83;
    UART[0] = UART_DIVISOR & 255;
    UART[1] = UART_DIVISOR >> 8;
    UART[3] = 3;
    UART[1] = 0;
    /* Enable both 16-byte FIFOs and clear them; keep RX trigger at one byte. */
    UART[2] = 7;
#endif
}

static void putc_uart(uint8_t c) {
#ifdef BOOTROM_TEST
    boot_test_putc(c);
#else
    while (!(UART[5] & 0x20)) {}
    UART[0] = c;
#endif
}
static void flush_uart(void) {
#ifndef BOOTROM_TEST
    while (!(UART[5] & 0x40)) {}
#endif
}

static void puts_uart(const char *s) {
    while (*s) putc_uart((uint8_t)*s++);
}

static void hex64(uint64_t n) {
    for (int shift = 60; shift >= 0; shift -= 4) {
        unsigned d = (n >> shift) & 15;
        putc_uart(d < 10 ? '0' + d : 'a' + d - 10);
    }
}

static void uart_stage(const char *stage,uint64_t ticks,uint32_t length) {
    puts_uart("UART stage="); puts_uart(stage); puts_uart(" ticks=0x"); hex64(ticks);
    puts_uart(" length=0x"); hex64(length); puts_uart(" timebase_hz=0x"); hex64(CPU_HZ);
    puts_uart("\r\n");
}
static void uart_crc_failure(const char *stage,uint32_t length,uint32_t expected,uint32_t actual) {
    puts_uart("UART fail stage="); puts_uart(stage); puts_uart(" length=0x"); hex64(length);
    puts_uart(" expected_crc=0x"); hex64(expected); puts_uart(" actual_crc=0x"); hex64(actual);
    puts_uart("\r\n");
}

/* Drain RX FIFO promptly; CRC/copy work remains outside the receive loop. */
static int getc_timeout(uint64_t budget) {
#ifdef BOOTROM_TEST
    return boot_test_getc(budget);
#else
    uint64_t start = cycles();
    do {
        unsigned status = UART[5];
        if (status & 0x0a) {
            if (status & 1) (void)UART[0];
            return -2;
        }
        if (status & 1) return UART[0];
    } while (cycles() - start < budget);
    return -1;
#endif
}

static int receive(uint8_t *p, unsigned n) {
    for (unsigned i = 0; i < n; ++i) {
        int c = getc_timeout(CPU_HZ * 3);
        if (c < 0) return 0;
        p[i] = (uint8_t)c;
    }
    return 1;
}

static void drain_rx(void) {
    while (getc_timeout(CPU_HZ / 20) >= 0) {}
}

static uint32_t get32(const uint8_t *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static void put32(uint32_t n) {
    for (unsigned i = 0; i < 4; ++i) putc_uart(n >> (i * 8));
}

static uint32_t crc_update(uint32_t crc, const uint8_t *p, unsigned n) {
    return firmware_crc_update(crc, p, n);
}

static uint32_t crc32(const uint8_t *p, unsigned n) {
    return crc_update(0xffffffffU, p, n) ^ 0xffffffffU;
}

static void reply(uint32_t seq, unsigned status) {
    puts_uart("VACK");
    put32(seq);
    put32(status);
}

/* Wrong/partial frames abort after an idle gap, so a fresh 'd' starts a clean session. */
static void abort_transfer(uint32_t seq, unsigned status) {
    drain_rx();
    reply(seq, status);
    puts_uart("\r\nDOWNLOAD ABORT\r\n");
}

static void download(void) {
    uint8_t header[36], frame[16];
    uint32_t offset = 0, expected = 0, running = 0xffffffffU;
    uint32_t previous_size = 0, previous_crc = 0;
    uint64_t upload_start=cycles(), stream_ticks=0;
    image_valid = 0;
    image_network = 0;
    puts_uart("VLOAD1\r\n");
    if (!receive(header, sizeof header)) {
        abort_transfer(HEADER_SEQ, TIMEOUT);
        return;
    }
    if (get32(header) != 0x31444c56U || get32(header + 4) != 1 ||
        get32(header + 24) != CHUNK_MAX || get32(header + 28) != 0 ||
        get32(header + 32) != crc32(header, 32)) {
        reply(HEADER_SEQ, BAD_HEADER);
        return;
    }
    uint32_t base = get32(header + 8), entry = get32(header + 12);
    uint32_t length = get32(header + 16), wanted_crc = get32(header + 20);
    if (base != RAM_BASE || !length || length > IMAGE_LIMIT ||
        entry < base || (uint64_t)entry >= (uint64_t)base + length || (entry & 3)) {
        reply(HEADER_SEQ, BAD_RANGE);
        return;
    }
    reply(HEADER_SEQ, OK);
    while (offset < length) {
        if (!receive(frame, sizeof frame)) {
            abort_transfer(expected, TIMEOUT);
            return;
        }
        uint32_t seq = get32(frame + 4), size = get32(frame + 8), sum = get32(frame + 12);
        if (get32(frame) != 0x41544144U || size == 0 || size > CHUNK_MAX) {
            abort_transfer(seq, BAD_HEADER);
            return;
        }
        if (!receive(packet, size)) {
            abort_transfer(seq, TIMEOUT);
            return;
        }
        if (crc32(packet, size) != sum) {
            reply(seq, BAD_CRC);
            continue;
        }
        /* Retransmission after a lost ACK is idempotent. */
        if (expected && seq == expected - 1 && size == previous_size && sum == previous_crc) {
            reply(seq, OK);
            continue;
        }
        if (seq != expected) {
            reply(seq, BAD_SEQUENCE);
            continue;
        }
        unsigned remaining = length - offset;
        unsigned wanted_size = remaining > CHUNK_MAX ? CHUNK_MAX : remaining;
        if (size != wanted_size) {
            reply(seq, BAD_RANGE);
            continue;
        }
        volatile uint8_t *dst = image_memory(offset);
        for (unsigned i = 0; i < size; ++i) dst[i] = packet[i];
        uint64_t crc_start=cycles();
        running = crc_update(running, packet, size);
        stream_ticks+=cycles()-crc_start;
        offset += size;
        ++expected;
        previous_size = size;
        previous_crc = sum;
        reply(seq, OK);
    }
    uart_stage("rx_done",cycles()-upload_start,length);
    uart_stage("stream_crc",stream_ticks,length);
    if ((running ^ 0xffffffffU) != wanted_crc) {
        reply(HEADER_SEQ, BAD_CRC);
        puts_uart("\r\nIMAGE CRC FAIL\r\n");
        uart_crc_failure("stream_crc",length,wanted_crc,running^0xffffffffU);
        return;
    }
    /* Verify RAM, not only the serial stream. */
#ifndef BOOTROM_TEST
    __asm__ volatile ("fence rw, rw" ::: "memory");
#endif
    puts_uart("UART stage=ram_crc begin\r\n");
    uint64_t verify_start=cycles();
    uint32_t actual_crc=crc32(image_memory(0), length);
    uart_stage("ram_crc",cycles()-verify_start,length);
    if (actual_crc != wanted_crc) {
        reply(HEADER_SEQ, BAD_CRC);
        puts_uart("\r\nRAM CRC FAIL\r\n");
        uart_crc_failure("ram_crc",length,wanted_crc,actual_crc);
        return;
    }
    image_entry = entry;
    image_length = length;
    image_valid = 1;
    puts_uart("VDON");
    put32(length);
    put32(wanted_crc);
    puts_uart("\r\nDOWNLOAD OK\r\n");
}

/* Keep the command protocol compatible with uart_load.py; diagnostics live in apps. */
static void boot_loop(void) __attribute__((noreturn));
#ifdef BOARD_NETBOOT
static int network_download(void) {
    image_valid = 0;
    image_network = 1;
    puts_uart("network boot (TFTP); d=UART recovery\r\n");
    if (board_netboot(&image_entry, &image_length)) {
        image_valid = 1;
        puts_uart("NETWORK IMAGE VERIFIED\r\n");
        return 1;
    }
    puts_uart("network boot unavailable/failed; UART recovery\r\n");
    return 0;
}
#endif
static void boot_loop(void) {
    for (;;) {
        puts_uart(image_valid ? "ready to boot\r\n" : "download mode (UART)\r\n");
        int c;
        /* Ignore terminal line endings/noise and retired test commands silently. */
        do {
#ifdef BOARD_NETBOOT
            c = board_netboot_command();
            if (!c) c = getc_timeout(CPU_HZ * 3);
#else
            c = getc_timeout(CPU_HZ * 3);
#endif
        } while (c != 'd' && c != 'g'
#ifdef BOARD_NETBOOT
                 && c != 'n'
#endif
        );
        if (c == 'd') download();
#ifdef BOARD_NETBOOT
        else if (c == 'n') { if (network_download()) c = 'g'; else continue; }
#endif
        if (c == 'g' && (!image_valid || !image_length)) puts_uart("NO IMAGE\r\n");
        else if (c == 'g') {
#ifdef BOARD_NETBOOT
            if (!board_netboot_quiet()) { puts_uart("DMA BUSY; RESET REQUIRED\r\n"); continue; }
#endif
#ifdef BOARD_DDR
            puts_uart(image_network ? "boot from Ethernet (DDR) @ 0x" : "boot from UART (DDR) @ 0x");
#else
            puts_uart("boot from UART (RAM) @ 0x");
#endif
            hex64(image_entry);
            puts_uart("\r\n");
#ifdef BOARD_NETBOOT
            board_netboot_jump(image_entry,image_length);
#endif
            flush_uart();
            run_image(image_entry);
            uart_init();
            puts_uart("\r\nAPP RETURN\r\n");
        }
    }
}

void boot_main(void) {
    uart_init();
    puts_uart("Valence Bootrom V0.1\r\n");
#ifdef BOARD_NETBOOT
    if (network_download()) {
        puts_uart("boot from Ethernet (DDR) @ 0x");
        hex64(image_entry); puts_uart("\r\n");
        board_netboot_jump(image_entry,image_length);
        flush_uart();
        run_image(image_entry);
        uart_init(); puts_uart("\r\nAPP RETURN\r\n");
    }
#endif
    boot_loop();
}

void boot_recover(uint64_t cause, uint64_t pc) {
    uart_init();
    puts_uart("\r\nTRAP cause=");
    hex64(cause);
    puts_uart(" pc=");
    hex64(pc);
    puts_uart("\r\n");
    image_valid = 0;
    boot_loop();
}
