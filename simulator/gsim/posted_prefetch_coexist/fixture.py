#!/usr/bin/env python3
"""Fresh posted/PF cache-boundary tests; synthetic manager and explicit premises.

Every run starts a new model. Copied historical stimulus is executed afresh;
no old receipt is read. FENCE/recovery coverage is limited to the cache's
seal, flush/drain and epoch interface; no executing CPU or real-home claim.
"""
import argparse
import json
from pathlib import Path

import cache_base as base
from pf_oracle import PrefetchLedger, require


class Coexist(base.Cache):
    def __init__(self, executable, directory, name, policy, generation_bits=64, wb_entries=2):
        self.policy = policy
        self.pf = PrefetchLedger(policy)
        super().__init__(executable, directory, name, True, generation_bits, wb_entries)
        self.tag = (1 << 63) + 4096  # Exercise full, nontruncated CPU token identity.

    def begin(self, address, *, prefetch=False, proof_flags=None, expected_error=False, **kwargs):
        token = super().begin(address, **kwargs)
        self.request['bits']['prefetchNextAllowed'] = int(prefetch)
        self.request['proof_flags'] = dict(proof_flags or {})
        self.request['error'] |= expected_error
        return token

    def tick(self, **updates):
        q = self.request
        current = None
        if q:
            bits = q['bits']
            ordinary = not bits['atomic'] and not bits['virtualized'] and not bits['uncached']
            ordinary &= 4096 <= bits['address'] and bits['address'] + (1 << bits['size']) <= 8192
            eligible = q['proof'] and ordinary and bits['write'] and not bits['precheckedLoad']
            eligible &= bits['translationEpoch'] == 0 and all(q.get('proof_flags', {}).values())
            current = {'address': bits['address'], 'write': bool(bits['write']), 'ordinary': ordinary,
                       'eligible': eligible, 'resident': (bits['address'] & ~63) in self.model.resident}
            updates = {'posted.requestProof.bits.' + key: value for key, value in q.get('proof_flags', {}).items()} | updates
        before = {'request': current, 'exhausted': self.model.exhausted}
        if updates.get('posted.seal'):
            for run in self.model.runs.values():
                run.sealed = True
        a = super().tick(**updates)
        self.pf.sample(a, self.state, before, self.cycle)
        if current and self.state['upstream.request.valid'] and self.state['posted.requestProof.valid']:
            if not a['upstream.request.ready']:
                self.count['held_proof_cycles'] += 1
            elif not a['accepted.valid'] and not a['fallback.valid']:
                self.count['proof_legacy_hit' if current['resident'] else 'proof_legacy_miss'] += 1
        if a['posted.episodeActive'] and not a['posted.busy'] and a['prefetch.candidate']:
            self.count['candidate_with_retained_cohort'] += 1
        if self.state['upstream.response.ready'] and a['upstream.response.valid'] and a['upstream.response.bits.error']:
            self.count['precise_cpu_error'] += 1
        return a

    def idle(self):
        super().idle()
        self.until(lambda: self.pf.empty() and not self.last['prefetchBusy'] and not self.acquires and
                   not self.release_acks and not self.responses and self.request is None and
                   not self.last['posted.busy'], 'all posted and PF transport responsibility drained')
        self.tick()

    def close(self, success=True):
        result = super().close(success)
        result['pf_events'] = dict(self.pf.count)
        result['pf_history'] = self.pf.history
        return result


def warm(t, address, *, write=False, value=0):
    t.send(address, write=write, value=value)
    t.idle()


def warm_stream(t):
    warm(t, 4160)
    warm(t, 4224)


def establish_cohort(t):
    t.send(6208, write=True, value=0xFEDCBA9876543210, proof=True)
    t.idle()
    require(t.model.episode_root is not None and not t.model.busy(), 'retained empty cohort setup absent')
    return t.model.episode_root


def read_candidate(t):
    t.send(4160, prefetch=True)
    t.idle()
    t.send(4224, prefetch=True)
    require(t.last['prefetch.candidate'], 'fresh accepted read stream did not produce a candidate')


