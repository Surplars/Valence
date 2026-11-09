"""Independent byte-addressed AXI environment. No cache/home state is read."""
from collections import deque, Counter


def require(condition, message):
    if not condition:
        raise AssertionError(message)


class Memory:
    def __init__(self, image, base=4096):
        self.bytes = dict(image)
        self.base = base
        self.reads = {}
        self.writes = deque()
        self.acks = deque()
        self.r = None
        self.delay = 32
        self.delay_by_line = {}
        self.hold_r = self.hold_w = False
        self.count = Counter()

    def inputs(self, cycle):
        if self.r is None and not self.hold_r:
            eligible = [tag for tag, q in self.reads.items() if q['due'] <= cycle]
            if eligible:
                tag = max(eligible)
                q = self.reads[tag]
                start = q['beat'] * 8
                self.r = dict(id=tag, data=int.from_bytes(q['bytes'][start:start+8], 'little'),
                              resp=0, last=int(q['beat'] == q['beats']-1))
        out = {'ddrAxi.ar.ready': len(self.reads) < 4, 'ddrAxi.aw.ready': len(self.writes) < 2,
               'ddrAxi.w.ready': bool(self.writes) and not self.hold_w,
               'ddrAxi.r.valid': self.r is not None,
               'ddrAxi.b.valid': bool(self.acks and self.acks[0]['due'] <= cycle)}
        if self.r:
            out.update({'ddrAxi.r.bits.' + k: v for k, v in self.r.items()})
        if self.acks:
            out.update({'ddrAxi.b.bits.id': self.acks[0]['id'], 'ddrAxi.b.bits.resp': 0})
        return out

    def sample(self, actual, inputs, cycle):
        a, s = actual, inputs
        for channel in ['ar', 'aw']:
            prefix = 'ddrAxi.' + channel
            if a[prefix + '.valid'] and s[prefix + '.ready']:
                tag = a[prefix + '.bits.id']
                address = self.base + a[prefix + '.bits.addr']
                beats = a[prefix + '.bits.len'] + 1
                require(a[prefix+'.bits.size'] == 3 and a[prefix+'.bits.burst'] == 1,
                        'AXI is not an aligned 64-bit INCR transfer')
                require(address % 8 == 0 and beats in (1, 8), 'unexpected AXI geometry')
                require(all(address+i in self.bytes for i in range(beats*8)), 'AXI address escaped independent image')
                if channel == 'ar':
                    require(tag not in self.reads, 'AXI reused a live read ID')
                    self.reads[tag] = dict(address=address, beats=beats, beat=0,
                                          bytes=bytes(self.bytes[address+i] for i in range(beats*8)),
                                          due=cycle+self.delay_by_line.get(address & ~63, self.delay))
                else:
                    require(all(q['id'] != tag for q in [*self.writes, *self.acks]), 'AXI reused a live write ID')
                    self.writes.append(dict(id=tag,address=address,beats=beats,beat=0))
                self.count[channel] += 1
        if a['ddrAxi.w.valid'] and s['ddrAxi.w.ready']:
            require(self.writes, 'unowned AXI W beat')
            q = self.writes[0]
            require(bool(a['ddrAxi.w.bits.last']) == (q['beat'] == q['beats']-1), 'AXI WLAST owner mismatch')
            data = a['ddrAxi.w.bits.data'].to_bytes(8, 'little')
            for i in range(8):
                if a['ddrAxi.w.bits.strb'] >> i & 1:
                    self.bytes[q['address'] + q['beat']*8+i] = data[i]
            q['beat'] += 1
            if q['beat'] == q['beats']:
                self.acks.append(dict(id=q['id'],due=cycle+3)); self.writes.popleft()
            self.count['w'] += 1
        if s['ddrAxi.r.valid'] and a['ddrAxi.r.ready']:
            require(self.r is not None, 'R fire without independent held offer')
            q = self.reads[self.r['id']]
            q['beat'] += 1
            if self.r['last']:
                require(q['beat'] == q['beats'], 'AXI read ended early')
                del self.reads[self.r['id']]
            self.r = None; self.count['r'] += 1
        if s['ddrAxi.b.valid'] and a['ddrAxi.b.ready']:
            require(self.acks and self.acks[0]['due'] <= cycle, 'unowned AXI B')
            self.acks.popleft(); self.count['b'] += 1

    def busy(self):
        return bool(self.reads or self.writes or self.acks or self.r)
