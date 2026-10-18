#ifndef I1_DIAGNOSTIC_PLATFORM_H
#define I1_DIAGNOSTIC_PLATFORM_H
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#ifndef CPU_HZ
#define CPU_HZ 300000000UL
#endif
#define SOURCE_PA 0x81000000UL
#define DEST_PA   0x83000040UL
#define SOURCE_VA 0x41000000UL
#define DEST_VA   0x43000040UL
#define PATTERN 0x123400000000UL
static inline uint64_t cycles(void) { uint64_t x; __asm__ volatile("rdcycle %0" : "=r"(x) :: "memory"); return x; }
static inline uint64_t retired(void) { uint64_t x; __asm__ volatile("rdinstret %0" : "=r"(x) :: "memory"); return x; }
static inline uint64_t ticks(void) { uint64_t x; __asm__ volatile("rdtime %0" : "=r"(x) :: "memory"); return x; }
static inline void fence_memory(void) { __asm__ volatile("fence rw,rw" ::: "memory"); }
void putchar_uart(int c);
int getchar_uart(void);
int diag_vprintf(const char *fmt, va_list ap);
int diag_printf(const char *fmt, ...);
void print_ratio(uint64_t numerator, uint64_t denominator, unsigned decimals);
extern int quiet_output;
extern volatile uint64_t supervisor_active, trap_cause, trap_pc, trap_value;
int run_supervisor(void (*job)(void));
void trap_entry(void);
void fatal_trap(uint64_t cause, uint64_t pc, uint64_t value) __attribute__((noreturn));
uint64_t stream_read(const uint64_t *p, size_t bytes);
void stream_write(uint64_t *p, size_t bytes, uint64_t seed);
void stream_copy(uint64_t *dst, const uint64_t *src, size_t bytes);
void scalar_copy(uint64_t *dst, const uint64_t *src, size_t bytes);
void run_coremark(int short_run);
extern uint64_t cm_cycles, cm_instructions, cm_ticks, cm_iterations;
extern unsigned cm_crcs[5], cm_validated, cm_errors;
#endif
