# https://stackoverflow.com/questions/3232943/update-value-of-a-nested-dictionary-of-varying-depth
import collections.abc
import datetime
import json
import logging
import os
import shutil
from typing import Dict


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

    cache_dir: str = ""
    cached_config: Dict[str, str] = {}
    """
        Indicate that cloud offerings updated credentials or settings.
        Thus we have to write down changes.
    """
    config_updated = False

    def __init__(self, cache_dir):
        self.cache_dir = os.path.abspath(cache_dir)
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir, exist_ok=True)
        else:
            self.load_config()

    def load_config(self):
        for cloud in ["azure", "aws"]:
            cloud_config_file = os.path.join(self.cache_dir, "{}.json".format(cloud))
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
        update_dict(self.cached_config, val, keys)
        self.config_updated = True

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
        Acccess cached version of a function.

        :param deployment: allowed deployment clouds or local
        :param benchmark:
        :param  language:

        :return: a tuple of JSON config and absolute path to code or None
    """

    def get_function(self, deployment: str, benchmark: str, language: str):
        cfg = self.get_benchmark_config(deployment, benchmark)
        if cfg and language in cfg:
            return (cfg[language], os.path.join(self.cache_dir, cfg[language]["code"]))
        else:
            return (None, None)

    """
        Acccess cached storage config of a benchmark.

        :param deployment: allowed deployment clouds or local
        :param benchmark:

        :return: a JSON config or None
    """

    def get_storage_config(self, deployment: str, benchmark: str):
        cfg = self.get_benchmark_config(deployment, benchmark)
        return cfg["storage"] if cfg else None

    def update_storage(self, deployment: str, benchmark: str, config: dict):
        benchmark_dir = os.path.join(self.cache_dir, benchmark)
        with open(os.path.join(benchmark_dir, "config.json"), "r") as fp:
            cached_config = json.load(fp)
        cached_config[deployment]["storage"] = config
        with open(os.path.join(benchmark_dir, "config.json"), "w") as fp:
            json.dump(cached_config, fp, indent=2)

    """
        Update stored function code and configuration.
        Replaces entire config for specified deployment

        :param deployment:
        :param benchmark:
        :param language:
        :param code_package:
        :param config: Updated config values to use.
    """

    def update_function(
        self,
        deployment: str,
        benchmark: str,
        language: str,
        code_package: str,
        config: dict,
    ):

        benchmark_dir = os.path.join(self.cache_dir, benchmark)
        cached_dir = os.path.join(benchmark_dir, deployment, language)
        # copy code
        if os.path.isdir(code_package):
            dest = os.path.join(cached_dir, "code")
            shutil.rmtree(dest)
            shutil.copytree(code_package, dest)
        # copy zip file
        else:
            shutil.copy2(code_package, cached_dir)
        # update JSON config
        with open(os.path.join(benchmark_dir, "config.json"), "r") as fp:
            cached_config = json.load(fp)
        date = str(datetime.datetime.now())
        cached_config[deployment][language] = config
        cached_config[deployment][language]["date"]["modified"] = date
        with open(os.path.join(benchmark_dir, "config.json"), "w") as fp:
            json.dump(cached_config, fp, indent=2)

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
        deployment,
        benchmark,
        language,
        code_package,
        language_config,
        storage_config,
    ):

        benchmark_dir = os.path.join(self.cache_dir, benchmark)
        os.makedirs(benchmark_dir, exist_ok=True)

        # Check if cache directory for this deployment exist
        cached_dir = os.path.join(benchmark_dir, deployment, language)
        if not os.path.exists(cached_dir):
            os.makedirs(cached_dir, exist_ok=True)

            # copy code
            if os.path.isdir(code_package):
                cached_location = os.path.join(cached_dir, "code")
                shutil.copytree(code_package, cached_location)
            # copy zip file
            else:
                package_name = os.path.basename(code_package)
                cached_location = os.path.join(cached_dir, package_name)
                shutil.copy2(code_package, cached_dir)

            config = {
                deployment: {language: language_config, "storage": storage_config}
            }

            # don't store absolute path to avoid problems with moving cache dir
            relative_cached_loc = os.path.relpath(cached_location, self.cache_dir)
            config[deployment][language]["code"] = relative_cached_loc
            date = str(datetime.datetime.now())
            config[deployment][language]["date"] = {"created": date, "modified": date}
            # make sure to not replace other entries
            if os.path.exists(os.path.join(benchmark_dir, "config.json")):
                with open(os.path.join(benchmark_dir, "config.json"), "r") as fp:
                    cached_config = json.load(fp)
                    if deployment in cached_config:
                        cached_config[deployment][language] = language_config
                    else:
                        cached_config[deployment] = {
                            language: language_config,
                            "storage": storage_config,
                        }
                    config = cached_config
            with open(os.path.join(benchmark_dir, "config.json"), "w") as fp:
                json.dump(config, fp, indent=2)

        else:
            # TODO: update
            raise RuntimeError(
                "Cached application {} for {} already exists!".format(
                    benchmark, deployment
                )
            )
