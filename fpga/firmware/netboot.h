#ifndef VALENCE_NETBOOT_H
#define VALENCE_NETBOOT_H
#include <stdint.h>
#include <stddef.h>
/* Portable protocol engine. Platform must bound I/O, own both aligned buffers,
 * and reject writes outside [0,limit). CRC verification is against actual RAM.
 * RFC2347/2348/7440: opt-in 512..1024-byte blocks and windows of 1..16 (platform capacity further bounds negotiation).
 * Unnegotiated servers remain 512/window1. <=5 consecutive retries.
 * No DHCP, IP fragmentation, TCP or authenticated boot.
 */
#define NB_TFTP_BLOCK_MAX 1024U
#define NB_TFTP_WINDOW_MAX 16U
#define NB_TFTP_FINAL_ACK_SECONDS 2U
enum nb_stage { NB_INIT, NB_ARP, NB_RX, NB_HEADER, NB_STREAM_CRC, NB_RAM_CRC,
                NB_RX_TX_DRAIN, NB_MAC_STOP, NB_JUMP, NB_RAM_PREPARE };
enum nb_failure { NB_NONE, NB_SEND_FAILED, NB_RX_ABORTED, NB_RETRY_LIMIT,
                  NB_SERVER_ERROR, NB_BAD_HEADER, NB_BAD_RANGE, NB_STORE_FAILED,
                  NB_LENGTH_MISMATCH, NB_STREAM_MISMATCH, NB_RAM_MISMATCH, NB_BAD_OPTIONS, NB_RAM_PREPARE_FAILED };
/* Optional aggregate evidence: ticks use ops.hz, no logging in packet/poll loops.
 * Caller zero-initializes this once per attempt. The stream and actual-RAM CRCs
 * remain independent; instrumentation never substitutes one for the other. */
struct nb_stats {
    uint64_t rx_ticks, copy_ticks, crc_ticks, tx_ticks, verify_ticks;
    uint32_t rx_calls, rx_frames, rx_timeouts, tx_frames, retries, duplicates;
    uint32_t received, expected_length, expected_crc, stream_crc;
    uint32_t header_crc_expected, header_crc_actual;
    uint32_t block_size, window_size, acks, out_of_order;
    uint64_t final_ack_ticks;
    enum nb_stage stage;
    enum nb_failure failure;
};
struct nb_ops {
    void *context;
    uint8_t *tx, *rx; /* distinct buffers: TX >=512 bytes, RX >=2048 bytes */
    uint8_t mac[6];
    uint32_t ip, server_ip, base, limit; /* IPs are host integers in wire order */
    uint64_t hz;
    uint64_t (*now)(void *);
    int (*send)(void *, unsigned);
    int (*recv)(void *, uint64_t); /* bytes / 0 timeout / -1 abort */
    int (*store)(void *, uint32_t, const uint8_t *, unsigned);
    int (*verify)(void *, uint32_t, uint32_t); /* 0 verified / -1 mismatch / -2 cancel */
    struct nb_stats *stats;
    void (*stage)(void *, enum nb_stage); /* optional, phase boundaries only */
    /* Explicit platform opt-in: advertise only burst sizes the RX queue holds.
     * Zero omits that option. Rejected/absent options use 512/window1. */
    unsigned request_blksize, request_windowsize;
    /* Optional borrowed frame after a positive recv. Valid until the next recv
     * or platform shutdown; parser, stream CRC and store finish before release. */
    uint8_t *(*received_frame)(void *);
    /* Optional ownership/cache maintenance after final ACK/dally, before CRC timing. */
    int (*prepare_verify)(void *);

};
uint32_t nb_crc_update(uint32_t, const uint8_t *, unsigned);
int nb_tftp(struct nb_ops *, const char *, uint32_t *, uint32_t *);
int board_netboot(uint32_t *, uint32_t *);
int board_netboot_quiet(void);
uint32_t board_netboot_verified_crc(void);
void board_netboot_info(void);
int board_netboot_command(void);
void board_netboot_jump(uint32_t, uint32_t);
#endif
