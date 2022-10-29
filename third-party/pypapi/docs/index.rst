Welcome to PyPAPI's documentation!
==================================

PyPAPI is a Python binding for the PAPI (Performance Application Programming
Interface) library. PyPAPI implements the whole PAPI High Level API and
partially the Low Level API.

Example usage:
--------------

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


.. toctree::
   :maxdepth: 2
   :caption: Contents:

   install
   papi_high
   papi_low
   types
   events
   consts
   exceptions
   licenses

* :ref:`genindex`
* :ref:`modindex`

* `Github <https://github.com/flozz/pypapi>`_
