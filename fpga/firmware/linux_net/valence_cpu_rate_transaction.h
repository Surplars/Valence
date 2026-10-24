/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef VALENCE_CPU_RATE_TRANSACTION_H
#define VALENCE_CPU_RATE_TRANSACTION_H
#include "valence_clockmon_abi.h"

/* One bounded rate page. The caller holds the sole owner mutex throughout.
 * CPU uses the default wrappers; boot-only fabric uses a page adapter and the
 * explicit 250 MHz cap. No W1C, retry, raw DRP or software rollback exists. */
struct vcpu_io {
	void *context;
	u64 (*read)(void *, unsigned int);
	void (*write)(void *, unsigned int, u64);
	void (*pause)(void *);
	u64 (*now_us)(void *);
};
struct vcpu_transaction {
	unsigned int poisoned, initialized;
	u32 known_parameters, last_completion;
	u32 requested_hz, actual_hz, before_completion;
	u64 errors, status;
};
static inline u32 vcpu_parameters(u32 hz)
{
	return hz == 50000000 ? 0x14280a : hz == 125000000 ? 0x08280a : 0;
}
static inline int vcpu_contract_limit(const struct vcpu_io *io, u32 maximum_hz)
{
	return io->read(io->context, 0x78) == 0x4352000300000002ULL &&
		io->read(io->context, 0x38) == 0x000080033e200a0aULL &&
		io->read(io->context, 0x40) == 0x30 &&
		io->read(io->context, 0x28) == 50000000 &&
		io->read(io->context, 0x70) == 250000000 &&
		io->read(io->context, 0x68) == 10000000 &&
		io->read(io->context, 0x60) == maximum_hz;
}
static inline int vcpu_observe(const struct vcpu_io *io, struct vcpu_transaction *t,
			       u32 *completed)
{
	u64 n = io->read(io->context, 0x50);
	u64 s = io->read(io->context, 0x10);
	u64 a = io->read(io->context, 8);
	u64 e = io->read(io->context, 0x18);
	t->actual_hz = 0; /* Any malformed/racing read must discard stale proof. */
	if ((s & ~0x7ffULL) || (e & ~0x3ffULL) || a > 0xffffffffULL)
		return -EPROTO;
	if (n > 0xffffffffULL || n != io->read(io->context, 0x50) ||
	    s != io->read(io->context, 0x10))
		return -EAGAIN;
	t->status = s; t->errors = e;
	t->actual_hz = (s & (1 | 2 | 512 | 1024)) == (2 | 1024) &&
		vcpu_parameters((u32)a) && a <= 0xffffffffULL ? (u32)a : 0;
	*completed = (u32)n;
	return 0;
}
/* Only untouched cold boot establishes an active tuple without a DRP read.
 * ABI reset values and completion0 bind boot50 to hardware's fixed M40/O20.
 * A pre-Linux rate transaction, even an equal-Hz tuple, is not admitted. */
static inline int vcpu_initialize_limit(const struct vcpu_io *io, struct vcpu_transaction *t, u32 maximum_hz)
{
	u32 completed;
	if (t->initialized || t->poisoned || !io->now_us)
		return -EINVAL;
	if (!vcpu_contract_limit(io, maximum_hz))
		return -EPROTO;
	if (vcpu_observe(io, t, &completed) || t->actual_hz != 50000000 ||
	    t->errors || completed || io->read(io->context, 0x58) ||
	    io->read(io->context, 0) != 50000000 ||
	    io->read(io->context, 0x20) != 50000000 ||
	    io->read(io->context, 0x30) != 0x14280a)
		return -EBUSY;
	t->known_parameters = 0x14280a; t->last_completion = 0;
	t->initialized = 1;
	return 0;
}
static inline int vcpu_set_limit(const struct vcpu_io *io, struct vcpu_transaction *t,
			   u32 hz, unsigned int polls, u32 maximum_hz)
{
	u32 n, parameters = vcpu_parameters(hz);
	unsigned int i;
	u64 started;
	int ret;
	if (t->poisoned)
		return -EIO;
	if (!t->initialized || !parameters || !polls || !io->now_us)
		return -EINVAL;
	if (!vcpu_contract_limit(io, maximum_hz))
		return -EPROTO;
	ret = vcpu_observe(io, t, &n);
	if (ret)
		return ret;
	if (!t->actual_hz || t->errors || io->read(io->context, 0x58) != 0)
		return -EBUSY;
	if (n != t->last_completion ||
	    t->known_parameters != vcpu_parameters(t->actual_hz)) {
		t->actual_hz = 0; t->poisoned = 1;
		return -EIO;
	}
	/* Boot50 is known. A same-rate request never changes the MMCM tuple. */
	if (t->actual_hz == hz)
		return 0;
	t->requested_hz = hz; t->before_completion = n;
	/* Poison before the first write: no uncertain partial submission can be
	 * retried. Only one verified successful completion clears this latch. */
	t->poisoned = 1;
	started = io->now_us(io->context);
	io->write(io->context, 0x30, parameters);
	if (io->read(io->context, 0x30) != parameters)
		return -EIO;
	if (io->now_us(io->context) - started >= 100000)
		return -ETIMEDOUT;
	io->write(io->context, 0, hz);
	for (i = 0; i < polls; i++) {
		if (io->now_us(io->context) - started >= 100000)
			break;
		ret = vcpu_observe(io, t, &n);
		if (!ret && n != t->before_completion && !(t->status & 1)) {
			if (n != (u32)(t->before_completion + 1) ||
			    !(t->status & 256) || t->errors || t->actual_hz != hz ||
			    io->read(io->context, 0x58) != 0 ||
			    io->read(io->context, 0x20) != hz ||
			    io->read(io->context, 0) != hz)
				return -EIO;
			t->known_parameters = parameters; t->last_completion = n;
			t->poisoned = 0;
			return 0;
		}
		/* Errors during autonomous fallback do not mean fallback completed. */
		if (io->pause)
			io->pause(io->context);
	}
	t->actual_hz = 0; /* Unknown outcome; never advertise a cached fallback. */
	return -ETIMEDOUT;
}
/* CPU wrappers keep their original strict 300 MHz maximum contract. The boot-
 * only fabric caller uses a bounded page adapter and the exact 250 MHz cap. */
static inline int vcpu_initialize(const struct vcpu_io *io, struct vcpu_transaction *t)
{
	return vcpu_initialize_limit(io, t, 300000000);
}
static inline int vcpu_set(const struct vcpu_io *io, struct vcpu_transaction *t,
			   u32 hz, unsigned int polls)
{
	return vcpu_set_limit(io, t, hz, polls, 300000000);
}
#endif