def resident_proof_store(t):
    warm_stream(t)
    root = establish_cohort(t)
    t.send(4162, write=True, size=1, value=0xA1B2, proof=True, prefetch=True)
    t.idle()
    t.send(4231, write=True, size=0, value=0xC3, proof=True, prefetch=True)
    require(t.count['proof_legacy_hit'] == 2 and t.count['posted_accept'] == 1,
            'accepted proof-bearing legacy hits were not exercised')
    require(bool(t.last['prefetch.candidate']) == t.policy, 'resident proof policy OFF/ON distinction missing')
    t.idle()
    require(t.pf.count['candidate_store'] == int(t.policy) and t.pf.count['allocated_store'] == int(t.policy),
            'checked store prediction did not allocate exactly the policy-authorized line')
    require(t.model.episode_root == root, 'PF changed retained full cohort root')
    t.read_line(4160)
    t.read_line(4224)
    t.read_line(4288)
    t.flush()


def retained_cohort_reads(t):
    warm_stream(t)
    root = establish_cohort(t)
    t.send(4160, prefetch=True)
    t.idle()
    t.send(4224, prefetch=True)
    require(bool(t.last['prefetch.candidate']) == t.policy, 'retained cohort read gate mismatch')
    t.idle()
    require(t.pf.count['allocated_read'] == int(t.policy), 'retained cohort read stream lacks allocation witness')
    t.send(4288)
    t.idle()
    require(t.pf.count['useful_read'] == int(t.policy), 'retained cohort PF did not serve actual demand')
    require(t.model.episode_root == root, 'empty cohort identity was implicitly ended')
    t.flush()


def candidate_new_owner(t):
    warm_stream(t)
    read_candidate(t)
    require(not t.model.episode_root and t.pf.candidate, 'new-owner arbitration setup already owned posted work')
    token = t.begin(4416, write=True, value=0x8877665544332211, proof=True)
    a = t.tick()
    require(a['prefetchBusy'] and not a['upstream.request.ready'] and t.request['intent'].token == token,
            'pre-edge candidate failed to hold unchanged new-owner request')
    require(not a['prefetch.allocated'] and not a['prefetch.candidate'], 'held new-owner offer failed to cancel candidate')
    t.idle()
    require(t.count['posted_new'] == 1 and t.pf.count['candidate_cancelled'] == 1 and not t.pf.count['a'],
            'candidate cancellation or later posted progress absent')
    t.read_line(4416)
    t.flush()


def ineligible_proof_cancels(t):
    warm_stream(t)
    t.hold_cpu = True
    t.send(4160, prefetch=True)
    t.send(4224, prefetch=True)
    require(t.last['prefetch.candidate'] and len(t.responses) == 2, 'candidate plus full response credits not reached')
    token = t.begin(4232, write=True, value=0xAABBCCDD, size=2, proof=True, prefetch=True,
                    proof_flags={'headAuthorized': 0})
    for _ in range(6):
        a = t.tick()
        require(t.request and t.request['intent'].token == token and not a['prefetch.candidate'] and
                not a['prefetch.allocated'], 'ineligible held resident proof was exempted from candidate exclusion')
    t.hold_cpu = False
    t.idle()
    require(not t.count['posted_accept'] and t.count['proof_legacy_hit'] == 1 and
            t.pf.count['candidate_cancelled'] == 1, 'malformed authority did not stay on original legacy path')
    t.read_line(4224)
    t.flush()


def live_pf_and_probe(t):
    warm_stream(t)
    read_candidate(t)
    t.hold_a = True
    t.hold_e = True
    t.tick()
    require(t.pf.count['allocated_read'] == 1, 'PF MSHR allocation absent')
    token = t.begin(4416, write=True, value=0xA9B8C7D6, proof=True)
    for _ in range(5):
        a = t.tick()
        require(a['prefetchBusy'] and t.request and t.request['intent'].token == token and
                not a['accepted.valid'], 'held PF A did not block a new posted owner')
    t.hold_a = False
    t.until(lambda: bool(t.acquires) and all(g['beat'] == 8 for g in t.acquires.values()), 'PF GrantData through held E')
    t.start_probe(4288)
    for _ in range(5):
        a = t.tick()
        require(not t.probe['accepted'] and not a['accepted.valid'], 'probe/new posted owner crossed held PF E')
    t.hold_e = False
    t.finish_probe()
    t.idle()
    require(t.count['probe_stall'] >= 5 and t.count['posted_new'] == 1 and t.pf.count['refill_success'] == 1,
            'live PF/probe/post-owner progress witness absent')
    t.read_line(4416)
    t.flush()


