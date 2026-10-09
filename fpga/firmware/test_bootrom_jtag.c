/* Real BootROM command/verification code against an independent register model.
 * This is host software proof, not RTL, JTAG electrical or physical DDR proof. */
#define BOOTROM_TEST 1
#define BOARD_JTAG_DOWNLOAD 1
#define BOARD_DDR 1
#define BOARD_RAM_BYTES 0x80000000UL
#define BOARD_MONITOR_BASE 0xffff8000UL
#define CPU_HZ 1000ULL
#ifndef FIRMWARE_CRC_MODE
#define FIRMWARE_CRC_MODE 0
#endif
#include <assert.h>
#include <setjmp.h>
#include <stdio.h>
#include <string.h>
#include "bootrom.c"

_Static_assert(JTAG_DOWNLOAD_BASE == 0x10003000UL && JTAG_STATUS == 0 && JTAG_COMMAND == 8 &&
    JTAG_ENTRY == 16 && JTAG_LENGTH == 24 && JTAG_CRC == 32 && JTAG_GENERATION == 40 &&
    JTAG_RAM_BASE == 48 && JTAG_RAM_END == 56, "CPU register ABI changed");
_Static_assert(JTAG_ARMED == 1 && JTAG_COMMITTED == 2 && JTAG_CANCELLED == 4 &&
    JTAG_BUSY == 8 && JTAG_FAULT == 16 && JTAG_LINK_UP == 32 && JTAG_CLAIMED == 64 &&
    JTAG_OPEN == 1 && JTAG_CLOSE == 2 && JTAG_CLAIM == 3, "CPU status/command ABI changed");

static uint8_t memory[16384];
static char output[16384];
static unsigned output_at, reads, writes, opens, closes, claims, prepares, fences, runs;
static unsigned net_quiets, net_downloads, status_polls, drain_remaining, closes_at_open;
static uint64_t model_status, model_generation, model_entry, model_length, model_crc;
static uint64_t model_base, model_end, now;
static int dma_busy, network_busy, prepare_failure, probe_cancel, wait_cancel;
static int no_commit, drain_stuck, close_ignored, corrupt_ram, reset_at_metadata;
static int reset_at_prepare, reset_at_fence, reset_at_claim, epoch_at_metadata;
static int epoch_at_fence, host_abort, host_fault, trap_at_open, epoch_at_claim;
static int commit_busy, reset_during_crc;
static unsigned crc_probes;
static const char *commands;
static jmp_buf escape;

