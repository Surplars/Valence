/* Small bring-up initramfs, not the final Debian userspace.
 * The KVM probe executes a real VS guest and checks its MMIO exit independently.
 */
#include <errno.h>
#include <fcntl.h>
#include <linux/kvm.h>
#include <signal.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/mount.h>
#include <sys/utsname.h>
#include <sys/wait.h>
#include <unistd.h>
#include "kvm-guest.h"

static void check(int ok, const char *operation)
{
    if (!ok) {
        perror(operation);
        exit(1);
    }
}

static void reg_set(int cpu, uint64_t index, unsigned long value)
{
    struct kvm_one_reg reg = {
        .id = KVM_REG_RISCV | KVM_REG_SIZE_U64 | KVM_REG_RISCV_CORE | index,
        .addr = (uintptr_t)&value,
    };
    check(ioctl(cpu, KVM_SET_ONE_REG, &reg) == 0, "KVM_SET_ONE_REG");
}

static void guest_test(void)
{
    alarm(5);
    int kvm = open("/dev/kvm", O_RDWR | O_CLOEXEC);
    check(kvm >= 0, "open /dev/kvm");
    check(ioctl(kvm, KVM_GET_API_VERSION, 0) == KVM_API_VERSION, "KVM_GET_API_VERSION");
    int vm = ioctl(kvm, KVM_CREATE_VM, 0);
    check(vm >= 0, "KVM_CREATE_VM");
    void *ram = mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    check(ram != MAP_FAILED, "guest RAM mmap");
    memcpy(ram, guest_code, sizeof(guest_code));
    struct kvm_userspace_memory_region region = {
        .slot = 0, .guest_phys_addr = 0x80000000,
        .memory_size = 4096, .userspace_addr = (uintptr_t)ram,
    };
    check(ioctl(vm, KVM_SET_USER_MEMORY_REGION, &region) == 0, "KVM_SET_USER_MEMORY_REGION");
    int cpu = ioctl(vm, KVM_CREATE_VCPU, 0);
    check(cpu >= 0, "KVM_CREATE_VCPU");
    int bytes = ioctl(kvm, KVM_GET_VCPU_MMAP_SIZE, 0);
    check(bytes > 0, "KVM_GET_VCPU_MMAP_SIZE");
    struct kvm_run *run = mmap(NULL, bytes, PROT_READ | PROT_WRITE, MAP_SHARED, cpu, 0);
    check(run != MAP_FAILED, "KVM run mmap");
    reg_set(cpu, KVM_REG_RISCV_CORE_REG(regs.pc), 0x80000000);
    reg_set(cpu, KVM_REG_RISCV_CORE_REG(mode), KVM_RISCV_MODE_S);
    puts("KVM_ENTER_VS_GUEST");
    check(ioctl(cpu, KVM_RUN, 0) == 0, "KVM_RUN");
    uint32_t value = 0;
    memcpy(&value, run->mmio.data, sizeof(value));
    printf("KVM exit=%u address=%#llx write=%u bytes=%u data=%#x\n",
           run->exit_reason, (unsigned long long)run->mmio.phys_addr,
           run->mmio.is_write, run->mmio.len, value);
    check(run->exit_reason == KVM_EXIT_MMIO && run->mmio.phys_addr == 0x10000000 &&
          run->mmio.is_write && run->mmio.len == 4 && value == 0x4b564d31, "guest MMIO oracle");
    puts("PASS_VALENCE_KVM_VS_GUEST_MMIO");
    exit(0);
}

static void kvm_test(void)
{
    pid_t child = fork();
    if (child == 0) guest_test();
    if (child < 0) { perror("fork"); return; }
    int status;
    if (waitpid(child, &status, 0) == child)
        printf("KVM probe child status=%#x\n", status);
}

static void info(void)
{
    struct utsname name;
    if (uname(&name) == 0) printf("%s %s %s\n", name.sysname, name.release, name.machine);
    puts("Diagnostic initramfs; final rootfs target: Debian 13 riscv64.");
}

int main(void)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    if (mount("devtmpfs", "/dev", "devtmpfs", 0, NULL)) perror("mount /dev");
    if (mount("proc", "/proc", "proc", 0, NULL)) perror("mount /proc");
    if (mount("sysfs", "/sys", "sysfs", 0, NULL)) perror("mount /sys");
    puts("VALENCE_LINUX_INIT_OK");
    info();
    kvm_test();
    char line[80];
    for (;;) {
        puts("Commands: info, kvm, help");
        printf("valence# ");
        if (!fgets(line, sizeof(line), stdin)) { sleep(1); clearerr(stdin); continue; }
        line[strcspn(line, "\r\n")] = 0;
        if (!strcmp(line, "kvm")) kvm_test();
        else if (!strcmp(line, "info")) info();
    }
}