def held_prefetch_release(t):
    warm_stream(t)
    warm(t, 4800, write=True, value=0x1122334455667788)
    warm(t, 5312, write=True, value=0x99AABBCCDDEEFF00)
    t.send(4160, write=True, value=0x1234, prefetch=True)
    t.idle()
    t.hold_ack = True
    t.send(4224, write=True, value=0x5678, prefetch=True)
    require(t.last['prefetch.candidate'], 'store PF dirty-victim candidate absent')
    t.until(lambda: t.last['prefetch.missOwners'] == 0 and t.last['prefetch.releaseOwners'] == 1,
            'PF ReleaseAck responsibility outliving MSHR')
    require(t.pf.count['wb_capture_dirty'] == 1 and t.pf.count['refill_success'] == 1,
            'held PF release did not capture actual dirty SRAM bytes')
    victim = next(iter(t.pf.releases.values()))['address']
    token = t.begin(4416, write=True, value=0xDEADBEEF, proof=True)
    t.start_probe(victim)
    for _ in range(6):
        a = t.tick()
        require(a['prefetchBusy'] and t.request and t.request['intent'].token == token and
                not a['accepted.valid'] and not t.probe['accepted'],
                'new posted owner/probe crossed exact held PF ReleaseAck')
    t.hold_ack = False
    t.finish_probe()
    t.idle()
    require(t.pf.count['release_ack'] == 1 and t.count['posted_new'] == 1,
            'exact PF ReleaseAck did not permit later posted progress')
    t.flush()


def response_credits(t):
    warm_stream(t)
    read_candidate(t)
    t.hold_e = True
    t.until(lambda: bool(t.acquires) and all(g['beat'] == 8 for g in t.acquires.values()) and not t.responses,
            'PF owns held E independently of CPU response tickets')
    t.hold_cpu = True
    t.send(4160)
    t.send(4168)
    t.begin(4224, write=True, value=0xACE1, size=1, proof=True)
    for _ in range(6):
        a = t.tick()
        require(t.request and len(t.responses) == 2 and a['pfObservation.responseFull'],
                'third request crossed two held original response credits')
    t.hold_e = False
    t.until(lambda: t.pf.empty(), 'PF refill drains without allocating a CPU response ticket')
    require(len(t.responses) == 2 and t.request, 'PF stole/completed an unrelated CPU response credit')
    t.hold_cpu = False
    t.idle()
    require(t.count['proof_legacy_hit'] == 1, 'held original store did not become precise legacy hit')
    t.send(4416, write=True, value=0xD00D, proof=True)
    t.idle()
    t.flush()


def seal_held_tail(t):
    t.grant_delay = 100
    t.send(4160, write=True, value=0x11223344, size=2, proof=True)
    t.tick(**{'posted.seal': 1})
    token = t.begin(4162, write=True, value=0xAA55, size=1, proof=True, prefetch=True)
    for _ in range(6):
        a = t.tick()
        require(t.request and t.request['intent'].token == token and not a['accepted.valid'],
                'cache seal admitted a younger join into the old owner')
    t.idle()
    require(t.count['posted_accept'] == 1 and t.count['proof_legacy_hit'] == 1,
            'sealed younger request did not wait for independent legacy acceptance')
    t.read_line(4160)
    t.flush()


def cache_context_recovery(t):
    warm_stream(t)
    root = establish_cohort(t)
    t.send(4160, prefetch=True)
    t.idle()
    t.send(4224, prefetch=True)
    t.tick(**{'posted.seal': 1})
    # This is the cache-side drain prerequisite for FENCE/context/recovery,
    # not a claim that a real CPU executed any of those instructions.
    t.flush()
    t.end_episode()
    require(t.pf.empty() and not t.model.busy(), 'context boundary retained accepted cache work')
    t.model.context_boundary(9)
    t.send(4480, write=True, value=0x10203040, proof=True)
    t.idle()
    require(t.model.episode_root != root and t.model.context_epoch == 9, 'new epoch reused stale cohort lineage')
    t.read_line(4480)
    t.flush()


def failure_then_demand(t):
    warm_stream(t)
    t.deny_line = 4288
    read_candidate(t)
    t.idle()
    require(t.pf.count['error'] == 1 and t.count['precise_cpu_error'] == 0 and
            4288 not in t.model.resident and not t.count['posted_accept'],
            'failed PF installed bytes or fabricated architectural error/posted proof')
    t.send(4288, expected_error=True)
    t.idle()
    require(t.count['precise_cpu_error'] == 1 and t.pf.count['error'] == 1 and 4288 not in t.model.resident,
            'later demand did not retain exactly its own precise error')
    t.deny_line = None
    t.read_line(4288)
    t.flush()


