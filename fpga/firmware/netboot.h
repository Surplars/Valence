#ifndef VALENCE_NETBOOT_H
#define VALENCE_NETBOOT_H
#include <stdint.h>
#include <stddef.h>
/* Portable protocol engine. Platform must bound I/O, own both aligned buffers,
 * and reject writes outside [0,limit). CRC verification is against actual RAM.
 * 512-byte TFTP blocks, one outstanding block, <=5 consecutive retries.
 * No DHCP, IP fragmentation, TCP, options negotiation or authenticated boot.
 */
struct nb_ops {
    void *context;
    uint8_t *tx, *rx; /* two distinct buffers, each >=2048 bytes */
    uint8_t mac[6];
    uint32_t ip, server_ip, base, limit; /* IPs are host integers in wire order */
    uint64_t hz;
    uint64_t (*now)(void *);
    int (*send)(void *, unsigned);
    int (*recv)(void *, uint64_t); /* bytes / 0 timeout / -1 abort */
    int (*store)(void *, uint32_t, const uint8_t *, unsigned);
    int (*verify)(void *, uint32_t, uint32_t);
};
uint32_t nb_crc_update(uint32_t, const uint8_t *, unsigned);
int nb_tftp(struct nb_ops *, const char *, uint32_t *, uint32_t *);
int board_netboot(uint32_t *, uint32_t *);
int board_netboot_quiet(void);
int board_netboot_command(void);
#endif
