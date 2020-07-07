# https://stackoverflow.com/questions/3232943/update-value-of-a-nested-dictionary-of-varying-depth
import collections.abc
import datetime
import json
import logging
import os
import shutil
import threading
from typing import Any, Dict, List, Optional, TYPE_CHECKING  # noqa

if TYPE_CHECKING:
    from sebs.benchmark import Benchmark
    from sebs.faas.function import Function


def update(d, u):
    for k, v in u.items():
        if isinstance(v, collections.abc.Mapping):
            d[k] = update(d.get(k, {}), v)
        else:
            d[k] = v
    return d


def update_dict(cfg, val, keys):
    def map_keys(obj, val, keys):
        if len(keys):
            return {keys[0]: map_keys(obj, val, keys[1:])}
        else:
            return val

    update(cfg, map_keys(cfg, val, keys))


class Cache:

    cached_config: Dict[str, str] = {}
    """
        Indicate that cloud offerings updated credentials or settings.
        Thus we have to write down changes.
    """
    config_updated = False

    def __init__(self, cache_dir: str):
        self.cache_dir = os.path.abspath(cache_dir)
        self._lock = threading.RLock()
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir, exist_ok=True)
        else:
            self.load_config()

    def load_config(self):
        with self._lock:
            for cloud in ["azure", "aws"]:
                cloud_config_file = os.path.join(
                    self.cache_dir, "{}.json".format(cloud)
                )
                if os.path.exists(cloud_config_file):
                    self.cached_config[cloud] = json.load(open(cloud_config_file, "r"))

    def get_config(self, cloud):
        return self.cached_config[cloud] if cloud in self.cached_config else None

    """
        Update config values. Sets flag to save updated content in the end.
        val: new value to store
        keys: array of consecutive keys for multi-level dictionary
    """

    def update_config(self, val, keys):
        with self._lock:
            update_dict(self.cached_config, val, keys)
        self.config_updated = True

    def lock(self):
        self._lock.acquire()

    def unlock(self):
        self._lock.release()

    def shutdown(self):
        if self.config_updated:
            for cloud in ["azure", "aws"]:
                if cloud in self.cached_config:
                    cloud_config_file = os.path.join(
                        self.cache_dir, "{}.json".format(cloud)
                    )
                    logging.info("Update cached config {}".format(cloud_config_file))
                    with open(cloud_config_file, "w") as out:
                        json.dump(self.cached_config[cloud], out, indent=2)

    """
        Acccess cached config of a benchmark.

        :param deployment: allowed deployment clouds or local
        :param benchmark:
        :param  language:

        :return: a JSON config or None when not exists
    """

    def get_benchmark_config(self, deployment: str, benchmark: str):
        benchmark_dir = os.path.join(self.cache_dir, benchmark)
        if os.path.exists(benchmark_dir):
            with open(os.path.join(benchmark_dir, "config.json"), "r") as fp:
                cfg = json.load(fp)
                return cfg[deployment] if deployment in cfg else None

    """
        Acccess cached version of benchmark code.

        :param deployment: allowed deployment clouds or local
        :param benchmark:
        :param  language:

        :return: a tuple of JSON config and absolute path to code or None
    """

    def get_code_package(
        self, deployment: str, benchmark: str, language: str
    ) -> Optional[Dict[str, Any]]:
        cfg = self.get_benchmark_config(deployment, benchmark)
        if cfg and language in cfg:
            return cfg[language]["code_package"]
        else:
            return None

    def get_functions(
        self, deployment: str, benchmark: str, language: str
    ) -> Optional[Dict[str, Any]]:
        cfg = self.get_benchmark_config(deployment, benchmark)
        if cfg and language in cfg:
            return cfg[language]["functions"]
        else:
            return None

    """
        Acccess cached storage config of a benchmark.

        :param deployment: allowed deployment clouds or local
        :param benchmark:

        :return: a JSON config or None
    """

    def get_storage_config(self, deployment: str, benchmark: str):
        cfg = self.get_benchmark_config(deployment, benchmark)
        return cfg["storage"] if cfg and "storage" in cfg else None

    def update_storage(self, deployment: str, benchmark: str, config: dict):
        benchmark_dir = os.path.join(self.cache_dir, benchmark)
        with self._lock:
            with open(os.path.join(benchmark_dir, "config.json"), "r") as fp:
                cached_config = json.load(fp)
            cached_config[deployment]["storage"] = config
            with open(os.path.join(benchmark_dir, "config.json"), "w") as fp:
                json.dump(cached_config, fp, indent=2)

    def add_code_package(
        self, deployment_name: str, language_name: str, code_package: "Benchmark"
    ):
        with self._lock:
            language = code_package.language_name
            benchmark_dir = os.path.join(self.cache_dir, code_package.benchmark)
            os.makedirs(benchmark_dir, exist_ok=True)
            # Check if cache directory for this deployment exist
            cached_dir = os.path.join(benchmark_dir, deployment_name, language)
            if not os.path.exists(cached_dir):
                os.makedirs(cached_dir, exist_ok=True)

                # copy code
                if os.path.isdir(code_package.code_location):
                    cached_location = os.path.join(cached_dir, "code")
                    shutil.copytree(code_package.code_location, cached_location)
                # copy zip file
                else:
                    package_name = os.path.basename(code_package.code_location)
                    cached_location = os.path.join(cached_dir, package_name)
                    shutil.copy2(code_package.code_location, cached_dir)
                language_config: Dict[str, Any] = {
                    "code_package": code_package.serialize(),
                    "functions": {},
                }
                # don't store absolute path to avoid problems with moving cache dir
                relative_cached_loc = os.path.relpath(cached_location, self.cache_dir)
                language_config["code_package"]["location"] = relative_cached_loc
                date = str(datetime.datetime.now())
                language_config["code_package"]["date"] = {
                    "created": date,
                    "modified": date,
                }
                config = {deployment_name: {language: language_config}}
                # make sure to not replace other entries
                if os.path.exists(os.path.join(benchmark_dir, "config.json")):
                    with open(os.path.join(benchmark_dir, "config.json"), "r") as fp:
                        cached_config = json.load(fp)
                        if deployment_name in cached_config:
                            cached_config[deployment_name][language] = language_config
                        else:
                            cached_config[deployment_name] = {
                                language: language_config,
                            }
                        config = cached_config
                with open(os.path.join(benchmark_dir, "config.json"), "w") as fp:
                    json.dump(config, fp, indent=2)
            else:
                # TODO: update
                raise RuntimeError(
                    "Cached application {} for {} already exists!".format(
                        code_package.benchmark, deployment_name
                    )
                )

    def update_code_package(
        self, deployment_name: str, language_name: str, code_package: "Benchmark"
    ):
        with self._lock:
            language = code_package.language_name
            benchmark_dir = os.path.join(self.cache_dir, code_package.benchmark)
            # Check if cache directory for this deployment exist
            cached_dir = os.path.join(benchmark_dir, deployment_name, language)
            if os.path.exists(cached_dir):

                # copy code
                if os.path.isdir(code_package.code_location):
                    cached_location = os.path.join(cached_dir, "code")
                    shutil.copytree(code_package.code_location, cached_location)
                # copy zip file
                else:
                    package_name = os.path.basename(code_package.code_location)
                    cached_location = os.path.join(cached_dir, package_name)
                    shutil.copy2(code_package.code_location, cached_dir)

                with open(os.path.join(benchmark_dir, "config.json"), "r") as fp:
                    config = json.load(fp)
                    date = str(datetime.datetime.now())
                    config[deployment_name][language]["code_package"]["date"][
                        "modified"
                    ] = date
                    config[deployment_name][language]["code_package"][
                        "hash"
                    ] = code_package.hash
                with open(os.path.join(benchmark_dir, "config.json"), "w") as fp:
                    json.dump(config, fp, indent=2)
            else:
                self.add_code_package(deployment_name, language_name, code_package)

    """
        Add new function to cache.

        :param deployment:
        :param benchmark:
        :param language:
        :param code_package: Path to directory/ZIP with code.
        :param language_config: Configuration of language and code.
        :param storage_config: Configuration of storage buckets.
    """

    def add_function(
        self,
        deployment_name: str,
        language_name: str,
        code_package: "Benchmark",
        function: "Function",
    ):
        with self._lock:
            benchmark_dir = os.path.join(self.cache_dir, code_package.benchmark)
            language = code_package.language_name
            cache_config = os.path.join(benchmark_dir, "config.json")

            if os.path.exists(cache_config):
                functions_config: Dict[str, Any] = {
                    function.name: {
                        **function.serialize(),
                        "code_version": code_package.hash,
                    }
                }

                with open(cache_config, "r") as fp:
                    cached_config = json.load(fp)
                    if "functions" not in cached_config[deployment_name][language]:
                        cached_config[deployment_name][language][
                            "functions"
                        ] = functions_config
                    else:
                        cached_config[deployment_name][language]["functions"].update(
                            functions_config
                        )
                    config = cached_config
                with open(cache_config, "w") as fp:
                    json.dump(config, fp, indent=2)
            else:
                raise RuntimeError(
                    "Can't cache function {} for a non-existing code package!".format(
                        function.name
                    )
                )
