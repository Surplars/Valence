#ifndef VALENCE_LINUX_SYSCALL_H
#define VALENCE_LINUX_SYSCALL_H

static inline long linux_syscall3(long number, long arg0, long arg1, long arg2) {
    register long a0 __asm__("a0") = arg0;
    register long a1 __asm__("a1") = arg1;
    register long a2 __asm__("a2") = arg2;
    register long a7 __asm__("a7") = number;
    __asm__ volatile("ecall" : "+r"(a0) : "r"(a1), "r"(a2), "r"(a7) : "memory");
    return a0;
}

static inline long linux_syscall1(long number, long arg0) {
    return linux_syscall3(number, arg0, 0, 0);
}

static inline long linux_syscall4(long number, long arg0, long arg1, long arg2, long arg3) {
    register long a0 __asm__("a0") = arg0;
    register long a1 __asm__("a1") = arg1;
    register long a2 __asm__("a2") = arg2;
    register long a3 __asm__("a3") = arg3;
    register long a7 __asm__("a7") = number;
    __asm__ volatile("ecall" : "+r"(a0) : "r"(a1), "r"(a2), "r"(a3), "r"(a7) : "memory");
    return a0;
}

static inline long linux_write(const char *value, unsigned long length) {
    return linux_syscall3(64, 1, (long)value, length);
}

static inline void linux_puts(const char *value) {
    const char *end = value;
    while (*end) ++end;
    linux_write(value, (unsigned long)(end - value));
}

#endif
