#ifndef VALENCE_GSIM_UART_CONSOLE_H
#define VALENCE_GSIM_UART_CONSOLE_H

#include <algorithm>
#include <cerrno>
#include <cstdint>
#include <deque>
#include <fcntl.h>
#include <stdexcept>
#include <termios.h>
#include <unistd.h>

class UartConsoleInput {
public:
    bool tty = false;
    bool eof = false;
    bool stop = false;
    std::deque<uint8_t> bytes;

    void activate() {
        tty = isatty(STDIN_FILENO);
        if (tty) {
            if (tcgetattr(STDIN_FILENO, &originalTerm)) throw std::runtime_error("cannot read terminal settings");
            termios active = originalTerm;
            active.c_lflag &= ~(ICANON | ECHO);
            active.c_cc[VMIN] = 0;
            active.c_cc[VTIME] = 0;
            if (tcsetattr(STDIN_FILENO, TCSANOW, &active))
                throw std::runtime_error("cannot set terminal input mode");
            changedTerm = true;
        }
        originalFlags = fcntl(STDIN_FILENO, F_GETFL);
        if (originalFlags < 0 || fcntl(STDIN_FILENO, F_SETFL, originalFlags | O_NONBLOCK))
            throw std::runtime_error("cannot make terminal input nonblocking");
    }

    ~UartConsoleInput() {
        if (originalFlags >= 0) fcntl(STDIN_FILENO, F_SETFL, originalFlags);
        if (changedTerm) tcsetattr(STDIN_FILENO, TCSANOW, &originalTerm);
    }

    void poll() {
        if (eof || stop || bytes.size() >= 4096) return;
        uint8_t buffer[256];
        const size_t space = std::min(sizeof(buffer), size_t(4096 - bytes.size()));
        const ssize_t count = read(STDIN_FILENO, buffer, space);
        if (count < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) return;
            throw std::runtime_error("terminal input read failed");
        }
        if (count == 0) { if (!tty) eof = true; return; }
        for (ssize_t index = 0; index < count; ++index) {
            if (tty && buffer[index] == 4) { stop = true; break; }
            bytes.push_back(buffer[index]);
        }
    }

private:
    int originalFlags = -1;
    bool changedTerm = false;
    termios originalTerm{};
};

class UartSerialRx {
public:
    bool active = false;

    void ack(uint8_t byte) {
        if (waitingForEcho && (byte == value || (value == '\n' && byte == '\r')))
            waitingForEcho = false;
    }

    bool next(std::deque<uint8_t> &bytes) {
        // Linux hvc0 polls SBI input without an IRQ; the SoC UART has one RX slot.
        if (!active && cooldown) { --cooldown; return true; }
        if (!active && waitingForEcho) {
            if (++waitCycles < 25000000) return true;
            waitingForEcho = false; // Covers a console configured without local echo.
        }
        if (!active && !bytes.empty()) {
            value = bytes.front();
            bytes.pop_front();
            frameCycle = 0;
            active = true;
            waitingForEcho = true;
            waitCycles = 0;
        }
        if (!active) return true;
        const unsigned bit = frameCycle / 16;
        const bool level = bit == 0 ? false : bit == 9 ? true : (value >> (bit - 1)) & 1;
        if (++frameCycle == 160) { active = false; cooldown = 300000; }
        return level;
    }

private:
    uint8_t value = 0;
    unsigned frameCycle = 0;
    unsigned cooldown = 0;
    bool waitingForEcho = false;
    unsigned waitCycles = 0;
};

#endif
