/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef VALENCE_TX_QUEUE_H
#define VALENCE_TX_QUEUE_H
#include "valence_rx_queue.h"
#define VGT_ADDRESS 0xe0U
#define VGT_RESULT 0xe8U
#define VGT_COMMAND 0xf0U
#define VGT_STATUS 0xf8U
#define VGT_ENABLE 1U
#define VGT_DISABLE 2U
#define VGT_POST 4U
#define VGT_POP 8U
#define VGT_STOP 16U
struct vgt_ring {
	struct vgq_ops ops;
	vgq_u64 address[VGQ_MAX_SLOTS];
	unsigned int length[VGQ_MAX_SLOTS], order[VGQ_MAX_SLOTS];
	vgq_u32 owned;
	unsigned int slots, capacity, posted, head, tail, completion_slot, completion_high_water;
	bool enabled, completion_seen;
};
static inline unsigned int vgt_cap_slots(vgq_u64 cap)
{
	unsigned int slots = (cap >> 24) & 255;
	return (cap & 4) && slots && slots <= VGQ_MAX_SLOTS && !(slots & (slots - 1)) ? slots : 0;
}
static inline int vgt_init(struct vgt_ring *q, struct vgq_ops ops,
		unsigned int slots, unsigned int capacity, const vgq_u64 *address)
{
	struct vgq_ring validation;
	unsigned int i;
	if (vgq_init(&validation, ops, slots, capacity, address)) return -1;
	q->ops = ops; q->slots = slots; q->capacity = capacity;
	q->owned = q->posted = q->head = q->tail = q->completion_high_water = 0;
	q->enabled = q->completion_seen = false;
	for (i = 0; i < slots; ++i) { q->address[i] = address[i]; q->length[i] = 0; }
	return 0;
}
static inline int vgt_start(struct vgt_ring *q)
{
	if (q->enabled || q->owned || (q->ops.read(q->ops.context, 0x28) & 1)) return -1;
	q->ops.write(q->ops.context, 0x20, 2);
	q->ops.write(q->ops.context, VGT_COMMAND, VGT_ENABLE);
	if (!(q->ops.read(q->ops.context, VGT_COMMAND) & 1)) return -1;
	q->enabled = true;
	return 0;
}
static inline int vgt_free_slot(const struct vgt_ring *q)
{
	unsigned int i;
	if (!q->enabled || q->posted >= q->slots) return -1;
	for (i = 0; i < q->slots; ++i) if (!(q->owned & (1U << i))) return (int)i;
	return -1;
}
static inline int vgt_post(struct vgt_ring *q, unsigned int slot, unsigned int bytes)
{
	if (!q->enabled || q->posted >= q->slots || slot >= q->slots ||
	    (q->owned & (1U << slot)) || !bytes || bytes > q->capacity) return -1;
	q->ops.publish(q->ops.context);
	q->ops.write(q->ops.context, VGT_ADDRESS, q->address[slot]);
	q->ops.write(q->ops.context, VGT_RESULT, bytes);
	q->ops.write(q->ops.context, VGT_COMMAND, VGT_POST);
	q->owned |= 1U << slot; q->length[slot] = bytes;
	q->order[q->tail] = slot; q->tail = (q->tail + 1) % q->slots; ++q->posted;
	return 0;
}
static inline int vgt_peek(struct vgt_ring *q, struct vgq_completion *c)
{
	vgq_u64 status, address, result;
	unsigned int slot;
	q->completion_seen = false;
	if (!q->enabled) return -1;
	status = q->ops.read(q->ops.context, VGT_STATUS);
	if (!(status & (1ULL << 18)) || (status & VGQ_STOPPED) ||
	    vgq_hw_owned(status) != q->posted || q->posted != vgq_count(q->owned)) return -1;
	if (!((status >> 8) & 255)) return 0;
	if (((status >> 8) & 255) > q->completion_high_water) q->completion_high_water = (status >> 8) & 255;
	address = q->ops.read(q->ops.context, VGT_ADDRESS);
	result = q->ops.read(q->ops.context, VGT_RESULT);
	slot = q->order[q->head];
	if (!q->posted || slot >= q->slots || q->address[slot] != address || !(q->owned & (1U << slot)) ||
	    (!(result & VGQ_ERROR) && (result & 65535) != q->length[slot])) return -1;
	q->ops.consume(q->ops.context);
	q->completion_slot = slot; q->completion_seen = true;
	c->slot = slot; c->bytes = q->length[slot]; c->error = !!(result & VGQ_ERROR);
	return 1;
}
static inline int vgt_release(struct vgt_ring *q, unsigned int slot)
{
	if (!q->enabled || !q->completion_seen || slot != q->completion_slot || slot >= q->slots ||
	    !q->posted || q->order[q->head] != slot || !(q->owned & (1U << slot))) return -1;
	q->ops.write(q->ops.context, VGT_COMMAND, VGT_POP);
	q->owned &= ~(1U << slot); q->completion_seen = false;
	q->head = (q->head + 1) % q->slots; --q->posted;
	return 0;
}
#endif
