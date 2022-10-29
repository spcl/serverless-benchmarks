// PAPI error code (definitions from papi.h)

#define PAPI_OK          0     /**< No error */
#define PAPI_EINVAL     -1     /**< Invalid argument */
#define PAPI_ENOMEM     -2     /**< Insufficient memory */
#define PAPI_ESYS       -3     /**< A System/C library call failed */
#define PAPI_ECMP       -4     /**< Not supported by component */
#define PAPI_ESBSTR     -4     /**< Backwards compatibility */
#define PAPI_ECLOST     -5     /**< Access to the counters was lost or interrupted */
#define PAPI_EBUG       -6     /**< Internal error, please send mail to the developers */
#define PAPI_ENOEVNT    -7     /**< Event does not exist */
#define PAPI_ECNFLCT    -8     /**< Event exists, but cannot be counted due to counter resource limitations */
#define PAPI_ENOTRUN    -9     /**< EventSet is currently not running */
#define PAPI_EISRUN     -10    /**< EventSet is currently counting */
#define PAPI_ENOEVST    -11    /**< No such EventSet Available */
#define PAPI_ENOTPRESET -12    /**< Event in argument is not a valid preset */
#define PAPI_ENOCNTR    -13    /**< Hardware does not support performance counters */
#define PAPI_EMISC      -14    /**< Unknown error code */
#define PAPI_EPERM      -15    /**< Permission level does not permit operation */
#define PAPI_ENOINIT    -16    /**< PAPI hasn't been initialized yet */
#define PAPI_ENOCMP     -17    /**< Component Index isn't set */
#define PAPI_ENOSUPP    -18    /**< Not supported */
#define PAPI_ENOIMPL    -19    /**< Not implemented */
#define PAPI_EBUF       -20    /**< Buffer size exceeded */
#define PAPI_EINVAL_DOM -21    /**< EventSet domain is not supported for the operation */
#define PAPI_EATTR      -22    /**< Invalid or missing event attributes */
#define PAPI_ECOUNT     -23    /**< Too many events or attributes */
#define PAPI_ECOMBO     -24    /**< Bad combination of features */
#define PAPI_NUM_ERRORS  25    /**< Number of error messages specified in this API */


// PAPI initialization state (definitions from papi.h)

#define PAPI_NOT_INITED           0
#define PAPI_LOW_LEVEL_INITED     1      /* Low level has called library init */
#define PAPI_HIGH_LEVEL_INITED    2      /* High level has called library init */
#define PAPI_THREAD_LEVEL_INITED  4      /* Threads have been inited */


// PAPI states (definitions from papi.h)

#define PAPI_STOPPED      0x01  /**< EventSet stopped */
#define PAPI_RUNNING      0x02  /**< EventSet running */
#define PAPI_PAUSED       0x04  /**< EventSet temp. disabled by the library */
#define PAPI_NOT_INIT     0x08  /**< EventSet defined, but not initialized */
#define PAPI_OVERFLOWING  0x10  /**< EventSet has overflowing enabled */
#define PAPI_PROFILING    0x20  /**< EventSet has profiling enabled */
#define PAPI_MULTIPLEXING 0x40  /**< EventSet has multiplexing enabled */
#define PAPI_ATTACHED     0x80  /**< EventSet is attached to another thread/process */
#define PAPI_CPU_ATTACHED 0x100 /**< EventSet is attached to a specific cpu (not counting thread of execution) */


// Other PAPI constants (definitions from papi.h)

#define PAPI_NULL       -1      /**<A nonexistent hardware event used as a placeholder */


// PAPI HIGH (definitions from papi.h)

int PAPI_accum_counters(long long * values, int array_len); /**< add current counts to array and reset counters */
int PAPI_num_counters(void); /**< get the number of hardware counters available on the system */
int PAPI_num_components(void); /**< get the number of components available on the system */
int PAPI_read_counters(long long * values, int array_len); /**< copy current counts to array and reset counters */
int PAPI_start_counters(int *events, int array_len); /**< start counting hardware events */
int PAPI_stop_counters(long long * values, int array_len); /**< stop counters and return current counts */
int PAPI_flips(float *rtime, float *ptime, long long * flpins, float *mflips); /**< simplified call to get Mflips/s (floating point instruction rate), real and processor time */
int PAPI_flops(float *rtime, float *ptime, long long * flpops, float *mflops); /**< simplified call to get Mflops/s (floating point operation rate), real and processor time */
int PAPI_ipc(float *rtime, float *ptime, long long * ins, float *ipc); /**< gets instructions per cycle, real and processor time */
int PAPI_epc(int event, float *rtime, float *ptime, long long *ref, long long *core, long long *evt, float *epc); /**< gets (named) events per cycle, real and processor time, reference and core cycles */


