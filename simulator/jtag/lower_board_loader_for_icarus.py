#!/usr/bin/env python3
"""Exact-fixture compatibility lowering for a separately staged drain-test copy.

This is not a general SV compiler. Fail closed on any unreviewed source change.
Automatic entry initializers become explicit per-entry assignments; simply
removing 'automatic' would silently turn them into one-time initialization.
"""
import hashlib
import re

REVIEWED_SHA256 = "c0e45a9e864311cb67bac3ed97e24e14aa0169a363634b71474df58148142e4f"
ADAPTED_SHA256 = "4d861109b6aaf75a6c600e3ba9b2bfd90d889c828ccc9b4dd9a3457e9ce2429b"


def verify_adapted(text):
    if hashlib.sha256(text.encode()).hexdigest() != ADAPTED_SHA256:
        raise ValueError("adapted loader differs from reviewed per-entry initializer projection")


DECL = re.compile(r"(?m)^([ ]*)automatic\s+logic\s+(\[[0-9]+:[0-9]+\]\s*)?([A-Za-z_][A-Za-z_0-9]*)(\s*=\s*[^;]+)?;")


def lower(text):
    source_hash = hashlib.sha256(text.encode()).hexdigest()
    if source_hash != REVIEWED_SHA256:
        raise ValueError("unreviewed loader fixture; review lifetime/dataflow before adapting")
    # One non-reentrant sequential process, no delayed activation or dynamic calls.
    clean = re.sub(r'//[^\n]*|/\*.*?\*/', '', text, flags=re.DOTALL)
    if len(re.findall(r'\balways\s*@\(posedge clock\)', clean)) != 1:
        raise ValueError("review loader process shape")
    if re.search(r'\b(task|function|fork|join|wait|initial|forever|while|for)\b|#', clean):
        raise ValueError("dynamic activation/timing control unsupported")
    matches = list(DECL.finditer(text))
    if len(matches) != text.count('automatic logic'):
        raise ValueError("unsupported automatic declaration syntax")
    groups = []
    for match in matches:
        if not groups or text[groups[-1][-1].end():match.start()].strip():
            groups.append([])
        groups[-1].append(match)
    # Bound this adapter to the six reviewed nested declaration groups.
    counts = [len(group) for group in groups]
    if counts != [47, 24, 2, 1, 1, 3]:
        raise ValueError("review automatic declaration groups: " + str(counts))
    edits = []
    receipt = []
    for group in groups:
        indent = group[0].group(1)
        declarations, initializers, names = [], [], []
        for match in group:
            space, width, name, initializer = match.groups()
            if space != indent:
                raise ValueError("mixed declaration scope")
            names.append(name)
            declarations.append(space + 'logic ' + (width or '') + name + ';')
            if initializer:
                initializers.append(space + name + ' = ' + initializer.split('=', 1)[1].strip() + ';')
        # All temporaries must be assigned at entry, before first read and before
        # any nested control. This proves retained static values are irrelevant.
        suffix = '\n'.join(initializers) + '\n' + text[group[-1].end():]
        branch = re.search(r'\b(if|begin|end|case|for|while)\b', suffix)
        if not branch:
            raise ValueError("missing scope boundary")
        for name in names:
            first = re.search(r'\b' + re.escape(name) + r'\b', suffix)
            if not first or first.start() >= branch.start() or not re.match(r'\s*=(?!=)', suffix[first.end():]):
                raise ValueError("temporary not definitely assigned before first read: " + name)
        replacement = '\n'.join(declarations + initializers)
        edits.append((group[0].start(), group[-1].end(), replacement))
        receipt.append(dict(source_line=text[:group[0].start()].count('\n')+1,
                            declarations=names, per_entry_initializers=len(initializers)))
    if sum(group['per_entry_initializers'] for group in receipt) != 5:
        raise ValueError("review initializer count")
    result = text
    for start, end, replacement in reversed(edits):
        result = result[:start] + replacement + result[end:]
    if 'automatic' in result:
        raise ValueError("unhandled automatic lifetime")
    verify_adapted(result)
    # Removing declarations/relocating initializers changes only this test copy.
    return result, dict(schema='valence-exact-loader-lifetime-adapter-v1',
                        original_sha256=source_hash,
                        adapted_sha256=hashlib.sha256(result.encode()).hexdigest(),
                        groups=receipt, automatic_declarations=sum(counts),
                        per_entry_initializers=5, source_rtl_modified=False,
                        production_timeout_changed=False, physical_qualification=False)
