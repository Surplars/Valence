"""Pure Python checks for independent IEEE arithmetic and qualification entry."""
import unittest
import guarded_guest_fp_arithmetic as target


def op(single=True, sub=False, rm=0):
    return ((int(not single) + 4 * sub) << 25) | (rm << 12) | 0x53


def s(bits):
    return 0xffffffff00000000 | bits


class ArithmeticOracleTests(unittest.TestCase):
    def test_negative_halfway_and_odd_tie(self):
        for single, one, half, sign in [(True, s(0x3f800000), s(0x33800000), 1 << 31),
                                       (False, 0x3ff0000000000000, 0x3ca0000000000000, 1 << 63)]:
            for rm in range(5):
                expected = (one | sign) + int(rm in (2,4))
                self.assertEqual(target.ieee_add_sub(op(single, rm=rm), one | sign, half | sign), (expected,1))
            self.assertEqual(target.ieee_add_sub(op(single), one+1, half), (one+2,1))

    def test_exact_and_dependencies(self):
        self.assertEqual(target.ieee_add_sub(op(), s(0x3f800000), s(0x40000000)), (s(0x40400000), 0))
        self.assertEqual(target.ieee_add_sub(op(False, True), 0x4008000000000000, 0x3ff0000000000000), (0x4000000000000000, 0))

    def test_halfway_all_modes_and_dynamic(self):
        for single, one, half, step in [(True, s(0x3f800000), s(0x33800000), 1),
                                       (False, 0x3ff0000000000000, 0x3ca0000000000000, 1)]:
            for rm in range(5):
                wanted = one + (step if rm in (3, 4) else 0)
                self.assertEqual(target.ieee_add_sub(op(single, rm=rm), one, half), (wanted, 1))
                self.assertEqual(target.ieee_add_sub(op(single, rm=7), one, half, rm), (wanted, 1))
                self.assertEqual(target.ieee_add_sub(op(single, rm=rm), one, half, 6), (wanted, 1))

    def test_nan_infinity_and_boxing(self):
        for single, inf, qnan, snan, one, neginf in [
            (True, s(0x7f800000), s(0x7fc00000), s(0x7f800001), s(0x3f800000), s(0xff800000)),
            (False, 0x7ff0000000000000, 0x7ff8000000000000, 0x7ff0000000000001, 0x3ff0000000000000, 0xfff0000000000000)]:
            self.assertEqual(target.ieee_add_sub(op(single), qnan, one), (qnan, 0))
            self.assertEqual(target.ieee_add_sub(op(single), snan, one), (qnan, 16))
            self.assertEqual(target.ieee_add_sub(op(single), inf, neginf), (qnan, 16))
        self.assertEqual(target.ieee_add_sub(op(), 0x7f800001, s(0x3f800000)), (s(0x7fc00000), 0))

    def test_zero_and_subnormal(self):
        for single, zero, negative, one in [(True, s(0), s(0x80000000), s(1)), (False, 0, 1 << 63, 1)]:
            for rm in range(5):
                self.assertEqual(target.ieee_add_sub(op(single, rm=rm), zero, negative), (negative if rm == 2 else zero, 0))
                self.assertEqual(target.ieee_add_sub(op(single, rm=rm), negative, negative), (negative, 0))
            self.assertEqual(target.ieee_add_sub(op(single), one, one), (one + 1, 0))

    def test_overflow_all_modes_and_signs(self):
        for single, maximum, inf, sign in [(True, s(0x7f7fffff), s(0x7f800000), 1 << 31),
                                          (False, 0x7fefffffffffffff, 0x7ff0000000000000, 1 << 63)]:
            for rm in range(5):
                for negative in (False, True):
                    a = maximum | (sign if negative else 0)
                    result = (inf if rm in (0, 4) or rm == (2 if negative else 3) else maximum) | (sign if negative else 0)
                    self.assertEqual(target.ieee_add_sub(op(single, rm=rm), a, a), (result, 5))

    def test_reserved_modes(self):
        for rm in (5, 6):
            with self.assertRaisesRegex(ValueError, 'reserved arithmetic'):
                target.ieee_add_sub(op(rm=rm), s(0), s(0))
        for frm in (5, 6, 7):
            with self.assertRaisesRegex(ValueError, 'reserved arithmetic'):
                target.ieee_add_sub(op(rm=7), s(0), s(0), frm)



