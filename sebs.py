#!/usr/bin/env python3


import json
import logging
import functools
import os
import traceback
from typing import cast, List, Optional

import click

import sebs
from sebs import SeBS
from sebs.types import Storage as StorageTypes
from sebs.types import NoSQLStorage as NoSQLStorageTypes
from sebs.regression import regression_suite
from sebs.utils import update_nested_dict, append_nested_dict, catch_interrupt
from sebs.faas import System as FaaSSystem
from sebs.faas.function import Trigger

PROJECT_DIR = os.path.dirname(os.path.realpath(__file__))

deployment_client: Optional[FaaSSystem] = None
sebs_client: Optional[SeBS] = None


class ExceptionProcesser(click.Group):
    def __call__(self, *args, **kwargs):
        try:
            return self.main(*args, **kwargs)
        except Exception as e:
            logging.error(e)
            traceback.print_exc()
            logging.info("# Experiments failed! See out.log for details")
        finally:
            # Close
            if deployment_client is not None:
                deployment_client.shutdown()
            if sebs_client is not None:
                sebs_client.shutdown()


def simplified_common_params(func):
    @click.option(
        "--config",
        required=True,
        type=click.Path(readable=True),
        help="Location of experiment config.",
    )
    @click.option("--output-dir", default=os.path.curdir, help="Output directory for results.")
    @click.option("--output-file", default="out.log", help="Output filename for logging.")
    @click.option(
        "--cache",
        default=os.path.join(os.path.curdir, "cache"),
        help="Location of experiments cache.",
    )
    @click.option("--verbose/--no-verbose", default=False, help="Verbose output.")
    @click.option(
        "--preserve-out/--no-preserve-out",
        default=True,
        help="Preserve current results in output directory.",
    )
    @click.option(
        "--language",
        default=None,
        type=click.Choice(["python", "nodejs"]),
        help="Benchmark language",
    )
    @click.option("--language-version", default=None, type=str, help="Benchmark language version")
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


def common_params(func):
    @click.option(
        "--update-code/--no-update-code",
        default=False,
        help="Update function code in cache and cloud deployment.",
    )
    @click.option(
        "--update-storage/--no-update-storage",
        default=False,
        help="Update benchmark storage files in cloud deployment.",
    )
    @click.option(
        "--deployment",
        default=None,
        type=click.Choice(["azure", "aws", "gcp", "local", "openwhisk"]),
        help="Cloud deployment to use.",
    )
    @click.option(
        "--architecture",
        default=None,
        type=click.Choice(["x64", "arm64"]),
        help="Target architecture",
    )
    @click.option(
        "--container-deployment/--no-container-deployment",
        default=False,
        help="Deploy functions as containers (AWS only). When enabled, functions are packaged as container images and pushed to Amazon ECR."
    )
    @click.option(
        "--resource-prefix",
        default=None,
        type=str,
        help="Resource prefix to look for.",
    )

    @simplified_common_params
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


def parse_common_params(
    config,
    output_dir,
    output_file,
    cache,
    verbose,
    preserve_out,
    update_code,
    update_storage,
    deployment,
    language,
    language_version,
    architecture,
    container_deployment,
    resource_prefix: Optional[str] = None,
    initialize_deployment: bool = True,
    ignore_cache: bool = False,
    storage_configuration: Optional[List[str]] = None
):

    global sebs_client, deployment_client
    config_obj = json.load(open(config, "r"))
    os.makedirs(output_dir, exist_ok=True)
    logging_filename = os.path.abspath(os.path.join(output_dir, output_file))

    sebs_client = sebs.SeBS(cache, output_dir, verbose, logging_filename)
    output_dir = sebs.utils.create_output(output_dir, preserve_out, verbose)

    sebs_client.logging.info("Created experiment output at {}".format(output_dir))

    # CLI overrides JSON options
    update_nested_dict(config_obj, ["experiments", "runtime", "language"], language)
    update_nested_dict(config_obj, ["experiments", "runtime", "version"], language_version)
    update_nested_dict(config_obj, ["deployment", "name"], deployment)
    update_nested_dict(config_obj, ["experiments", "update_code"], update_code)
    update_nested_dict(config_obj, ["experiments", "update_storage"], update_storage)
    update_nested_dict(config_obj, ["experiments", "architecture"], architecture)
    update_nested_dict(config_obj, ["experiments", "container_deployment"], container_deployment)

    # set the path the configuration was loaded from
    update_nested_dict(config_obj, ["deployment", "local", "path"], config)

    if storage_configuration is not None:

        for cfg_f in storage_configuration:
            sebs_client.logging.info(f"Loading storage configuration from {cfg_f}")

            cfg = json.load(open(cfg_f, 'r'))
            append_nested_dict(config_obj, ["deployment", deployment, "storage"], cfg)

    if initialize_deployment:
        deployment_client = sebs_client.get_deployment(
            config_obj, logging_filename=logging_filename
        )
        deployment_client.initialize(resource_prefix=resource_prefix)
    else:
        deployment_client = None

    if ignore_cache:
        sebs_client.ignore_cache()

    catch_interrupt()

    return config_obj, output_dir, logging_filename, sebs_client, deployment_client


