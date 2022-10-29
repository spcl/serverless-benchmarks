#include <assert.h>
#include <stdlib.h>
#include <sys/time.h>
#include <stdio.h>

#include <papi.h>

#define DEBUG 0
#define DEBUG_PRINT(fmt, ...)\
  do { if(DEBUG) fprintf(stderr, "PYPAPI: "fmt, __VA_ARGS__); } while(0)

#define BUFFER_SIZE 100

static long long ** buffer = NULL;
static int buffer_size = BUFFER_SIZE, buffer_counter = 0;
static int counter = 0, cur_buffer_size = 0, events = 0;

long long * overflow_buffer(int size, int event_count)
{
  static long long * values = NULL;
  if(size > 0) {

    // clean. otherwise continue aggregation
    if(!buffer) {

      buffer = calloc(BUFFER_SIZE, sizeof(long long*));
      buffer_size = BUFFER_SIZE;
      buffer_counter = 0;
      DEBUG_PRINT("Allocated buffers storage of length %d\n", BUFFER_SIZE);

      values = malloc(sizeof(long long) * size * (event_count + 1));
      buffer[buffer_counter++] = values;
      DEBUG_PRINT("Allocate storage %p of size %ld at pos %d\n", values, sizeof(long long) * size * (event_count + 1), buffer_counter - 1);
      events = event_count;
      cur_buffer_size = size;
    }

    return values;
  } else if(size < 0) {
    //for(int i = 0; i < buffer_counter; ++i)
    //free(buffer[i]);
    values = NULL;
    free(buffer);
    buffer = NULL;
    buffer_size = buffer_counter = 0;
    counter = cur_buffer_size = events = 0;
    return NULL;
  } else {
    if(counter == cur_buffer_size) {

      if(buffer_counter == buffer_size) {
        buffer_size *= 2;
        buffer = realloc(buffer, sizeof(long long*) * buffer_size);
        DEBUG_PRINT("Reallocate buffers storage to length %d\n", buffer_size);
      }
      values = calloc(cur_buffer_size * (events + 1), sizeof(long long));
      buffer[buffer_counter++] = values;
      DEBUG_PRINT("Allocate storage %p of size %ld at pos %d\n", values, cur_buffer_size * (events + 1) * sizeof(long long), buffer_counter - 1);
      counter = 0;
    }
    return &values[(events + 1) * counter++];
  }
}

int overflow_buffer_count(void)
{
  return buffer_counter;
}

int overflow_buffer_size(int cnt)
{
  return (cnt == (buffer_counter - 1) ? counter : cur_buffer_size) * (events + 1);
}

long long * overflow_buffer_access(int cnt)
{
  DEBUG_PRINT("Overflow buffer acccess %p at %d\n", buffer[cnt], cnt);
  return buffer[cnt];
}

void overflow_buffer_allocate(int size, int event_count)
{
  assert(size > 0);
  assert(event_count > 0);
  overflow_buffer(size, event_count);
}

void overflow_buffer_deallocate(void)
{
  overflow_buffer(-1, 0);
}

long long * overflow_buffer_get(void)
{
  return overflow_buffer(0, 0);
}

void overflow_C_callback(
    int EventSet, void* address,
    long long overflow_vector, void* ctx)
{
  struct timeval tp;
  gettimeofday(&tp, NULL);
  long long cur_time = tp.tv_sec * 1000 * 1000 + tp.tv_usec;
  long long * data = overflow_buffer_get();
  data[0] = cur_time;
  DEBUG_PRINT("Overflow storage at %p\n", data);
  PAPI_read(EventSet, data + 1);
}

