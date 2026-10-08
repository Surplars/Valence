/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef VALENCE_MEDIA_POLICY_H
#define VALENCE_MEDIA_POLICY_H

/* Pure decoder, also compiled by the independent native policy tests. */
static inline unsigned int vg_managed_media_speed(unsigned long long status)
{
	unsigned int rate = (status >> 4) & 3;
	if ((status >> 56) != 1 || (status & 0x1003ULL) != 0x1003ULL ||
	    (status & 0x0fc0ULL) || rate == 3 || ((status >> 2) & 3) != rate)
		return 0;
	return rate == 2 ? 1000 : rate == 1 ? 100 : 10;
}

enum {
	VG_MEDIA_STATS_LEGACY = 6,
	VG_MEDIA_STATS_V1 = 27,
};

struct vg_media_stat_descriptor {
	const char *name;
	unsigned int offset;
	unsigned int width;
};

/* Existing offsets are always safe. Never probe additive offsets merely to
 * discover whether they exist. The caller reads the extension version only
 * after CAP advertises both managed PHY and the media register extension;
 * unknown versions keep the legacy statistic set.
 */
static inline unsigned int vg_media_stat_count(unsigned long long capabilities,
					      unsigned int version)
{
	const unsigned long long required = (1ULL << 10) | (1ULL << 11) | (1ULL << 12);
	return (capabilities & required) == required && version == 1 ?
		VG_MEDIA_STATS_V1 : VG_MEDIA_STATS_LEGACY;
}

/* Every value comes directly from a documented hardware register. Counters
 * are raw modulo-64 (MAC) or modulo-32 (PHY) snapshots, not software-extended
 * lifetime values. MAC counters clear on cold reset/CLEAR_STATS; PHY counters
 * clear on cold reset only. media_status_v1 is a status word, not a counter.
 * There is no global atomic snapshot across different statistic registers.
 */
static inline const struct vg_media_stat_descriptor *vg_media_stat(unsigned int index)
{
	static const struct vg_media_stat_descriptor descriptors[VG_MEDIA_STATS_V1] = {
		{ "mac_tx_frames", 0x40, 64 },
		{ "mac_rx_frames", 0x48, 64 },
		{ "mac_rx_drops", 0x50, 64 },
		{ "mac_rx_bad_fcs", 0x58, 64 },
		{ "mac_tx_bytes", 0x60, 64 },
		{ "mac_rx_bytes", 0x68, 64 },
		{ "rx_drop_bank_full", 0xb0, 64 },
		{ "rx_drop_admission_closed", 0xb8, 64 },
		{ "rx_drop_preamble", 0xc0, 64 },
		{ "rx_drop_fcs", 0xc8, 64 },
		{ "rx_drop_length", 0xd0, 64 },
		{ "rx_drop_address", 0xd8, 64 },
		{ "rx_drop_phy_error", 0xe0, 64 },
		{ "rx_drop_link_abort", 0xe8, 64 },
		{ "tx_link_aborted_frames", 0xf0, 64 },
		{ "rx_fifo_stall_cycles", 0xf8, 64 },
		{ "tx_fifo_stall_cycles", 0x100, 64 },
		{ "rx_odd_nibble_tails", 0x108, 64 },
		{ "rx_ingress_overflows", 0x120, 64 },
		{ "rx_ingress_wholly_skipped", 0x128, 64 },
		{ "phy_no_ack", 0xa0, 32 },
		{ "phy_verify_failures", 0xa4, 32 },
		{ "phy_link_changes", 0xa8, 32 },
		{ "phy_completed_polls", 0xac, 32 },
		{ "phy_unsupported_modes", 0x110, 32 },
		{ "media_transition_timeouts", 0x114, 32 },
		{ "media_status_v1", 0x98, 64 },
	};
	return &descriptors[index];
}

typedef unsigned int (*vg_media_read32)(void *context, unsigned int offset);

/* 0=legacy software PHY owner, 1=managed V1, -1=unsupported combination.
 * externalMdio can advertise bit11 without the media register extension, so
 * bit11 alone must NEVER authorize an access to the reserved 0x98/0x9c word.
 * Bit10 establishes that register ABI; bit12 separately gates diagnostics.
 */
static inline int vg_managed_media_probe(unsigned long long capabilities,
					 vg_media_read32 read, void *context)
{
	if (!(capabilities & (1ULL << 11)))
		return 0;
	if (!(capabilities & (1ULL << 10)))
		return -1;
	return (read(context, 0x9c) >> 24) == 1 ? 1 : -1;
}

/* Ordered 32-bit CSR reads also work when the CPU/MMIO path is only 32 bits.
 * Retrying on a changed high half prevents a carry/reset/wrap from producing a
 * torn 64-bit value. No write, latch manipulation, MDIO transaction, artificial
 * rollover extension or read-and-clear operation is performed. Independent
 * packed PHY counters are sampled with one read of their actual 32-bit lane.
 * Counter high halves cannot continuously change at MMIO speed: the fastest
 * source is 125MHz, giving at least 34.36s between ordinary high-half carries.
 */
static inline unsigned long long vg_media_stat_read(vg_media_read32 read,
						  void *context, unsigned int index)
{
	const struct vg_media_stat_descriptor *stat = vg_media_stat(index);
	unsigned int before, low, after;
	if (stat->width == 32)
		return read(context, stat->offset);
	do {
		before = read(context, stat->offset + 4);
		low = read(context, stat->offset);
		after = read(context, stat->offset + 4);
	} while (before != after);
	return ((unsigned long long)after << 32) | low;
}
#endif
