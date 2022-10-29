from collections import namedtuple


#: Results tuple for the :py:func:`~pypapi.papi_high.flips` function
#: See PAPI documentation for more informations:
#:
#: * http://icl.cs.utk.edu/projects/papi/wiki/PAPIC:PAPI_flops.3#Arguments
Flips = namedtuple("Flips", "rtime ptime flpins mflips")


#: Results tuple for the :py:func:`~pypapi.papi_high.flops` function
#: See PAPI documentation for more informations:
#:
#: * http://icl.cs.utk.edu/projects/papi/wiki/PAPIC:PAPI_flops.3#Arguments
Flops = namedtuple("Flops", "rtime ptime flpops mflops")


#: Results tuple for the :py:func:`~pypapi.papi_high.ipc` function
#: See PAPI documentation for more informations:
#:
#: * http://icl.cs.utk.edu/projects/papi/wiki/PAPIC:PAPI_ipc.3#Arguments
IPC = namedtuple("IPC", "rtime ptime ins ipc")


#: Results tuple for the :py:func:`~pypapi.papi_high.epc` function
#: See PAPI documentation for more informations:
#:
#: * http://icl.cs.utk.edu/papi/docs/da/d4e/classPAPI__epc.html
EPC = namedtuple("EPC", "rtime ptime ref core evt epc")
