// 시뮬레이터 앱 프로세스 하나의 벽시계만 옮긴다(홍보용 렌더 전용, 일회용 복제 시뮬에서만).
// TIMESHIFT_PROC 와 실행 파일 이름이 같을 때만, TIMESHIFT_OFFSET 초만큼 REALTIME을 민다.
// 원함수가 안에서 다른 시계 함수를 불러도 두 번 밀리지 않게 스레드별 재진입 표시를 둔다.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

static __thread int busy = 0;
static long long offset_s = 0;
static int active = 0;

__attribute__((constructor)) static void ts_init(void) {
    const char *want = getenv("TIMESHIFT_PROC");
    const char *off = getenv("TIMESHIFT_OFFSET");
    const char *me = getprogname();
    if (off && want && me && strcmp(me, want) == 0) {
        offset_s = atoll(off);
        active = 1;
    }
    const char *log = getenv("TIMESHIFT_LOG");
    if (log && active) {
        FILE *f = fopen(log, "a");
        if (f) { fprintf(f, "%s pid=%d offset=%lld\n", me, getpid(), offset_s); fclose(f); }
    }
}

// active가 아니면(=Trace가 아닌 프로세스, 또는 초기화 전) 스레드 지역 변수를 건드리지 않는다.
// libSystem 초기화 중 corecrypto가 시계를 부르는데 그때 TLS를 만지면 _tlv_bootstrap_error로 죽는다(실측).
static int ts_gettimeofday(struct timeval *tv, void *tz) {
    if (!active) return gettimeofday(tv, tz);
    int was = busy; busy = 1;
    int r = gettimeofday(tv, tz);
    busy = was;
    if (!was && tv && r == 0) tv->tv_sec += offset_s;
    return r;
}

static int ts_clock_gettime(clockid_t c, struct timespec *ts) {
    if (!active) return clock_gettime(c, ts);
    int was = busy; busy = 1;
    int r = clock_gettime(c, ts);
    busy = was;
    if (!was && ts && r == 0 && c == CLOCK_REALTIME) ts->tv_sec += offset_s;
    return r;
}

static uint64_t ts_clock_gettime_nsec_np(clockid_t c) {
    if (!active) return clock_gettime_nsec_np(c);
    int was = busy; busy = 1;
    uint64_t r = clock_gettime_nsec_np(c);
    busy = was;
    if (!was && c == CLOCK_REALTIME && r) r += (uint64_t)offset_s * 1000000000ULL;
    return r;
}

__attribute__((used)) static const struct { const void *rep; const void *orig; } ts_interpose[]
    __attribute__((section("__DATA,__interpose"))) = {
    {(const void *)ts_gettimeofday, (const void *)gettimeofday},
    {(const void *)ts_clock_gettime, (const void *)clock_gettime},
    {(const void *)ts_clock_gettime_nsec_np, (const void *)clock_gettime_nsec_np},
};
