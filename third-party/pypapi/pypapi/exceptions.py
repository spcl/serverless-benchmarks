import functools

from ._papi import lib


class PapiError(Exception):
    """Base classe for PAPI exceptions."""

    c_name = None
    c_value = None

    def __init__(self, message=None):
        Exception.__init__(self, "%s (%s)" % (
            message if message else self.__doc__,
            self.c_name))


class PapiInvalidValueError(PapiError):
    """Invalid Argument."""
    c_name = "PAPI_EINVAL"
    c_value = lib.PAPI_EINVAL


class PapiNoMemoryError(PapiError):
    """Insufficient memory."""
    c_name = "PAPI_ENOMEM"
    c_value = lib.PAPI_ENOMEM


class PapiSystemError(PapiError):
    """A System/C library call failed."""
    c_name = "PAPI_ESYS"
    c_value = lib.PAPI_ESYS


class PapiComponentError(PapiError):
    """Not supported by component."""
    c_name = "PAPI_ECMP, PAPI_ESBSTR"
    c_value = lib.PAPI_ECMP


class PapiCountersLost(PapiError):
    """Access to the counters was lost or interrupted."""
    c_name = "PAPI_ECLOST"
    c_value = lib.PAPI_ECLOST


class PapiBugError(PapiError):
    """Internal error, please send mail to the developers."""
    c_name = "PAPI_EBUG"
    c_value = lib.PAPI_EBUG


class PapiNoEventError(PapiError):
    """Event does not exist."""
    c_name = "PAPI_ENOEVNT"
    c_value = lib.PAPI_ENOEVNT


class PapiConflictError(PapiError):
    """Event exists, but cannot be counted due to counter resource limitations."""  # noqa
    c_name = "PAPI_ECNFLCT"
    c_value = lib.PAPI_ECNFLCT


class PapiNotRunningError(PapiError):
    """EventSet is currently not running."""
    c_name = "PAPI_ENOTRUN"
    c_value = lib.PAPI_ENOTRUN


class PapiIsRunningError(PapiError):
    """EventSet is currently counting."""
    c_name = "PAPI_EISRUN"
    c_value = lib.PAPI_EISRUN


class PapiNoEventSetError(PapiError):
    """No such EventSet Available."""
    c_name = "PAPI_ENOEVST"
    c_value = lib.PAPI_ENOEVST


class PapiNotPresetError(PapiError):
    """Event in argument is not a valid preset."""
    c_name = "PAPI_ENOTPRESET"
    c_value = lib.PAPI_ENOTPRESET


class PapiNoCounterError(PapiError):
    """Hardware does not support performance counters."""
    c_name = "PAPI_ENOCNTR"
    c_value = lib.PAPI_ENOCNTR


class PapiMiscellaneousError(PapiError):
    """Unknown error code."""
    c_name = "PAPI_EMISC"
    c_value = lib.PAPI_EMISC


class PapiPermissionError(PapiError):
    """Permission level does not permit operation."""
    c_name = "PAPI_EPERM"
    c_value = lib.PAPI_EPERM


class PapiInitializationError(PapiError):
    """PAPI hasn't been initialized yet."""
    c_name = "PAPI_ENOINIT"
    c_value = lib.PAPI_ENOINIT


class PapiNoComponentError(PapiError):
    """Component Index isn't set."""
    c_name = "PAPI_ENOCMP"
    c_value = lib.PAPI_ENOCMP


class PapiNotSupportedError(PapiError):
    """Not supported."""
    c_name = "PAPI_ENOSUPP"
    c_value = lib.PAPI_ENOSUPP


class PapiNotImplementedError(PapiError):
    """Not implemented."""
    c_name = "PAPI_ENOIMPL"
    c_value = lib.PAPI_ENOIMPL


class PapiBufferError(PapiError):
    """Buffer size exceeded."""
    c_name = "PAPI_EBUF"
    c_value = lib.PAPI_EBUF


class PapiInvalidDomainError(PapiError):
    """EventSet domain is not supported for the operation."""
    c_name = "PAPI_EINVAL_DOM"
    c_value = lib.PAPI_EINVAL_DOM


class PapiAttributeError(PapiError):
    """Invalid or missing event attributes."""
    c_name = "PAPI_EATTR"
    c_value = lib.PAPI_EATTR


class PapiCountError(PapiError):
    """Too many events or attributes."""
    c_name = "PAPI_ECOUNT"
    c_value = lib.PAPI_ECOUNT


class PapiCombinationError(PapiError):
    """Bad combination of feature."""
    c_name = "PAPI_ECOMBO"
    c_value = lib.PAPI_ECOMBO


def papi_error(function):
    """Decorator to raise PAPI errors."""
    @functools.wraps(function)
    def papi_error_wrapper(*args, **kwargs):
        rcode, rvalue = function(*args, **kwargs)
        if rcode < 0:
            for name, object_ in globals().items():
                if object_ and hasattr(object_, "c_value") and object_.c_value == rcode:  # noqa
                    raise object_()
            raise PapiMiscellaneousError()
        return rvalue
    return papi_error_wrapper
