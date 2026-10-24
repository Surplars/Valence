/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <pthread.h>
#include "valence_cpu_rate_transaction.h"
struct fixture { u64 r[16]; unsigned int writes, pauses, fault; };
static u64 rd(void *p, unsigned int off)
{
	struct fixture *f = p;
	assert(!(off & 7) && off < 0x80); /* Never touches fabric. */
	return f->r[off / 8];
}
static void wr(void *p, unsigned int off, u64 value)
{
	struct fixture *f = p;
	assert(off == 0x30 || off == 0);
	assert(off == ((f->writes & 1) ? 0 : 0x30));
	f->writes++;
	if (off == 0x30 && f->fault == 1) return;
	f->r[off / 8] = value;
	if (!off) {
		assert(f->r[6] == vcpu_parameters((u32)value));
		f->r[2] |= 1; f->r[11] = 1;
	}
}
static void pause_io(void *p)
{
	struct fixture *f = p;
	f->pauses++;
	if (f->fault == 2 || f->pauses < 2) return;
	f->r[2] = 1026 | 256; f->r[11] = 0;
	f->r[10] = (u32)(f->r[10] + 1);
	f->r[1] = f->r[4] = f->r[0];
	if (f->fault == 3) { /* Actual autonomous fallback, not software retry. */
		f->r[1] = f->r[4] = 50000000; f->r[3] = 16; f->r[2] &= ~256ULL;
	}
	if (f->fault == 4) f->r[10]++;
	if (f->fault == 5) f->r[1] = 100000000;
	if (f->fault == 6) f->r[2] |= 512;
}
static u64 now_us(void *p)
{
	return ((struct fixture *)p)->pauses * 100ULL;
}
static void setup(struct fixture *f)
{
	memset(f, 0, sizeof(*f));
	f->r[15] = 0x4352000300000002ULL; f->r[7] = 0x000080033e200a0aULL;
	f->r[8] = 0x30; f->r[5] = 50000000; f->r[14] = 250000000;
	f->r[13] = 10000000; f->r[12] = 300000000;
	f->r[0] = f->r[1] = f->r[4] = 50000000; f->r[6] = 0x14280a; f->r[2] = 1026;
}
static pthread_mutex_t owner = PTHREAD_MUTEX_INITIALIZER;
struct concurrent { struct vcpu_io *io; struct vcpu_transaction *t; int result; };
static void *request(void *p)
{
	struct concurrent *c = p;
	pthread_mutex_lock(&owner);
	c->result = vcpu_set(c->io, c->t, 125000000, 8);
	pthread_mutex_unlock(&owner);
	return NULL;
}
int main(void)
{
	struct fixture f; struct vcpu_transaction t = {0};
	struct vcpu_io io = { &f, rd, wr, pause_io, now_us };
	/* Initialization rejects prior Linux/firmware transactions and nonboot tuples. */
	setup(&f); f.r[10] = 1; assert(vcpu_initialize(&io, &t) == -EBUSY && !f.writes);
	setup(&f); f.r[6] = 0x10320a; assert(vcpu_initialize(&io, &t) == -EBUSY && !f.writes);
	setup(&f); f.r[1] = 125000000; assert(vcpu_initialize(&io, &t) == -EBUSY && !f.writes);
	setup(&f); assert(!vcpu_initialize(&io, &t)); assert(!vcpu_set(&io, &t, 50000000, 8) && !f.writes);
	assert(vcpu_set(&io, &t, 100000000, 8) == -EINVAL && !f.writes);
	assert(!vcpu_set(&io, &t, 125000000, 8));
	assert(t.actual_hz == 125000000 && !t.poisoned && f.writes == 2);
	f.pauses = 0; assert(!vcpu_set(&io, &t, 50000000, 8) && f.writes == 4);
	for (unsigned int field = 0; field < 7; field++) {
		static const unsigned int indices[] = {15, 7, 8, 5, 14, 13, 12};
		setup(&f); memset(&t, 0, sizeof(t)); t.initialized = 1; t.known_parameters = 0x14280a; f.r[indices[field]] ^= 1;
		assert(vcpu_set(&io, &t, 125000000, 8) == -EPROTO && !f.writes);
	}
	for (unsigned int fault = 1; fault <= 6; fault++) {
		setup(&f); memset(&t, 0, sizeof(t)); t.initialized = 1; t.known_parameters = 0x14280a; f.fault = fault;
		assert(vcpu_set(&io, &t, 125000000, 8) < 0 && t.poisoned);
		unsigned int writes = f.writes;
		assert(vcpu_set(&io, &t, 50000000, 8) == -EIO && f.writes == writes);
		if (fault == 2) {
			u32 completed;
			assert(!t.actual_hz); /* Timeout is unknown, not rollback. */
			f.fault = 0; pause_io(&f);
			assert(!vcpu_observe(&io, &t, &completed));
			assert(t.actual_hz == 125000000 && t.poisoned);
			assert(vcpu_set(&io, &t, 50000000, 8) == -EIO && f.writes == writes);
		}
		if (fault == 3) assert(t.actual_hz == 50000000 && t.errors);
	}
	setup(&f); memset(&t, 0, sizeof(t)); t.initialized = 1; t.known_parameters = 0x14280a; f.r[2] |= 0x800;
	assert(vcpu_set(&io, &t, 125000000, 8) == -EPROTO && !f.writes);
	setup(&f); f.r[3] = 0x400;
	assert(vcpu_set(&io, &t, 125000000, 8) == -EPROTO && !f.writes);
	setup(&f); memset(&t, 0, sizeof(t)); t.initialized = 1; t.known_parameters = 0x14280a; f.r[2] |= 1;
	assert(vcpu_set(&io, &t, 125000000, 8) == -EBUSY && !f.writes);
	setup(&f); f.r[3] = 1;
	assert(vcpu_set(&io, &t, 125000000, 8) == -EBUSY && !f.writes);
	setup(&f); f.r[10] = 0xffffffffU; t.last_completion = 0xffffffffU;
	assert(!vcpu_set(&io, &t, 125000000, 8) && f.r[10] == 0);
	setup(&f); memset(&t, 0, sizeof(t)); t.initialized = 1; t.known_parameters = 0x14280a;
	struct concurrent a = {&io, &t, -1}, b = {&io, &t, -1}; pthread_t ta, tb;
	assert(!pthread_create(&ta, NULL, request, &a));
	assert(!pthread_create(&tb, NULL, request, &b));
	assert(!pthread_join(ta, NULL) && !pthread_join(tb, NULL));
	assert(!a.result && !b.result && f.writes == 2);
	setup(&f); memset(&t, 0, sizeof(t)); assert(!vcpu_initialize(&io, &t));
	f.fault = 2;
	assert(vcpu_set(&io, &t, 125000000, 2000) == -ETIMEDOUT);
	assert(f.pauses == 1000 && t.poisoned && !t.actual_hz); /* Real TIME deadline. */
	setup(&f); memset(&t, 0, sizeof(t)); assert(!vcpu_initialize(&io, &t));
	f.r[2] |= 0x800;
	assert(vcpu_set(&io, &t, 125000000, 8) == -EPROTO && !t.actual_hz && !f.writes);
	setup(&f); memset(&t, 0, sizeof(t)); assert(!vcpu_initialize(&io, &t));
	f.r[10] = 1; /* Another owner, even at unchanged50, invalidates tuple proof. */
	assert(vcpu_set(&io, &t, 50000000, 8) == -EIO && t.poisoned && !f.writes);
	setup(&f); memset(&t, 0, sizeof(t)); assert(!vcpu_initialize(&io, &t));
	f.r[1] = 125000000; t.known_parameters = 0x0a320a;
	assert(vcpu_set(&io, &t, 125000000, 8) == -EIO && t.poisoned && !f.writes);
	puts("CPU_RATE_CORE_PASS exact_profiles preflight zero_write_rejection completion_wrap fallback timeout_poison no_retry concurrent_single_owner");
}
