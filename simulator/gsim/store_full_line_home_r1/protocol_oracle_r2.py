"""Independent B0 accepted-event oracle. No simulator/DUT private-state imports.
Trace producer and runtime remain gated. Call edge events in the declared order;
record pre-edge offers separately for stability checks. Addresses here are full PA.
"""
from collections import deque


def require(ok, why):
    if not ok:
        raise AssertionError(why)


class Oracle:
    def __init__(self):
        self.requests = deque()
        self.acquire = {}
        self.sinks = {}
        self.results = deque()
        self.directory = {}  # physical line -> independent abstract directory slot
        self.reserved = {}
        self.release = {}
        self.ar = {}
        self.read_requests = []
        self.target_read_bytes = {}
        self.returned_read_bytes = {}
        self.held = {}
        self.sequence = 0
        self.expected_read_bytes = None
        self.aw = {}
        self.aw_order = deque()
        self.w_complete = deque()
        self.w_beats = []

    def offer(self, channel, valid, ready, payload):
        if channel in self.held:
            require(valid and payload == self.held[channel], 'withdrawn/changed held '+channel)
        if valid and not ready:
            self.held[channel] = payload
        else:
            self.held.pop(channel, None)

    def expect_reads(self, counts):
        require(not self.acquire and not self.target_read_bytes, "declare expected reads before traffic")
        self.expected_read_bytes = dict(counts)

    def engine_denied_shim(self, source):
        require(source in self.acquire, "shim without engine owner")
        self.acquire[source]["engine_error"] = True

    def request(self, tag, address, permission):
        require(address % 64 == 0 and 4096 <= address < 8192, 'request shape')
        require(all(x['tag'] != tag for x in self.acquire.values()) and
                all(x[0] != tag for x in self.requests), 'live caller tag reuse')
        self.requests.append((tag, address, permission))

    def a(self, source, address, opcode, param, size):
        require(source not in self.acquire and self.requests, 'A source/request ownership')
        tag, expected, perm = self.requests.popleft()
        require((address, opcode, param, size) == (expected, 7 if perm else 6, 1, 6), 'A shape/kind')
        require(address not in self.directory and all(x['address'] != address for x in self.acquire.values()), 'A line alias')
        slots = [(address >> 6) & 7, 8 + ((address >> 6) & 7)]
        occupied = set(self.directory.values()) | set(self.reserved)
        available = [s for s in slots if s not in occupied]
        paired = None
        if not available:
            candidates = [(src, x) for src, x in self.release.items()
                          if x['beats'] < 8 and x['slot'] in slots and x['slot'] not in self.reserved]
            require(len(candidates) == 1, 'no exact future directory')
            _, old = candidates[0]
            paired = old
            require(old['address'] != address, 'future aliases old dirty line')
            slot = old['slot']
        else:
            slot = available[0]
        self.reserved[slot] = source
        self.acquire[source] = dict(tag=tag, address=address, perm=perm, slot=slot,
                                    paired=paired, beats=0, denied=False)

    def grant(self, source, sink, opcode, size, cap, denied, corrupt, internal=False):
        require(source in self.acquire, 'grant without source')
        a = self.acquire[source]
        require(size == 6 and cap == 0, 'grant requires toT')
        require(opcode == (4 if a['perm'] else 5), 'wrong grant opcode')
        require(not (a['perm'] and (corrupt or internal)), 'permission grant transport/corrupt')
        if a['paired'] is not None:
            old = a['paired']
            require(old['beats'] == 8, 'grant before paired C-last')
        if a['beats'] == 0:
            require(sink not in self.sinks, 'live sink reused')
            self.sinks[sink] = source
            a['sink'] = sink
        else:
            require(a['sink'] == sink, 'grant changed sink')
        a['denied'] |= denied or corrupt
        a['beats'] += 8 if internal else 1
        require(a['beats'] <= (1 if a['perm'] else 8), 'extra grant beat')

    def e(self, sink):
        require(sink in self.sinks, 'E without sink')
        source = self.sinks.pop(sink)
        a = self.acquire[source]
        require(a['beats'] == (1 if a['perm'] else 8), 'E before complete grant')
        require(a['slot'] not in self.directory.values(), 'E directory still owned')
        if not a['denied']:
            self.directory[a['address']] = a['slot']
        del self.reserved[a['slot']]
        self.results.append((a['tag'], not a['perm'], a['denied'] or a.get('engine_error', False)))
        # Engine still retains its source until result is consumed.
        a['acked'] = True

    def result(self, tag, has_data, error):
        require((tag, has_data, error) in self.results, 'result before E/wrong identity')
        self.results.remove((tag, has_data, error))
        matches = [s for s, a in self.acquire.items() if a['tag'] == tag and a.get('acked')]
        require(len(matches) == 1, 'result generation ownership')
        del self.acquire[matches[0]]

    def c(self, source, address, beat, last, data):
        if source not in self.release:
            require(beat == 0 and address in self.directory, 'release requires committed owner')
            self.release[source] = dict(address=address, slot=self.directory[address], beats=0, b=False, words=[], aw=False)
        r = self.release[source]
        require(address == r['address'] and beat == r['beats'] and last == (beat == 7), 'C identity/count')
        r['words'].append(data)
        r['beats'] += 1
        if last:
            del self.directory[address]  # selected mixed-mode C-last contract

    def axi_aw(self, ident, offset, length, size, burst):
        require(ident not in self.aw and (length, size, burst) == (7, 3, 1), 'AW identity/shape')
        address = 4096 + offset
        matches = [(src, r) for src, r in self.release.items()
                   if r['address'] == address and r['beats'] == 8 and not r['aw']]
        require(len(matches) == 1, 'AW without exact complete dirty victim')
        src, r = matches[0]
        r['aw'] = True
        self.aw[ident] = dict(source=src, owner=r, wdone=False)
        self.aw_order.append(ident)
        self.pair_writes()

    def axi_w(self, data, strobe, last):
        require(strobe == 255 and last == (len(self.w_beats) == 7), 'W strobe/count/last')
        self.w_beats.append(data)
        if last:
            self.w_complete.append(self.w_beats)
            self.w_beats = []
        self.pair_writes()

    def pair_writes(self):
        # AXI4 W has no ID: write bursts associate in accepted AW order.
        # Either W or AW can arrive first; neither authorizes B alone.
        while self.aw_order and self.w_complete:
            ident = self.aw_order.popleft()
            words = self.w_complete.popleft()
            a = self.aw[ident]
            require(words == a['owner']['words'], 'backing W differs from accepted dirty C payload')
            a['wdone'] = True

    def axi_b(self, ident, response):
        require(ident in self.aw and self.aw[ident]['wdone'] and response == 0, 'B ownership/data/error')
        a = self.aw.pop(ident)
        require(self.release.get(a['source']) is a['owner'] and not a['owner']['b'], 'B release generation')
        a['owner']['b'] = True

    def release_ack(self, source):
        require(source in self.release and self.release[source]['b'], 'ReleaseAck before B')
        del self.release[source]  # never erase a reused directory

    def line_read(self, address):
        require(not any(a['address'] == address and a['perm'] for a in self.acquire.values()), 'permission target logical read')
        self.read_requests.append(address)

    def axi_ar(self, ident, offset, length, size, burst):
        require(ident not in self.ar and size == 3 and length == 7 and burst == 1, 'AR identity/shape')
        address = 4096 + offset
        require(address % 64 == 0 and address in self.read_requests, 'AR without independent logical read')
        self.read_requests.remove(address)
        require(self.expected_read_bytes is not None and address in self.expected_read_bytes, 'unplanned target AR')
        require(self.target_read_bytes.get(address, 0) + 64 <= self.expected_read_bytes[address], 'target read exceeds declared budget')
        self.ar[ident] = [address, 0]
        self.target_read_bytes[address] = self.target_read_bytes.get(address, 0) + 64

    def axi_r(self, ident, last):
        require(ident in self.ar, 'R without AR')
        address, beat = self.ar[ident]
        require(last == (beat == 7), 'R count/last')
        self.returned_read_bytes[address] = self.returned_read_bytes.get(address, 0) + 8
        if last:
            del self.ar[ident]
        else:
            self.ar[ident][1] += 1

    def drained(self):
        require(not (self.requests or self.acquire or self.sinks or self.results or self.reserved or
                     self.release or self.ar or self.read_requests or self.held or self.aw or self.aw_order or self.w_complete or self.w_beats), 'undrained owner')
        require(self.target_read_bytes == self.returned_read_bytes, 'DDR read byte mismatch')
        require(self.expected_read_bytes is not None, 'missing independent per-target read expectation')
        for address, expected in self.expected_read_bytes.items():
            require(self.target_read_bytes.get(address, 0) == expected, 'full-drain target byte expectation')
