"""Bind each fresh candidate stage to exact prior inputs/checkpoints; no tool run."""
import argparse
from pathlib import Path, PurePosixPath
import re
from combined_contract import checked_files, info, read, require, sha, write, source_closure, validate_validator_revision
from verify_combined_package import verify


def stage_identity(root, vivado):
    verify(root, vivado)
    contract = read(root/'evidence/combined-inputs.json')
    return dict(packageSealSha256=sha(root/'package-seal.json'),
                sourceCommit=contract['sourceClosure']['commit'],
                nativeInventorySha256=sha(root/'native/rtl-inventory.json'),
                emissionToolchain=contract['emissionToolchain'], vivadoVersion=vivado)


def transient_artifact(name):
    """Only known Vivado process scratch and exit-mutated runtime bookkeeping."""
    parts = PurePosixPath(name).parts
    scratch = {'.lpr', 'HWH/design.hdf', 'elab.rtd', 'realtime/axi_clock_converter_ddr_stub.v',
               'realtime/blk_mem_gen_0_stub.v', 'realtime/clk_wiz_ddr_stub.v', 'realtime/ddr4_0_stub.v',
               'realtime/dupFiles.rpt', 'realtime/soc_top_fpga_next_ddr.tcl',
               'realtime/soc_top_fpga_next_ddr_synth.xdc', 'wt/project.wpc',
               'wt/synthesis.wdf', 'wt/synthesis_details.wdf'}
    return name == 'dfx_runtime.txt' or (len(parts) >= 3 and parts[0] == '.Xil' and
        re.fullmatch(r'Vivado-[0-9]+-[^/]+', parts[1]) is not None and '/'.join(parts[2:]) in scratch)


def durable_artifacts(artifacts):
    return {name: value for name, value in artifacts.items() if not transient_artifact(name)}


def check_synthesis(root, identity, recovery=None):
    stage = root/'synthesis'
    receipt = read(stage/'combined-stage-receipt.json')
    require(receipt['schema'] == 'combined-bandwidth-stage-v1' and receipt['stage'] == 'synthesis' and
            receipt['status'] == 'SYNTHESIZED_NOT_PHYSICALLY_QUALIFIED', 'Stale/non-synthesis receipt')
    require(receipt['identity'] == identity, 'Synthesis inputs/source/toolchain changed')
    require(receipt['checkpoint'] == info(stage/'post_synth_unconstrained.dcp'), 'Swapped synthesis checkpoint')
    if recovery is None:
        checked_files(stage, receipt['artifacts'])
    else:
        record = read(recovery)
        require(record['schema'] == 'combined-bandwidth-stage-recovery-v1', 'Wrong recovery schema')
        require(record['originalReceiptSha256'] == sha(stage/'combined-stage-receipt.json'), 'Changed original receipt')
        require(record['identity'] == identity and record['checkpoint'] == receipt['checkpoint'], 'Recovery identity mismatch')
        stable = durable_artifacts(receipt['artifacts'])
        excluded = {name: value for name, value in receipt['artifacts'].items() if transient_artifact(name)}
        require(record['artifacts'] == stable and record['excludedOriginalArtifacts'] == excluded, 'Recovery artifact omission')
        require(record['physicalQualification'] is False, 'Recovery cannot qualify hardware')
        checked_files(stage, stable)
    require(not (stage/'failure.txt').exists(), 'Failed synthesis cannot feed placement')
    return receipt


def recover_synthesis(root, identity, output, expected_receipt, expected_checkpoint, validator):
    stage = root/'synthesis'
    require(sha(stage/'combined-stage-receipt.json') == expected_receipt, 'Unexpected original receipt')
    require(sha(stage/'post_synth_unconstrained.dcp') == expected_checkpoint, 'Unexpected recovery checkpoint')
    receipt = read(stage/'combined-stage-receipt.json')
    stable = durable_artifacts(receipt['artifacts'])
    excluded = {name: value for name, value in receipt['artifacts'].items() if transient_artifact(name)}
    require(bool(excluded), 'No known transient artifacts to recover')
    require({'post_synth_unconstrained.dcp', 'stage-result.txt', 'utilization.rpt', 'ip_status.rpt', 'rom-init.tsv'} <= set(stable),
            'Missing required durable synthesis outputs')
    checked_files(stage, stable)
    record = dict(schema='combined-bandwidth-stage-recovery-v1', originalReceiptSha256=expected_receipt,
                  identity=identity, checkpoint=info(stage/'post_synth_unconstrained.dcp'), artifacts=stable,
                  excludedOriginalArtifacts=excluded, validatorClosure=validator, physicalQualification=False)
    # Validate all original stage/identity constraints before writing an exclusive sidecar.
    require(receipt['schema'] == 'combined-bandwidth-stage-v1' and receipt['stage'] == 'synthesis' and
            receipt['status'] == 'SYNTHESIZED_NOT_PHYSICALLY_QUALIFIED', 'Invalid original stage')
    require(receipt['identity'] == identity and receipt['checkpoint'] == record['checkpoint'], 'Recovery identity/checkpoint mismatch')
    require(not (stage/'failure.txt').exists(), 'Failed synthesis cannot be recovered')
    write(output, record)


