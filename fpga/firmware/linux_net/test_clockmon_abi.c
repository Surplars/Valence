/* Host tests execute the same bounded, read-only ABI helpers as the driver. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "valence_clockmon_abi.h"
static u64 regs[0x300 / 8];
static unsigned int reads, mode, seq_reads;
static u64 rd(void *ctx, unsigned int offset)
{
	(void)ctx;
	assert(!(offset & 7) && offset < 0x300);
	reads++;
	if (mode == 1 && offset == 0x100) return ++seq_reads;
	/* CPU invalidation happens while the fabric bank is being read. */
	if (mode == 2 && offset == 0x240) regs[0x108 / 8] = 4;
	if (mode == 3 && offset == 0x50) return ++seq_reads;
	return regs[offset / 8];
}
static void setup(void)
{
	unsigned int d, i;
	memset(regs, 0, sizeof(regs)); reads = mode = seq_reads = 0;
	for (d = 0; d < 2; d++) {
		unsigned int r = d * 0x80, p = 0x100 + d * 0x100;
		regs[(r + 0x78) / 8] = 0x4352000300000002ULL;
		regs[(r + 0x38) / 8] = 0x000080033e200a0aULL;
		regs[(r + 0x28) / 8] = 50000000;
		regs[(r + 0x70) / 8] = 250000000;
		regs[(r + 0x68) / 8] = 10000000;
		regs[(r + 0x60) / 8] = d ? 250000000 : 300000000;
		regs[(p + 0x28) / 8] = 0x544d002000000001ULL;
		regs[p / 8] = 9; regs[(p + 8) / 8] = 1;
		regs[(p + 0x10) / 8] = 50000000;
		regs[(p + 0x18) / 8] = 50000;
		regs[(p + 0x20) / 8] = 450000;
		for (i = 0; i < 8; i++) {
			regs[(p + 0x40 + i * 8) / 8] = i ? 100 : 125000;
			regs[(p + 0x80 + i * 8) / 8] = 0xffffffffULL;
		}
	}
}
int main(void)
{
	struct vcm_snapshot s;
	struct vcm_rate r;
	setup(); regs[8 / 8] = 125000000; regs[0x10 / 8] = 1026;
	assert(vcm_current_rate(rd, NULL, 0) == 125000000);
	regs[0x10 / 8] |= 1; assert(!vcm_current_rate(rd, NULL, 0));
	regs[0x10 / 8] = 1538; assert(!vcm_current_rate(rd, NULL, 0));
	regs[0x10 / 8] = 2; assert(!vcm_current_rate(rd, NULL, 0));
	regs[0x10 / 8] = 1026; regs[8 / 8] = 300000001;
	assert(!vcm_current_rate(rd, NULL, 0));
	regs[8 / 8] = 125000000; mode = 3; reads = 0;
	assert(!vcm_current_rate(rd, NULL, 0) && reads <= 20);
	assert(!vcm_current_rate(rd, NULL, 2));
	setup(); assert(!vcm_validate(rd, NULL));
	assert(!vcm_read_snapshot(rd, NULL, &s, 4));
	assert(s.domain[0].sequence == s.domain[1].sequence);
	assert(vcm_measured_hz(&s.domain[0]) == 125000000);
	assert(s.domain[1].total[7] == 0xffffffffU);
	assert(!vcm_read_rate(rd, NULL, 0, &r, 4));
	assert(vcm_read_rate(rd, NULL, 2, &r, 4) == -EINVAL);
	setup(); regs[0x78 / 8] = 0x4352000300000001ULL; assert(vcm_validate(rd, NULL) == -EPROTO);
	setup(); regs[0x278 / 8] = 0; /* This is a counter, not the descriptor. */
	regs[0x228 / 8] = 0x544d002000000002ULL; assert(vcm_validate(rd, NULL) == -EPROTO);
	setup(); regs[0x38 / 8] ^= 1; assert(vcm_validate(rd, NULL) == -EPROTO);
	setup(); regs[0x70 / 8] = 125000000; assert(vcm_validate(rd, NULL) == -EPROTO);
	setup(); regs[0x128 / 8] = 0x544d002100000001ULL; assert(vcm_read_snapshot(rd, NULL, &s, 4) == -EPROTO);
	setup(); regs[0x128 / 8] = 0x544d000300000001ULL; assert(vcm_read_snapshot(rd, NULL, &s, 4) == -EPROTO);
	setup(); regs[0x140 / 8] = 0x100000000ULL; assert(vcm_read_snapshot(rd, NULL, &s, 4) == -EPROTO);
	setup(); regs[0x118 / 8] = 0; assert(vcm_read_snapshot(rd, NULL, &s, 4) == -EPROTO);
	setup(); regs[0x108 / 8] = 8; assert(vcm_read_snapshot(rd, NULL, &s, 4) == -EPROTO);
	setup(); regs[0x108 / 8] = 4; assert(!vcm_read_snapshot(rd, NULL, &s, 4));
	assert(!vcm_meter_valid(&s.domain[0]) && !vcm_measured_hz(&s.domain[0]));
	setup(); regs[0x108 / 8] = 3; regs[0x140 / 8] = 0;
	assert(!vcm_read_snapshot(rd, NULL, &s, 4));
	assert(vcm_meter_valid(&s.domain[0]) && !vcm_measured_hz(&s.domain[0]));
	setup(); mode = 1; assert(vcm_read_snapshot(rd, NULL, &s, 4) == -EAGAIN && reads < 300);
	setup(); mode = 2; assert(vcm_read_snapshot(rd, NULL, &s, 1) == -EAGAIN);
	setup(); regs[0x200 / 8]++; assert(vcm_read_snapshot(rd, NULL, &s, 4) == -EAGAIN);
	setup(); regs[0x220 / 8]++; assert(vcm_read_snapshot(rd, NULL, &s, 4) == -EAGAIN);
	setup(); mode = 3; assert(vcm_read_rate(rd, NULL, 0, &r, 4) == -EAGAIN && reads < 100);
	/* Narrow-width bank: no silent truncation, raw modulo totals preserved. */
	setup(); regs[0x128 / 8] = 0x544d000400000001ULL;
	assert(vcm_read_snapshot(rd, NULL, &s, 4) == -EPROTO);
	regs[0x118 / 8] = regs[0x218 / 8] = 1;
	for (unsigned int i = 0; i < 8; i++) {
		regs[(0x140 + i * 8) / 8] = 1;
		regs[(0x180 + i * 8) / 8] = 15;
	}
	assert(!vcm_read_snapshot(rd, NULL, &s, 4) && s.domain[0].total[0] == 15);
	regs[0x180 / 8] = 16; assert(vcm_read_snapshot(rd, NULL, &s, 4) == -EPROTO);
	/* ABI2 is admitted only for an explicit dual-retirement CPU profile. */
	setup(); regs[0x128 / 8] = 0x544d002000000002ULL;
	assert(vcm_validate(rd, NULL) == -EPROTO);
	assert(!vcm_validate_profile(rd, NULL, 2));
	assert(!vcm_read_snapshot_profile(rd, NULL, &s, 4, 2));
	assert(s.domain[0].retirement_lanes == 2 && s.domain[1].retirement_lanes == 1);
	regs[0x148 / 8] = 250000;
	assert(!vcm_read_snapshot_profile(rd, NULL, &s, 4, 2));
	assert(s.domain[0].delta[1] == 250000 && vcm_measured_hz(&s.domain[0]) == 125000000);
	regs[0x228 / 8] = 0x544d002000000002ULL;
	assert(vcm_validate_profile(rd, NULL, 2) == -EPROTO);
	assert(vcm_read_snapshot_profile(rd, NULL, &s, 4, 2) == -EPROTO);
	setup(); assert(vcm_validate_profile(rd, NULL, 2) == -EPROTO);
	assert(vcm_validate_profile(rd, NULL, 0) == -EPROTO);
	assert(vcm_validate_profile(rd, NULL, 3) == -EPROTO);
	/* Dual lane aggregate can wrap twice as fast: 10 bits / 12 edges per
	 * AON cycle admits window85, rejects86 even though ABI1 would admit it. */
	setup(); regs[0x128 / 8] = 0x544d000a00000002ULL;
	regs[0x118 / 8] = regs[0x218 / 8] = 85;
	for (unsigned int i = 0; i < 8; i++) {
		regs[(0x140 + i * 8) / 8] = 176;
		regs[(0x180 + i * 8) / 8] = 1023;
	}
	assert(!vcm_read_snapshot_profile(rd, NULL, &s, 4, 2));
	assert(s.domain[0].delta[1] == 176);
	regs[0x118 / 8] = regs[0x218 / 8] = 86;
	assert(vcm_read_snapshot_profile(rd, NULL, &s, 4, 2) == -EPROTO);
	setup(); regs[0x128 / 8] = 0x544d002000000002ULL; mode = 2;
	assert(vcm_read_snapshot_profile(rd, NULL, &s, 1, 2) == -EAGAIN);
	puts("CLOCKMON_ABI_HOST_PASS identity width bounded_stability cross_bank_sequence live_invalidate invalid_window exact_frequency read_only");
}
