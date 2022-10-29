"""
This module binds `PAPI High Level API
<http://icl.cs.utk.edu/projects/papi/wiki/PAPIC:PAPI.3#High_Level_Functions>`_.

Despite our desire to stay as close as possible as the original C API, we had
to make a lot of change to make this API more *pythonic*. If you are used to
the C API, please read carefully this documentation.

Example using :py:func:`flops`:

::

    from pypapi import papi_high

    # Starts counters
    papi_high.flops()  # -> Flops(0, 0, 0, 0)

    # Read values
    result = papi_high.flops()  # -> Flops(rtime, ptime, flpops, mflops)
    print(result.mflops)

    # Stop counters
    papi_high.stop_counters()   # -> []


Example counting some events:

::

    from pypapi import papi_high
    from pypapi import events as papi_events

    # Starts some counters
    papi_high.start_counters([
        papi_events.PAPI_FP_OPS,
        papi_events.PAPI_TOT_CYC
    ])

    # Reads values from counters and reset them
    results = papi_high.read_counters()  # -> [int, int]

    # Reads values from counters and stop them
    results = papi_high.stop_counters()  # -> [int, int]

"""


from ._papi import lib, ffi
from .papi_high_types import Flips, Flops, IPC, EPC
from .exceptions import papi_error


_counter_count = 0


# int PAPI_accum_counters(long long *values, int array_len);
@papi_error
def accum_counters(values):
    """accum_counters(values)

    Add current counts to the given list and reset counters.

    :param list(int) values: Values to which the counts will be added.

    :returns: A new list with added counts.
    :rtype: list(int)

    :raises PapiInvalidValueError: One or more of the arguments is invalid.
    :raises PapiSystemError: A system or C library call failed inside PAPI.
    """
    cvalues = ffi.new("long long[]", values)
    rcode = lib.PAPI_accum_counters(cvalues, len(values))
    return rcode, ffi.unpack(cvalues, len(values))


# int PAPI_num_counters(void);
def num_counters():
    """Get the number of hardware counters available on the system.

    :rtype: int

    :raises PapiInvalidValueError: ``papi.h`` is different from the version
        used to compile the PAPI library.
    :raises PapiNoMemoryError: Insufficient memory to complete the operation.
    :raises PapiSystemError: A system or C library call failed inside PAPI.
    """
    return lib.PAPI_num_counters()


# int PAPI_num_components(void);
def num_components():
    """Get the number of components available on the system.

    :rtype: int
    """
    return lib.PAPI_num_components()


# int PAPI_read_counters(long long * values, int array_len);
@papi_error
def read_counters():
    """read_counters()

    Get current counts and reset counters.

    :rtype: list(int)

    :raises PapiInvalidValueError: One or more of the arguments is invalid
        (this error should not happen with PyPAPI).
    :raises PapiSystemError: A system or C library call failed inside PAPI.
    """
    values = ffi.new("long long[]", _counter_count)
    rcode = lib.PAPI_read_counters(values, _counter_count)
    return rcode, ffi.unpack(values, _counter_count)


# int PAPI_start_counters(int *events, int array_len);
@papi_error
def start_counters(events):
    """start_counters(events)

    Start counting hardware events.

    :param list events: a list of events to count (from :doc:`events`)

    :raises PapiInvalidValueError: One or more of the arguments is invalid.
    :raises PapiIsRunningError: Counters have already been started, you must
        call :py:func:`stop_counters` before you call this function again.
    :raises PapiSystemError: A system or C library call failed inside PAPI.
    :raises PapiNoMemoryError: Insufficient memory to complete the operation.
    :raises PapiConflictError: The underlying counter hardware cannot count
        this event and other events in the EventSet simultaneously.
    :raises PapiNoEventError: The PAPI preset is not available on the
        underlying hardware.
    """
    global _counter_count
    _counter_count = len(events)

    events_ = ffi.new("int[]", events)
    array_len = len(events)

    rcode = lib.PAPI_start_counters(events_, array_len)

    return rcode, None


# int PAPI_stop_counters(long long * values, int array_len);
@papi_error
def stop_counters():
    """stop_counters()

    Stop counters and return current counts.

    :returns: the current counts (if counter started with
              :py:func:`start_counters`)
    :rtype: list

    :raises PapiInvalidValueError: One or more of the arguments is invalid
        (this error should not happen with PyPAPI).
    :raises PapiNotRunningError: The EventSet is not started yet.
    :raise PapiNoEventSetError: The EventSet has not been added yet.
    """
    global _counter_count
    array_len = _counter_count
    _counter_count = 0

    values = ffi.new("long long[]", array_len)

    rcode = lib.PAPI_stop_counters(values, array_len)

    return rcode, ffi.unpack(values, array_len)


