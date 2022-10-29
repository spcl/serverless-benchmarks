"""
Some constants used by PAPI.

.. NOTE::

    Event contants are located in an other file, see :doc:events
"""


from ._papi import lib


# Version

def _papi_version_number(maj, min_, rev, inc):
    return maj << 24 | min_ << 16 | rev << 8 | inc


#: PAPI version, as used internaly
PAPI_VERSION = _papi_version_number(5, 5, 1, 0)

#: PAPI version, without the revision and increment part
PAPI_VER_CURRENT = PAPI_VERSION & 0xFFFF0000


# PAPI Initialization

#: PAPI is not initilized
PAPI_NOT_INITED = lib.PAPI_NOT_INITED

#: Low level has called library init
PAPI_LOW_LEVEL_INITED = lib.PAPI_LOW_LEVEL_INITED

#: High level has called library init
PAPI_HIGH_LEVEL_INITED = lib.PAPI_HIGH_LEVEL_INITED

#: Threads have been inited
PAPI_THREAD_LEVEL_INITED = lib.PAPI_THREAD_LEVEL_INITED


# PAPI State

#: EventSet stopped
PAPI_STOPPED = lib.PAPI_STOPPED

#: EventSet running
PAPI_RUNNING = lib.PAPI_RUNNING

#: EventSet temp. disabled by the library
PAPI_PAUSED = lib.PAPI_PAUSED

#: EventSet defined, but not initialized
PAPI_NOT_INIT = lib.PAPI_NOT_INIT

#: EventSet has overflowing enabled
PAPI_OVERFLOWING = lib.PAPI_OVERFLOWING

#: EventSet has profiling enabled
PAPI_PROFILING = lib.PAPI_PROFILING

#: EventSet has multiplexing enabled
PAPI_MULTIPLEXING = lib.PAPI_MULTIPLEXING

#: EventSet is attached to another thread/process
PAPI_ATTACHED = lib.PAPI_ATTACHED

#: EventSet is attached to a specific cpu (not counting thread of execution)
PAPI_CPU_ATTACHED = lib.PAPI_CPU_ATTACHED


# Others

#: A nonexistent hardware event used as a placeholder
PAPI_NULL = lib.PAPI_NULL