static uint32_t oracle(const uint8_t *p, unsigned n) {
    uint32_t value = ~0U;
    while (n--) {
        value ^= *p++;
        for (unsigned bit = 0; bit < 8; ++bit)
            value = (value >> 1) ^ ((value & 1) ? 0xedb88320U : 0);
    }
    return ~value;
}
static int has(const char *s) { return strstr(output, s) != NULL; }
static void cancel_link(void) {
    model_status &= ~(JTAG_ARMED | JTAG_COMMITTED | JTAG_LINK_UP);
    model_status |= JTAG_CANCELLED;
}
uint8_t *boot_test_ram(void) { return memory; }
uint64_t boot_test_now(void) { return ++now; }
void boot_test_putc(uint8_t c) {
    assert(output_at + 1 < sizeof output);
    output[output_at++] = (char)c; output[output_at] = 0;
}
int boot_test_getc(uint64_t budget) {
    if (has("JTAG OWNERSHIP UNKNOWN")) longjmp(escape, 2);
    if (jtag_session_active) {
        if (!budget && prepares >= 2 && ++crc_probes == 2 && reset_during_crc) cancel_link();
        if (!budget && probe_cancel && prepares >= 2) { probe_cancel = 0; return 3; }
        if (budget && wait_cancel) { wait_cancel = 0; return 3; }
        return -1;
    }
    if (!budget) return -1;
    if (*commands) return (unsigned char)*commands++;
    longjmp(escape, 1);
}
int firmware_ram_dma_idle(void) { return !dma_busy; }
int firmware_ram_prepare(uint64_t *flush, uint64_t *sweep) {
    ++prepares;
    assert(!(model_status & (JTAG_ARMED | JTAG_BUSY | JTAG_CLAIMED)));
    if (opens) assert(model_status & JTAG_COMMITTED);
    *flush = 1; *sweep = 2;
    if (reset_at_prepare && opens) cancel_link();
    return !dma_busy && prepares != (unsigned)prepare_failure;
}
void boot_test_jtag_fence(void) {
    ++fences;
    assert(prepares == 2 && !claims && !(model_status & JTAG_BUSY));
    if (reset_at_fence) cancel_link();
    if (epoch_at_fence) ++model_generation;
}
uint64_t boot_test_jtag_read(unsigned offset) {
    ++reads;
    assert(jtag_session_active);
    assert((offset & 7) == 0 && offset <= JTAG_RAM_END);
    switch (offset) {
    case JTAG_STATUS:
        if (drain_remaining && !drain_stuck) {
            if (!--drain_remaining) model_status &= ~JTAG_BUSY;
        }
        if (opens && !claims && (model_status & JTAG_ARMED)) {
            if (++status_polls >= 3 && !no_commit) {
                model_status &= ~(JTAG_ARMED | JTAG_BUSY);
                model_status |= JTAG_COMMITTED;
                if (commit_busy) { model_status |= JTAG_BUSY; drain_remaining = 4; }
                if (corrupt_ram) memory[model_length / 2] ^= 1;
                if (host_abort) {
                    model_status &= ~JTAG_COMMITTED;
                    model_status |= JTAG_CANCELLED | JTAG_BUSY;
                    drain_remaining = 4;
                }
                if (host_fault) model_status |= JTAG_FAULT;
            }
        }
        return model_status;
    case JTAG_ENTRY:
        if (reset_at_metadata) cancel_link();
        if (epoch_at_metadata) ++model_generation;
        return model_entry;
    case JTAG_LENGTH: return model_length;
    case JTAG_CRC: return model_crc;
    case JTAG_GENERATION: return model_generation;
    case JTAG_RAM_BASE: return model_base;
    case JTAG_RAM_END: return model_end;
    default: assert(0); return 0;
    }
}
void boot_test_jtag_write(unsigned offset, uint64_t value) {
    ++writes;
    assert(offset == JTAG_COMMAND && jtag_session_active);
    switch ((uint32_t)value) {
    case JTAG_OPEN:
        assert(prepares == 1 && !dma_busy && !network_busy);
        assert(!(model_status & (JTAG_ARMED | JTAG_COMMITTED | JTAG_BUSY | JTAG_CLAIMED)));
        assert(model_status & JTAG_LINK_UP);
        ++opens; closes_at_open = closes;
        if (trap_at_open) boot_recover(7, JTAG_DOWNLOAD_BASE + JTAG_COMMAND);
        model_generation = (uint32_t)(model_generation + 1);
        model_status = JTAG_LINK_UP | JTAG_ARMED | JTAG_BUSY;
        break;
    case JTAG_CLOSE:
        ++closes;
        if (!close_ignored) {
            model_status &= ~(JTAG_ARMED | JTAG_COMMITTED);
            model_status |= JTAG_CANCELLED;
        }
        if (model_status & JTAG_BUSY) drain_remaining = 4;
        break;
    case JTAG_CLAIM:
        assert(prepares == 2 && fences == 1 && closes == closes_at_open);
        ++claims;
        if (reset_at_claim) cancel_link();
        if (epoch_at_claim) ++model_generation;
        if (!(model_status & JTAG_COMMITTED) || !(model_status & JTAG_LINK_UP) ||
            (model_status & (JTAG_BUSY | JTAG_CANCELLED | JTAG_FAULT)) ||
            (uint32_t)(value >> 32) != model_generation)
            boot_recover(7, JTAG_DOWNLOAD_BASE + JTAG_COMMAND);
        model_status &= ~JTAG_COMMITTED;
        model_status |= JTAG_CLAIMED;
        break;
    default: assert(0);
    }
}
void run_image(uintptr_t entry) {
    assert(entry == model_entry && external_state_untrusted && !jtag_session_active);
    assert((model_status & JTAG_CLAIMED) && !(model_status & (JTAG_ARMED | JTAG_BUSY)));
    assert(claims == 1 && fences == 1 && prepares == 2);
    ++runs;
}
#ifdef BOARD_NETBOOT
int board_netboot_quiet(void) { ++net_quiets; assert(!external_state_untrusted); return !network_busy; }
int board_netboot(uint32_t *e, uint32_t *n) { (void)e; (void)n; ++net_downloads; return 0; }
int board_netboot_command(void) { return 0; }
uint32_t board_netboot_verified_crc(void) { return 0; }
void board_netboot_jump(uint32_t e, uint32_t n) { (void)e; (void)n; assert(0); }
#endif
#ifdef BOOT_MENU
int monitor_memory_dma_idle(void) { return !dma_busy; }
void monitor_run_diagnostic(unsigned op, unsigned n) { (void)op; (void)n; assert(0); }
#endif
static void reset(void) {
    memset(output, 0, sizeof output);
    output_at = reads = writes = opens = closes = claims = prepares = fences = runs = 0;
    net_quiets = net_downloads = status_polls = drain_remaining = closes_at_open = 0;
    dma_busy = network_busy = prepare_failure = probe_cancel = wait_cancel = 0;
    no_commit = drain_stuck = close_ignored = corrupt_ram = reset_at_metadata = 0;
    reset_at_prepare = reset_at_fence = reset_at_claim = epoch_at_metadata = 0;
    epoch_at_fence = host_abort = host_fault = trap_at_open = epoch_at_claim = 0;
    commit_busy = reset_during_crc = 0; crc_probes = 0;
    model_status = JTAG_LINK_UP;
    model_generation = 41;
    model_entry = RAM_BASE + 4;
    model_length = 8193; /* Exercise three CRC batches and a padded tail. */
    model_base = RAM_BASE; model_end = RAM_BASE + IMAGE_LIMIT;
    for (unsigned i = 0; i < sizeof memory; ++i) memory[i] = (uint8_t)(i * 13 + 7);
    model_crc = oracle(memory, (unsigned)model_length);
    now = 0; commands = "";
    image_valid = image_entry = image_length = image_network = external_state_untrusted = 0;
    jtag_session_active = 0;
#ifdef BOOT_MENU
    image_crc = image_record_crc = menu_ansi = 0; menu_pending = 0;
#else
    legacy_crc = legacy_record_crc = 0; legacy_pending = 0;
#endif
}
static int session(void) {
    int result = setjmp(escape);
    if (!result) jtag_download();
    return result;
}
static void rejected(const char *reason) {
    assert(session() == 0 && !runs && !claims && !image_valid && !jtag_session_active);
    assert(!(model_status & (JTAG_ARMED | JTAG_COMMITTED | JTAG_BUSY)));
    assert(has(reason) && has("retry with j"));
}
int main(int argc,char **argv) {
#ifdef BOOT_MENU
    if(argc>1&&!strcmp(argv[1],"--snapshot")){reset();menu_ansi=1;show_menu();fwrite(output,1,output_at,stdout);return 0;}
#else
    (void)argc;(void)argv;
#endif
    unsigned cases = 0;
    reset(); assert(session() == 0 && runs == 1 && claims == 1 && opens == 1 && !closes);
    assert(has("JTAG RAM IMAGE VERIFIED") && has("APP RETURN") && external_state_untrusted); ++cases;
    reset(); model_length = 1; model_entry = RAM_BASE; model_crc = oracle(memory, 1);
    assert(session() == 0 && runs == 1); ++cases;
    reset(); model_status |= JTAG_ARMED | JTAG_BUSY;
    assert(session() == 0 && runs == 1 && closes == 1); ++cases;
    reset(); commit_busy = 1; assert(session() == 0 && runs == 1 && !drain_remaining); ++cases;
    reset(); model_generation = UINT32_MAX; assert(session() == 0 && runs == 1 && model_generation == 0); ++cases;
    reset(); corrupt_ram = 1; rejected("JTAG RAM CRC FAIL"); assert(prepares == 2 && !fences); ++cases;
    reset(); model_crc ^= 1; rejected("JTAG RAM CRC FAIL"); ++cases;
    reset(); model_length = 0; rejected("JTAG IMAGE RANGE FAIL"); ++cases;
    reset(); model_length = IMAGE_LIMIT + 1; rejected("JTAG IMAGE RANGE FAIL"); ++cases;
    reset(); model_length = UINT64_MAX; rejected("JTAG IMAGE RANGE FAIL"); ++cases;
    reset(); model_entry = RAM_BASE - 4; rejected("JTAG IMAGE RANGE FAIL"); ++cases;
    reset(); model_entry = RAM_BASE + model_length; rejected("JTAG IMAGE RANGE FAIL"); ++cases;
    reset(); model_entry += 1; rejected("JTAG IMAGE RANGE FAIL"); ++cases;
    reset(); model_crc |= UINT64_C(1) << 32; rejected("JTAG IMAGE RANGE FAIL"); ++cases;
    reset(); model_end = RAM_BASE + model_length; rejected("JTAG IMAGE RANGE FAIL"); ++cases;
    reset(); model_end = RAM_BASE + model_length - 10; rejected("JTAG IMAGE RANGE FAIL"); ++cases;
    reset(); model_base += 8; rejected("JTAG CAPABILITY/RANGE FAIL"); assert(!opens); ++cases;
    reset(); model_end = RAM_BASE; rejected("JTAG CAPABILITY/RANGE FAIL"); ++cases;
    reset(); model_end = RAM_BASE + BOARD_RAM_BYTES + 1; rejected("JTAG CAPABILITY/RANGE FAIL"); ++cases;
    reset(); model_end = RAM_BASE + IMAGE_LIMIT + 4;
    rejected("JTAG CAPABILITY/RANGE FAIL"); assert(!opens); ++cases;
    reset(); model_generation = UINT64_C(1) << 32;
    rejected("JTAG CAPABILITY/RANGE FAIL"); assert(!opens); ++cases;
    reset(); model_status = 0; rejected("JTAG LINK DOWN"); assert(!opens); ++cases;
    reset(); dma_busy = 1; rejected("MEMORY DMA BUSY"); assert(!prepares && !opens); ++cases;
    reset(); prepare_failure = 1; rejected("MEMORY DMA BUSY"); assert(!opens); ++cases;
    reset(); prepare_failure = 2; rejected("MEMORY DMA BUSY"); assert(opens && !fences); ++cases;
#ifdef BOARD_NETBOOT
    reset(); network_busy = 1; rejected("DMA BUSY"); assert(!prepares && !opens); ++cases;
#endif
    reset(); wait_cancel = no_commit = 1; rejected("JTAG CANCELLED"); assert(closes == 1 && prepares == 1); ++cases;
    reset(); probe_cancel = 1; rejected("JTAG VERIFY CANCELLED"); assert(prepares == 2 && !fences); ++cases;
    reset(); host_abort = 1; rejected("JTAG SESSION LOST"); assert(prepares == 1); ++cases;
    reset(); host_fault = 1; rejected("JTAG SESSION LOST"); ++cases;
    reset(); reset_at_metadata = 1; rejected("JTAG SESSION LOST"); ++cases;
    reset(); epoch_at_metadata = 1; rejected("JTAG SESSION LOST"); ++cases;
    reset(); reset_at_prepare = 1; rejected("JTAG SESSION LOST"); ++cases;
    reset(); reset_during_crc = 1; rejected("JTAG SESSION LOST"); assert(crc_probes == 2); ++cases;
    reset(); reset_at_fence = 1; rejected("JTAG SESSION LOST"); assert(fences == 1); ++cases;
    reset(); epoch_at_fence = 1; rejected("JTAG SESSION LOST"); ++cases;
    reset(); reset_at_claim = 1; assert(session() == 2 && !runs && claims == 1 && jtag_session_active);
    assert(has("TRAP cause=") && !has("retry with j")); ++cases;
    reset(); epoch_at_claim = 1; assert(session() == 2 && !runs && claims == 1 && jtag_session_active); ++cases;
    reset(); trap_at_open = 1; assert(session() == 2 && !runs && jtag_session_active); ++cases;
    reset(); no_commit = wait_cancel = drain_stuck = 1;
    assert(session() == 2 && !runs && jtag_session_active && (model_status & JTAG_BUSY));
    assert(!has("retry with j") && now >= CPU_HZ * 2); ++cases;
    reset(); no_commit = wait_cancel = close_ignored = 1;
    assert(session() == 2 && !runs && jtag_session_active && (model_status & JTAG_ARMED)); ++cases;
    reset(); model_status |= JTAG_CLAIMED;
    assert(session() == 2 && !prepares && !opens && !closes); ++cases;
    reset(); external_state_untrusted = 1; assert(session() == 0 && !reads && !writes && !prepares && !net_quiets);
    assert(has("EXTERNAL STATE LOCKED")); ++cases;
    reset(); if (!setjmp(escape)) boot_main();
    assert(!reads && !writes && !opens && !runs); ++cases;
    reset(); commands = "jgjdj"; if (!setjmp(escape)) boot_loop();
    assert(runs == 1 && opens == 1 && external_state_untrusted && has("EXTERNAL STATE LOCKED")); ++cases;
    /* A failed attempt may be re-armed only after the close/drain has returned. */
    reset(); wait_cancel = no_commit = 1; rejected("JTAG CANCELLED");
    assert(!(model_status & JTAG_BUSY));
    no_commit = 0; closes = prepares = opens = status_polls = 0;
    assert(session() == 0 && runs == 1); ++cases;
    printf("BOOTROM_JTAG_PASS cases=%u menu=%u network=%u host_model_only=1 epoch_claim=1 abort_drain=1 external_lock=1\n",
        cases,
#ifdef BOOT_MENU
        1U,
#else
        0U,
#endif
#ifdef BOARD_NETBOOT
        1U
#else
        0U
#endif
    );
    return 0;
}
