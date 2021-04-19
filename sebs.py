#!/usr/bin/env python3


import json
import logging
import functools
import os
import sys
import traceback
from typing import cast, Optional

import click

import sebs
from sebs import SeBS
from sebs.regression import regression_suite
from sebs.utils import update_nested_dict
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


def common_params(func):
    @click.option(
        "--config",
        required=True,
        type=click.Path(readable=True),
        help="Location of experiment config.",
    )
    @click.option(
        "--output-dir", default=os.path.curdir, help="Output directory for results."
    )
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
        type=click.Choice(["azure", "aws", "gcp", "local"]),
        help="Cloud deployment to use.",
    )
    @click.option(
        "--language",
        default=None,
        type=click.Choice(["python", "nodejs"]),
        help="Benchmark language",
    )
    @click.option(
        "--language-version", default=None, type=str, help="Benchmark language version"
    )
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


def parse_common_params(
    config,
    output_dir,
    cache,
    verbose,
    preserve_out,
    update_code,
    update_storage,
    deployment,
    language,
    language_version,
    initialize_deployment: bool = True,
    ignore_cache: bool = False
):
    global sebs_client, deployment_client

    config_obj = json.load(open(config, "r"))
    sebs_client = sebs.SeBS(cache, output_dir)
    output_dir = sebs.utils.create_output(output_dir, preserve_out, verbose)
    logging.info("Created experiment output at {}".format(output_dir))

    # CLI overrides JSON options
    update_nested_dict(config_obj, ["experiments", "runtime", "language"], language)
    update_nested_dict(
        config_obj, ["experiments", "runtime", "version"], language_version
    )
    update_nested_dict(config_obj, ["deployment", "name"], deployment)
    update_nested_dict(config_obj, ["experiments", "update_code"], update_code)
    update_nested_dict(config_obj, ["experiments", "update_storage"], update_storage)
    update_nested_dict(config_obj, ["experiments", "benchmark"], benchmark)

    logging_filename = os.path.abspath(os.path.join(output_dir, "out.log"))
    if initialize_deployment:
        deployment_client = sebs_client.get_deployment(
            config_obj["deployment"], logging_filename=logging_filename, verbose=verbose
        )
        deployment_client.initialize()
    else:
        deployment_client = None

    if ignore_cache:
        sebs_client.ignore_cache()

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
@click.option(
    "--repetitions", default=5, type=int, help="Number of experimental repetitions."
)
@click.option(
    "--function-name",
    default=None,
    type=str,
    help="Override function name for random generation.",
)
@common_params
def invoke(benchmark, benchmark_input_size, repetitions, function_name, **kwargs):

    (
        config,
        output_dir,
        logging_filename,
        sebs_client,
        deployment_client,
    ) = parse_common_params(**kwargs)
    experiment_config = sebs_client.get_experiment_config(config["experiments"])
    benchmark_obj = sebs_client.get_benchmark(
        benchmark,
        deployment_client,
        experiment_config,
        logging_filename=logging_filename,
    )
    func = deployment_client.get_function(
        benchmark_obj, function_name if function_name else deployment_client.default_function_name(benchmark_obj)
    )
    storage = deployment_client.get_storage(
        replace_existing=experiment_config.update_storage
    )
    input_config = benchmark_obj.prepare_input(
        storage=storage, size=benchmark_input_size
    )

    result = sebs.experiments.ExperimentResult(
        experiment_config, deployment_client.config
    )
    result.begin()
    # FIXME: repetitions
    # FIXME: trigger type
    triggers = func.triggers(Trigger.TriggerType.HTTP)
    if len(triggers) == 0:
        trigger = deployment_client.create_trigger(
            func, Trigger.TriggerType.HTTP
        )
    else:
        trigger = triggers[0]
    ret = trigger.sync_invoke(input_config)
    if ret.stats.failure:
        deployment_client.get_invocation_error(
            function_name=self.name, start_time=start_time, end_time=end_time
        )
    result.end()
    result.add_invocation(func, ret)
    with open("experiments.json", "w") as out_f:
        out_f.write(sebs.utils.serialize(result))
    logging.info("Save results to {}".format(os.path.abspath("experiments.json")))


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
    logging.info("Load results from {}".format(os.path.abspath("experiments.json")))
    with open("experiments.json", "r") as in_f:
        config = json.load(in_f)
        experiments = sebs.experiments.ExperimentResult.deserialize(
            config,
            sebs_client.cache_client,
            sebs_client.logging_handlers(logging_filename),
        )

    for func in experiments.functions():
        deployment_client.download_metrics(
            func, *experiments.times(), experiments.invocations(func)
        )
    with open("results.json", "w") as out_f:
        out_f.write(sebs.utils.serialize(experiments))
    logging.info("Save results to {}".format(os.path.abspath("results.json")))