# int PAPI_flips(float *rtime, float *ptime, long long *flpins, float *mflips);
@papi_error
def flips():
    """flips()

    Simplified call to get Mflips/s (floating point instruction rate), real
    and processor time.

    :rtype: pypapi.papi_high_types.Flips

    :raises PapiInvalidValueError: The counters were already started by
        something other than :py:func:`flips`.
    :raises PapiNoEventError: The floating point operations or total cycles
        event does not exist.
    :raises PapiNoMemoryError: Insufficient memory to complete the operation.
    """
    rtime = ffi.new("float*", 0)
    ptime = ffi.new("float*", 0)
    flpins = ffi.new("long long*", 0)
    mflips = ffi.new("float*", 0)

    rcode = lib.PAPI_flops(rtime, ptime, flpins, mflips)

    return rcode, Flips(
            ffi.unpack(rtime, 1)[0],
            ffi.unpack(ptime, 1)[0],
            ffi.unpack(flpins, 1)[0],
            ffi.unpack(mflips, 1)[0]
            )


# int PAPI_flops(float *rtime, float *ptime, long long *flpops, float *mflops);
@papi_error
def flops():
    """flops()

    Simplified call to get Mflops/s (floating point operation rate), real
    and processor time.

    :rtype: pypapi.papi_high_types.Flops

    :raises PapiInvalidValueError: The counters were already started by
        something other than :py:func:`flops`.
    :raises PapiNoEventError: The floating point instructions or total cycles
        event does not exist.
    :raises PapiNoMemoryError: Insufficient memory to complete the operation.
    """
    rtime = ffi.new("float*", 0)
    ptime = ffi.new("float*", 0)
    flpops = ffi.new("long long*", 0)
    mflops = ffi.new("float*", 0)

    rcode = lib.PAPI_flops(rtime, ptime, flpops, mflops)

    return rcode, Flops(
            ffi.unpack(rtime, 1)[0],
            ffi.unpack(ptime, 1)[0],
            ffi.unpack(flpops, 1)[0],
            ffi.unpack(mflops, 1)[0]
            )


# int PAPI_ipc(float *rtime, float *ptime, long long *ins, float *ipc);
@papi_error
def ipc():
    """ipc()

    Gets instructions per cycle, real and processor time.

    :rtype: pypapi.papi_high_types.IPC

    :raises PapiInvalidValueError: The counters were already started by
        something other than :py:func:`ipc`.
    :raises PapiNoEventError: The total instructions or total cycles event does
        not exist.
    :raises PapiNoMemoryError: Insufficient memory to complete the operation.
    """
    rtime = ffi.new("float*", 0)
    ptime = ffi.new("float*", 0)
    ins = ffi.new("long long*", 0)
    ipc_ = ffi.new("float*", 0)

    rcode = lib.PAPI_ipc(rtime, ptime, ins, ipc_)

    return rcode, IPC(
            ffi.unpack(rtime, 1)[0],
            ffi.unpack(ptime, 1)[0],
            ffi.unpack(ins, 1)[0],
            ffi.unpack(ipc_, 1)[0]
            )


# int PAPI_epc(int event, float *rtime, float *ptime, long long *ref,
#              long long *core, long long *evt, float *epc);
@papi_error
def epc(event=0):
    """epc(event=0)

    Gets (named) events per cycle, real and processor time, reference and
    core cycles.

    :param int event: The target event (from :doc:`events`, default:
        :py:const:`pypapi.events.PAPI_TOT_INS`).

    :rtype: pypapi.papi_high_types.EPC
    """
    rtime = ffi.new("float*", 0)
    ptime = ffi.new("float*", 0)
    ref = ffi.new("long long*", 0)
    core = ffi.new("long long*", 0)
    evt = ffi.new("long long*", 0)
    epc_ = ffi.new("float*", 0)

    rcode = lib.PAPI_epc(event, rtime, ptime, ref, core, evt, epc_)

    return rcode, EPC(
            ffi.unpack(rtime, 1)[0],
            ffi.unpack(ptime, 1)[0],
            ffi.unpack(ref, 1)[0],
            ffi.unpack(core, 1)[0],
            ffi.unpack(evt, 1)[0],
            ffi.unpack(epc_, 1)[0]
            )
