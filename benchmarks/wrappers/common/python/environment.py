# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""
Passive, best-effort introspection of the function's execution environment.

The static record (runtime, OS, CPU, limits, virtualization hints)
is collected on the first invocation in a process. Later invocations
return only the kernel boot id.

Only reads local files and process state. A failing probe in the static record
leaves its value as None and records the reason in the record's `unavailable`
map. An unreadable boot id is None.
"""

import os
import platform
import sys
import threading
import time

# Lambda runtime identifier, and how the sandbox was started (on-demand,
# provisioned-concurrency, or snap-start).
ENV_ALLOWLIST = [
    "AWS_EXECUTION_ENV",
    "AWS_LAMBDA_INITIALIZATION_TYPE",
]

_collected = False
# Handlers may run concurrently in threads (e.g., GCP, Azure); only one gets the record.
_lock = threading.Lock()


def _read(path):
    with open(path) as f:
        return f.read().strip()


def _first_existing(*paths):
    for path in paths:
        if os.path.exists(path):
            return _read(path)
    raise FileNotFoundError(paths[0])


def _cgroup_limit(name, v1_path):
    # cgroup v2 limits live in the process's own cgroup, given as "0::<path>".
    own = ''
    for line in _read('/proc/self/cgroup').splitlines():
        if line.startswith('0::'):
            own = line[3:].lstrip('/')
    return _first_existing(
        os.path.join('/sys/fs/cgroup', own, name), os.path.join('/sys/fs/cgroup', name), v1_path
    )


def _cpuinfo():
    fields = {}
    for line in _read('/proc/cpuinfo').splitlines():
        key, _, value = line.partition(':')
        fields.setdefault(key.strip(), value.strip())
    flags = fields.get('flags') or fields.get('Features') or ''
    return {
        'model': fields.get('model name') or fields.get('CPU part'),
        'count': os.cpu_count(),
        'flags': flags.split(),
    }


def _meminfo_total_kb():
    for line in _read('/proc/meminfo').splitlines():
        if line.startswith('MemTotal:'):
            return int(line.split()[1])
    raise KeyError('MemTotal')


def _os_release():
    fields = dict(
        line.split('=', 1) for line in _read('/etc/os-release').splitlines() if '=' in line
    )
    return {key: fields[key].strip('"') for key in ('ID', 'VERSION_ID', 'PRETTY_NAME') if key in fields}


def _static():
    unavailable = {}

    def probe(key, fn):
        try:
            return fn()
        except Exception as e:
            unavailable[key] = f"{type(e).__name__}: {e}"
            return None

    uname = platform.uname()
    return {
        'runtime': {
            'name': platform.python_implementation(),
            'version': platform.python_version(),
            'executable': sys.executable,
        },
        'os': {
            'system': uname.system,
            'release': uname.release,
            'version': uname.version,
            'machine': uname.machine,
            'release_info': probe('os.release_info', _os_release),
        },
        'cpu': probe('cpu', _cpuinfo),
        'memory_total_kb': probe('memory_total_kb', _meminfo_total_kb),
        'cgroup': {
            'cpu_max': probe('cgroup.cpu_max', lambda: _cgroup_limit(
                'cpu.max', '/sys/fs/cgroup/cpu/cpu.cfs_quota_us')),
            'memory_max': probe('cgroup.memory_max', lambda: _cgroup_limit(
                'memory.max', '/sys/fs/cgroup/memory/memory.limit_in_bytes')),
        },
        'virtualization': {
            'dmi_sys_vendor': probe('virtualization.dmi_sys_vendor',
                                    lambda: _read('/sys/class/dmi/id/sys_vendor')),
            'dmi_product_name': probe('virtualization.dmi_product_name',
                                      lambda: _read('/sys/class/dmi/id/product_name')),
            'proc_version': probe('virtualization.proc_version', lambda: _read('/proc/version')),
            'kernel_cmdline': probe('virtualization.kernel_cmdline', lambda: _read('/proc/cmdline')),
        },
        'env': {key: os.environ[key] for key in ENV_ALLOWLIST if key in os.environ},
        'unavailable': unavailable,
    }


def collect():
    """
    Environment record for the invocation response.

    Returns the full static record on the first call in this process, otherwise
    only the boot id, so a record with `static` marks a cold start.
    Call it once the benchmark timing has stopped.
    """
    global _collected
    try:
        boot_id = _read('/proc/sys/kernel/random/boot_id')
    except Exception:
        boot_id = None

    with _lock:
        first, _collected = not _collected, True
    if not first:
        return {'boot_id': boot_id}

    begin = time.perf_counter()
    static = _static()
    return {
        'boot_id': boot_id,
        'probe_us': int((time.perf_counter() - begin) * 1e6),
        'static': static,
    }
