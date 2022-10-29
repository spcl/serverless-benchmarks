"""
This module binds the PAPI Low Level API.

Despite our desire to stay as close as possible as the original C API, we had
to make a lot of change to make this API more *pythonic*. If you are used to
the C API, please read carefully this documentation.

Simple example::

    from pypapi import papi_low as papi
    from pypapi import events

    papi.library_init()

    evs = papi.create_eventset()
    papi.add_event(evs, events.PAPI_FP_OPS)

    papi.start(evs)

    # Do some computation here

    result = papi.stop(evs)
    print(result)

    papi.cleanup_eventset(evs)
    papi.destroy_eventset(evs)

.. NOTE::

    This binding is currently very partial, there is a lot of missing function.
    If you need one of the missing functions, please `fill an issue on Github
    <https://github.com/flozz/pypapi/issues>`_.
"""


from ._papi import lib, ffi
from .exceptions import papi_error, PapiError, PapiInvalidValueError
from .consts import PAPI_VER_CURRENT, PAPI_NULL


# int PAPI_accum(int EventSet, long long * values);
@papi_error
def accum(eventSet, values):
    """accum(eventSet, values)

    Adds the counters of the indicated event set into the array values. The
    counters are zeroed and continue counting after the operation.

    :param int eventSet: An integer handle for a PAPI Event Set as created by
        :py:func:`create_eventset`.
    :param list(int) values: A list to hold the counter values of the counting
        events.

    :rtype: list(int)

    :raise PapiInvalidValueError: One or more of the arguments is invalid.
    :raise PapiSystemError: A system or C library call failed inside PAPI, see
        the errno variable.
    :raise PapiNoEventSetError: The event set specified does not exist.
    """
    eventCount_p = ffi.new("int*", 0)
    rcode = lib.PAPI_list_events(eventSet, ffi.NULL, eventCount_p)

    if rcode < 0:
        return rcode, None

    eventCount = ffi.unpack(eventCount_p, 1)[0]

    if len(values) != eventCount:
        raise PapiInvalidValueError(message="the length of the 'value' list "
                                            "(%i) is different of the one of "
                                            "the event set (%i)" % (
                                                len(values),
                                                eventCount))

    values = ffi.new("long long[]", values)

    rcode = lib.PAPI_accum(eventSet, values)

    return rcode, ffi.unpack(values, eventCount)


# int PAPI_add_event(int EventSet, int Event);
@papi_error
def add_event(eventSet, eventCode):
    """add_event(eventSet, eventCode)

    Add single PAPI preset or native hardware event to an event set.

    :param int eventSet: An integer handle for a PAPI Event Set as created by
        :py:func:`create_eventset`.
    :param int eventCode: A defined event such as ``PAPI_TOT_INS`` (from
        :doc:`events`).

    :raise PapiInvalidValueError: One or more of the arguments is invalid.
    :raise PapiNoMemoryError: Insufficient memory to complete the operation.
    :raise PapiNoEventSetError: The event set specified does not exist.
    :raise PapiIsRunningError: The event set is currently counting events.
    :raise PapiConflictError: The underlying counter hardware can not count
        this event and other events in the event set simultaneously.
    :raise PapiNoEventError: The PAPI preset is not available on the underlying
        hardware.
    :raise PapiBugError: Internal error, please send mail to the developers.
    """
    rcode = lib.PAPI_add_event(eventSet, eventCode)

    if rcode > 0:
        raise PapiError(message="Unable to add some of the given events: %i of"
                        " 1 event added to the event set" % rcode)

    return rcode, None


# int PAPI_add_events(int EventSet, int *Events, int number);
@papi_error
def add_events(eventSet, eventCodes):
    """add_events(eventSet, eventCodes)

    Add list of PAPI preset or native hardware events to an event set.

    :param int eventSet: An integer handle for a PAPI Event Set as created by
        :py:func:`create_eventset`.
    :param list(int) eventCodes: A list of defined events (from :doc:`events`).

    :raise PapiInvalidValueError: One or more of the arguments is invalid.
    :raise PapiNoMemoryError: Insufficient memory to complete the operation.
    :raise PapiNoEventSetError: The event set specified does not exist.
    :raise PapiIsRunningError: The event set is currently counting events.
    :raise PapiConflictError: The underlying counter hardware can not count
        this event and other events in the event set simultaneously.
    :raise PapiNoEventError: The PAPI preset is not available on the underlying
        hardware.
    :raise PapiBugError: Internal error, please send mail to the developers.
    """
    number = len(eventCodes)
    eventCodes_p = ffi.new("int[]", eventCodes)
    rcode = lib.PAPI_add_events(eventSet, eventCodes_p, number)

    if rcode > 0:
        raise PapiError(message="Unable to add some of the given events: %i of"
                        " %i events added to the event set" % (rcode, number))

    return rcode, None


