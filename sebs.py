#!/usr/bin/env python3


import argparse
import json
import logging
import os
import traceback
from typing import Optional

import sebs

PROJECT_DIR = os.path.dirname(os.path.realpath(__file__))

parser = argparse.ArgumentParser(description="Run cloud experiments.")
parser.add_argument(
    "action",
    choices=[
        "publish",
        "test_invoke",
        "experiment",
        "create",
        "results",
        "logs",
        "burst_invoke",
        "download_metrics"
    ],
    help="Benchmark name",
)
parser.add_argument("benchmark", type=str, help="Benchmark name")
parser.add_argument("output_dir", type=str, help="Output dir")
parser.add_argument(
    "size", choices=["test", "small", "large"], help="Benchmark input test size"
)
parser.add_argument("config", type=str, help="Config JSON for experiments")
parser.add_argument(
    "--deployment", choices=["azure", "aws", "local", "gcp"], help="Cloud to use"
)
parser.add_argument("--experiment", choices=["time_warm"], help="Experiment to run")
parser.add_argument(
    "--language", choices=["python", "nodejs"], default=None, help="Benchmark language"
)
parser.add_argument(
    "--language-version", type=str, default=None, help="Benchmark language version"
)
parser.add_argument(
    "--repetitions",
    action="store",
    default=5,
    type=int,
    help="Number of experimental repetitions",
)
# TODO: make JSON config
parser.add_argument(
    "--invocations", action="store", type=int, help="Number of experimental repetitions"
)
parser.add_argument(
    "--times-begin-idx",
    action="store",
    type=int,
    help="Number of experimental repetitions",
)
parser.add_argument(
    "--times-end-idx",
    action="store",
    type=int,
    help="Number of experimental repetitions",
)
parser.add_argument(
    "--config-experiment-runner",
    action="store",
    type=str,
    help="Number of experimental repetitions",
)
parser.add_argument(
    "--sleep-time", action="store", type=int, help="Number of experimental repetitions"
)
parser.add_argument(
    "--memory", action="store", type=int, help="Number of experimental repetitions"
)
parser.add_argument(
    "--extend",
    action="store",
    type=str,
    default=None,
    help="Number of experimental repetitions",
)
parser.add_argument(
    "--cache", action="store", default="cache", type=str, help="Cache directory"
)
parser.add_argument(
    "--function-name",
    action="store",
    default="",
    type=str,
    help="Override function name for random generation.",
)
parser.add_argument(
    "--update-code",
    action="store_true",
    default=False,
    help="Update function code in cache and deployment.",
)
parser.add_argument(
    "--update-storage",
    action="store_true",
    default=False,
    help="Update storage files in deployment.",
)
parser.add_argument(
    "--preserve-out",
    action="store_true",
    default=True,
    help="Dont clean output directory [default false]",
)
parser.add_argument(
    "--no-update-function",
    action="store_true",
    default=False,
    help="Dont clean output directory [default false]",
)
parser.add_argument(
    "--verbose", action="store", default=False, type=bool, help="Verbose output"
)
parser.add_argument(
    "--experiment-input", action="store", type=str, help="Verbose output"
)
args = parser.parse_args()

config = json.load(open(args.config, "r"))
output_dir = None
sebs_client = sebs.SeBS(args.cache)
deployment_client: Optional[sebs.faas.System] = None

# 0. Input args
args = parser.parse_args()
verbose = args.verbose
# CLI overrides JSON options
# Language
if args.language:
    config["experiments"]["runtime"]["language"] = args.language
if args.language_version:
    config["experiments"]["runtime"]["version"] = args.language_version
# deployment
if args.deployment:
    config["deployment"]["name"] = args.deployment
if args.update_code:
    config["experiments"]["update_code"] = args.update_code
if args.update_storage:
    config["experiments"]["update_storage"] = args.update_storage

config["experiments"]["benchmark"] = args.benchmark