@click.group(cls=ExceptionProcesser)
def cli():
    pass


@cli.group()
def benchmark():
    pass


@benchmark.command()
@click.argument("benchmark", type=str)  # , help="Benchmark to be used.")
@click.argument(
    "benchmark-input-size", type=click.Choice(["test", "small", "large"])
)  # help="Input test size")
@click.option("--repetitions", default=5, type=int, help="Number of experimental repetitions.")
@click.option(
    "--trigger",
    type=click.Choice(["library", "http"]),
    default="http",
    help="Function trigger to be used.",
)
@click.option(
    "--memory",
    default=None,
    type=int,
    help="Override default memory settings for the benchmark function.",
)
@click.option(
    "--timeout",
    default=None,
    type=int,
    help="Override default timeout settings for the benchmark function.",
)
@click.option(
    "--function-name",
    default=None,
    type=str,
    help="Override function name for random generation.",
)
@click.option(
    "--image-tag-prefix",
    default=None,
    type=str,
    help="Attach prefix to generated Docker image tag.",
)
@click.option("--storage-configuration", type=str, multiple=True, help="JSON configuration of deployed storage.")
@common_params
def invoke(
    benchmark,
    benchmark_input_size,
    repetitions,
    trigger,
    memory,
    timeout,
    function_name,
    image_tag_prefix,
    **kwargs,
):

    (
        config,
        output_dir,
        logging_filename,
        sebs_client,
        deployment_client
    ) = parse_common_params(**kwargs)

    if image_tag_prefix is not None:
        sebs_client.config.image_tag_prefix = image_tag_prefix

    experiment_config = sebs_client.get_experiment_config(config["experiments"])
    update_nested_dict(config, ["experiments", "benchmark"], benchmark)
    benchmark_obj = sebs_client.get_benchmark(
        benchmark,
        deployment_client,
        experiment_config,
        logging_filename=logging_filename,
    )

    if memory is not None:
        benchmark_obj.benchmark_config.memory = memory
    if timeout is not None:
        benchmark_obj.benchmark_config.timeout = timeout

    input_config = benchmark_obj.prepare_input(deployment_client.system_resources, size=benchmark_input_size, replace_existing=experiment_config.update_storage)

    func = deployment_client.get_function(
        benchmark_obj,
        function_name if function_name else deployment_client.default_function_name(benchmark_obj),
    )

    result = sebs.experiments.ExperimentResult(experiment_config, deployment_client.config)
    result.begin()

    trigger_type = Trigger.TriggerType.get(trigger)
    triggers = func.triggers(trigger_type)
    if len(triggers) == 0:
        trigger = deployment_client.create_trigger(func, trigger_type)
    else:
        trigger = triggers[0]
    for i in range(repetitions):
        sebs_client.logging.info(f"Beginning repetition {i+1}/{repetitions}")
        ret = trigger.sync_invoke(input_config)
        if ret.stats.failure:
            sebs_client.logging.info(f"Failure on repetition {i+1}/{repetitions}")
            # deployment_client.get_invocation_error(
            #    function_name=func.name, start_time=start_time, end_time=end_time
            # )
        result.add_invocation(func, ret)
    result.end()

    result_file = os.path.join(output_dir, "experiments.json")
    with open(result_file, "w") as out_f:
        out_f.write(sebs.utils.serialize(result))
    sebs_client.logging.info("Save results to {}".format(os.path.abspath(result_file)))