import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch



class ArithmeticEntryTests(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='mock-guest-fp-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.common = types.ModuleType('run')
        self.common.ROOT, self.common.BUILD = self.root, self.root/'build'
        self.common.setup = Mock(return_value=('pinned-gsim','clang++-19'))
        self.common.test = Mock(side_effect=self.generate)
        spec = importlib.util.spec_from_file_location('guest_entry', Path(__file__).with_name('guarded_guest_fp_arithmetic.py'))
        self.e = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'run':self.common}):
            spec.loader.exec_module(self.e)
        self.recipe = self.e.load_recipe(Path(__file__).with_name('config')/'guarded_guest_fp_arithmetic.json')

    def generate(self, gsim, cxx, output, *args, **kwargs):
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        for name in ('test.log','raw-baseline.jsonl'):
            (output/name).write_text('mock-only\n')
        return output

    def test_frozen_program_coverage_and_retirement_flags(self):
        arch = self.e.Architecture(self.recipe)
        events = arch.run(self.recipe['terminal_pc'])
        summary = self.e.validate_program(events)
        self.assertEqual(summary, {'events':698,'retirements':689,'arithmetic':49,'traps':9})
        for event in events:
            if event.get('arithmetic'):
                self.assertEqual(event['after']['fcsr'], event['before']['fcsr'] | event['flags'])
                self.assertTrue(event['mutation'])
            if event['trap'] and event['arithmetic_encoding']:
                for key in [f'fpr_{n}' for n in range(32)] + ['fcsr','hostFs','guestFs']:
                    self.assertEqual(event['before'][key],event['after'][key])
                self.assertFalse(event['mutation'])
        self.assertTrue(any(e['access'] and e['before']['virtualized'] and len(e['access']['ptes']) == 15 for e in events))

    def test_sticky_negative_removes_old_only_flag(self):
        arch=self.e.Architecture(self.recipe); events=arch.run(self.recipe['terminal_pc'])
        event=next(e for e in events if e.get('arithmetic') and e['flags'] == 1 and e['before']['fcsr'] & 4)
        ledger=types.SimpleNamespace(fp={'event':event})
        raw=dict.fromkeys(self.e.RAW_WIDTHS,0);raw['fpRetire$$valid']=1
        pre=event['before'].copy();post=event['after'].copy()
        mutate,applied=self.e.mutation_control('missing_sticky_flags')
        mutate(ledger,raw,pre,post,7)
        self.assertEqual(applied,[7])
        self.assertEqual(post['fcsr'],event['after']['fcsr'] & ~4)
        self.assertTrue(post['fcsr'] & 1)
        self.assertEqual(self.e.NEGATIVES['missing_sticky_flags'],'missing_sticky_flags')

    def test_real_flag_clears_are_required_for_observable_edges(self):
        arch=self.e.Architecture(self.recipe);events=arch.run(self.recipe['terminal_pc'])
        clears=[e for e in events if e['csr_write'] and e['csr_write']['address']==1
                and e['csr_write']['value']==0 and e['before']['fcsr'] & 31]
        self.assertEqual(len(clears),10)
        for event in clears:
            recipe=copy.deepcopy(self.recipe)
            # Defeat the executed clear by turning CSRRW into a read-only CSRRS x0.
            word=next(item for item in recipe['program'] if item[0]==event['physical'])
            word[1]=(word[1] & ~((31<<15)|(7<<12))) | (2<<12)
            changed=self.e.Architecture(recipe).run(recipe['terminal_pc'])
            with self.subTest(pc=event['pc']),self.assertRaisesRegex(RuntimeError,'observable'):
                self.e.validate_program(changed)

    def test_numeric_metadata_does_not_drive_results(self):
        recipe = copy.deepcopy(self.recipe)
        recipe['arithmetic_cases'] = []
        a = self.e.Architecture(self.recipe); b = self.e.Architecture(recipe)
        self.assertEqual(a.run(self.recipe['terminal_pc']), b.run(recipe['terminal_pc']))

    def test_fp_and_system_completion_may_share_retirement_edge(self):
        recipe, rows = self.same_edge_lifecycle()
        completion = next(row[0] for row in rows if row[3] == 'fp_complete')
        rows = [row for row in rows if row[3] != 'fp_complete']
        retiring = next(row for row in rows if row[3] == 'fp_retire')
        retiring[0].update({k:v for k,v in completion.items() if k.startswith('fpComplete$$')})
        retiring[0]['statePhase'] = 1
        ledger = self.e.Replay(recipe,'baseline')
        for cycle,(raw,pre,post,_) in enumerate(rows):
            ledger.step(raw,pre,post,cycle)
        self.assertEqual(ledger.counts['fp_retires'],1)
        for field,value,checker in [('fpComplete$$valid',0,'fp_commit_after_once_completion'),
                                    ('fpComplete$$bits$$token$$tag',999,'fp_completion_token'),
                                    ('fpComplete$$bits$$exception',1,'fp_completion_exception')]:
            changed=copy.deepcopy(rows)
            next(row for row in changed if row[3]=='fp_retire')[0][field]=value
            ledger=self.e.Replay(recipe,'baseline')
            with self.subTest(field=field),self.assertRaises(self.e.CheckFailure) as error:
                for cycle,(raw,pre,post,_) in enumerate(changed): ledger.step(raw,pre,post,cycle)
            self.assertEqual(error.exception.name,checker)

    def test_recipe_metadata_never_supplies_results(self):
        recipe = copy.deepcopy(self.recipe)
        recipe['fault_sites'] = []; recipe['phase_markers'] = []; recipe['code'] = []
        first = self.e.Architecture(self.recipe); second = self.e.Architecture(recipe)
        first.run(self.recipe['terminal_pc']); second.run(recipe['terminal_pc'])
        self.assertEqual(first.events,second.events)
        self.assertEqual(first.memory.changed(),second.memory.changed())

    def test_classification_signed_zero_infinities_nan_subnormal(self):
        for width,values in ((32,(0,0x80000000,0x7f800000,0xff800000,0x7f800001,0x7fc00000,1,0x80000001)),
                             (64,(0,1<<63,0x7ff0000000000000,0xfff0000000000000,0x7ff0000000000001,0x7ff8000000000000,1,(1<<63)|1))):
            self.assertEqual([self.e.classify(value,width) for value in values],[16,8,128,1,256,512,32,4])

    def test_single_moves_box_and_sign_extend(self):
        arch = self.e.Architecture(self.recipe)
        arch.host_fs=2; arch.x[1]=0xdeadbeef80000001
        arch.memory.put(arch.pc,0xf00080d3,4)  # FMV.W.X f1,x1
        event=arch.step()
        self.assertEqual(arch.f[1],0xffffffff80000001)
        self.assertTrue(event['fpWrite'])
        arch.memory.put(arch.pc,0xe0008153,4)  # FMV.X.W x2,f1
        arch.step(); self.assertEqual(arch.x[2],0xffffffff80000001)

    def raw_idle(self):
        raw=dict.fromkeys(self.e.RAW_WIDTHS,0)
        raw.update(commitEnable=1,trapReady=1,adapterIdle=1,translatorIdle=1,
                   responseBufferIdle=1,memoryDrained=1,fetchAdapterIdle=1,fetchTranslatorIdle=1,assemblerIdle=1)
        for name in ('instruction','fetchPte','dataPte','data'):
            raw[name+'$$request$$ready']=1
        return raw

    def test_sparse_rows_strict_types_duplicates_and_normalization(self):
        e=self.e; columns=sorted(e.RAW_WIDTHS)
        e.sparse_raw([],columns)
        index=columns.index('commitEnable')
        for row in ([[index,True]],[[index,1.0]],[[index,2]],[[index,0]],[[index,1],[index,1]]):
            with self.subTest(row=row),self.assertRaises(RuntimeError):
                e.sparse_raw(row,columns)
        index=columns.index('fpStart$$bits$$pc')
        with self.assertRaisesRegex(RuntimeError,'normalize'):
            e.sparse_raw([[index,1]],columns)

    def test_cached_groups_equal_original_prefix_checks_over_full_schema(self):
        e = self.e; columns = sorted(e.RAW_WIDTHS)
        groups = [(prefix+'$$bits', fields) for prefix, fields in e.EVENT_PAYLOAD_FIELDS.items()]
        groups += [(prefix+'$$request$$bits', fields) for prefix, fields in e.REQUEST_PAYLOAD_FIELDS.items()]
        groups += [('systemRequest$$', e.SYSTEM_REQUEST_FIELDS)]
        for prefix, fields in groups:
            self.assertEqual(fields, tuple(name for name in columns if name.startswith(prefix)))
            for selected in columns:
                raw = {name:int(name == selected) for name in columns}
                original = any(value for name,value in raw.items() if name.startswith(prefix))
                cached = any(raw[name] for name in fields)
                self.assertEqual(cached, original, (prefix,selected))

    def test_all32_state_schema_and_exact_raw_inputs(self):
        self.assertEqual(len([n for n in self.e.STATE_COLUMNS if n.startswith('fpr_')]),32)
        for field in ('instruction$$responseError','data$$response$$bits$$pageFault',
                      'commit0$$bits$$token$$tag','dataVirtualRequest$$valid','systemExecute'):
            self.assertIn(field,self.e.RAW_WIDTHS)
        self.assertNotIn('trap$$ready',self.e.RAW_WIDTHS)

    def test_json_duplicates_types_truncation_and_sanitizers_rejected(self):
        with self.assertRaises(RuntimeError):self.e.json_row('{"a":0,"a":1}')
        for value in (True,0.0):
            with self.assertRaises(RuntimeError):self.e.exact(value,0,'scalar')
        path=self.root/'raw'
        for value in (b'',b'{}',b'Sanitizer\n',b'runtime error:\n',b'\0\n',b'\xff\n'):
            path.write_bytes(value)
            with self.subTest(value=value),self.assertRaises(RuntimeError):self.e.clean_text(path)

    def test_missing_excessive_and_truncated_trace_never_negative(self):
        path=self.root/'trace'
        with self.assertRaises(RuntimeError):self.e.check_negative(path,self.recipe,'reserved_rounding_trap')
        path.write_bytes(b'\n'*(self.e.TRACE_LIMIT+1))
        with self.assertRaises(RuntimeError):self.e.check_trace(path,self.recipe,'baseline')

    def test_negative_requires_exact_named_checker_after_injection(self):
        e=self.e
        for failure in (RuntimeError('crash'),e.CheckFailure('unrelated',0)):
            with patch.object(e,'check_trace',side_effect=failure):
                with self.assertRaises(RuntimeError):e.check_negative(self.root/'trace',self.recipe,'reserved_rounding_trap')
        with patch.object(e,'check_trace',return_value={}):
            with self.assertRaisesRegex(RuntimeError,'not rejected'):
                e.check_negative(self.root/'trace',self.recipe,'reserved_rounding_trap')

    def mock_lifecycle(self):
        e=self.e; recipe=copy.deepcopy(self.recipe)
        base=recipe['reset_pc']
        instructions=[0x40b7,0x30009073,0xf2008053,0xe2000153,0x6f]
        recipe['program']=[[base+4*n,inst] for n,inst in enumerate(instructions)]
        recipe['terminal_pc']=base+16
        ledger=e.Replay(recipe,'baseline')
        rows=[]; state={**ledger.events[0]['before'],'hostSd':0}
        def add(phase,**updates):
            nonlocal state
            raw=self.raw_idle(); raw.update(updates)
            if ledger.owner:
                raw.update(ownerActive=1,**{'ownerToken$$index':ledger.owner['token'][0],
                    'ownerToken$$tag':ledger.owner['token'][1]})
                event=ledger.owner['event']; memory=event['instruction']&127 in (7,0x27)
                raw['contextMemoryEpoch']=int(not event['fp'] or memory); raw['fpMemoryEpoch']=int(memory)
            if ledger.fp:raw.update(fpBusy=1,statePhase=3 if ledger.fp['completed'] or phase=='fp_complete' else 1)
            pre=state.copy(); post=state.copy()
            if phase=='csr_execute':post.update(hostFs=2)
            if phase=='fp_retire':post.update(hostFs=3,hostSd=1,fpr_0=0x4000)
            rows.append((raw.copy(),pre.copy(),post.copy(),phase))
            ledger.step(raw,pre,post,len(rows)-1); state=post
        def request(prefix,pc,inst,index):
            return {prefix+'$$valid':1,prefix+'$$bits$$pc':pc,prefix+'$$bits$$instruction':inst,
                    prefix+'$$bits$$operand':0x4000,prefix+'$$bits$$token$$index':index,
                    prefix+'$$bits$$token$$tag':index+7}
        def commit(pc,inst,index,**fields):
            return {'commit0$$valid':1,'commit0$$bits$$pc':pc,'commit0$$bits$$instruction':inst,
                'commit0$$bits$$nextPc':pc+4,'commit0$$bits$$token$$index':index,
                'commit0$$bits$$token$$tag':index+7,**{'commit0$$bits$$'+k:v for k,v in fields.items()}}
        add('lui',**commit(base,instructions[0],0,rd=1,writesRd=1,data=0x4000))
        add('csr_start',**request('systemStart',base+4,instructions[1],1))
        add('csr_execute',systemExecute=1,**{'systemRequest$$pc':base+4,'systemRequest$$instruction':instructions[1],
            'systemRequest$$operand':0x4000,'systemRequest$$token$$index':1,'systemRequest$$token$$tag':8,
            'hostFsWrite$$valid':1,'hostFsWrite$$bits':2,'hWrite$$valid':1,
            'hWrite$$bits$$address':0x300,'hWrite$$bits$$data':0x4000})
        add('csr_complete',**{'systemComplete$$valid':1,'systemComplete$$bits$$completion$$token$$index':1,
            'systemComplete$$bits$$completion$$token$$tag':8})
        add('csr_retire',retireMatches=1,**commit(base+4,instructions[1],1))
        add('fp_start_system',**request('systemStart',base+8,instructions[2],2))
        add('fp_start',systemExecute=1,**request('fpStart',base+8,instructions[2],2),
            **{'systemRequest$$pc':base+8,'systemRequest$$instruction':instructions[2],
               'systemRequest$$operand':0x4000,'systemRequest$$token$$index':2,'systemRequest$$token$$tag':9})
        add('fp_complete',**{'fpComplete$$valid':1,'fpComplete$$bits$$token$$index':2,
            'fpComplete$$bits$$token$$tag':9,'fpComplete$$bits$$data':0x4000,'fpComplete$$bits$$nextPc':base+12})
        add('fp_system_complete',**{'systemComplete$$valid':1,'systemComplete$$bits$$completion$$token$$index':2,
            'systemComplete$$bits$$completion$$token$$tag':9})
        add('fp_retire',retireMatches=1,**commit(base+8,instructions[2],2),**{'fpRetire$$valid':1,
            'fpRetire$$bits$$index':2,'fpRetire$$bits$$tag':9,'mutation$$valid':1})
        return recipe,rows

    def same_edge_lifecycle(self):
        recipe, rows = self.mock_lifecycle()
        merged = []
        for raw, pre, post, phase in rows:
            if phase in ('csr_complete', 'fp_system_complete'):
                continue
            if phase in ('csr_retire', 'fp_retire'):
                completion_phase = 'csr_complete' if phase == 'csr_retire' else 'fp_system_complete'
                completion = next(row[0] for row in rows if row[3] == completion_phase)
                raw.update({key: value for key, value in completion.items() if key.startswith('systemComplete$$')})
            merged.append((raw, pre, post, phase))
        return recipe, merged

    def test_mock_same_edge_completion_and_retirement(self):
        recipe, rows = self.same_edge_lifecycle()
        ledger = self.e.Replay(recipe, 'baseline')
        for cycle, (raw, pre, post, _) in enumerate(rows):
            ledger.step(raw, pre, post, cycle)
        self.assertEqual((ledger.completed, ledger.counts['fp_retires']), (2, 1))
        self.assertIsNone(ledger.owner)
        self.assertIsNone(ledger.system)
        self.assertIsNone(ledger.fp)

    def test_same_edge_requires_matching_accepted_completion(self):
        recipe, rows = self.same_edge_lifecycle()
        for field, value, checker in (
            ('systemComplete$$valid', 0, 'system_commit_after_completion'),
            ('systemComplete$$bits$$completion$$token$$tag', 999, 'system_completion_token'),
            ('systemComplete$$bits$$completion$$exception', 1, 'system_completion_exception')):
            changed = copy.deepcopy(rows)
            next(row for row in changed if row[3] == 'csr_retire')[0][field] = value
            ledger = self.e.Replay(recipe, 'baseline')
            with self.subTest(field=field), self.assertRaises(self.e.CheckFailure) as error:
                for cycle, (raw, pre, post, _) in enumerate(changed):
                    ledger.step(raw, pre, post, cycle)
            self.assertEqual(error.exception.name, checker)

    def test_mock_fp_lifecycle_only_mutates_at_real_commit(self):
        _,rows=self.mock_lifecycle()
        for _,pre,post,phase in rows:
            if phase!='fp_retire':self.assertEqual(pre['fpr_0'],post['fpr_0'])
        self.assertEqual(rows[-1][2]['fpr_0'],0x4000)

    def test_mock_lifecycle_rejects_early_mutation_owner_release_duplicate(self):
        recipe,rows=self.mock_lifecycle()
        for phase,section,field,value,checker in (
            ('csr_execute',0,'hostFsWrite$$valid',0,'decoded_host_fs_write'),
            ('csr_execute',0,'fpCsrWrite$$valid',1,'decoded_fp_csr_write'),
            ('fp_complete',2,'fpr_31',1,'architectural_post_state'),
            ('fp_complete',0,'ownerActive',0,'protected_owner_lifetime'),
            ('fp_system_complete',0,'fpComplete$$valid',1,'once_fp_completion'),
            ('fp_retire',0,'mutation$$bits$$guest',1,'captured_mutation_context')):
            ledger=self.e.Replay(recipe,'baseline'); changed=copy.deepcopy(rows)
            next(row for row in changed if row[3]==phase)[section][field]=value
            with self.subTest(phase=phase,field=field),self.assertRaises(self.e.CheckFailure) as error:
                for n,(raw,pre,post,_) in enumerate(changed):ledger.step(raw,pre,post,n)
            self.assertEqual(error.exception.name,checker)

    def invoke(self,*args):
        input_path=self.root/'simulator/gsim/config/guarded_guest_fp_arithmetic.json'
        input_path.parent.mkdir(parents=True,exist_ok=True);input_path.write_text('{}\n')
        fake={'terminal_pc':0,'scope':{'mock_only':True}}
        def native(output,arguments,name,env):
            (output/name).write_text('mock-only\n');(output/'raw-staggered.jsonl').write_text('mock-only\n')
            return output/name
        def negative(trace,recipe,name):
            self.assertTrue((trace.parent/'pristine-summary.json').is_file())
            self.assertTrue((trace.parent/'raw-staggered.jsonl').is_file())
            return {'name':name,'mock_only':True}
        with patch.object(sys,'argv',['entry',*args]),patch.dict(self.e.os.environ),\
             patch.object(self.e,'load_recipe',return_value=fake),\
             patch.object(self.e,'source_pins',return_value={'mock':'source'}),\
             patch.object(self.e,'Architecture'),\
             patch.object(self.e,'validate_program'),\
             patch.object(self.e,'check_positive',return_value={'mock_only':True}) as positive,\
             patch.object(self.e,'native_run',side_effect=native) as run,\
             patch.object(self.e,'check_negative',side_effect=negative) as negatives,\
             patch('sys.stdout',new_callable=io.StringIO):
            self.e.main()
            return run,positive,negatives

    def test_fresh_sanitized_model_strict_setup_two_schedules_saved_before_negatives(self):
        run,positive,negative=self.invoke()
        self.common.setup.assert_called_once_with(False)
        self.common.test.assert_called_once()
        kwargs=self.common.test.call_args.kwargs
        self.assertTrue(kwargs['sanitizer']);self.assertEqual(kwargs['timeout'],120)
        self.assertEqual(kwargs['mill_module'],'IonSoC.guardedGuestFpArithmetic')
        self.assertEqual(run.call_count,1);self.assertEqual(positive.call_count,2)
        self.assertEqual(negative.call_count,len(self.e.NEGATIVES))
        env=run.call_args.args[3]
        self.assertEqual(env['ASAN_OPTIONS'],'detect_leaks=0')
        self.assertEqual(env['UBSAN_OPTIONS'],'halt_on_error=1')
        self.assertTrue((self.common.BUILD/'guarded-guest-fp-arithmetic/source-pins.json').is_file())

    def test_existing_file_directory_symlink_preserved(self):
        for kind in ('file','directory','link'):
            path=self.root/kind
            if kind=='file':path.write_text('keep')
            elif kind=='directory':path.mkdir()
            else:path.symlink_to(self.root/'absent')
            with self.assertRaises(RuntimeError):self.invoke('--output',str(path))
        self.common.setup.assert_not_called()

    def test_setup_failure_prevents_build(self):
        self.common.setup.side_effect=RuntimeError('pin mismatch')
        with self.assertRaisesRegex(RuntimeError,'pin mismatch'):self.invoke()
        self.common.test.assert_not_called()

    def test_build_failure_is_not_success(self):
        self.common.test.side_effect=RuntimeError('build failed')
        with self.assertRaisesRegex(RuntimeError,'build failed'):self.invoke()

    def test_changed_build_destination_rejected(self):
        self.common.test.side_effect=lambda *a,**k:self.root
        with self.assertRaisesRegex(RuntimeError,'destination changed'):self.invoke()

    def test_timeout_crash_nonzero_never_evidence(self):
        e=self.e
        with patch.object(e.subprocess,'run',side_effect=subprocess.TimeoutExpired('run',120)):
            with self.assertRaises(subprocess.TimeoutExpired):e.native_run(self.root,(),'timeout.log',{})
        for code in (1,2,-11,True):
            with patch.object(e.subprocess,'run',return_value=types.SimpleNamespace(returncode=code)):
                with self.subTest(code=code),self.assertRaises(RuntimeError):
                    e.native_run(self.root,(),f'crash-{code}.log',{})


if __name__ == "__main__": unittest.main()
