/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef VALENCE_CLOCKMON_ABI_H
#define VALENCE_CLOCKMON_ABI_H
#ifdef __KERNEL__
#include <linux/types.h>
#include <linux/errno.h>
#else
#include <stdint.h>
#include <errno.h>
typedef uint64_t u64;
typedef uint32_t u32;
#endif

/* Logical offsets: two rate pages at0, two meter pages at0x100.
 * Caller supplies ordered 64-bit device reads. There is deliberately no writer.
 */
typedef u64 (*vcm_read_fn)(void *context, unsigned int offset);
struct vcm_rate { u64 word[16]; };
struct vcm_meter {
	u64 sequence, flags, reference_hz, window, timestamp;
	u32 delta[8], total[8];
	unsigned int width, retirement_lanes;
};
struct vcm_snapshot { struct vcm_meter domain[2]; };

static inline int vcm_rate_descriptor(u64 id)
{
	return id == 0x4352000100000002ULL || id == 0x4352000300000002ULL;
}

static inline int vcm_meter_width_profile(u64 id, unsigned int lanes)
{
	unsigned int width = (id >> 32) & 0xffff;
	if ((id >> 48) != 0x544d || (lanes != 1 && lanes != 2) || (id & 0xffffffffULL) != lanes || width < 4 || width > 32)
		return -EPROTO;
	return (int)width;
}

static inline int vcm_meter_width(u64 id)
{
	return vcm_meter_width_profile(id, 1);
}

static inline int vcm_validate_profile(vcm_read_fn read, void *ctx, unsigned int cpu_lanes)
{
	unsigned int d;
	for (d = 0; d < 2; d++) {
		unsigned int r = d * 0x80, p = 0x100 + d * 0x100;
		if (!vcm_rate_descriptor(read(ctx, r + 0x78)) ||
		    read(ctx, r + 0x38) != 0x000080033e200a0aULL ||
		    read(ctx, r + 0x28) != 50000000 ||
		    read(ctx, r + 0x70) != 250000000 ||
		    read(ctx, r + 0x68) != 10000000 ||
		    read(ctx, r + 0x60) != (d ? 250000000 : 300000000) ||
		    vcm_meter_width_profile(read(ctx, p + 0x28), d ? 1 : cpu_lanes) < 0 ||
		    read(ctx, p + 0x10) != 50000000)
			return -EPROTO;
	}
	return 0;
}

static inline int vcm_validate(vcm_read_fn read, void *ctx)
{
	return vcm_validate_profile(read, ctx, 1);
}

/* Rate pages are live, not a hardware snapshot. Reject observed transitions;
 * this bounded stability read is not an atomic ownership/qualification claim.
 */
static inline int vcm_read_rate(vcm_read_fn read, void *ctx, unsigned int d,
			      struct vcm_rate *result, unsigned int retries)
{
	unsigned int attempt, i, b = d * 0x80;
	if (d > 1)
		return -EINVAL;
	for (attempt = 0; attempt < retries; attempt++) {
		u64 completed = read(ctx, b + 0x50), status = read(ctx, b + 0x10);
		for (i = 0; i < 16; i++)
			result->word[i] = read(ctx, b + i * 8);
		if (!vcm_rate_descriptor(result->word[15]))
			return -EPROTO;
		if (completed == result->word[10] && status == result->word[2] &&
		    completed == read(ctx, b + 0x50) && status == read(ctx, b + 0x10))
			return 0;
	}
	return -EAGAIN;
}

/* Atomic-context-safe CCF query: bounded ordered reads, no sleep or writes.
 * Return zero (unknown), never a cached nominal frequency, during transitions.
 */
static inline u64 vcm_current_rate(vcm_read_fn read, void *ctx, unsigned int d)
{
	unsigned int i, b = d * 0x80;
	if (d > 1)
		return 0;
	for (i = 0; i < 4; i++) {
		u64 n = read(ctx, b + 0x50), status = read(ctx, b + 0x10);
		u64 hz = read(ctx, b + 8);
		if (n != read(ctx, b + 0x50) || status != read(ctx, b + 0x10))
			continue;
		if ((status & (1 | 2 | 512 | 1024)) != (2 | 1024) ||
		    hz < 10000000 || hz > (d ? 250000000ULL : 300000000ULL))
			return 0;
		return hz;
	}
	return 0;
}

/* Both banks share one AON publication sequence. Check live invalidate on both
 * sides of the ENTIRE two-bank read, not only each individual bank. Invalid but
 * coherent windows are returned with their raw flags; never label them measured.
 */
static inline int vcm_read_snapshot_profile(vcm_read_fn read, void *ctx,
				  struct vcm_snapshot *out, unsigned int retries, unsigned int cpu_lanes)
{
	unsigned int attempt, d, i;
	for (attempt = 0; attempt < retries; attempt++) {
		u64 seq[2], flags[2];
		int stable = 1;
		for (d = 0; d < 2; d++) {
			unsigned int b = 0x100 + d * 0x100;
			seq[d] = read(ctx, b); flags[d] = read(ctx, b + 8);
		}
		for (d = 0; d < 2; d++) {
			unsigned int b = 0x100 + d * 0x100;
			struct vcm_meter *s = &out->domain[d];
			unsigned int lanes = d ? 1 : cpu_lanes;
			int width = vcm_meter_width_profile(read(ctx, b + 0x28), lanes);
			u64 mask;
			if (width < 0)
				return width;
			s->retirement_lanes = lanes;
			s->width = (unsigned int)width; mask = (1ULL << width) - 1;
			s->sequence = seq[d]; s->flags = flags[d];
			s->reference_hz = read(ctx, b + 0x10);
			s->window = read(ctx, b + 0x18); s->timestamp = read(ctx, b + 0x20);
			if (s->reference_hz != 50000000 || !s->window || s->window > 0xffffffffULL || (s->flags & ~7ULL))
				return -EPROTO;
			/* A delta is modulo counter width. Reject a window that could
			 * wrap more than once at this domain's maximum admitted rate. */
			if (s->window * (d ? 5ULL : 6ULL * lanes) > mask)
				return -EPROTO;
			for (i = 0; i < 8; i++) {
				u64 delta = read(ctx, b + 0x40 + i * 8);
				u64 total = read(ctx, b + 0x80 + i * 8);
				if ((delta | total) & ~mask)
					return -EPROTO;
				s->delta[i] = (u32)delta; s->total[i] = (u32)total;
			}
		}
		for (d = 0; d < 2; d++) {
			unsigned int b = 0x100 + d * 0x100;
			if (flags[d] != read(ctx, b + 8) || seq[d] != read(ctx, b))
				stable = 0;
		}
		if (stable && seq[0] == seq[1] &&
		    out->domain[0].timestamp == out->domain[1].timestamp &&
		    out->domain[0].window == out->domain[1].window)
			return 0;
	}
	return -EAGAIN;
}

/* Legacy callers remain strictly ABI1; only an explicit platform profile may
 * select CPU ABI2. Fabric is always ABI1. */
static inline int vcm_read_snapshot(vcm_read_fn read, void *ctx,
		struct vcm_snapshot *out, unsigned int retries)
{
	return vcm_read_snapshot_profile(read, ctx, out, retries, 1);
}

static inline int vcm_meter_valid(const struct vcm_meter *s)
{
	return (s->flags & 5) == 1;
}
static inline u64 vcm_measured_hz(const struct vcm_meter *s)
{
	return vcm_meter_valid(s) && s->window ?
		(u64)s->delta[0] * s->reference_hz / s->window : 0;
}
#endif