@benchmark.command()
@common_params
def process(**kwargs):

    (
        config,
        output_dir,
        logging_filename,
        sebs_client,
        deployment_client,
    ) = parse_common_params(**kwargs)

    result_file = os.path.join(output_dir, "experiments.json")
    sebs_client.logging.info("Load results from {}".format(os.path.abspath(result_file)))
    with open(result_file, "r") as in_f:
        config = json.load(in_f)
        experiments = sebs.experiments.ExperimentResult.deserialize(
            config,
            sebs_client.cache_client,
            sebs_client.generate_logging_handlers(logging_filename),
        )

    for func in experiments.functions():
        deployment_client.download_metrics(
            func, *experiments.times(), experiments.invocations(func), experiments.metrics(func)
        )

    output_file = os.path.join(output_dir, "results.json")
    with open(output_file, "w") as out_f:
        out_f.write(sebs.utils.serialize(experiments))
    sebs_client.logging.info("Save results to {}".format(output_file))


@benchmark.command()
@click.argument(
    "benchmark-input-size", type=click.Choice(["test", "small", "large"])
)  # help="Input test size")
@click.option(
    "--benchmark-name",
    default=None,
    type=str,
    help="Run only the selected benchmark.",
)
@common_params
@click.option(
    "--cache",
    default=os.path.join(os.path.curdir, "regression-cache"),
    help="Location of experiments cache.",
)
@click.option(
    "--output-dir",
    default=os.path.join(os.path.curdir, "regression-output"),
    help="Output directory for results.",
)
def regression(benchmark_input_size, benchmark_name, **kwargs):
    # for regression, deployment client is initialized locally
    # disable default initialization
    (config, output_dir, logging_filename, sebs_client, _) = parse_common_params(
        initialize_deployment=False, **kwargs
    )
    regression_suite(
        sebs_client,
        config["experiments"],
        set((config["deployment"]["name"],)),
        config,
        benchmark_name,
    )


"""
    Storage operations have the following characteristics:
    - Two operations, start and stop.
    - Three options, object storage, NoSQL storage, and all.
    - Port and additional settings.

    Configuration is read from a JSON.
"""


@cli.group()
def storage():
    pass


@storage.command("start")
@click.argument("storage", type=click.Choice(["object", "nosql", "all"]))
@click.argument("config", type=click.Path(dir_okay=False, readable=True))
@click.option("--output-json", type=click.Path(dir_okay=False, writable=True), default=None)
def storage_start(storage, config, output_json):

    import docker

    sebs.utils.global_logging()
    user_storage_config = json.load(open(config, 'r'))

    if storage in ["object", "all"]:

        storage_type_name = user_storage_config["object"]["type"]
        storage_type_enum = StorageTypes(storage_type_name)

        storage_type = sebs.SeBS.get_storage_implementation(storage_type_enum)
        storage_config = sebs.SeBS.get_storage_config_implementation(storage_type_enum)
        config = storage_config.deserialize(user_storage_config["object"][storage_type_name])

        storage_instance = storage_type(docker.from_env(), None, None, True)
        storage_instance.config = config

        storage_instance.start()

        user_storage_config["object"][storage_type_name] = storage_instance.serialize()
    else:
        user_storage_config.pop("object")

    if storage in ["nosql", "all"]:

        storage_type_name = user_storage_config["nosql"]["type"]
        storage_type_enum = NoSQLStorageTypes(storage_type_name)

        storage_type = sebs.SeBS.get_nosql_implementation(storage_type_enum)
        storage_config = sebs.SeBS.get_nosql_config_implementation(storage_type_enum)
        config = storage_config.deserialize(user_storage_config["nosql"][storage_type_name])

        storage_instance = storage_type(docker.from_env(), None, config)

        storage_instance.start()

        key, value = storage_instance.serialize()
        user_storage_config["nosql"][key] = value
    else:
        user_storage_config.pop("nosql")

    if output_json:
        logging.info(f"Writing storage configuration to {output_json}.")
        with open(output_json, "w") as f:
            json.dump(user_storage_config, fp=f, indent=2)
    else:
        logging.info("Writing storage configuration to stdout.")
        logging.info(json.dumps(user_storage_config, indent=2))


