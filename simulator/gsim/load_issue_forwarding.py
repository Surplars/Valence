#!/usr/bin/env python3
"""Short backend load-to-registered-execution test with an independent architectural oracle."""
import os
import subprocess
from run import setup, run, BUILD, HERE


def main():
    gsim, cxx = setup(False)
    output = BUILD / "load-issue-forwarding"
    output.mkdir(parents=True, exist_ok=True)
    top = "LoadIssueForwardingGsim"
    run(["mill", "-i", "IonSoC.test.runMain", "ooo.LoadIssueForwardingGsimMain", output],
        log=output / "elaborate.log")
    for old in output.glob(top + "[0-9]*.cpp"):
        old.unlink()
    run([gsim, "--threads=1", f"--dir={output}", output / f"{top}.fir"], log=output / "generate.log")
    flags = ["-std=c++20", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
             "-I" + str(output)]
    objects = []
    for source in sorted(output.glob(top + "[0-9]*.cpp")):
        obj = source.with_suffix(".o")
        run([cxx, *flags, "-c", source, "-o", obj], log=obj.with_suffix(".compile.log"))
        objects.append(obj)
    print("Dedicated model objects ready; heavy compilation finished", flush=True)
    run([cxx, *flags, HERE / "harness" / "load_issue_forwarding.cpp", *objects, "-ldl", "-o", output / "run"],
        log=output / "compile.log")
    run([output / "run"], env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"},
        timeout=120, log=output / "test.log")
    with (output / "negative-test.log").open("w") as stream:
        result = subprocess.run([output / "run", "--inject-mismatch"], stdout=stream,
                                stderr=subprocess.STDOUT, timeout=30,
                                env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
    if result.returncode != 1 or "independent architectural result mismatch" not in (output / "negative-test.log").read_text():
        raise RuntimeError("architectural oracle mutation was not rejected")
    print("GSIM load issue forwarding oracle mutation: PASS", flush=True)


if __name__ == "__main__":
    main()
