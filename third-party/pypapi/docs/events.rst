Events
======


Bellow the list of all events supported by PAPI. They can be used with the
:py:func:`~pypapi.papi.start_counters` function:

::

    from pypapi import papi_high
    from pypapi import events as papi_events

    papi_high.start_counters([
        papi_events.PAPI_FP_OPS,
        papi_events.PAPI_TOT_CYC
    ])


Event List
----------

.. automodule:: pypapi.events
    :members:
