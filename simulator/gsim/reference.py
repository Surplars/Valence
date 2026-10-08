"""Build an isolated, pinned NEMU reference without mutating the vendored worktree."""

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

sys.dont_write_bytecode = True

from run import ROOT, HERE, BUILD, run


def build_reference():
    lock = json.loads((HERE / "config/reference-lock.json").read_text())
    source = BUILD / "nemu-src"
    source.mkdir(parents=True, exist_ok=True)
    # Archive-restored source trees have no Git metadata. An explicit isolated
    # repository may supply only the locked commit; never infer another revision.
    explicit_gitdir = os.environ.get("NEMU_REFERENCE_GIT_DIR")
    if explicit_gitdir:
        gitdir = Path(explicit_gitdir).resolve()
        if not gitdir.is_dir():
            raise RuntimeError("explicit NEMU reference Git directory does not exist")
    else:
        common = Path(subprocess.check_output(["git", "-C", ROOT, "rev-parse", "--git-common-dir"], text=True).strip())
        gitdir = (common if common.is_absolute() else ROOT / common) / "modules/NEMU"
        if not gitdir.is_dir():
            gitdir = Path(subprocess.check_output(["git", "-C", ROOT / "NEMU", "rev-parse", "--absolute-git-dir"],
                                                  text=True).strip())
    resolved_revision = subprocess.check_output(
        ["git", f"--git-dir={gitdir}", "rev-parse", lock["revision"] + "^{commit}"], text=True).strip()
    if resolved_revision != lock["revision"]:
        raise RuntimeError("NEMU reference revision differs from the lock")
    archive = subprocess.check_output(["git", f"--git-dir={gitdir}", "archive", lock["revision"]])
    with tarfile.open(fileobj=io.BytesIO(archive)) as tree:
        for entry in tree.getmembers():
            destination = source / entry.name
            if not destination.resolve().is_relative_to(source.resolve()):
                raise RuntimeError("unexpected reference archive path")
            if entry.isdir():
                destination.mkdir(parents=True, exist_ok=True)
            elif entry.isfile():
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(tree.extractfile(entry).read())
                destination.chmod(entry.mode)
            else:
                raise RuntimeError(f"unsupported reference archive member: {entry.name}")
    # Only the checkpoint layout header is compiled; the proto/empty nanopb directory prevent upstream
    # unconditional fetches. Protobuf checkpoint support is disabled; these tests use no checkpoints.
    resource_root = Path(os.environ.get("NEMU_REFERENCE_RESOURCE_ROOT", str(ROOT / "NEMU/resource")))
    for name, expected in lock["resources"].items():
        data = (resource_root / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError(f"NEMU resource hash mismatch: {name}")
        destination = source / "resource" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    (source / "resource/nanopb").mkdir(parents=True, exist_ok=True)
    config = HERE / "config/rv64-integer-ref_defconfig"
    shutil.copyfile(config, source / "configs/gsim-integer_defconfig")
    env = {**os.environ, "NEMU_HOME": str(source), "CCACHE_DIR": str(BUILD / "ccache-nemu")}
    # Upstream make otherwise automatically stages/commits its parent repository on every compilation.
    arguments = ["make", "git_commit="]
    run([*arguments, "gsim-integer_defconfig"], cwd=source, env=env, log=BUILD / "reference-config.log")
    resolved = (source / ".config").read_text()
    required = ["CONFIG_ISA_riscv64=y", "CONFIG_SHARE=y", "CONFIG_FPU_NONE=y",
                "CONFIG_MBASE=0x80000000", "CONFIG_MSIZE=0x01000000", "CONFIG_RV_ZICOND=y", "CONFIG_RVB=y"]
    forbidden = ["CONFIG_LIGHTQS=y", "CONFIG_RVH=y", "CONFIG_RVV=y", "CONFIG_RV_AME=y",
                 "CONFIG_DIFFTEST_CHECK_VCSR=y", "CONFIG_DIFFTEST_CHECK_FCSR=y", "CONFIG_DIFFTEST_CHECK_SDTRIG=y",
                 "CONFIG_LIBCHECKPOINT_RESTORER=y", "CONFIG_FPU_SOFT=y", "CONFIG_FPU_HOST=y"]
    if any(option not in resolved.splitlines() for option in required) or any(option in resolved.splitlines() for option in forbidden):
        raise RuntimeError("resolved NEMU configuration violates the audited reference ABI/build profile")
    run([*arguments, "-j2", "LDFLAGS=-rdynamic -shared -fPIC -Wl,--no-undefined -lz -Wl,--gc-sections -Wl,--exclude-libs,ALL"],
        cwd=source, env=env, log=BUILD / "reference-build.log")
    library = source / "build/riscv64-nemu-interpreter-so"
    used = {**lock, "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
            "resolved_config_sha256": hashlib.sha256((source / ".config").read_bytes()).hexdigest(),
            "library_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
            "compiler": subprocess.check_output(["gcc", "--version"], text=True).splitlines()[0]}
    (BUILD / "reference-used.json").write_text(json.dumps(used, indent=2) + "\n")
    return library


if __name__ == "__main__":
    print(build_reference())
