"""Bind each fresh candidate stage to exact prior inputs/checkpoints; no tool run."""
import argparse
from pathlib import Path
from combined_contract import checked_files, info, read, require, sha, write
from verify_combined_package import verify


def stage_identity(root, vivado):
    verify(root, vivado)
    contract = read(root/'evidence/combined-inputs.json')
    return dict(packageSealSha256=sha(root/'package-seal.json'),
                sourceCommit=contract['sourceClosure']['commit'],
                nativeInventorySha256=sha(root/'native/rtl-inventory.json'),
                emissionToolchain=contract['emissionToolchain'], vivadoVersion=vivado)


def check_synthesis(root, identity):
    stage = root/'synthesis'
    receipt = read(stage/'combined-stage-receipt.json')
    require(receipt['schema'] == 'combined-bandwidth-stage-v1' and receipt['stage'] == 'synthesis' and
            receipt['status'] == 'SYNTHESIZED_NOT_PHYSICALLY_QUALIFIED', 'Stale/non-synthesis receipt')
    require(receipt['identity'] == identity, 'Synthesis inputs/source/toolchain changed')
    require(receipt['checkpoint'] == info(stage/'post_synth_unconstrained.dcp'), 'Swapped synthesis checkpoint')
    checked_files(stage, receipt['artifacts'])
    require(not (stage/'failure.txt').exists(), 'Failed synthesis cannot feed placement')
    return receipt


def seal(root, stage, identity):
    directory = root/stage
    require(not (directory/'failure.txt').exists(), 'Failed stage cannot be sealed')
    require((directory/'stage-result.txt').is_file(), 'Missing tool stage completion marker')
    if stage == 'synthesis':
        checkpoint = 'post_synth_unconstrained.dcp'
        status = 'SYNTHESIZED_NOT_PHYSICALLY_QUALIFIED'
        prior = None
    else:
        check_synthesis(root, identity)
        checkpoint = 'placed.dcp'
        status = 'PLACED_REPORTS_REQUIRE_REVIEW_NOT_QUALIFIED'
        prior = sha(root/'synthesis/combined-stage-receipt.json')
        require((directory/'combined-rom-preplace.json').is_file() and
                (directory/'combined-rom-placed.json').is_file(), 'Missing candidate ROM reconstruction reports')
    artifacts = {p.relative_to(directory).as_posix(): info(p) for p in directory.rglob('*') if p.is_file()}
    write(directory/'combined-stage-receipt.json', dict(schema='combined-bandwidth-stage-v1', stage=stage,
        status=status, identity=identity, checkpoint=info(directory/checkpoint), artifacts=artifacts,
        priorSynthesisReceiptSha256=prior, physicalQualification=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--vivado-version', required=True)
    parser.add_argument('--seal-stage')
    parser.add_argument('--check-synthesis', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    identity = stage_identity(root, args.vivado_version)
    if args.seal_stage:
        require(args.seal_stage and all(c.isalnum() or c in '_-' for c in args.seal_stage), 'Bad stage path')
        seal(root, args.seal_stage, identity)
    elif args.check_synthesis:
        check_synthesis(root, identity)
    else:
        parser.error('Specify stage seal or synthesis verification')
    print('PASS_COMBINED_STAGE_BINDING_ONLY_NOT_PHYSICAL_QUALIFICATION')


if __name__ == '__main__':
    main()