@storage.command("stop")
@click.argument("storage", type=click.Choice(["object", "nosql", "all"]))
@click.argument("input-json", type=click.Path(exists=True, dir_okay=False, readable=True))
def storage_stop(storage, input_json):

    sebs.utils.global_logging()
    with open(input_json, "r") as f:
        cfg = json.load(f)

    if storage in ["object", "all"]:

        storage_type = cfg["object"]["type"]

        storage_cfg = sebs.SeBS.get_storage_config_implementation(storage_type)
        config = storage_cfg.deserialize(cfg["object"][storage_type])

        logging.info(f"Stopping storage deployment of {storage_type}.")
        storage_instance = sebs.SeBS.get_storage_implementation(storage_type).deserialize(config, None, None)
        storage_instance.stop()
        logging.info(f"Stopped storage deployment of {storage_type}.")

    if storage in ["nosql", "all"]:

        storage_type = cfg["nosql"]["type"]

        storage_cfg = sebs.SeBS.get_nosql_config_implementation(storage_type)
        config = storage_cfg.deserialize(cfg["nosql"][storage_type])

        logging.info(f"Stopping nosql deployment of {storage_type}.")
        storage_instance = sebs.SeBS.get_nosql_implementation(storage_type).deserialize(config, None, None)
        storage_instance.stop()
        logging.info(f"Stopped nosql deployment of {storage_type}.")

@cli.group()
def local():
    pass


@local.command()
@click.argument("benchmark", type=str)
@click.argument("benchmark-input-size", type=click.Choice(["test", "small", "large"]))
@click.argument("output", type=str)
@click.option("--deployments", default=1, type=int, help="Number of deployed containers.")
@click.option("--storage-configuration", type=str, multiple=True, help="JSON configuration of deployed storage.")
@click.option("--measure-interval", type=int, default=-1,
              help="Interval duration between memory measurements in ms.")
@click.option(
    "--remove-containers/--no-remove-containers",
    default=True,
    help="Remove containers after stopping.",
)
@click.option(
    "--architecture",
    default=None,
    type=click.Choice(["x64", "arm64"]),
    help="Target architecture",
)
@simplified_common_params
def start(
    benchmark,
    benchmark_input_size,
    output,
    deployments,
    storage_configuration,
    measure_interval,
    remove_containers,
    architecture,
    **kwargs,
):
    """
    Start a given number of function instances and a storage instance.
    """

    (config, output_dir, logging_filename, sebs_client, deployment_client) = parse_common_params(
        update_code=False, update_storage=False,
        deployment="local", storage_configuration=storage_configuration,
        container_deployment=False, architecture=architecture,
        **kwargs
    )
    deployment_client = cast(sebs.local.Local, deployment_client)
    deployment_client.remove_containers = remove_containers
    result = sebs.local.Deployment()
    result.measurement_file = deployment_client.start_measurements(measure_interval)

    experiment_config = sebs_client.get_experiment_config(config["experiments"])
    benchmark_obj = sebs_client.get_benchmark(
        benchmark,
        deployment_client,
        experiment_config,
        logging_filename=logging_filename,
    )
    input_config = benchmark_obj.prepare_input(
        deployment_client.system_resources,
        size=benchmark_input_size,
        replace_existing=experiment_config.update_storage
    )
    result.set_storage(deployment_client.system_resources.get_storage())
    result.add_input(input_config)

    for i in range(deployments):
        func = deployment_client.get_function(
            benchmark_obj, deployment_client.default_function_name(benchmark_obj,deployment_client.config.resources)
        )
        result.add_function(func)

    # Disable shutdown of storage only after we succed
    # Otherwise we want to clean up as much as possible
    deployment_client.shutdown_storage = False

    result.serialize(output)
    sebs_client.logging.info(f"Save results to {os.path.abspath(output)}")


