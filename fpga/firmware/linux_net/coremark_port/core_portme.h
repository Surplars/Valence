#ifndef VALENCE_GC_CORE_PORTME_H
#define VALENCE_GC_CORE_PORTME_H
#include <stddef.h>
#include <stdint.h>
#define HAS_FLOAT 1
#define HAS_TIME_H 1
#define HAS_STDIO 1
#define HAS_PRINTF 1
#define SEED_METHOD SEED_ARG
#define MEM_METHOD MEM_STATIC
#define MAIN_HAS_NOARGC 0
#define MAIN_HAS_NORETURN 0
#define MULTITHREAD 1
#define COMPILER_VERSION __VERSION__
#define COMPILER_FLAGS "-O2 -march=rv64gc -mabi=lp64d (integer algorithms unchanged)"
#define MEM_LOCATION "Linux initramfs static RAM, hard-float time reporting"
typedef int16_t ee_s16;
typedef uint16_t ee_u16;
typedef int32_t ee_s32;
typedef uint32_t ee_u32;
typedef uint8_t ee_u8;
typedef uintptr_t ee_ptr_int;
typedef size_t ee_size_t;
typedef uint64_t CORE_TICKS;
#define align_mem(x) (void *)(4 + (((ee_ptr_int)(x) - 1) & ~(ee_ptr_int)3))
typedef struct CORE_PORTABLE_S { ee_u8 portable_id; } core_portable;
extern ee_u32 default_num_contexts;
void portable_init(core_portable *, int *, char *[]);
void portable_fini(core_portable *);
#endif