@benchmark.command()
@click.argument(
    "benchmark-input-size", type=click.Choice(["test", "small", "large"])
)  # help="Input test size")
@common_params
@click.option(
    "--cache",
    default=os.path.join(os.path.curdir, "regression-cache"),
    help="Location of experiments cache.",
)
@click.option(
    "--output-dir", default=os.path.join(os.path.curdir, "regression-output"), help="Output directory for results."
)
def regression(benchmark_input_size, **kwargs):
    # for regression, deployment client is initialized locally
    # disable default initialization
    (
        config,
        output_dir,
        logging_filename,
        sebs_client,
        _
    ) = parse_common_params(
        initialize_deployment=False,
        **kwargs
    )
    succ = regression_suite(sebs_client, config["experiments"], set( (config['deployment']['name'],) ))

@cli.group()
def local():
    pass

@local.command()
@click.argument("benchmark", type=str)
@click.argument(
    "benchmark-input-size", type=click.Choice(["test", "small", "large"])
)
@click.argument("output", type=str)
@click.option(
    "--deployments", default=1, type=int, help="Number of deployed containers."
)
@click.option(
    "--remove-containers/--no-remove-containers", default=True, help="Remove containers after stopping."
)
@click.option(
    "--config",
    required=True,
    type=click.Path(readable=True),
    help="Location of experiment config.",
)
@click.option(
    "--output-dir", default=os.path.curdir, help="Output directory for results."
)
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
@click.option(
    "--language-version", default=None, type=str, help="Benchmark language version"
)
def start(benchmark, benchmark_input_size, output, deployments, remove_containers, **kwargs):
    """
        Start a given number of function instances.
    """

    (
        config,
        output_dir,
        logging_filename,
        sebs_client,
        deployment_client
    ) = parse_common_params(
        ignore_cache = True,
        update_code = False,
        update_storage = False,
        deployment = "local",
        **kwargs
    )
    deployment_client = cast(sebs.local.Local, deployment_client)
    deployment_client.remove_containers = remove_containers

    experiment_config = sebs_client.get_experiment_config(config["experiments"])
    benchmark_obj = sebs_client.get_benchmark(
        benchmark,
        deployment_client,
        experiment_config,
        logging_filename=logging_filename,
    )
    result = sebs.local.Deployment()
    for i in range(deployments):
        func = deployment_client.get_function(
            benchmark_obj, deployment_client.default_function_name(benchmark_obj)
        )
        result.add_function(func)
    storage = deployment_client.get_storage(
        replace_existing=experiment_config.update_storage
    )
    result.set_storage(storage)
    input_config = benchmark_obj.prepare_input(
        storage=storage, size=benchmark_input_size
    )
    result.add_input(input_config)

    # Disable shutdown of storage only after we succed
    # Otherwise we want to clean up as much as possible
    deployment_client.shutdown_storage = False
    result.serialize(output)
    logging.info(f"Save results to {os.path.abspath(output)}")

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
def experment_process(experiment, extend_time_interval, **kwargs):
    (
        config,
        output_dir,
        logging_filename,
        sebs_client,
        deployment_client,
    ) = parse_common_params(**kwargs)
    experiment = sebs_client.get_experiment(experiment, config["experiments"])
    experiment.process(sebs_client, deployment_client, output_dir, logging_filename, extend_time_interval)


if __name__ == "__main__":
    cli()

