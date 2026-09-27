typedef unsigned long usize;

enum {
    SYS_mount = 40,
    SYS_openat = 56,
    SYS_close = 57,
    SYS_read = 63,
    SYS_write = 64,
    SYS_nanosleep = 101,
    SYS_uname = 160,
    SYS_getpid = 172,
    SYS_exit = 93,
};

enum { AT_FDCWD = -100, O_RDONLY = 0 };

struct timespec {
    long seconds;
    long nanoseconds;
};

struct utsname {
    char sysname[65];
    char nodename[65];
    char release[65];
    char version[65];
    char machine[65];
    char domainname[65];
};

static long syscall1(long number, long arg0) {
    register long a0 __asm__("a0") = arg0;
    register long a7 __asm__("a7") = number;
    __asm__ volatile("ecall" : "+r"(a0) : "r"(a7) : "memory");
    return a0;
}

static long syscall3(long number, long arg0, long arg1, long arg2) {
    register long a0 __asm__("a0") = arg0;
    register long a1 __asm__("a1") = arg1;
    register long a2 __asm__("a2") = arg2;
    register long a7 __asm__("a7") = number;
    __asm__ volatile("ecall" : "+r"(a0) : "r"(a1), "r"(a2), "r"(a7) : "memory");
    return a0;
}

static long syscall4(long number, long arg0, long arg1, long arg2, long arg3) {
    register long a0 __asm__("a0") = arg0;
    register long a1 __asm__("a1") = arg1;
    register long a2 __asm__("a2") = arg2;
    register long a3 __asm__("a3") = arg3;
    register long a7 __asm__("a7") = number;
    __asm__ volatile("ecall" : "+r"(a0) : "r"(a1), "r"(a2), "r"(a3), "r"(a7) : "memory");
    return a0;
}

static long syscall5(long number, long arg0, long arg1, long arg2, long arg3, long arg4) {
    register long a0 __asm__("a0") = arg0;
    register long a1 __asm__("a1") = arg1;
    register long a2 __asm__("a2") = arg2;
    register long a3 __asm__("a3") = arg3;
    register long a4 __asm__("a4") = arg4;
    register long a7 __asm__("a7") = number;
    __asm__ volatile("ecall" : "+r"(a0) : "r"(a1), "r"(a2), "r"(a3), "r"(a4), "r"(a7) : "memory");
    return a0;
}

static usize string_length(const char *text) {
    usize length = 0;
    while (text[length] != '\0') {
        ++length;
    }
    return length;
}

static int string_equal(const char *left, const char *right) {
    while (*left != '\0' && *left == *right) {
        ++left;
        ++right;
    }
    return *left == *right;
}

static int starts_with(const char *text, const char *prefix) {
    while (*prefix != '\0' && *text == *prefix) {
        ++text;
        ++prefix;
    }
    return *prefix == '\0';
}

static void write_bytes(int fd, const char *data, usize length) {
    while (length != 0) {
        long written = syscall3(SYS_write, fd, (long)data, (long)length);
        if (written <= 0) {
            return;
        }
        data += written;
        length -= (usize)written;
    }
}

static void print(const char *text) {
    write_bytes(1, text, string_length(text));
}

static void print_number(long value) {
    char buffer[24];
    usize cursor = sizeof(buffer);
    unsigned long remaining = (unsigned long)value;
    do {
        buffer[--cursor] = (char)('0' + remaining % 10);
        remaining /= 10;
    } while (remaining != 0);
    write_bytes(1, buffer + cursor, sizeof(buffer) - cursor);
}

static void mount_filesystems(void) {
    syscall5(SYS_mount, (long)"devtmpfs", (long)"/dev", (long)"devtmpfs", 0, 0);
    syscall5(SYS_mount, (long)"proc", (long)"/proc", (long)"proc", 0, 0);
    syscall5(SYS_mount, (long)"sysfs", (long)"/sys", (long)"sysfs", 0, 0);
}

static void print_file(const char *path) {
    char buffer[256];
    long fd = syscall4(SYS_openat, AT_FDCWD, (long)path, O_RDONLY, 0);
    if (fd < 0) {
        print("open failed\n");
        return;
    }
    for (;;) {
        long length = syscall3(SYS_read, fd, (long)buffer, sizeof(buffer));
        if (length <= 0) {
            break;
        }
        write_bytes(1, buffer, (usize)length);
    }
    syscall1(SYS_close, fd);
}

static void print_uname(void) {
    struct utsname name;
    if (syscall1(SYS_uname, (long)&name) < 0) {
        print("uname failed\n");
        return;
    }
    print(name.sysname);
    print(" ");
    print(name.release);
    print(" ");
    print(name.machine);
    print("\n");
}

static void run_command(char *command) {
    if (string_equal(command, "help")) {
        print("commands: help, uname, pid, meminfo, cpuinfo, sleep, echo TEXT\n");
    } else if (string_equal(command, "uname")) {
        print_uname();
    } else if (string_equal(command, "pid")) {
        print_number(syscall1(SYS_getpid, 0));
        print("\n");
    } else if (string_equal(command, "meminfo")) {
        print_file("/proc/meminfo");
    } else if (string_equal(command, "cpuinfo")) {
        print_file("/proc/cpuinfo");
    } else if (string_equal(command, "sleep")) {
        const struct timespec duration = {1, 0};
        syscall3(SYS_nanosleep, (long)&duration, 0, 0);
        print("timer wakeup ok\n");
    } else if (starts_with(command, "echo ")) {
        print(command + 5);
        print("\n");
    } else if (command[0] != '\0') {
        print("unknown command; type help\n");
    }
}

static void command_loop(void) {
    char command[128];
    for (;;) {
        print("ionsoc# ");
        long length = syscall3(SYS_read, 0, (long)command, sizeof(command) - 1);
        if (length <= 0) {
            const struct timespec retry = {0, 100000000};
            syscall3(SYS_nanosleep, (long)&retry, 0, 0);
            continue;
        }
        while (length > 0 && (command[length - 1] == '\n' || command[length - 1] == '\r')) {
            --length;
        }
        command[length] = '\0';
        run_command(command);
    }
}

__attribute__((noreturn)) void _start(void) {
    print("\n[init] IonSoC userspace reached\n");
    print("[init] pid=");
    print_number(syscall1(SYS_getpid, 0));
    print("\n");
    mount_filesystems();
    print("[init] devtmpfs/proc/sysfs mount requested\n");
    command_loop();
    syscall1(SYS_exit, 0);
    for (;;) {}
}
