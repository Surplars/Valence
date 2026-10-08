#!/usr/bin/env python3
"""One short UART runtime/level-rearm batch; unchanged production RTL."""
from run import setup, test, run
import subprocess

gsim, cxx = setup(False)
uart = test(gsim, cxx, 'uart-runtime', 'ip.UartGsimMain', 'UartConsole', 'uart_runtime.cpp')
mutant = subprocess.run([uart / 'run', '--mutate-oracle'], capture_output=True, text=True,
                        env={'ASAN_OPTIONS': 'detect_leaks=0'}, timeout=30)
if mutant.returncode != 1 or 'TX wire differs' not in mutant.stderr:
    raise RuntimeError('UART independent TX oracle mutation was not detected')
(uart / 'mutation.log').write_text(mutant.stderr)
test(gsim, cxx, 'aia-supervisor-uart', 'ip.AiaSupervisorUartGsimMain',
     'AiaSupervisorUartGsim', 'aia_supervisor_uart.cpp')
print('UART_RUNTIME_BATCH_PASS_NOT_LINUX_OR_BOARD_EXECUTION')
