"""Pure helpers for runtime serialization and root-confined input paths."""
from pathlib import Path, PurePosixPath
import hashlib
import json


def positive_threads(value):
    """Validate syntax here; the installed Vivado validates its own upper bound."""
    import re
    if not re.fullmatch(r'[0-9]+', str(value)) or int(value) < 1:
        raise ValueError('Thread count must be a positive integer')
    return int(value)


def relative_input(root, name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
        raise ValueError('Input manifest path must be portable and relative: ' + name)
    result = (Path(root) / path).resolve()
    if not result.is_relative_to(Path(root).resolve()):
        raise ValueError('Input manifest path escapes its root: ' + name)
    return result


def tcl_value(value):
    if isinstance(value, list):
        return '[list ' + ' '.join(tcl_value(item) for item in value) + ']'
    return '[encoding convertfrom utf-8 [binary decode hex {' + str(value).encode().hex() + '}]]'


def tcl_config(settings):
    allowed = {'threads', 'part', 'python_mode', 'python_command', 'wsl_command',
               'wsl_distribution', 'rom_sha256', 'padded_sha256'}
    if set(settings) != allowed:
        raise ValueError('Unexpected runtime configuration keys')
    return 'set ::r3_config [dict create]\n' + ''.join(
        'dict set ::r3_config ' + key + ' ' + tcl_value(value) + '\n'
        for key, value in settings.items())


def validate_native(native, reference, recipe):
    """Retain the source emitter's exact five reference witnesses and projection."""
    for name in ('profile.json', 'actual-core-parameters.json', 'actual-product-field-order.json'):
        data = (native / name).read_bytes()
        info = recipe['reference_files'][name]
        if len(data) != info['bytes'] or hashlib.sha256(data).hexdigest() != info['sha256']:
            raise ValueError('Native reference witness mismatch: ' + name)
    core = json.loads((native / 'actual-core-parameters.json').read_text(encoding='utf-8'))
    if len(core) != 178 or core['memoryEntries'] != 4:
        raise ValueError('Native core must retain 178 fields and LSU4')
    actual = json.loads((native / 'actual-native.json').read_text(encoding='utf-8'))
    cpu = json.loads((reference / 'actual-three-proof-row-cpu.json').read_text(encoding='utf-8'))
    if actual['threeRow'] != cpu:
        raise ValueError('Native three-row CPU witness mismatch')
    excluded = {'bscanPrimitiveSimulated', 'cdcQualified', 'nativeMediaEnginesSimulated',
                'phyQualified', 'physicalComparisonCommit', 'productionPhysicalClocksSimulated',
                'publishedSourceBaseCommit', 'qualificationInherited', 'rawMediaImplementedInGsim',
                'replacementBoundaries', 'schema'}
    fabric = json.loads((reference / 'actual-fabric.json').read_text(encoding='utf-8'))
    if set(actual['excludedCpuOnlyObservationKeys']) != excluded:
        raise ValueError('Unknown native observation projection')
    if actual['commonFabric'] != {key: value for key, value in fabric.items() if key not in excluded}:
        raise ValueError('Native common fabric witness mismatch')
