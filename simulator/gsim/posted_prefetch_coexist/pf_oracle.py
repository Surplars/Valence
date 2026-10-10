"""Independent PF transaction ledger, beside the full posted token/byte contract.

Authored requests authorize candidate addresses. Actual A/D/E and C/ReleaseAck
handshakes account for transport lifetime. No observed success pulse produces an
expected byte, token, generation, or request. This is not a CPU proof producer.
"""
from collections import Counter


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def check_policy(policy, *, busy, episode, proof_offer, eligible_hit, candidate, allocated):
    """Obligations independent of READY: an offered proof protects the boundary."""
    if busy:
        require(not candidate and not allocated, 'PF crossed accepted posted/fallback responsibility')
    if proof_offer and (not policy or not eligible_hit):
        require(not candidate and not allocated, 'PF crossed a held non-legacy posted proof offer')
    if not policy and episode:
        require(not candidate and not allocated, 'policy OFF prefetched within a retained cohort')


class PrefetchLedger:
    def __init__(self, policy):
        self.policy = policy
        self.candidate = None
        self.misses = {}
        self.releases = {}
        self.count = Counter()
        self.history = []

    def empty(self):
        return self.candidate is None and not self.misses and not self.releases

    def sample(self, a, s, before, cycle):
        p = lambda field: a['pfObservation.' + field]
        q = before['request']
        offered = q is not None and bool(s['upstream.request.valid'])
        accepted = offered and bool(a['upstream.request.ready'])
        proof_offer = offered and bool(s['posted.requestProof.valid'])
        eligible_hit = bool(q and q['eligible'] and not before['exhausted'] and q['resident'])
        check_policy(self.policy, busy=bool(a['posted.busy']), episode=bool(a['posted.episodeActive']),
                     proof_offer=proof_offer, eligible_hit=eligible_hit,
                     candidate=bool(p('candidate')), allocated=bool(p('allocated')))
        require(p('candidate') == a['prefetch.candidate'] and p('allocated') == a['prefetch.allocated'],
                'public PF events detached from actual allocation observations')
        require(p('useful') == a['prefetch.useful'], 'public useful event disagreed')
        require(p('mshrLiveMask') == a['mshrMask'], 'posted and PF views lost physical MSHR identity')
        require(not (a['postedMask'] & p('mshrPrefetchMask') & p('mshrLiveMask')),
                'a physical MSHR became both posted and PF')
        live = p('mshrLiveMask') & p('mshrPrefetchMask')
        require(live == sum(1 << slot for slot in self.misses), 'PF MSHR lifetime differs from independent ledger')
        wb = p('wbLiveMask') & p('wbPrefetchMask')
        require(wb == sum(1 << slot for slot in self.releases), 'PF WB lifetime differs from exact ReleaseAck ledger')
        require(a['prefetch.missOwners'] == len(self.misses) and
                a['prefetch.releaseOwners'] == len(self.releases), 'public PF responsibility counts differ')
        require(bool(a['prefetchBusy']) == (not self.empty()), 'PF busy lost candidate/MSHR/ReleaseAck responsibility')
        if self.policy and a['fallback.valid']:
            require(not a['prefetchBusy'] and self.empty(), 'fallback admission crossed pre-edge PF responsibility')
        if a['accepted.valid']:
            require(not a['prefetchBusy'], 'new posted admission crossed pre-edge PF responsibility')
        if self.candidate is not None:
            if p('allocated'):
                slot, address = p('allocatedSlot'), p('allocatedAddress')
                require(address == self.candidate['address'], 'allocated PF address differs from authored next line')
                require(bool(p('allocatedStore')) == self.candidate['store'], 'PF origin changed while candidate held')
                require(not (p('mshrLiveMask') & (1 << slot)) and slot not in self.misses,
                        'PF allocation reused a live physical source')
                require(not p('demandAlloc') and not a['accepted.valid'], 'PF stole an admitted request slot')
                require(not (offered and s['upstream.request.bits.write']), 'PF allocation crossed offered write')
                self.misses[slot] = dict(self.candidate, acquired=False, beats=[], sink=None,
                                         error=False, e=False, installed=False)
                self.count['allocated_store' if p('allocatedStore') else 'allocated_read'] += 1
                self.history.append(('allocate', cycle, address, slot))
            else:
                self.count['candidate_cancelled'] += 1
            self.candidate = None  # The wrapper uses the original one-attempt policy.
        else:
            require(not p('allocated'), 'PF allocated without an independently observed prior candidate')
        if p('candidate'):
            require(accepted and q['ordinary'] and s['upstream.request.bits.prefetchNextAllowed'],
                    'PF candidate lacked an accepted ordinary checked request')
            address = (q['address'] & ~63) + 64
            require(4096 <= address < 8192 and (address >> 12) == (q['address'] >> 12),
                    'candidate escaped authored checked page/aperture')
            require(bool(p('candidateStore')) == q['write'], 'candidate origin differs from accepted request')
            self.candidate = {'address': address, 'store': q['write']}
            self.count['candidate_store' if q['write'] else 'candidate_read'] += 1
            self.history.append(('candidate', cycle, address))
        if p('wbCapture') and p('wbCapturePrefetch'):
            slot, mshr = p('wbCaptureSlot'), p('wbCaptureMshr')
            require(slot not in self.releases and mshr in self.misses and p('wbCaptureFromMiss'),
                    'PF victim capture lacked an exact live miss or reused WB slot')
            self.releases[slot] = {'address': p('wbCaptureAddress'), 'mshr': mshr,
                                   'dirty': bool(p('wbCaptureDirty')), 'beats': 0, 'sent': False}
            self.count['wb_capture_dirty' if p('wbCaptureDirty') else 'wb_capture_clean'] += 1
        if a['tl.a.valid'] and s['tl.a.ready']:
            slot = a['tl.a.bits.source']
            if slot in self.misses:
                owner = self.misses[slot]
                require(not owner['acquired'] and a['tl.a.bits.address'] == owner['address'],
                        'PF A reused or changed the allocated full source/address')
                require(not a['acquired.valid'], 'PF transaction gained posted acquisition identity')
                owner['acquired'] = True
                self.count['a'] += 1
        if s['tl.d.valid'] and a['tl.d.ready']:
            source = s['tl.d.bits.source']
            if s['tl.d.bits.opcode'] == 6:
                slot = source - 2
                if slot in self.releases:
                    require(self.releases[slot]['sent'], 'PF ReleaseAck preceded exact C-last')
                    del self.releases[slot]
                    self.count['release_ack'] += 1
            elif source in self.misses:
                owner = self.misses[source]
                require(owner['acquired'] and len(owner['beats']) < 8, 'PF D without actual A/eight-beat ownership')
                sink = s['tl.d.bits.sink']
                require(owner['sink'] in (None, sink), 'PF Grant changed sink while held')
                owner['sink'] = sink
                owner['beats'].append(s['tl.d.bits.data'])
                owner['error'] |= bool(s['tl.d.bits.denied'] or s['tl.d.bits.corrupt'])
                require(s['tl.d.bits.param'] == 0 or owner['error'], 'PF success received non-T permission')
        if a['tl.e.valid'] and s['tl.e.ready']:
            owners = [g for g in self.misses.values() if g['acquired'] and g['sink'] == a['tl.e.bits.sink']]
            if owners:
                require(len(owners) == 1 and len(owners[0]['beats']) == 8 and not owners[0]['e'],
                        'PF E was not the full eight-beat owned grant')
                owners[0]['e'] = True
                self.count['e'] += 1
        if a['tl.c.valid'] and s['tl.c.ready'] and a['tl.c.bits.opcode'] in (6, 7):
            slot = a['tl.c.bits.source'] - 2
            if slot in self.releases:
                owner = self.releases[slot]
                require(not owner['sent'] and a['tl.c.bits.address'] == owner['address'],
                        'PF C changed its captured victim identity')
                require(a['tl.c.bits.opcode'] == (7 if owner['dirty'] else 6), 'PF victim lost dirty data duty')
                owner['beats'] += 1
                owner['sent'] = owner['beats'] == (8 if owner['dirty'] else 1)
                if owner['sent']:
                    self.count['c_last'] += 1
        if p('refill') and p('refillPrefetch'):
            slot = p('refillSlot')
            require(slot in self.misses, 'PF refill lacked full physical source ownership')
            owner = self.misses[slot]
            require(owner['e'] and p('refillAddress') == owner['address'], 'PF refill crossed E or changed address')
            require(bool(p('refillError')) == owner['error'], 'PF error lost its actual Grant outcome')
            require(bool(a['prefetch.error']) == owner['error'], 'PF error pulse changed transport outcome')
            require(not a['refillValid'] and not a['installedValid'], 'PF refill gained posted lineage')
            if owner['error']:
                require(not a['lineWrite'], 'failed PF installed SRAM bytes')
                self.count['error'] += 1
            else:
                data = [a['installWord' + str(i)] for i in range(8)]
                require(a['lineWrite'] and not a['lineWritePosted'] and a['lineWriteAddress'] == owner['address'] and
                        data == owner['beats'], 'PF SRAM bytes differ from its own exact Grant stream')
                self.count['refill_success'] += 1
            self.history.append(('refill_error' if owner['error'] else 'refill', cycle, owner['address'], slot))
            del self.misses[slot]
        else:
            require(not a['prefetch.error'], 'PF error without owned PF refill')
        if p('useful'):
            require(accepted and q['ordinary'], 'PF usefulness lacked actual ordinary demand acceptance')
            self.count['useful_store' if p('usefulStore') else 'useful_read'] += 1
