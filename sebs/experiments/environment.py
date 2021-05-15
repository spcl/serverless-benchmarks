from typing import List

from sebs.utils import execute

"""
    Assumes that all cores are online in the beginning.
    TODO: use lscpu to discover online cores

    Currently supports only Intel CPUs with intel_pstate driver.
"""


class ExperimentEnvironment:
    def __init__(self):
        # find CPU mapping
        ret = execute('cat /proc/cpuinfo | grep -e "processor" -e "core id"', shell=True)
        # skip empty line at the end
        mapping = [int(x.split(":")[1]) for x in ret.split("\n") if x]

        number_of_cores = int(len(mapping) / 2)
        cpu_status_path = "/sys/devices/system/cpu/cpu{cpu_id}/online"
        # read status of each cpu
        # let's assume cpu0 does not have a corresponding online file
        # on some systems it's impossible to disable it
        # https://lwn.net/Articles/475018/
        cpus_status = [1] + [
            int(open(cpu_status_path.format(cpu_id=cpu_id), "r").read())
            for cpu_id in range(1, number_of_cores)
        ]

        self._cpu_mapping = {}
        # iterate over every two elements i na list
        for logical_core, physical_core in zip(*[iter(mapping)] * 2):
            core_description = {
                "core": logical_core,
                "online": cpus_status[logical_core],
            }
            if physical_core in self._cpu_mapping:
                self._cpu_mapping[physical_core].append(core_description)
            else:
                self._cpu_mapping[physical_core] = [core_description]

        vendor = execute('lscpu | grep -e "Vendor ID"', shell=True).split(";")[1]
        if vendor == "GenuineIntel":
            self._vendor = "intel"
        else:
            raise NotImplementedError()

        # Assume all CPU use the same
        scaling_governor_path = "/sys/devices/system/cpu/cpu{cpu_id}/cpufreq/scaling_driver"
        governor = execute("cat {path}".format(path=scaling_governor_path))
        if governor == "intel_pstate":
            self._governor = governor
        else:
            raise NotImplementedError()

    def write_cpu_status(self, cores: List[int], status: int):

        cpu_status_path = "/sys/devices/system/cpu/cpu{cpu_id}/online"
        for core in cores:
            logical_cores = self._cpu_mapping[core]
            for logical_core in logical_cores[1:]:
                path = cpu_status_path.format(cpu_id=logical_core["core"])
                execute(
                    cmd="echo {status} | sudo tee {path}".format(status=status, path=path),
                    shell=True,
                )

    def disable_hyperthreading(self, cores: List[int]):
        self.write_cpu_status(cores, 0)

    def enable_hyperthreading(self, cores: List[int]):
        self.write_cpu_status(cores, 1)

    def disable_boost(self, cores: List[int]):
        if self._governor == "intel_pstate":
            boost_path = "/sys/devices/system/cpu/intel_pstate"
            self._prev_boost_status = execute("cat " + boost_path)
            execute("echo 0 | sudo tee {path}".format(path=boost_path))
        else:
            raise NotImplementedError()

    def enable_boost(self, cores: List[int]):
        if self._governor == "intel_pstate":
            boost_path = "/sys/devices/system/cpu/intel_pstate"
            execute(
                "echo {status} | sudo tee {path}".format(
                    status=self._prev_boost_status, path=boost_path
                )
            )
        else:
            raise NotImplementedError()

    def drop_page_cache(self):
        execute("echo 3 | sudo tee /proc/sys/vm/drop_caches")

    def set_frequency(self, max_freq: int):
        path = "/sys/devices/system/cpu/intel_pstate/min_perf_pct"
        self._prev_min_freq = execute("cat " + path)
        execute("echo {freq} | sudo tee {path}".format(freq=max_freq, path=path))

    def unset_frequency(self):
        path = "/sys/devices/system/cpu/intel_pstate/min_perf_pct"
        execute("echo {freq} | sudo tee {path}".format(freq=self._prev_min_freq, path=path))

    def setup_benchmarking(self, cores: List[int]):
        self.disable_boost(cores)
        self.disable_hyperthreading(cores)
        self.set_frequency(100)
        self.drop_page_cache()

    def after_benchmarking(self, cores: List[int]):
        self.enable_boost(cores)
        self.enable_hyperthreading(cores)
        self.unset_frequency()
