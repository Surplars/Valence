/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef VALENCE_IRQ_POLICY_H
#define VALENCE_IRQ_POLICY_H

#define VA_SOURCES 31
#define VA_SELFTEST_SOURCE 31
#define VA_CLAIM_BUDGET 64
#define VG_NAPI_WEIGHT 8
#define VG_NAPI_TIME_NS 2000000ULL

static inline unsigned int va_claim_id(unsigned long word)
{
	return (word >> 16) & 0x7ff;
}

static inline int va_valid_source(unsigned int source)
{
	return source && source <= VA_SOURCES;
}

static inline int va_claim_valid(unsigned long word)
{
	unsigned int id = va_claim_id(word);

	return va_valid_source(id) && (word & 0x7ff) == id;
}

static inline int va_retrigger_level(unsigned int levels, unsigned int source,
				     unsigned int inputs)
{
	return va_valid_source(source) && (levels & inputs & (1U << source));
}

static inline int vg_irq_allowed(int running, int configured, int faulted)
{
	return running && configured && !faulted;
}

#endif
