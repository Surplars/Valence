/* Small Linux PID 1 command loop, with CoreMark as a separate ELF process. */
#include "linux-syscall.h"

static char line[96];

static void run_coremark(char *iterations) {
    char *args[] = { "/bin/coremark", "0", "0", "0", iterations, 0 };
    long pid = linux_syscall1(220, 17); /* clone(SIGCHLD): fork semantics */
    if (pid == 0) {
        linux_syscall3(221, (long)args[0], (long)args, 0); /* execve */
        linux_puts("execve /bin/coremark failed\n");
        linux_syscall1(93, 127); /* exit */
        for (;;) {}
    }
    if (pid < 0) {
        linux_puts("clone failed\n");
        return;
    }
    long status = 0;
    linux_syscall4(260, pid, (long)&status, 0, 0); /* wait4 */
    linux_puts("[coremark returned]\n");
}

void _start(void) {
    linux_puts("VALENCE_LINUX_INIT_OK\nCommands: coremark [iterations], help, exit\n");
    for (;;) {
        linux_puts("valence# ");
        unsigned length = 0;
        for (;;) {
            char byte;
            if (linux_syscall3(63, 0, (long)&byte, 1) != 1) continue;
            if (byte == '\r' || byte == '\n') {
                break;
            }
            if (byte == 127 || byte == '\b') {
                if (length) { --length; linux_puts("\b \b"); }
                continue;
            }
            if (byte >= ' ' && byte < 127 && length + 1 < sizeof(line)) {
                line[length++] = byte;
            }
        }
        line[length] = 0;
        if (line[0] == 0) continue;
        if (line[0] == 'c' && line[1] == 'o' && line[2] == 'r' && line[3] == 'e' &&
            line[4] == 'm' && line[5] == 'a' && line[6] == 'r' && line[7] == 'k' &&
            (line[8] == 0 || line[8] == ' ')) {
            char *iterations = "0"; /* CoreMark's automatic ten-second calibration. */
            if (line[8] == ' ') {
                iterations = line + 9;
                while (*iterations == ' ') ++iterations;
                if (!*iterations) iterations = "0";
                for (char *p = iterations; *p; ++p) {
                    if (*p < '0' || *p > '9') { iterations = 0; break; }
                }
            }
            if (iterations) run_coremark(iterations);
            else linux_puts("usage: coremark [iterations]\n");
        } else if (line[0] == 'h' && line[1] == 'e' && line[2] == 'l' && line[3] == 'p' && !line[4]) {
            linux_puts("coremark [iterations]: run Linux user-space CoreMark\nexit: stop GSIM\n");
        } else if (line[0] == 'e' && line[1] == 'x' && line[2] == 'i' && line[3] == 't' && !line[4]) {
            linux_puts("VALENCE_LINUX_EXIT\n");
            for (;;) linux_syscall1(101, 0); /* park PID 1 until GSIM exits */
        } else {
            linux_puts("unknown command; type help\n");
        }
    }
}
