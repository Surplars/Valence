#!/usr/bin/env python3
"""Explicit SBI recovery or upstream 8250 IRQ console build contract."""
import re

PROFILES = ('sbi', 'uart-irq')
NATIVE_BOOT_CONSOLE = 'console=ttyS0,460800n8'


def check_profile(profile):
    if profile not in PROFILES:
        raise RuntimeError('Unsupported UART console profile: ' + str(profile))


def bootargs(text, profile):
    check_profile(profile)
    if text.split().count('console=hvc0') != 1:
        raise RuntimeError('Expected exactly one SBI recovery console')
    return text.replace('console=hvc0', NATIVE_BOOT_CONSOLE) if profile == 'uart-irq' else text


def config_flags(profile):
    check_profile(profile)
    if profile == 'sbi':
        return ['--enable', 'HVC_RISCV_SBI']
    # An enabled but unselected HVC still creates a polling receive owner.
    # Keep the separate SBI earlycon implementation for pre-driver diagnostics.
    return ['--disable', 'HVC_RISCV_SBI', '--enable', 'SERIAL_8250',
            '--enable', 'SERIAL_8250_CONSOLE', '--enable', 'SERIAL_OF_PLATFORM',
            '--enable', 'SERIAL_EARLYCON', '--enable', 'SERIAL_EARLYCON_RISCV_SBI',
            '--set-val', 'SERIAL_8250_NR_UARTS', '1',
            '--set-val', 'SERIAL_8250_RUNTIME_UARTS', '1']


def validate_config(text, profile):
    check_profile(profile)
    lines = set(text.splitlines())
    if profile == 'sbi':
        if 'CONFIG_HVC_RISCV_SBI=y' not in lines:
            raise RuntimeError('SBI recovery console driver missing')
        return
    required = ('TTY', 'SERIAL_8250', 'SERIAL_8250_CONSOLE', 'SERIAL_OF_PLATFORM',
                'SERIAL_EARLYCON', 'SERIAL_EARLYCON_RISCV_SBI')
    for name in required:
        if 'CONFIG_' + name + '=y' not in lines:
            raise RuntimeError('IRQ UART requires built-in ' + name)
    if '# CONFIG_HVC_RISCV_SBI is not set' not in lines:
        raise RuntimeError('IRQ UART forbids a concurrent SBI HVC receive owner')
    for name in ('SERIAL_8250_NR_UARTS', 'SERIAL_8250_RUNTIME_UARTS'):
        if 'CONFIG_' + name + '=1' not in lines:
            raise RuntimeError('IRQ UART must be the single ttyS0 port')
    command = next((line for line in lines if line.startswith('CONFIG_CMDLINE=')), '')
    if NATIVE_BOOT_CONSOLE not in command or 'console=hvc' in command or 'keep_bootcon' in command:
        raise RuntimeError('IRQ UART requires exclusive ttyS0 and normal earlycon handover')


def device_tree(text, profile):
    check_profile(profile)
    if profile == 'sbi':
        return text
    marker = '            reg-io-width = <1>;'
    if text.count(marker) != 1 or 'valence_aia: interrupt-controller@c000000' not in text:
        raise RuntimeError('IRQ UART requires the qualified CSR-only IRQ domain')
    text = text.replace(marker, marker + '\n'
        '            interrupts-extended = <&valence_aia 3 4>;\n'
        '            fifo-size = <16>;')
    return text.replace('* UART remains SBI DBCN/hvc polling; packet DMA uses source 6.',
                        '* UART uses source 3; packet DMA uses source 6 (both level-high).')


def validate_dts(text, profile):
    check_profile(profile)
    uart = re.search(r'\bserial@10000000\s*\{([^{}]*)\};', text)
    if not uart:
        raise RuntimeError('UART node missing')
    body = uart.group(1)
    if profile == 'sbi':
        if 'interrupts-extended' in body:
            raise RuntimeError('SBI recovery profile must not claim UART IRQ ownership')
        return
    # validate_dtb resolves the numeric phandle independently after dtc.
    if ('interrupts-extended' not in body or 'fifo-size' not in body or
            NATIVE_BOOT_CONSOLE not in text or 'console=hvc' in text or 'keep_bootcon' in text):
        raise RuntimeError('Incomplete/exclusive IRQ UART device-tree contract')
