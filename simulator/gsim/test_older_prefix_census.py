import copy
import importlib.util
from pathlib import Path
import sys
import unittest

DIRECTORY = Path(__file__).resolve().parents[2] / 'fpga/next'
sys.path.insert(0, str(DIRECTORY))
import older_prefix_census as census


class PrefixCensusTests(unittest.TestCase):
    def pair(self):
        a = {'source_sha256': census.native_export.sources(),
             'profile': census.expected_profile(False),
             'scopes': {'BoardSocTop': {'excluded_external_instances': {'BUFGCE': 3, 'blk_mem_gen_0': 1}}},
             'modules': {name: {'sha256': 'same'} for name in ('InstructionRom', 'ManagedClockBuffer')}}
        b = copy.deepcopy(a)
        b['profile'] = census.expected_profile(True)
        return a, b

    def test_exact_pair(self):
        census.validate_pair(*self.pair())

    def test_flag_profile_and_owner_mutations(self):
        changes = {'lsu_entries': 2, 'load_order_older_retire': False, 'physical_load_ingress_flow': False,
                   'virtual_ram_load_precheck': True, 'prechecked_data_flow': True,
                   'dma_line_transfers': False, 'dma_line_entries': 2, 'dma_line_yield_cycles': 4,
                   'cache_bytes': 65536, 'name': 'selected-lsu4-dma-lines-owners4'}
        for field, value in changes.items():
            a, b = self.pair()
            b['profile'][field] = value
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                census.validate_pair(a, b)

    def test_source_external_and_wrapper_mutations(self):
        for kind in ('source', 'external', 'wrapper', 'scope'):
            a, b = self.pair()
            if kind == 'source': b['source_sha256']['source'] = 'changed'
            elif kind == 'external': b['scopes']['BoardSocTop']['excluded_external_instances']['BUFGCE'] = 4
            elif kind == 'wrapper': b['modules']['InstructionRom']['sha256'] = 'changed'
            else: b['scopes']['IntegerBackend'] = {}
            with self.subTest(kind=kind), self.assertRaises(RuntimeError):
                census.validate_pair(a, b)

    def test_common_mode_profile_and_inventory_mutations(self):
        for kind in ('prefetch', 'missing-source', 'empty-source', 'unknown-profile', 'missing-profile'):
            a, b = self.pair()
            for item in (a, b):
                if kind == 'prefetch': item['profile']['prefetch_break_on_store'] = True
                elif kind == 'missing-source': item['source_sha256'].pop('build.mill')
                elif kind == 'empty-source': item['source_sha256'] = {}
                elif kind == 'unknown-profile': item['profile']['unqualified_option'] = True
                else: item['profile'].pop('cpu_hz')
            with self.subTest(kind=kind), self.assertRaises(RuntimeError):
                census.validate_pair(a, b)


if __name__ == '__main__':
    unittest.main()
