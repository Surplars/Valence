/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef VALENCE_RX_QUEUE_H
#define VALENCE_RX_QUEUE_H
/* Portable ownership core shared by the kernel adapter and its fake-MMIO test.
 * No buffer is returned to software until its retained completion is consumed.
 * Callers serialize these operations and copy payload before release/repost.
 */
#ifdef __KERNEL__
#include <linux/types.h>
typedef u64 vgq_u64;
typedef u32 vgq_u32;
#else
#include <stdint.h>
#include <stdbool.h>
typedef uint64_t vgq_u64;
typedef uint32_t vgq_u32;
#endif
#define VGQ_MAX_SLOTS 16U
#define VGQ_CAP 0x98U
#define VGQ_CAP_POSTED 2ULL
#define VGQ_POST_ADDRESS 0xa0U
#define VGQ_POST_CAPACITY 0xa8U
#define VGQ_POST 0xb0U
#define VGQ_CONTROL 0xb8U
#define VGQ_STATUS 0xc0U
#define VGQ_COMPLETE_ADDRESS 0xc8U
#define VGQ_COMPLETE_RESULT 0xd0U
#define VGQ_POP 0xd8U
#define VGQ_STOPPED (1ULL << 17)
#define VGQ_ERROR (1ULL << 16)
struct vgq_ops {
	void *context;
	vgq_u64 (*read)(void *, unsigned int);
	void (*write)(void *, unsigned int, vgq_u64);
	void (*publish)(void *);
	void (*consume)(void *);
};
struct vgq_ring {
	struct vgq_ops ops;
	vgq_u64 address[VGQ_MAX_SLOTS];
	vgq_u32 owned;
	unsigned int slots, capacity, completion_slot, completion_high_water;
	unsigned int order[VGQ_MAX_SLOTS], head, tail, posted;
	bool enabled, completion_seen;
};
struct vgq_completion {
	unsigned int slot, bytes;
	bool error;
};
/* Unknown/malformed capability records use the reset legacy ABI. */
static inline unsigned int vgq_cap_slots(vgq_u64 cap)
{
	unsigned int slots = (cap >> 8) & 255;
	return (cap & 3) == 3 && slots && slots <= VGQ_MAX_SLOTS &&
	       !(slots & (slots - 1)) ? slots : 0;
}
static inline unsigned int vgq_count(vgq_u32 mask)
{
	unsigned int n = 0;
	while (mask) { mask &= mask - 1; ++n; }
	return n;
}
static inline unsigned int vgq_hw_owned(vgq_u64 status)
{
	return (status & 255) + ((status >> 8) & 255) + ((status >> 16) & 1);
}
static inline int vgq_init(struct vgq_ring *q, struct vgq_ops ops,
			  unsigned int slots, unsigned int capacity,
			  const vgq_u64 *address)
{
	unsigned int i, j;
	if (!slots || slots > VGQ_MAX_SLOTS || !capacity || capacity > 16384 ||
	    !ops.read || !ops.write || !ops.publish || !ops.consume)
		return -1;
	for (i = 0; i < slots; ++i) {
		if ((address[i] & 7) || address[i] > ~(vgq_u64)0 - capacity)
			return -1;
		for (j = 0; j < i; ++j)
			if (address[i] < address[j] + capacity && address[j] < address[i] + capacity)
				return -1;
	}
	q->ops = ops; q->slots = slots; q->capacity = capacity;
	q->owned = 0; q->enabled = false; q->completion_seen = false;
	q->head = q->tail = q->posted = q->completion_high_water = 0;
	for (i = 0; i < slots; ++i) q->address[i] = address[i];
	return 0;
}
static inline int vgq_post(struct vgq_ring *q, unsigned int slot)
{
	if (!q->enabled || slot >= q->slots || (q->owned & (1U << slot)) ||
	    q->posted >= q->slots)
		return -1;
	q->ops.publish(q->ops.context);
	q->ops.write(q->ops.context, VGQ_POST_ADDRESS, q->address[slot]);
	q->ops.write(q->ops.context, VGQ_POST, 1);
	q->owned |= 1U << slot;
	q->order[q->tail] = slot; q->tail = (q->tail + 1) % q->slots; ++q->posted;
	return 0;
}
static inline int vgq_start(struct vgq_ring *q)
{
	unsigned int i;
	if (q->enabled || q->owned || (q->ops.read(q->ops.context, 0x48) & 1))
		return -1;
	q->ops.write(q->ops.context, 0x40, 2); /* clear an idle legacy completion */
	q->ops.write(q->ops.context, VGQ_CONTROL, 1);
	if (!(q->ops.read(q->ops.context, VGQ_CONTROL) & 1)) return -1;
	q->enabled = true;
	/* All buffers have identical capacity; publish it once, not per packet. */
	q->ops.write(q->ops.context, VGQ_POST_CAPACITY, q->capacity);
	for (i = 0; i < q->slots; ++i) if (vgq_post(q, i)) return -1;
	return 0;
}
/* 1=retained completion, 0=no work, -1=ownership/reset/stop fault. */
static inline int vgq_peek(struct vgq_ring *q, struct vgq_completion *c)
{
	vgq_u64 status, address, result;
	unsigned int i;
	q->completion_seen = false;
	if (!q->enabled) return -1;
	status = q->ops.read(q->ops.context, VGQ_STATUS);
	if ((status & VGQ_STOPPED) || vgq_hw_owned(status) != q->posted || q->posted != vgq_count(q->owned)) return -1;
	if (!((status >> 8) & 255)) return 0;
	if (((status >> 8) & 255) > q->completion_high_water)
		q->completion_high_water = (status >> 8) & 255;
	address = q->ops.read(q->ops.context, VGQ_COMPLETE_ADDRESS);
	result = q->ops.read(q->ops.context, VGQ_COMPLETE_RESULT);
	i = q->order[q->head];
	if (!q->posted || i >= q->slots || q->address[i] != address || !(q->owned & (1U << i))) return -1;
	q->ops.consume(q->ops.context);
	q->completion_slot = i; q->completion_seen = true;
	c->slot = i; c->bytes = result & 65535; c->error = !!(result & VGQ_ERROR);
	return 1;
}
static inline int vgq_release(struct vgq_ring *q, unsigned int slot, bool repost)
{
	if (!q->enabled || !q->completion_seen || slot != q->completion_slot ||
	    slot >= q->slots || !q->posted || q->order[q->head] != slot ||
	    !(q->owned & (1U << slot))) return -1;
	q->ops.write(q->ops.context, VGQ_POP, 1);
	q->owned &= ~(1U << slot); q->completion_seen = false;
	q->head = (q->head + 1) % q->slots; --q->posted;
	return repost ? vgq_post(q, slot) : 0;
}
/* Shared bound: budget zero is TX-only; never complete NAPI from that call. */
static inline bool vgq_poll_yield(unsigned int work, unsigned int budget,
				 vgq_u64 now, vgq_u64 deadline)
{
	return budget && work && (work >= budget || now >= deadline);
}
#endif