# int PAPI_attach(int EventSet, unsigned long tid);
@papi_error
def attach(eventSet, pid):
    """attach(eventSet, pid)

    Attach specified event set to a specific process or thread id.

    :param int eventSet: An integer handle for a PAPI Event Set as created by
        :py:func:`create_eventset`.
    :param int pid: A process id.

    :raise PapiComponentError: This feature is unsupported on this component.
    :raise PapiInvalidValueError: One or more of the arguments is invalid.
    :raise PapiNoEventSetError: The event set specified does not exist.
    :raise PapiIsRunningError: The event set is currently counting events.
    """
    rcode = lib.PAPI_attach(eventSet, pid)
    return rcode, None


# int PAPI_cleanup_eventset(int EventSet);
@papi_error
def cleanup_eventset(eventSet):
    """cleanup_eventset(eventSet)

    Remove all PAPI events from an event set  and turns off profiling and
    overflow for all events in the EventSet. This can not be called if the
    EventSet is not stopped.

    :param int eventSet: An integer handle for a PAPI Event Set as created by
        :py:func:`create_eventset`.

    :raise PapiInvalidValueError: One or more of the arguments is invalid.
    :raise PapiNoEventSetError: The event set specified does not exist.
    :raise PapiIsRunningError: The event set is currently counting events.
    :raise PapiBugError: Internal error, please send mail to the developers.

    .. WARNING::

        If the user has set profile on an event with the call, then when
        destroying the EventSet the memory allocated by will not be freed. The
        user should turn off profiling on the Events before destroying the
        EventSet to prevent this behavior.
    """
    rcode = lib.PAPI_cleanup_eventset(eventSet)
    return rcode, None


# int PAPI_create_eventset(int *EventSet);
@papi_error
def create_eventset():
    """create_eventset()

    Create a new empty PAPI event set. The user may then add hardware events to
    the event set by calling :py:func:`add_event` or similar routines.

    :returns: the event set handle.
    :rtype: int

    :raise PapiInvalidValueError: The argument handle has not been initialized
        to PAPI_NULL or the argument is a NULL pointer.
    :raise PapiNoMemoryError: Insufficient memory to complete the operation.

    .. NOTE::

        PAPI-C uses a late binding model to bind EventSets to components. When
        an EventSet is first created it is not bound to a component. This will
        cause some API calls that modify EventSet options to fail. An EventSet
        can be bound to a component explicitly by calling
        :py:func:`assign_eventset_component` or implicitly by calling
        :py:func:`add_event` or similar routines.
    """
    eventSet = ffi.new("int*", PAPI_NULL)
    rcode = lib.PAPI_create_eventset(eventSet)
    return rcode, ffi.unpack(eventSet, 1)[0]


# int PAPI_detach(int EventSet);
@papi_error
def detach(eventSet):
    """detach(eventSet)

    Detach specified event set from a previously specified process or
    thread id.

    :param int eventSet: An integer handle for a PAPI Event Set as created by
        :py:func:`create_eventset`.

    :raise PapiComponentError: This feature is unsupported on this component.
    :raise PapiInvalidValueError: One or more of the arguments is invalid.
    :raise PapiNoEventSetError: The event set specified does not exist.
    :raise PapiIsRunningError: The event set is currently counting events.
    """
    rcode = lib.PAPI_detach(eventSet)
    return rcode, None


# int PAPI_destroy_eventset(int *EventSet);
@papi_error
def destroy_eventset(eventSet):
    """destroy_eventset(eventSet)

    Deallocates memory associated with an empty PAPI event set.

    :param int eventSet: An integer handle for a PAPI Event Set as created by
        :py:func:`create_eventset`.

    :raise PapiInvalidValueError: One or more of the arguments is invalid.
        Attempting to destroy a non-empty event set or passing in a null
        pointer to be destroyed.
    :raise PapiNoEventSetError: The event set specified does not exist.
    :raise PapiIsRunningError: The event set is currently counting events.
    :raise PapiBugError: Internal error, please send mail to the developers.

    .. WARNING::

        If the user has set profile on an event with the call, then when
        destroying the EventSet the memory allocated by will not be freed. The
        user should turn off profiling on the Events before destroying the
        EventSet to prevent this behavior.
    """
    eventSet_p = ffi.new("int*", eventSet)
    rcode = lib.PAPI_destroy_eventset(eventSet_p)
    return rcode, None


