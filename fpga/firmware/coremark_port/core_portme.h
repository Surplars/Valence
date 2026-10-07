#ifndef VALENCE_FPGA_CORE_PORTME_H
#define VALENCE_FPGA_CORE_PORTME_H

#include <stddef.h>
#include <stdint.h>

#define HAS_FLOAT 1
#define HAS_TIME_H 0
#define HAS_STDIO 0
#define HAS_PRINTF 0
#define SEED_METHOD SEED_VOLATILE
#define MEM_METHOD MEM_STATIC
#define PERFORMANCE_RUN 1
#define MAIN_HAS_NOARGC 1
#define MAIN_HAS_NORETURN 0
#define MULTITHREAD 1
#define COMPILER_VERSION COREMARK_COMPILER_VERSION
#ifndef COREMARK_COMPILER_FLAGS
#define COREMARK_COMPILER_FLAGS "-O2 -march=rv64im_zicsr_zifencei -mabi=lp64"
#endif
#define COMPILER_FLAGS COREMARK_COMPILER_FLAGS
#ifndef MEM_LOCATION
#define MEM_LOCATION "code and data in 1 MiB on-chip UltraRAM at 40 MHz"
#endif

typedef int16_t ee_s16;
typedef uint16_t ee_u16;
typedef int32_t ee_s32;
typedef uint32_t ee_u32;
typedef uint8_t ee_u8;
typedef uintptr_t ee_ptr_int;
typedef size_t ee_size_t;
typedef uint64_t CORETIMETYPE;
typedef uint64_t CORE_TICKS;
#define align_mem(x) (void *)(4 + (((ee_ptr_int)(x) - 1) & ~(ee_ptr_int)3))

typedef struct CORE_PORTABLE_S { ee_u8 portable_id; } core_portable;
extern ee_u32 default_num_contexts;
void portable_init(core_portable *p, int *argc, char *argv[]);
void portable_fini(core_portable *p);
int ee_printf(const char *fmt, ...);

#endif