def exhaustion_candidate_fallback(t):
    for i in range(4):
        t.send(4160 + 64 * i, write=True, value=0x100 + i, proof=True)
        t.end_episode()
    require(t.model.exhausted, 'generation2 exhaustion precondition absent')
    warm(t, 4672)
    warm(t, 4544)
    warm(t, 4608)
    t.send(4544, prefetch=True)
    t.idle()
    t.send(4608, prefetch=True)
    require(t.last['prefetch.candidate'], 'exhausted fallback candidate arbitration setup absent')
    t.hold_ack = True
    t.begin(5184, write=True, value=0xEEDDCCBBAA998877, proof=True)
    a = t.tick()
    require(not a['prefetch.allocated'] and not a['prefetch.candidate'],
            'exhausted held fallback offer failed to cancel PF candidate')
    t.until(lambda: t.count['fallback'] == 1 and not t.responses and bool(t.release_acks),
            'fallback ACK with actual dirty ReleaseAck tail')
    require(t.last['posted.busy'] and not t.model.busy(), 'fallback busy did not retain coherence tail after ACK')
    t.begin(5248, write=True, value=0xAABB, size=1, proof=True, prefetch=True)
    for _ in range(6):
        a = t.tick()
        require(t.request and not a['prefetch.allocated'] and not a['prefetch.candidate'],
                'new fallback or PF crossed accepted fallback drain')
    t.hold_ack = False
    t.idle()
    require(t.count['fallback'] == 2 and t.count['posted_accept'] == 4 and
            t.pf.count['candidate_cancelled'] == 1, 'fallback exhaustion wrapped or lost later progress')
    t.read_line(5184)
    t.read_line(5248)
    t.flush()


def exhausted_resident_fallback_pf_tail(t):
    require(t.policy, 'new exhaustion/PF guard is an ON-only qualification')
    for i in range(4):
        t.send(4160 + 64 * i, write=True, value=0xF000 + i, proof=True)
        t.end_episode()
    warm(t, 5248)  # Clean second way beside dirty line 4224, in PF target set 2.
    warm(t, 4608)
    warm(t, 4672)
    t.send(4608, prefetch=True)
    t.idle()
    t.hold_ack = True
    t.send(4672, prefetch=True)  # Read-origin PF to absent 4736 releases clean 5248.
    require(t.last['prefetch.candidate'], 'exhausted read PF setup absent')
    t.until(lambda: t.last['prefetch.missOwners'] == 0 and t.last['prefetch.releaseOwners'] == 1,
            'exhausted read PF MSHR drained with exact ReleaseAck held')
    require(t.pf.count['wb_capture_clean'] == 1 and t.pf.count['refill_success'] == 1 and
            4160 in t.model.resident, 'read PF clean-victim/resident-fallback setup changed')
    token = t.begin(4162, write=True, size=1, value=0x7788, proof=True, prefetch=True)
    t.hold_cpu = True
    for _ in range(6):
        a = t.tick()
        require(t.request and t.request['intent'].token == token and not a['fallback.valid'] and
                not a['upstream.request.ready'] and not a['prefetch.candidate'],
                'exhausted resident fallback crossed held PF ReleaseAck')
    prior_ack = t.count['release_ack']
    t.hold_ack = False
    t.until(lambda: t.count['release_ack'] > prior_ack, 'real PF ReleaseAck before resident fallback')
    require(t.request and not t.last['fallback.valid'], 'resident fallback committed on old PF ReleaseAck edge')
    t.until(lambda: t.request is None, 'resident fallback only after registered PF/foreign drain')
    require(t.count['fallback'] == 1 and len(t.responses) == 1 and t.last['posted.busy'] == 0,
            'resident fallback accepted more than once or lost original response')
    # The acceptance observation is pre-edge; the following cycle owns the tail.
    t.tick()
    require(t.last['posted.busy'] and t.model.busy(), 'fallback lost held original response obligation')
    t.hold_cpu = False
    t.idle()
    require(t.count['fallback'] == 1 and t.pf.count['release_ack'] == 1 and not t.model.busy(),
            'resident fallback failed exact single response/tail reclamation')
    t.read_line(4160)
    t.flush()