# int PAPI_is_initialized(void);
def is_initialized():
    """is_initialized()

    Return the initialized state of the PAPI library.

    :returns: the initialized state of the PAPI library (one of the
        :ref:`consts_init`).
    :rtype: int
    """
    return lib.PAPI_is_initialized()


# int PAPI_library_init(int version);
@papi_error
def library_init(version=PAPI_VER_CURRENT):
    """library_init(version=pypapi.consts.PAPI_VER_CURRENT)

    Initialize the PAPI library.

    :param int version: upon initialization, PAPI checks the argument against
        the internal value of ``PAPI_VER_CURRENT`` when the library was
        compiled.  This guards against portability problems when updating the
        PAPI shared libraries on your system (optional, default:
        :py:data:`pypapi.consts.PAPI_VER_CURRENT`).

    :raise PapiInvalidValueError: papi.h is different from the version used to
        compile the PAPI library.
    :raise PapiNoMemoryError: Insufficient memory to complete the operation.
    :raise PapiComponentError: This component does not support the underlying
        hardware.
    :raise PapiSystemError: A system or C library call failed inside PAPI.

    .. WARNING::

            If you don't call this before using any of the low level PAPI
            calls, your application could core dump.
    """
    rcode = lib.PAPI_library_init(version)
    return rcode, None


# int PAPI_list_events(int EventSet, int *Events, int *number);
@papi_error
def list_events(eventSet):
    """list_events(eventSet)

    List the events that are members of an event set

    :param int eventSet: An integer handle for a PAPI Event Set as created by
        :py:func:`create_eventset`.

    :returns: the list of events.
    :rtype: list(int)

    :raise PapiInvalidValueError: One or more of the arguments is invalid.
    :raise PapiNoEventSetError: The event set specified does not exist.
    """
    number = ffi.new("int*", 0)

    rcode = lib.PAPI_list_events(eventSet, ffi.NULL, number)

    if rcode < 0:
        return rcode, None

    eventCount = ffi.unpack(number, 1)[0]
    events = ffi.new("int[]", eventCount)

    rcode = lib.PAPI_list_events(eventSet, events, number)

    return rcode, ffi.unpack(events, eventCount)


# int PAPI_read(int EventSet, long long * values);
@papi_error
def read(eventSet):
    """read(eventSet)

    Copies the counters of the indicated event set into the provided array. The
    counters continue counting after the read and are not reseted.

    :param int eventSet: An integer handle for a PAPI Event Set as created by
        :py:func:`create_eventset`.

    :rtype: list(int)

    :raise PapiInvalidValueError: One or more of the arguments is invalid.
    :raise PapiSystemError: A system or C library call failed inside PAPI, see
        the errno variable.
    :raise PapiNoEventSetError: The event set specified does not exist.
    """
    eventCount_p = ffi.new("int*", 0)
    rcode = lib.PAPI_list_events(eventSet, ffi.NULL, eventCount_p)

    if rcode < 0:
        return rcode, None

    eventCount = ffi.unpack(eventCount_p, 1)[0]
    values = ffi.new("long long[]", eventCount)

    rcode = lib.PAPI_read(eventSet, values)

    return rcode, ffi.unpack(values, eventCount)


# int PAPI_remove_event(int EventSet, int EventCode);
@papi_error
def remove_event(eventSet, eventCode):
    """remove_event(eventSet, eventCode)

    Remove a hardware event from a PAPI event set.

    :param int eventSet: An integer handle for a PAPI Event Set as created by
        :py:func:`create_eventset`.
    :param int eventCode: A defined event such as ``PAPI_TOT_INS`` or a native
        event. (from :doc:`events`).

    :raise PapiInvalidValueError: One or more of the arguments is invalid.
    :raise PapiNoEventSetError: The event set specified does not exist.
    :raise PapiIsRunningError: The event set is currently counting events.
    :raise PapiConflictError: The underlying counter hardware can not count
        this event and other events in the event set simultaneously.
    :raise PapiNoEventError: The PAPI preset is not available on the underlying
        hardware.
    """
    rcode = lib.PAPI_remove_event(eventSet, eventCode)
    return rcode, None


