#define _POSIX_C_SOURCE 200809L
#include <arpa/inet.h>
#include <errno.h>
#include <netinet/tcp.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

static uint64_t now_ns(void)
{
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) { perror("clock"); exit(1); }
    return (uint64_t)t.tv_sec * 1000000000ULL + t.tv_nsec;
}
static void put64(unsigned char *p, uint64_t x)
{
    for (unsigned i = 0; i < 8; i++) p[i] = x >> (56 - 8 * i);
}
static uint64_t get64(const unsigned char *p)
{
    uint64_t x = 0;
    for (unsigned i = 0; i < 8; i++) x = (x << 8) | p[i];
    return x;
}
static int exact(int fd, unsigned char *p, size_t bytes, int sending)
{
    while (bytes) {
        ssize_t n = sending ? send(fd, p, bytes, 0) : recv(fd, p, bytes, 0);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) { if (n < 0) perror("socket IO"); else fputs("unexpected EOF\n", stderr); return -1; }
        p += n; bytes -= n;
    }
    return 0;
}
int main(int argc, char **argv)
{
    if (argc < 3 || argc > 5 || (strcmp(argv[1], "tx") && strcmp(argv[1], "rx"))) {
        fprintf(stderr, "Usage: net-bench tx|rx PC_IPV4 [PORT=5001] [MiB=1]\n"); return 2;
    }
    char *end;
    unsigned long port = argc > 3 ? strtoul(argv[3], &end, 10) : 5001;
    if (!port || port > 65535 || (argc > 3 && (!*argv[3] || *end))) return 2;
    unsigned long mib = argc > 4 ? strtoul(argv[4], &end, 10) : 1;
    if (!mib || mib > 256 || (argc > 4 && (!*argv[4] || *end))) return 2;
    int sending = !strcmp(argv[1], "tx");
    uint64_t count = (uint64_t)mib * 1048576, received_ns = 0;
    struct sockaddr_in peer = { .sin_family = AF_INET, .sin_port = htons(port) };
    if (inet_pton(AF_INET, argv[2], &peer.sin_addr) != 1) return 2;
    signal(SIGPIPE, SIG_IGN);
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) { perror("socket"); return 1; }
    struct timeval timeout = { .tv_sec = 30 };
    int one = 1;
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
    printf("Valence NETBENCH %s peer=%s:%lu payload=%llu bytes\n",
        sending ? "TX" : "RX", argv[2], port, (unsigned long long)count);
    fflush(stdout);
    if (connect(fd, (struct sockaddr *)&peer, sizeof(peer))) { perror("connect"); close(fd); return 1; }
    unsigned char header[24] = "VNETB001", ack[24], buffer[16384], pattern[16384];
    header[11] = sending ? 1 : 2;
    put64(header + 16, count);
    memset(pattern, 0xa5, sizeof(pattern));
    if (exact(fd, header, sizeof(header), 1)) goto failed;
    uint64_t begin = now_ns(), done = 0;
    while (done < count) {
        size_t chunk = count - done < sizeof(buffer) ? count - done : sizeof(buffer);
        if (sending) {
            if (exact(fd, pattern, chunk, 1)) goto failed;
        } else {
            if (exact(fd, buffer, chunk, 0)) goto failed;
            if (memcmp(buffer, pattern, chunk)) { fputs("payload verification failed\n", stderr); goto failed; }
        }
        done += chunk;
    }
    if (sending) {
        shutdown(fd, SHUT_WR);
        if (exact(fd, ack, sizeof(ack), 0) || memcmp(ack, "VNETACK1", 8) || get64(ack + 8) != count) goto failed;
        received_ns = get64(ack + 16); /* PC receiver's payload interval */
    } else {
        received_ns = now_ns() - begin;
        memcpy(ack, "VNETACK1", 8);
        put64(ack + 8, count); put64(ack + 16, received_ns);
        if (exact(fd, ack, sizeof(ack), 1)) goto failed;
    }
    uint64_t elapsed = now_ns() - begin;
    close(fd);
    if (!received_ns || !elapsed) return 1;
    printf("%s verified=%llu bytes receiver=%.6f s %.3f MiB/s %.3f Mbit/s\n",
        sending ? "TX" : "RX", (unsigned long long)count, received_ns / 1e9,
        count * 1e9 / received_ns / 1048576.0, count * 8000.0 / received_ns);
    printf("End-to-end confirmed elapsed=%.6f s; NET BENCH PASS\n", elapsed / 1e9);
    puts("TCP + CPU copies/checks + 1ms polling; not MAC/MIG peak bandwidth.");
    return 0;
failed:
    close(fd); puts("NET BENCH FAIL"); return 1;
}
