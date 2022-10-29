
import datetime, gc, platform, os, sys

def start_benchmarking(disable_gc):
    if disable_gc:
        gc.disable()
    return datetime.datetime.now()

def stop_benchmarking():
    end = datetime.datetime.now()
    gc.enable()
    return end

def get_config():
    # get currently loaded modules
    # https://stackoverflow.com/questions/4858100/how-to-list-imported-modules
    modulenames = set(sys.modules) & set(globals())
    allmodules = [sys.modules[name] for name in modulenames]
    return {'name': 'python',
            'version': platform.python_version(),
            'modules': str(allmodules)}
