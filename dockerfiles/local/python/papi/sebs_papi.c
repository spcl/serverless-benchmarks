/*
 * Hardware counters for local function containers: a minimal PAPI wrapper.
 *
 * Python loads it with ctypes (see sebs_papi.py), so the interface uses only
 * integers, strings, and arrays of long long. Compiled against the PAPI of
 * the run image, which keeps the event tables (libpfm4) up to date with the
 * distribution.
 *
 * Overflow sampling: every `threshold` occurrences of an event, PAPI calls
 * overflow_handler from a signal handler. The handler stores a timestamp
 * (microseconds since the epoch) and the current values of all events in a
 * buffer allocated before counting starts, since allocating memory in a
 * signal handler is unsafe. Samples that don't fit are counted as dropped.
 *
 * One event set per process; the functions are not thread-safe.
 */

#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <papi.h>

static int event_set = PAPI_NULL;
static int num_events = 0;

static long long *samples = NULL;
static long long capacity = 0;
static volatile long long num_samples = 0;
static volatile long long num_dropped = 0;

int sebs_papi_init(void)
{
  if (!PAPI_is_initialized()) {
    int ret = PAPI_library_init(PAPI_VER_CURRENT);
    if (ret != PAPI_VER_CURRENT)
      return ret < 0 ? ret : PAPI_EINVAL;
  }
  if (event_set != PAPI_NULL)
    return PAPI_OK;
  num_events = 0;
  return PAPI_create_eventset(&event_set);
}

const char *sebs_papi_strerror(int code)
{
  return PAPI_strerror(code);
}

int sebs_papi_add_event(const char *name)
{
  int ret = PAPI_add_named_event(event_set, name);
  if (ret == PAPI_OK)
    ++num_events;
  return ret;
}

int sebs_papi_num_events(void)
{
  return num_events;
}

static void overflow_handler(int set, void *address, long long overflow_vector, void *context)
{
  (void)set;
  (void)address;
  (void)overflow_vector;
  (void)context;

  if (num_samples >= capacity) {
    ++num_dropped;
    return;
  }
  long long *row = samples + num_samples * (num_events + 1);
  struct timespec now;
  clock_gettime(CLOCK_REALTIME, &now);
  row[0] = (long long)now.tv_sec * 1000000 + now.tv_nsec / 1000;
  if (PAPI_read(event_set, row + 1) == PAPI_OK)
    ++num_samples;
}

/* Sample all events every `threshold` occurrences of `event` (one of the added events).
 * Call after adding all events and before sebs_papi_start; keeps up to `max_samples`. */
int sebs_papi_overflow(const char *event, int threshold, long long max_samples)
{
  int code;
  int ret = PAPI_event_name_to_code(event, &code);
  if (ret != PAPI_OK)
    return ret;
  if (threshold <= 0 || max_samples <= 0 || num_events == 0)
    return PAPI_EINVAL;

  free(samples);
  samples = calloc((size_t)max_samples * (num_events + 1), sizeof(long long));
  if (!samples)
    return PAPI_ENOMEM;
  capacity = max_samples;
  num_samples = num_dropped = 0;
  return PAPI_overflow(event_set, code, threshold, 0, overflow_handler);
}

int sebs_papi_start(void)
{
  return PAPI_start(event_set);
}

/* Stops counting and writes the totals of all events to `values`. */
int sebs_papi_stop(long long *values)
{
  return PAPI_stop(event_set, values);
}

long long sebs_papi_num_samples(void)
{
  return num_samples;
}

long long sebs_papi_num_dropped(void)
{
  return num_dropped;
}

/* Copies the samples to `out`: rows of (timestamp, value of each event).
 * Returns the number of rows copied and empties the buffer. */
long long sebs_papi_take_samples(long long *out, long long max_rows)
{
  if (!samples || max_rows <= 0)
    return 0;
  long long rows = num_samples < max_rows ? num_samples : max_rows;
  memcpy(out, samples, (size_t)rows * (num_events + 1) * sizeof(long long));
  num_samples = num_dropped = 0;
  return rows;
}

void sebs_papi_finish(void)
{
  if (event_set != PAPI_NULL) {
    PAPI_cleanup_eventset(event_set);
    PAPI_destroy_eventset(&event_set);
  }
  event_set = PAPI_NULL;
  num_events = 0;
  free(samples);
  samples = NULL;
  capacity = num_samples = num_dropped = 0;
}