// PAPI LOW (definitions from papi.h)
// (commented definitions are not (yet?) binded)

typedef void (*PAPI_overflow_handler_t) (int EventSet, void *address,
                              long long overflow_vector, void *context);

int PAPI_accum(int EventSet, long long * values); /**< accumulate and reset hardware events from an event set */
int PAPI_add_event(int EventSet, int Event); /**< add single PAPI preset or native hardware event to an event set */
// int PAPI_add_named_event(int EventSet, char *EventName); /**< add an event by name to a PAPI event set */
int PAPI_add_events(int EventSet, int *Events, int number); /**< add array of PAPI preset or native hardware events to an event set */
// int PAPI_assign_eventset_component(int EventSet, int cidx); /**< assign a component index to an existing but empty eventset */
int PAPI_attach(int EventSet, unsigned long tid); /**< attach specified event set to a specific process or thread id */
int PAPI_cleanup_eventset(int EventSet); /**< remove all PAPI events from an event set */
int PAPI_create_eventset(int *EventSet); /**< create a new empty PAPI event set */
int PAPI_detach(int EventSet); /**< detach specified event set from a previously specified process or thread id */
int PAPI_destroy_eventset(int *EventSet); /**< deallocates memory associated with an empty PAPI event set */
// int PAPI_enum_event(int *EventCode, int modifier); /**< return the event code for the next available preset or natvie event */
// int PAPI_enum_cmp_event(int *EventCode, int modifier, int cidx); /**< return the event code for the next available component event */
// int PAPI_event_code_to_name(int EventCode, char *out); /**< translate an integer PAPI event code into an ASCII PAPI preset or native name */
// int PAPI_event_name_to_code(char *in, int *out); /**< translate an ASCII PAPI preset or native name into an integer PAPI event code */
// int PAPI_get_dmem_info(PAPI_dmem_info_t *dest); /**< get dynamic memory usage information */
// int PAPI_get_event_info(int EventCode, PAPI_event_info_t * info); /**< get the name and descriptions for a given preset or native event code */
// const PAPI_exe_info_t *PAPI_get_executable_info(void); /**< get the executable's address space information */
// const PAPI_hw_info_t *PAPI_get_hardware_info(void); /**< get information about the system hardware */
// const PAPI_component_info_t *PAPI_get_component_info(int cidx); /**< get information about the component features */
// int PAPI_get_multiplex(int EventSet); /**< get the multiplexing status of specified event set */
// int PAPI_get_opt(int option, PAPI_option_t * ptr); /**< query the option settings of the PAPI library or a specific event set */
// int PAPI_get_cmp_opt(int option, PAPI_option_t * ptr,int cidx); /**< query the component specific option settings of a specific event set */
// long long PAPI_get_real_cyc(void); /**< return the total number of cycles since some arbitrary starting point */
// long long PAPI_get_real_nsec(void); /**< return the total number of nanoseconds since some arbitrary starting point */
// long long PAPI_get_real_usec(void); /**< return the total number of microseconds since some arbitrary starting point */
// const PAPI_shlib_info_t *PAPI_get_shared_lib_info(void); /**< get information about the shared libraries used by the process */
// int PAPI_get_thr_specific(int tag, void **ptr); /**< return a pointer to a thread specific stored data structure */
// int PAPI_get_overflow_event_index(int Eventset, long long overflow_vector, int *array, int *number); /**< # decomposes an overflow_vector into an event index array */
// long long PAPI_get_virt_cyc(void); /**< return the process cycles since some arbitrary starting point */
// long long PAPI_get_virt_nsec(void); /**< return the process nanoseconds since some arbitrary starting point */
// long long PAPI_get_virt_usec(void); /**< return the process microseconds since some arbitrary starting point */
int PAPI_is_initialized(void); /**< return the initialized state of the PAPI library */
int PAPI_library_init(int version); /**< initialize the PAPI library */
int PAPI_list_events(int EventSet, int *Events, int *number); /**< list the events that are members of an event set */
// int PAPI_list_threads(unsigned long *tids, int *number); /**< list the thread ids currently known to PAPI */
// int PAPI_lock(int); /**< lock one of two PAPI internal user mutex variables */
// int PAPI_multiplex_init(void); /**< initialize multiplex support in the PAPI library */
// int PAPI_num_cmp_hwctrs(int cidx); /**< return the number of hardware counters for a specified component */
// int PAPI_num_events(int EventSet); /**< return the number of events in an event set */
int PAPI_overflow(int EventSet, int EventCode, int threshold, int flags, PAPI_overflow_handler_t handler); /**< set up an event set to begin registering overflows */
// void PAPI_perror(char *msg ); /**< Print a PAPI error message */
// int PAPI_profil(void *buf, unsigned bufsiz, caddr_t offset, unsigned scale, int EventSet, int EventCode, int threshold, int flags); /**< generate PC histogram data where hardware counter overflow occurs */
// int PAPI_query_event(int EventCode); /**< query if a PAPI event exists */
// int PAPI_query_named_event(char *EventName); /**< query if a named PAPI event exists */
int PAPI_read(int EventSet, long long * values); /**< read hardware events from an event set with no reset */
// int PAPI_read_ts(int EventSet, long long * values, long long *cyc); /**< read from an eventset with a real-time cycle timestamp */
// int PAPI_register_thread(void); /**< inform PAPI of the existence of a new thread */
int PAPI_remove_event(int EventSet, int EventCode); /**< remove a hardware event from a PAPI event set */
// int PAPI_remove_named_event(int EventSet, char *EventName); /**< remove a named event from a PAPI event set */
int PAPI_remove_events(int EventSet, int *Events, int number); /**< remove an array of hardware events from a PAPI event set */
// int PAPI_reset(int EventSet); /**< reset the hardware event counts in an event set */
// int PAPI_set_debug(int level); /**< set the current debug level for PAPI */
// int PAPI_set_cmp_domain(int domain, int cidx); /**< set the component specific default execution domain for new event sets */
// int PAPI_set_domain(int domain); /**< set the default execution domain for new event sets  */
// int PAPI_set_cmp_granularity(int granularity, int cidx); /**< set the component specific default granularity for new event sets */
// int PAPI_set_granularity(int granularity); /**<set the default granularity for new event sets */
// int PAPI_set_multiplex(int EventSet); /**< convert a standard event set to a multiplexed event set */
// int PAPI_set_opt(int option, PAPI_option_t * ptr); /**< change the option settings of the PAPI library or a specific event set */
// int PAPI_set_thr_specific(int tag, void *ptr); /**< save a pointer as a thread specific stored data structure */
// void PAPI_shutdown(void); /**< finish using PAPI and free all related resources */
// int PAPI_sprofil(PAPI_sprofil_t * prof, int profcnt, int EventSet, int EventCode, int threshold, int flags); /**< generate hardware counter profiles from multiple code regions */
int PAPI_start(int EventSet); /**< start counting hardware events in an event set */
int PAPI_state(int EventSet, int *status); /**< return the counting state of an event set */
int PAPI_stop(int EventSet, long long * values); /**< stop counting hardware events in an event set and return current events */
// char* PAPI_strerror(int); /**< return a pointer to the error name corresponding to a specified error code */
// unsigned long PAPI_thread_id(void); /**< get the thread identifier of the current thread */
// int PAPI_thread_init(unsigned long (*id_fn) (void)); /**< initialize thread support in the PAPI library */
// int PAPI_unlock(int); /**< unlock one of two PAPI internal user mutex variables */
// int PAPI_unregister_thread(void); /**< inform PAPI that a previously registered thread is disappearing */
// int PAPI_write(int EventSet, long long * values); /**< write counter values into counters */
// int PAPI_get_event_component(int EventCode);  /**< return which component an EventCode belongs to */
// int PAPI_get_eventset_component(int EventSet);  /**< return which component an EventSet is assigned to */
// int PAPI_get_component_index(char *name); /**< Return component index for component with matching name */
// int PAPI_disable_component(int cidx); /**< Disables a component before init */
// int PAPI_disable_component_by_name( char *name ); /**< Disable, before library init, a component by name. */
