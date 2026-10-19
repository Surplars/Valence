# Bare-core internal paths only; not a board/CDC/I/O timing qualification.
create_clock -name orbital_i1_cpu -period 5.000 [get_ports clock]