@local.command()
@click.argument("input-json", type=str)
@click.argument("output-json", type=str, default="memory_stats.json")
# @simplified_common_params
def stop(input_json, output_json, **kwargs):
    """
    Stop function and storage containers.
    """

    sebs.utils.global_logging()

    logging.info(f"Stopping deployment from {os.path.abspath(input_json)}")

    deployment = sebs.local.Deployment.deserialize(input_json, None)
    deployment.shutdown(output_json)

    logging.info(f"Stopped deployment from {os.path.abspath(input_json)}")


@cli.group()
def experiment():
    pass


@experiment.command("invoke")
@click.argument("experiment", type=str)  # , help="Benchmark to be launched.")
@common_params
def experiment_invoke(experiment, **kwargs):
    (
        config,
        output_dir,
        logging_filename,
        sebs_client,
        deployment_client,
    ) = parse_common_params(**kwargs)
    experiment = sebs_client.get_experiment(experiment, config["experiments"])
    experiment.prepare(sebs_client, deployment_client)
    experiment.run()


@experiment.command("process")
@click.argument("experiment", type=str)  # , help="Benchmark to be launched.")
@click.option("--extend-time-interval", type=int, default=-1)  # , help="Benchmark to be launched.")
@common_params
def experiment_process(experiment, extend_time_interval, **kwargs):
    (
        config,
        output_dir,
        logging_filename,
        sebs_client,
        deployment_client,
    ) = parse_common_params(**kwargs)
    experiment = sebs_client.get_experiment(experiment, config["experiments"])
    experiment.process(
        sebs_client, deployment_client, output_dir, logging_filename, extend_time_interval
    )


@cli.group()
def resources():
    pass


@resources.command("list")
@click.argument("resource", type=click.Choice(["buckets", "resource-groups"]))
@common_params
def resources_list(resource, **kwargs):

    (
        config,
        output_dir,
        logging_filename,
        sebs_client,
        deployment_client,
    ) = parse_common_params(**kwargs)

    if resource == "buckets":
        storage_client = deployment_client.system_resources.get_storage(False)
        buckets = storage_client.list_buckets()
        sebs_client.logging.info("Storage buckets:")
        for idx, bucket in enumerate(buckets):
            sebs_client.logging.info(f"({idx}) {bucket}")

    elif resource == "resource-groups":

        if deployment_client.name() != "azure":
            sebs_client.logging.error("Resource groups are only supported on Azure!")
            return

        groups = deployment_client.config.resources.list_resource_groups(
            deployment_client.cli_instance
        )
        sebs_client.logging.info("Resource grup:")
        for idx, bucket in enumerate(groups):
            sebs_client.logging.info(f"({idx}) {bucket}")


@resources.command("remove")
@click.argument("resource", type=click.Choice(["buckets", "resource-groups"]))
@click.argument("prefix", type=str)
@click.option("--wait/--no-wait", type=bool, default=True, help="Wait for completion of removal.")
@click.option(
    "--dry-run/--no-dry-run",
    type=bool,
    default=False,
    help="Simulate run without actual deletions.",
)
@common_params
def resources_remove(resource, prefix, wait, dry_run, **kwargs):

    (
        config,
        output_dir,
        logging_filename,
        sebs_client,
        deployment_client,
    ) = parse_common_params(**kwargs)

    storage_client = deployment_client.system_resources.get_storage(False)
    if resource == "buckets":

        buckets = storage_client.list_buckets()
        for idx, bucket in enumerate(buckets):

            if len(prefix) > 0 and not bucket.startswith(prefix):
                continue

            sebs_client.logging.info(f"Removing bucket: {bucket}")
            if not dry_run:
                storage_client.clean_bucket(bucket)
                storage_client.remove_bucket(bucket)

    elif resource == "resource-groups":

        if deployment_client.name() != "azure":
            sebs_client.logging.error("Resource groups are only supported on Azure!")
            return

        groups = deployment_client.config.resources.list_resource_groups(
            deployment_client.cli_instance
        )
        for idx, group in enumerate(groups):
            if len(prefix) > 0 and not group.startswith(prefix):
                continue

            sebs_client.logging.info(f"Removing resource group: {group}")
            deployment_client.config.resources.delete_resource_group(
                deployment_client.cli_instance, group, wait
            )
    else:
        raise NotImplementedError(f"Resource {resource} not supported.")


if __name__ == "__main__":
    cli()
