"""Complete independent contracts for explicit posted/PF Board experiments.

No hardware execution claim. The published posted_board_lineage API stays posted
OFF/ON; these profiles introduce separate coexistence and head-offer entry points.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'posted_board_lineage'))
import profile_check as original
BASELINE = json.loads((HERE / 'baseline-full-profile.json').read_text())


def expected(experiment, mode):
    original._require(experiment in ('posted', 'coexistence', 'head-offer'), 'unknown experiment')
    original._require(mode in ('off', 'on'), 'mode must be off or on')
    value = copy.deepcopy(BASELINE)
    posted = experiment != 'posted' or mode == 'on'
    coexist = experiment == 'head-offer' or (experiment == 'coexistence' and mode == 'on')
    head = experiment == 'head-offer' and mode == 'on'
    value['profile'].update(postedStoreMerge=posted, postedPrefetchCoexistence=coexist,
                            postedPrefetchHeadOffer=head)
    value['core'].update(postedStoreMerge=posted, postedPrefetchHeadOffer=head)
    value['cache']['postedPrefetchCoexistence'] = coexist
    return value


class Contract:
    def __init__(self, name, entrypoint, audit_entrypoint, differences):
        self.name = name
        self.entrypoint = entrypoint
        self.audit_entrypoint = audit_entrypoint
        self.differences = differences
        self.cases = tuple((side, 'on', control) for side in ('off', 'on')
                           for control in (None, 'token', 'byte'))
        self.snapshot_variants = ('off', 'on')

    def posted_enabled(self, mode):
        return True

    def case_name(self, mode, variant, control):
        return mode + ('-negative-' + control if control else '')

    def verify_profile(self, summary, mode):
        original._equal(summary, expected(self.name, mode), 'complete frozen ' + self.name + ' profile')
        # Independently retain the original geometry/placement checks as well.
        normalized = copy.deepcopy(summary)
        normalized['profile'].update(postedPrefetchCoexistence=False, postedPrefetchHeadOffer=False)
        normalized['core']['postedPrefetchHeadOffer'] = False
        normalized['cache']['postedPrefetchCoexistence'] = False
        original.verify_profile(normalized, 'on')
        return {'experiment': self.name, 'mode': mode, 'profile_fields': len(summary['profile']),
                'core_fields': len(summary['core']), 'frozen_baseline_sha256':
                hashlib.sha256((HERE / 'baseline-full-profile.json').read_bytes()).hexdigest()}

    def verify_profile_pair(self, off, on):
        self.verify_profile(off, 'off')
        self.verify_profile(on, 'on')
        normalized = copy.deepcopy(on)
        for path in self.differences:
            group, field = path.split('.')
            normalized[group][field] = False
        original._equal(off, normalized, 'OFF/ON full summary')
        return {'only_differences': list(self.differences)}


COEXISTENCE = Contract('coexistence', 'ooo.PostedPrefetchCoexistBoardGsimMain',
    'ooo.PostedPrefetchCoexistActualParamsAuditMain',
    ('profile.postedPrefetchCoexistence', 'cache.postedPrefetchCoexistence'))
HEAD_OFFER = Contract('head-offer', 'ooo.PostedPrefetchHeadOfferBoardGsimMain',
    'ooo.PostedPrefetchHeadOfferActualParamsAuditMain',
    ('profile.postedPrefetchHeadOffer', 'core.postedPrefetchHeadOffer'))
