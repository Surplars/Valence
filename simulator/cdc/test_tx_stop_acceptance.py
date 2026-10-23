#!/usr/bin/env python3
"""Independent exhaustive STOP acceptance/priority law, not an RTL simulation.

The full DMA's live assertion separately compares its actual old/new expressions.
Run the queue GSIM events test for actual descriptor state transitions.
"""
from itertools import product

def check():
    count = 0
    # Command/state classes include simultaneous engine completion, live pause,
    # stalled reply credit, malformed accesses, full owners and illegal POST.
    for flags in product((False, True), repeat=12):
        (valid, ready, write, hit, size_ok, mask_ok, enabled, empty,
         space, descriptor_ok, completed, stopped) = flags
        for offset, data in product((16, 224, 232, 240, 248, 256), (0, 1, 2, 4, 8, 16, 17, 1 << 63)):
            queue_known = offset in (224, 232, 240, 248)
            basic = hit and (queue_known or offset == 16) and size_ok and mask_ok
            commands = {1: not enabled and empty, 2: enabled and empty,
                        4: enabled and not stopped and space and descriptor_ok,
                        8: enabled and completed, 16: enabled}
            allowed = queue_known and (not write or offset in (224, 232) or
                                      (offset == 240 and commands.get(data, False)))
            # Other register-specific prohibitions cannot apply at offset240.
            legal = basic and (not write or ((offset != 16 or not enabled) and
                                             (not queue_known or allowed)))
            old_write = valid and ready and legal and write and queue_known
            old_stop = old_write and offset == 240 and data == 16
            new_stop = valid and ready and basic and write and offset == 240 and data == 16 and enabled
            assert old_stop == new_stop, (flags, offset, data)
            for active, idle, paused, pending in product((False, True), repeat=4):
                def transition(stop):
                    eligible = enabled and not active and idle and (not paused or stopped or stop) and pending
                    cancel = eligible and (stopped or stop)
                    launch = eligible and not cancel
                    return eligible, cancel, launch
                assert transition(old_stop) == transition(new_stop)
            count += 1
    print(f'TX_STOP_ACCEPTANCE_PASS accesses={count} priority_cases={count * 16}')

if __name__ == '__main__':
    check()