BASE_CASES = [('merge-response-reuse', base.merge_reuse), ('two-line-reordered', base.reordered),
              ('credit-held-to-legacy-hit', base.credit_late_hit), ('before-A-probe-DMA', base.pre_a_mutation),
              ('after-install-held-ACK-probe-DMA', base.post_install_probe), ('after-E-probe', base.probe_after_e),
              ('clean-victim-overlap', lambda t: base.victim(t, False)),
              ('dirty-victim-overlap', lambda t: base.victim(t, True)),
              ('probe-cancels-victim', base.cancel_victim), ('flush-live-owner', base.flush_busy),
              ('explicit-episode-boundary', base.episode_boundary)]
COEXIST_CASES = [('proof-resident-store-partial-bytes', resident_proof_store),
                 ('retained-cohort-read-stream', retained_cohort_reads),
                 ('pending-candidate-new-owner', candidate_new_owner),
                 ('ineligible-held-proof-cancellation', ineligible_proof_cancels),
                 ('live-PF-held-E-probe-new-owner', live_pf_and_probe),
                 ('PF-dirty-ReleaseAck-outlives-MSHR', held_prefetch_release),
                 ('PF-independent-response-credits', response_credits),
                 ('seal-held-younger-partial-store', seal_held_tail),
                 ('cache-fence-context-recovery-prerequisites', cache_context_recovery),
                 ('PF-failure-then-precise-demand-error', failure_then_demand)]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--executable', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--policy', type=int, choices=[0, 1], required=True)
    ap.add_argument('--generation-bits', type=int, choices=[2, 64], required=True)
    ap.add_argument('--wb-entries', type=int, choices=[2], default=2)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    cases = BASE_CASES + COEXIST_CASES if args.generation_bits == 64 else [
        ('generation2-real-fallback', base.tiny_generation),
        ('dirty-fallback-WB-tail', base.dirty_fallback_tail),
        ('candidate-exhaustion-fallback-drain', exhaustion_candidate_fallback)]
    if args.generation_bits == 2 and args.policy:
        cases.append(('exhausted-resident-fallback-held-PF-ReleaseAck', exhausted_resident_fallback_pf_tail))
    results = []

    def progress():
        (args.output / 'progress.json').write_text(json.dumps({'status': 'RUNNING', 'cases': results}, indent=2) + '\n')

    def new(name):
        return Coexist(args.executable, args.output, name, bool(args.policy), args.generation_bits, args.wb_entries)

    progress()
    for name, case in cases:
        t = new(name)
        try:
            case(t)
            require(t.pf.empty(), 'positive case left PF ownership live')
            results.append(t.close())
            progress()
        except BaseException:
            t.close(False)
            raise
    if args.generation_bits == 64:
        diagnostics = {'fatal-error': ['platform violated guaranteed posted RAM refill success'],
                       'fatal-cap': ['platform violated guaranteed posted RAM refill success'],
                       'held-proof': ['cache held original request/proof changed'],
                       'held-context': ['cache held posted context changed', 'cache original posted proof detached from request'],
                       'end-with-held': ['episode ended beside held or accepted original proof',
                                         'cohort may end only at an empty registered aggregate boundary']}
        negatives = [(name, lambda t, kind=name: base.negative(t, kind), guards) for name, guards in diagnostics.items()]
    else:
        negatives = [('fallback-context-before-WB-drain', lambda t: base.dirty_fallback_tail(t, context_negative=True),
                      ['cache fallback context changed before real coherence drain'])]
    for name, case, guards in negatives:
        t = new(name)
        try:
            case(t)
        except base.DriverFailure as error:
            t.close(False)
            matched = [guard for guard in guards if guard in str(error)]
            require(matched and t.child.returncode != 0, 'semantic negative did not reach exact expected RTL guard')
            results.append({'name': name, 'status': 'EXPECTED_RTL_ASSERTION', 'diagnostic': matched[0],
                            'exit': t.child.returncode, 'stimulus': t.poison, 'trace': t.trace_receipt})
            progress()
        except BaseException:
            t.close(False)
            raise
        else:
            t.close(False)
            raise AssertionError('semantic negative did not terminate actual model')
    report = {'status': 'PASS', 'scope': 'actual cache/engine/SRAM; synthetic TL manager and proof premises; no CPU/home claim',
              'historical_pass_inherited': False, 'policy': args.policy, 'posted_enabled': True,
              'generation_bits': args.generation_bits, 'wb_entries': args.wb_entries, 'cases': results}
    (args.output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'POSTED_PREFETCH_COEXIST_PASS policy={args.policy} generation_bits={args.generation_bits} cases={len(results)}')


if __name__ == '__main__':
    main()
