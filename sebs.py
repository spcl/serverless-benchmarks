#!/usr/bin/env python3


import json
import logging
import functools
import os
import traceback
from typing import Optional

import click

import sebs
from sebs import SeBS
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
    @click.option("--verbose", default=False, help="Verbose output.")
    @click.option(
        "--preserve-out",
        default=True,
        help="Preserve current results in output directory.",
    )
    @click.option(
        "--update-code",
        default=False,
        help="Update function code in cache and cloud deployment.",
    )
    @click.option(
        "--update-storage",
        default=False,
        help="Update benchmark storage files in cloud deployment.",
    )
    @click.option(
        "--deployment",
        default=None,
        type=click.Choice(["azure", "aws", "gcp"]),
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
    deployment_client = sebs_client.get_deployment(
        config_obj["deployment"], logging_filename=logging_filename
    )
    deployment_client.initialize()

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
        benchmark_obj, deployment_client.default_function_name(benchmark_obj)
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
    ret = func.triggers.get(Trigger.TriggerType.STORAGE).async_invoke(input_config)
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
@click.option(
    "--repetitions", default=5, type=int, help="Number of experimental repetitions."
)
@common_params
def regression(benchmark, benchmark_input_size, repetitions, function_name, **kwargs):
    (
        config,
        output_dir,
        logging_filename,
        sebs_client,
        deployment_client,
    ) = parse_common_params(**kwargs)
    raise NotImplementedError()


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
@common_params
def experment_process(experiment, **kwargs):
    (
        config,
        output_dir,
        logging_filename,
        sebs_client,
        deployment_client,
    ) = parse_common_params(**kwargs)
    experiment = sebs_client.get_experiment(config["experiments"])
    experiment.process(output_dir)


if __name__ == "__main__":
    cli()

