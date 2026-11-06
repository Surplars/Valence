#!/usr/bin/env python3
"""Independent finite-vector oracle for the tiny PMP fixture, not a CPU oracle."""
import json


def states(path):
    names, widths, values, time = {}, {}, {}, None
    for line in path.read_text().splitlines():
        words = line.split()
        if not words:
            continue
        if words[0] == "$var":
            names[words[3]], widths[words[3]] = words[4], int(words[2])
        elif line.startswith("#"):
            if time is not None:
                yield time, dict(values)
            time = int(line[1:])
        elif line[0] in "bB" and len(words) == 2 and words[1] in names:
            raw, code = words[0][1:].lower(), words[1]
            values[names[code]] = raw.rjust(widths[code], raw[0] if raw[0] in "xz" else "0")
        elif line[0] in "01xXzZ" and line[1:] in names:
            values[names[line[1:]]] = line[0].lower()
    if time is not None:
        yield time, dict(values)


def integer(value):
    return None if "x" in value or "z" in value else int(value, 2)


def check_case(directory, case, sites):
    name, kind, negative = case["name"], case["kind"], case["negative"]
    strict = json.loads((directory / f"{name}-strict.receipt.json").read_text())
    assert strict["returncode"] == (1 if negative else 0) and strict["killed_reason"] is None
    assert "-assert" in (directory / f"{name}-strict.ys").read_text()
    suffix = "observe" if negative else "strict"
    module = json.loads((directory / "observed.json").read_text())["modules"]["PmpLifetimeContract"]
    expected_inputs = {n: "0" * len(p["bits"]) for n, p in module["ports"].items() if p["direction"] == "input"}
    expected_inputs.update(io_privilege="01", io_size="011")
    expected_inputs.update(case["inputs"])
    snapshots = list(states(directory / f"{name}-{suffix}.vcd"))
    # Yosys emits nine applied samples and one unchanged terminal timestamp.
    assert [t for t, _ in snapshots] == list(range(0, 100, 10)), "missing or unexpected witness steps"
    for step, (_, values) in enumerate(snapshots):
        applied_step = min(step, 8)
        expected = dict(expected_inputs, clock=str(applied_step % 2),
                        reset="1" if applied_step < 2 or case["reset"] else "0")
        assert {n: values[n] for n in expected} == expected, (name, "stimulus binding", step)
    samples, active_samples, enabled, false, unknown, previous = 0, 0, set(), set(), set(), None
    for time, values in snapshots:
        before, previous = previous, values
        if before is None or before["clock"] != "0" or values["clock"] != "1":
            continue
        # Check settled original A/EN immediately BEFORE the sampling edge.
        s = before
        reset = integer(s["reset"])
        active_samples += int(reset == 0)
        owners = [integer(s["io_preparedValid"]) == 1,
                  integer(s["io_walker0State"]) == 1, integer(s["io_walker1State"]) == 1]
        address, size = integer(s["io_address"]), integer(s["io_size"])
        for i, site in enumerate(sites):
            en, predicate = integer(s[f"assert_EN_{i}"]), integer(s[f"assert_A_{i}"])
            assert integer(s[f"assert_TRG_{i}"]) == integer(s["clock"])
            if kind == "natural":
                owner, which = divmod(i, 2)
                assert f"io_denied_{owner}_pmp." in site["name"], "unsupported assertion order"
                assert en == (not reset and owners[owner]), (name, i, time)
                if address is not None and size is not None:
                    expected = (size <= 3 and address % (1 << size) == 0) if which == 0 else (
                        address >> 3) == ((address | ((1 << size) - 1)) >> 3)
                    assert predicate == expected, (name, i, time)
                assert integer(s[f"io_denied_{owner}"]) == (integer(s["io_privilege"]) != 3)
            elif i < 144:
                region, which = divmod(i % 48, 3)
                assert "io_denied_" not in site["name"], "unsupported bridge assertion order"
                assert en == (not reset and integer(s[f"io_state_regionActive_{region}"]) == 1)
                low = integer(s[f"io_state_regionLow_{region}"])
                end = integer(s[f"io_state_regionEnd_{region}"])
                expected = ((low >> 56) == 0 and (end >> 56) == 0,
                            low % 4 == 0 and end % 4 == 3, low <= end)[which]
                assert predicate == expected, (name, i, time)
            else:
                owner = i - 144
                assert f"io_denied_{owner}_pmp." in site["name"], "unsupported checker assertion order"
                assert en == (not reset and owners[owner])
            assert en is not None
            if en:
                enabled.add(i)
                if predicate == 0:
                    false.add(i)
                elif predicate is None:
                    unknown.add(i)
        samples += 1
    assert samples == 4 and active_samples == (0 if case["reset"] else 3), (name, samples, active_samples)
    if negative:
        assert false or unknown, name
        diagnostics = (directory / f"{name}-strict.stderr").read_text()
        assert any(sites[i]["name"] in diagnostics for i in false | unknown), name
        if name.endswith("-unknown"):
            assert unknown, name
    else:
        assert not false and not unknown, name
    return dict(name=name, strict_returncode=strict["returncode"], preedge_samples=samples,
                nonreset_preedge_samples=active_samples, all_input_samples_bound=True,
                enabled_sites=sorted(enabled), known_false_sites=sorted(false), active_unknown_sites=sorted(unknown))
