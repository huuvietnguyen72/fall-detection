// Port tối thiểu của Edge Impulse SDK cho máy tính (macOS/Linux) — dùng để chạy model trên PC.
#include "edge-impulse-sdk/porting/ei_classifier_porting.h"
#include "edge-impulse-sdk/tensorflow/lite/micro/debug_log.h"
#include <chrono>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <thread>

static const auto t0 = std::chrono::steady_clock::now();

EI_IMPULSE_ERROR ei_run_impulse_check_canceled() { return EI_IMPULSE_OK; }
EI_IMPULSE_ERROR ei_sleep(int32_t ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); return EI_IMPULSE_OK; }
uint64_t ei_read_timer_us() {
    return std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - t0).count();
}
uint64_t ei_read_timer_ms() { return ei_read_timer_us() / 1000; }
void ei_serial_set_baudrate(int) {}
void ei_putchar(char c) { fputc(c, stderr); }
char ei_getchar() { return 0; }
void ei_printf(const char *fmt, ...) { va_list a; va_start(a, fmt); vfprintf(stderr, fmt, a); va_end(a); }
void ei_printf_float(float f) { fprintf(stderr, "%f", f); }
void *ei_malloc(size_t n) { return malloc(n); }
void *ei_calloc(size_t n, size_t s) { return calloc(n, s); }
void ei_free(void *p) { free(p); }
void DebugLog(const char *s) { fputs(s, stderr); }
