#ifndef VALENCE_BOARD_MEMORY_H
#define VALENCE_BOARD_MEMORY_H
#ifndef BOARD_RAM_BYTES
#define BOARD_RAM_BYTES 0x00100000UL
#endif
#define RAM_BASE 0x80200000UL
#ifndef BOARD_MONITOR_BASE
#define BOARD_MONITOR_BASE (RAM_BASE + BOARD_RAM_BYTES - 0x4000UL)
#endif
#ifdef BOOT_MENU
#define DIAG_RESERVE_BYTES 0x80000UL
#define DIAG_BASE (BOARD_MONITOR_BASE-DIAG_RESERVE_BYTES)
#define IMAGE_LIMIT (DIAG_BASE-RAM_BASE)
_Static_assert(DIAG_BASE >= 0x80310000UL, "diagnostic reservation overlaps standard DTB/firmware area");
#else
#define IMAGE_LIMIT (BOARD_MONITOR_BASE - RAM_BASE)
#endif
_Static_assert(BOARD_MONITOR_BASE >= RAM_BASE &&
               BOARD_MONITOR_BASE + 0x4000UL <= RAM_BASE + BOARD_RAM_BYTES,
               "monitor outside RAM");
_Static_assert(BOARD_MONITOR_BASE <= 0xffff8000UL, "BootROM medany reach exceeded");
#endif