try:
    output_dir = sebs.utils.create_output(
        args.output_dir, args.preserve_out, args.verbose
    )
    logging.info("Created experiment output at {}".format(args.output_dir))
    experiment_config = sebs_client.get_experiment(config["experiments"])
    deployment_client = sebs_client.get_deployment(config["deployment"])
    deployment_client.initialize()

    if args.action in ("publish", "test_invoke", "download_metrics"):
        benchmark = sebs_client.get_benchmark(
            args.benchmark, output_dir, deployment_client, experiment_config
        )
        storage = deployment_client.get_storage(
            replace_existing=experiment_config.update_storage
        )
        input_config = benchmark.prepare_input(storage=storage, size=args.size)
        func = deployment_client.get_function(benchmark)

        if args.action == "test_invoke":
            # TODO bucket save of results
            bucket = None
            # bucket = deployment_client.prepare_experiment(args.benchmark)
            # input_config['logs'] = { 'bucket': bucket }

            result = sebs.experiments.ExperimentResult(
                experiment_config, deployment_client.config
            )
            result.begin()
            ret = func.sync_invoke(input_config)
            result.end()
            result.add_invocation(func.name, ret)
            with open("experiments.json", "w") as out_f:
                out_f.write(sebs.utils.serialize(result))

        elif args.action == "download_metrics":
            logging.info(
                "Load results from {}".format(os.path.abspath("experiments.json"))
            )
            with open("experiments.json", "r") as in_f:
                config = json.load(in_f)

            result = {func.name: {"execution_times": [], "user_memory_bytes": []}}

            deployment_client.download_metrics(func.name, {}, config["begin_time"], config["end_time"], result)

            with open("results.json", "w") as out_f:
                out_f.write(sebs.utils.serialize(result))
            logging.info(
                "Save results to {}".format(os.path.abspath("results.json"))
            )
    #    elif args.action == "experiment":
    #        # Prepare benchmark input
    #        input_config = prepare_input(
    #            client=deployment_client,
    #            benchmark=args.benchmark,
    #            size=args.size,
    #            update_storage=experiment_config["experiments"]["update_storage"],
    #        )
    #        package = CodePackage(
    #            args.benchmark,
    #            experiment_config,
    #            output_dir,
    #            systems_config[deployment],
    #            cache_client,
    #            docker_client,
    #            args.update,
    #        )
    #        assert args.invocations is not None
    #        assert args.sleep_time
    #        # TODO: experiment JSON config
    #        runner = ExperimentRunner(
    #            not args.no_update_function,
    #            config_file=args.config_experiment_runner,
    #            invocations=args.invocations,
    #            repetitions=args.repetitions,
    #            sleep_time=args.sleep_time,
    #            memory=args.memory,
    #            times_begin_idx=args.times_begin_idx,
    #            times_end_idx=args.times_end_idx,
    #            benchmark=args.benchmark,
    #            output_dir=output_dir,
    #            language=language,
    #            input_config=input_config,
    #            experiment_config=experiment_config,
    #            code_package=package,
    #            deployment_client=deployment_client,
    #            cache_client=cache_client,
    #        )
    #    elif args.action == "create":
    #        # Prepare benchmark input
    #        input_config = prepare_input(
    #            client=deployment_client,
    #            benchmark=args.benchmark,
    #            size=args.size,
    #            update_storage=experiment_config["experiments"]["update_storage"],
    #        )
    #        package = CodePackage(
    #            args.benchmark,
    #            experiment_config,
    #            output_dir,
    #            systems_config[deployment],
    #            cache_client,
    #            docker_client,
    #            args.update,
    #        )
    #        create_functions(
    #            deployment_client,
    #            cache_client,
    #            package,
    #            experiment_config,
    #            args.benchmark,
    #            language,
    #            args.memory,
    #            args.times_begin_idx,
    #            args.times_end_idx,
    #            args.sleep_time,
    #            args.extend,
    #        )
    #    elif args.action == "results":
    #        assert args.experiment_input is not None
    #        experiment = json.load(open(args.experiment_input, "r"))
    #        result = get_results(deployment_client, experiment, args.output_dir)
    #        with open(os.path.join(args.output_dir, "results.json"), "w") as out_f:
    #            json.dump(result, out_f, indent=2)
    #    elif args.action == "burst_invoke":
    #        input_config = prepare_input(
    #            client=deployment_client,
    #            benchmark=args.benchmark,
    #            size=args.size,
    #            update_storage=experiment_config["experiments"]["update_storage"],
    #        )
    #        begin = datetime.datetime.now()
    #        result = run_burst_experiment(
    #            config_file=args.config_experiment_runner,
    #            invocations=args.invocations,
    #            memories=[128, 256, 512, 1024],  # , 1536, 1792, 2048, 3092],
    #            repetitions=args.repetitions,
    #            benchmark=args.benchmark,
    #            output_dir=output_dir,
    #            language=language,
    #            input_config=input_config,
    #            experiment_config=experiment_config,
    #            deployment_client=deployment_client,
    #            cache_client=cache_client,
    #            additional_cfg=experiment_config,
    #        )
    #        end = datetime.datetime.now()
    else:
        raise RuntimeError("Unknown option")

except Exception as e:
    print(e)
    traceback.print_exc()
    if output_dir:
        print("# Experiments failed! See {}/out.log for details".format(output_dir))
finally:
    # Close
    if deployment_client is not None:
        deployment_client.shutdown()
    sebs_client.shutdown()