# int PAPI_remove_events(int EventSet, int *Events, int number);
@papi_error
def remove_events(eventSet, eventCodes):
    """remove_events(eventSet, eventCodes)

    Remove an list of hardware events from a PAPI event set.

    :param int eventSet: An integer handle for a PAPI Event Set as created by
        :py:func:`create_eventset`.
    :param int eventCodes: A list of defined event (from :doc:`events`).

    :raise PapiInvalidValueError: One or more of the arguments is invalid.
    :raise PapiNoEventSetError: The event set specified does not exist.
    :raise PapiIsRunningError: The event set is currently counting events.
    :raise PapiConflictError: The underlying counter hardware can not count
        this event and other events in the event set simultaneously.
    :raise PapiNoEventError: The PAPI preset is not available on the underlying
        hardware.
    """
    number = len(eventCodes)
    eventCodes_p = ffi.new("int[]", eventCodes)
    rcode = lib.PAPI_remove_events(eventSet, eventCodes_p, number)

    if rcode > 0:
        raise PapiError(message="Unable to remove some of the given events: "
                        "%i of %i events added to the event set"
                        % (rcode, number))

    return rcode, None


# int PAPI_start(int EventSet);
@papi_error
def start(eventSet):
    """start(eventSet)

    Starts counting all of the hardware events contained in the EventSet. All
    counters are implicitly set to zero before counting.

    :param int eventSet: An integer handle for a PAPI Event Set as created by
        :py:func:`create_eventset`.

    :raise PapiInvalidValueError: One or more of the arguments is invalid.
    :raise PapiSystemError: A system or C library call failed inside PAPI, see
        the errno variable.
    :raise PapiNoEventSetError: The event set specified does not exist.
    :raise PapiIsRunningError: The event set is currently counting events.
    :raise PapiConflictError: The underlying counter hardware can not count
        this event and other events in the event set simultaneously.
    :raise PapiNoEventError: The PAPI preset is not available on the underlying
        hardware.
    """
    rcode = lib.PAPI_start(eventSet)
    return rcode, None


# int PAPI_state(int EventSet, int *status);
@papi_error
def state(eventSet):
    """state(eventSet)

    Returns the counting state of the specified event set.

    :param int eventSet: An integer handle for a PAPI Event Set as created by
        :py:func:`create_eventset`.

    :returns: the initialized state of the PAPI library (one of the
        :ref:`consts_state`).
    :rtype: int

    :raise PapiInvalidValueError: One or more of the arguments is invalid.
    :raise PapiNoEventSetError: The event set specified does not exist.
    """
    status = ffi.new("int*", 0)
    rcode = lib.PAPI_state(eventSet, status)
    return rcode, ffi.unpack(status, 1)[0]


# int PAPI_stop(int EventSet, long long * values);
@papi_error
def stop(eventSet):
    """stop(eventSet)

    Stop counting hardware events in an event set and return current values.

    :param int eventSet: An integer handle for a PAPI Event Set as created by
        :py:func:`create_eventset`.

    :rtype: list(int)

    :raise PapiInvalidValueError: One or more of the arguments is invalid.
    :raise PapiSystemError: A system or C library call failed inside PAPI, see
        the errno variable.
    :raise PapiNoEventSetError: The event set specified does not exist.
    :raise PapiNotRunningError: The EventSet is currently not running.
    """
    eventCount_p = ffi.new("int*", 0)
    rcode = lib.PAPI_list_events(eventSet, ffi.NULL, eventCount_p)

    if rcode < 0:
        return rcode, None

    eventCount = ffi.unpack(eventCount_p, 1)[0]
    values = ffi.new("long long[]", eventCount)

    rcode = lib.PAPI_stop(eventSet, values)

    return rcode, ffi.unpack(values, eventCount)

@papi_error
def overflow_sampling(eventSet, event, threshold, buffer_size):

    # event count
    eventCount_p = ffi.new("int*", 0)
    rcode = lib.PAPI_list_events(eventSet, ffi.NULL, eventCount_p)
    if rcode < 0:
        return rcode, None
    eventCount = ffi.unpack(eventCount_p, 1)[0]

    lib.overflow_buffer_allocate(buffer_size, eventCount)
    rcode = lib.PAPI_overflow(eventSet, event, threshold,
            0, ffi.addressof(lib, "overflow_C_callback"))
    return rcode, None

@papi_error
def overflow_sampling_results(eventSet):

    data = []
    count = lib.overflow_buffer_count();
    if count > 0:
        buf_size = lib.overflow_buffer_size(0);
        for i in range(0, count - 1):
            data.append(ffi.unpack(lib.overflow_buffer_access(i), buf_size))
        # last buffer might not be full
        buf_size = lib.overflow_buffer_size(count - 1)
        data.append(ffi.unpack(lib.overflow_buffer_access(count - 1), buf_size))
    # clean
    lib.overflow_buffer_deallocate()
    return 0, data
