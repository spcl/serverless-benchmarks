// THIS IS THE SELFISH DETOUR EXAMPLE FROM NETGAUGE https://spcl.inf.ethz.ch/Research/Performance/Netgauge/OS_Noise/

#include <stdio.h>
#include <inttypes.h>
#include <unistd.h>

#define UINT64_T uint64_t
#define UINT32_T uint32_t

typedef struct {
    UINT32_T l;
    UINT32_T h;
} x86_64_timeval_t;

#define HRT_TIMESTAMP_T x86_64_timeval_t

/* TODO: Do we need a while loop here? aka Is rdtsc atomic? - check in the documentation */
#define HRT_GET_TIMESTAMP(t1)  __asm__ __volatile__ ("rdtsc" : "=a" (t1.l), "=d" (t1.h));

#define HRT_GET_ELAPSED_TICKS(t1, t2, numptr)	*numptr = (((( UINT64_T ) t2.h) << 32) | t2.l) - \
                                                          (((( UINT64_T ) t1.h) << 32) | t1.l);

#define HRT_GET_TIME(t1, time) time = (((( UINT64_T ) t1.h) << 32) | t1.l)

double get_ticks_per_second() {
    #define NUM_TESTS 10

    HRT_TIMESTAMP_T t1, t2;
    uint64_t res[NUM_TESTS];
    uint64_t min=0;
    int count;

    for (count=0; count<NUM_TESTS; count++) {
        HRT_GET_TIMESTAMP(t1);
        sleep(1);
        HRT_GET_TIMESTAMP(t2);
        HRT_GET_ELAPSED_TICKS(t1, t2, &res[count])
    }

    min = res[0];
    for (count=0; count<NUM_TESTS; count++) {
        if (min > res[count]) min = res[count];
    }

    return ((double) min);
}

void selfish_detour(int num_runs, int threshold, uint64_t *results) {
    int cnt=0, num_not_smaller = 0;
    HRT_TIMESTAMP_T current, prev, start;
    uint64_t sample = 0;
    uint64_t elapsed, thr, min=(uint64_t)~0;
    int i;

    // we will do a "calibration run" of the detour benchmark to
    // get a reasonable value for the minimal detour time
    // just perform the benchmark and record the minimal detour time until
    // this minimal detour time does not get smaller for 1000 (as defined by NOT_SMALLER)
    // consecutive runs

    #define NOT_SMALLER 100
    #define INNER_TRIES 50

    thr = min*(threshold/100.0);
    while (num_not_smaller < NOT_SMALLER) {
        cnt = 0;

        HRT_GET_TIMESTAMP(start);
        HRT_GET_TIMESTAMP(current);

        // this is exactly the same loop as below for measurement
        while (cnt < INNER_TRIES) {
            prev = current;
            HRT_GET_TIMESTAMP(current);

            sample++;

            HRT_GET_ELAPSED_TICKS(prev, current, &elapsed);
            // != instead of < in the benchmark loop in order to make the
            // notsmaller principle useful
            if ( elapsed != thr ) {
                HRT_GET_ELAPSED_TICKS(start, prev, &results[cnt++]);
                HRT_GET_ELAPSED_TICKS(start, current, &results[cnt++]);
            }
        }

        // find minimum in results array - this is outside the
        // calibration/measurement loop!
        {
            if(min == 0) {
                printf("The initialization reached 0 clock cycles - the clock accuracy seems too low (setting min=1 and exiting calibration)\n");
                min = 1;
                break;
            }
            int smaller=0;
            for(i = 0; i < INNER_TRIES; i+=2) {
                if(results[i+1]-results[i] < min) {
                    min = results[i+1]-results[i];
                    smaller=1;
                    //printf("[%i] min: %lu\n", r, min);
                }
            }
            if (!smaller) num_not_smaller++;
            else num_not_smaller = 0;
        }
    }

    // now we perform the actual benchmark: Read a time-stamp-counter in a tight
    // loop ignore the results if the timestamps are close to each other, as we can assume
    // that nobody interrupted us. If the difference of the timestamps exceeds a certain
    // threshold, we assume that we have been "hit" by a "noise event" and record the
    // time difference for later analysis

    cnt = 2;
    sample = 0;

    HRT_GET_TIMESTAMP(start);
    HRT_GET_TIMESTAMP(current);

    // perform this outside measurement loop in order to save
    // time/increase measurement frequency
    thr = min*(threshold/100.0);
    while (cnt < num_runs) {
        prev = current;
        HRT_GET_TIMESTAMP(current);

        sample++;

        HRT_GET_ELAPSED_TICKS(prev, current, &elapsed);
        if ( elapsed > thr ) {
            HRT_GET_ELAPSED_TICKS(start, prev, &results[cnt++]);
            HRT_GET_ELAPSED_TICKS(start, current, &results[cnt++]);
        }
    }

    results[0] = min;
    results[1] = sample;
}