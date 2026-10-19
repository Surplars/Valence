# Internal five-stage SoC 100 MHz estimate, not board/CDC/RGMII/MIG qualification.
create_clock -name orbital_i1_cpu -period 10.000 [get_ports clock]
# Placeholder synchronous fabric I/O budgets; external timing remains a board integration obligation.
set_input_delay 0.000 -clock orbital_i1_cpu [get_ports -filter {DIRECTION == IN && NAME != clock}]
set_output_delay 0.000 -clock orbital_i1_cpu [get_ports -filter {DIRECTION == OUT}]