def seal(root, stage, identity, recovery=None):
    directory = root/stage
    require(not (directory/'failure.txt').exists(), 'Failed stage cannot be sealed')
    require((directory/'stage-result.txt').is_file(), 'Missing tool stage completion marker')
    if stage == 'synthesis':
        checkpoint = 'post_synth_unconstrained.dcp'
        status = 'SYNTHESIZED_NOT_PHYSICALLY_QUALIFIED'
        prior = None
        require(all((directory/name).is_file() for name in ('utilization.rpt', 'ip_status.rpt', 'rom-init.tsv')),
                'Missing durable synthesis reports')
    else:
        check_synthesis(root, identity, recovery)
        checkpoint = 'placed.dcp'
        status = 'PLACED_REPORTS_REQUIRE_REVIEW_NOT_QUALIFIED'
        prior = sha(root/'synthesis/combined-stage-receipt.json')
        require((directory/'combined-rom-preplace.json').is_file() and
                (directory/'combined-rom-placed.json').is_file(), 'Missing candidate ROM reconstruction reports')
    artifacts = durable_artifacts({p.relative_to(directory).as_posix(): info(p) for p in directory.rglob('*') if p.is_file()})
    write(directory/'combined-stage-receipt.json', dict(schema='combined-bandwidth-stage-v1', stage=stage,
        status=status, identity=identity, checkpoint=info(directory/checkpoint), artifacts=artifacts,
        priorSynthesisReceiptSha256=prior, recoveryReceiptSha256=sha(recovery) if recovery else None, physicalQualification=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--vivado-version', required=True)
    parser.add_argument('--seal-stage')
    parser.add_argument('--check-synthesis', action='store_true')
    parser.add_argument('--recovery', type=Path)
    parser.add_argument('--create-recovery', type=Path)
    parser.add_argument('--expected-receipt-sha256')
    parser.add_argument('--expected-checkpoint-sha256')
    parser.add_argument('--validator-root', type=Path)
    parser.add_argument('--validator-commit')
    args = parser.parse_args()
    root = args.root.resolve()
    identity = stage_identity(root, args.vivado_version)
    validator = None
    if args.recovery or args.create_recovery:
        require(args.validator_root is not None and args.validator_commit, 'Recovery requires explicit validator revision')
        require(Path(__file__).resolve().parent == args.validator_root.resolve()/'fpga/next/physical_eval', 'Recovery validator must execute source-local')
        validator = source_closure(args.validator_root)
        require(validator['commit'] == args.validator_commit, 'Wrong recovery validator commit')
        validate_validator_revision(read(root/'evidence/combined-inputs.json')['sourceClosure'], validator)
        if args.recovery:
            require(read(args.recovery)['validatorClosure'] == validator, 'Recovery validator source changed')
    if args.create_recovery:
        recover_synthesis(root, identity, args.create_recovery, args.expected_receipt_sha256,
                          args.expected_checkpoint_sha256, validator)
    elif args.seal_stage:
        require(args.seal_stage and all(c.isalnum() or c in '_-' for c in args.seal_stage), 'Bad stage path')
        seal(root, args.seal_stage, identity, args.recovery)
    elif args.check_synthesis:
        check_synthesis(root, identity, args.recovery)
    else:
        parser.error('Specify stage seal or synthesis verification')
    print('PASS_COMBINED_STAGE_BINDING_ONLY_NOT_PHYSICAL_QUALIFICATION')


if __name__ == '__main__':
    main()
