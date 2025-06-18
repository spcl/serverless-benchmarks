"""Environment management for experiment execution.

This module provides the ExperimentEnvironment class for managing CPU settings
and system configuration during benchmark experiments. It handles:

- CPU frequency scaling and governor management
- Hyperthreading control (enable/disable)
- CPU boost control
- Memory management (page cache dropping)
- Intel CPU-specific optimizations

Currently supports only Intel CPUs with the intel_pstate driver.

Note:
    This module assumes that all CPU cores are online at initialization.
    Future versions should use lscpu to discover online cores dynamically.
"""

from typing import Dict, List

from sebs.utils import execute


class ExperimentEnvironment:
    """Environment management for benchmark experiments.
    
    This class provides methods to control CPU settings, memory management,
    and other system configurations that can affect benchmark results.
    It focuses on creating a stable, reproducible environment for experiments.
    
    Attributes:
        _cpu_mapping: Dictionary mapping physical cores to logical cores
        _vendor: CPU vendor identifier (currently only "intel" supported)
        _governor: CPU frequency scaling governor (e.g., "intel_pstate")
        _prev_boost_status: Previous boost status for restoration
        _prev_min_freq: Previous minimum frequency setting for restoration
    """
    def __init__(self) -> None:
        """Initialize the experiment environment.
        
        Discovers CPU topology, checks vendor compatibility, and verifies
        the CPU frequency scaling driver. Currently only supports Intel CPUs
        with the intel_pstate driver.
        
        Raises:
            NotImplementedError: If CPU vendor is not Intel or scaling driver
                is not intel_pstate
        """
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

        self._cpu_mapping: Dict[int, List[Dict[str, int]]] = {}
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
            self._vendor: str = "intel"
        else:
            raise NotImplementedError()

        # Assume all CPU use the same
        scaling_governor_path = "/sys/devices/system/cpu/cpu{cpu_id}/cpufreq/scaling_driver"
        governor = execute("cat {path}".format(path=scaling_governor_path))
        if governor == "intel_pstate":
            self._governor: str = governor
        else:
            raise NotImplementedError()

    def write_cpu_status(self, cores: List[int], status: int) -> None:
        """Write CPU online status for specified cores.
        
        Args:
            cores: List of physical core IDs to modify
            status: Status to set (0 for offline, 1 for online)
        """

        cpu_status_path = "/sys/devices/system/cpu/cpu{cpu_id}/online"
        for core in cores:
            logical_cores = self._cpu_mapping[core]
            for logical_core in logical_cores[1:]:
                path = cpu_status_path.format(cpu_id=logical_core["core"])
                execute(
                    cmd="echo {status} | sudo tee {path}".format(status=status, path=path),
                    shell=True,
                )

    def disable_hyperthreading(self, cores: List[int]) -> None:
        """Disable hyperthreading for specified cores.
        
        Args:
            cores: List of physical core IDs to disable hyperthreading for
        """
        self.write_cpu_status(cores, 0)

    def enable_hyperthreading(self, cores: List[int]) -> None:
        """Enable hyperthreading for specified cores.
        
        Args:
            cores: List of physical core IDs to enable hyperthreading for
        """
        self.write_cpu_status(cores, 1)

    def disable_boost(self, cores: List[int]) -> None:
        """Disable CPU boost (turbo) for specified cores.
        
        Args:
            cores: List of physical core IDs to disable boost for
            
        Raises:
            NotImplementedError: If CPU governor is not intel_pstate
        """
        if self._governor == "intel_pstate":
            boost_path = "/sys/devices/system/cpu/intel_pstate"
            self._prev_boost_status = execute("cat " + boost_path)
            execute("echo 0 | sudo tee {path}".format(path=boost_path))
        else:
            raise NotImplementedError()

    def enable_boost(self, cores: List[int]) -> None:
        """Enable CPU boost (turbo) for specified cores.
        
        Restores the previous boost status that was saved when boost was disabled.
        
        Args:
            cores: List of physical core IDs to enable boost for
            
        Raises:
            NotImplementedError: If CPU governor is not intel_pstate
        """
        if self._governor == "intel_pstate":
            boost_path = "/sys/devices/system/cpu/intel_pstate"
            execute(
                "echo {status} | sudo tee {path}".format(
                    status=self._prev_boost_status, path=boost_path
                )
            )
        else:
            raise NotImplementedError()

    def drop_page_cache(self) -> None:
        """Drop system page cache to ensure clean memory state.
        
        This method clears the page cache to prevent cached data from
        affecting benchmark measurements.
        """
        execute("echo 3 | sudo tee /proc/sys/vm/drop_caches")

    def set_frequency(self, max_freq: int) -> None:
        """Set minimum CPU frequency percentage.
        
        Args:
            max_freq: Minimum frequency percentage (0-100)
        """
        path = "/sys/devices/system/cpu/intel_pstate/min_perf_pct"
        self._prev_min_freq = execute("cat " + path)
        execute("echo {freq} | sudo tee {path}".format(freq=max_freq, path=path))

    def unset_frequency(self) -> None:
        """Restore previous minimum CPU frequency setting.
        
        Restores the frequency setting that was saved when set_frequency
        was called.
        """
        path = "/sys/devices/system/cpu/intel_pstate/min_perf_pct"
        execute("echo {freq} | sudo tee {path}".format(freq=self._prev_min_freq, path=path))

    def setup_benchmarking(self, cores: List[int]) -> None:
        """Set up the environment for stable benchmarking.
        
        This method applies a standard set of optimizations to create
        a stable environment for benchmarking:
        - Disables CPU boost/turbo
        - Disables hyperthreading
        - Sets CPU frequency to maximum
        - Drops page cache
        
        Args:
            cores: List of physical core IDs to configure
        """
        self.disable_boost(cores)
        self.disable_hyperthreading(cores)
        self.set_frequency(100)
        self.drop_page_cache()

    def after_benchmarking(self, cores: List[int]) -> None:
        """Restore environment settings after benchmarking.
        
        This method restores the system to its previous state after
        benchmarking is complete:
        - Re-enables CPU boost/turbo
        - Re-enables hyperthreading
        - Restores frequency settings
        
        Args:
            cores: List of physical core IDs to restore
        """
        self.enable_boost(cores)
        self.enable_hyperthreading(cores)
        self.unset_frequency()
