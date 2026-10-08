#ifndef VALENCE_MONITOR_DIAG_H
#define VALENCE_MONITOR_DIAG_H
unsigned monitor_external_state_untrusted(void);
void monitor_run_diagnostic(unsigned command,unsigned image_length);
int monitor_memory_dma_idle(void);
#endif
