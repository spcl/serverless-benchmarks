# Invoking a Single Function

This section describes how to invoke a single function using the `sebs.py benchmark invoke` command.

To invoke a function, you can use the following command:

```bash
python3 sebs.py benchmark invoke --config <config_file> --benchmark <benchmark_name> --platform <platform_name> --region <region> --deployment <deployment_type> --language <language> --function <function_name>
```

For example, to invoke the `110.dynamic-html` benchmark on AWS Lambda in the `us-east-1` region, you would use the following command:

```bash
python3 sebs.py benchmark invoke --config config/aws.json --benchmark 110.dynamic-html --platform aws --region us-east-1 --deployment docker --language python --function dynamic-html
```

It is important to choose a platform for your benchmark. For a more detailed explanation of platforms, please see [docs/platforms.md](docs/platforms.md).

There are two main options for code deployment:

1.  **Build a code package in a Docker builder:** This option builds your function code into a deployment package using a Docker container that matches the target FaaS platform's runtime environment.
2.  **Deploy a Docker container:** This option deploys your function as a Docker container, which can be useful for functions with complex dependencies or when you want more control over the execution environment.

For more details on invoking functions, please refer to [docs/usage.md](docs/usage.md).

# Benchmark Lifecycle: A Hello-World Example

This section explains the lifecycle of a benchmark by walking through adding a simple "hello-world" function.

Let's consider a basic "hello-world" function that simply returns a greeting message.

## Data Storage

For some benchmarks, you might need to upload data to a storage service (e.g., AWS S3, Azure Blob Storage). This data can then be accessed by your function during execution. For a simple "hello-world" function, this step is typically not required. However, for more complex benchmarks, SeBS provides mechanisms to manage and access this data.

## Input Generation

Every benchmark function in SeBS requires input. For our "hello-world" example, the input could be a name to include in the greeting. SeBS allows you to define how these inputs are generated. You can provide static inputs or define a process to generate dynamic inputs for each function invocation.

## SeBS Wrapper

SeBS interacts with your function code through a wrapper. This wrapper is responsible for:

1.  Receiving the invocation request from the FaaS platform.
2.  Loading any necessary data from storage.
3.  Preparing the input for your function based on the SeBS input generation mechanism.
4.  Calling your actual function code with the prepared input.
5.  Returning the output of your function.

This wrapper acts as a bridge between the SeBS framework and your specific benchmark logic, ensuring consistent execution and measurement across different platforms and languages.

## Build and Deployment

Once you have your function code and the SeBS wrapper, the next step is to build and deploy it to your chosen cloud platform. SeBS automates this process.

1.  **Build:** SeBS can package your code and its dependencies. This might involve compiling code (for languages like Java or Go) or simply packaging scripts (for languages like Python or Node.js). It often uses Docker to create a consistent build environment.
2.  **Deployment:** After a successful build, SeBS deploys the packaged function to the specified FaaS platform (e.g., AWS Lambda, Azure Functions, Google Cloud Functions). This involves configuring the function, setting up triggers, and making it ready for invocation.

For a more detailed explanation of the build and deployment process, please refer to [docs/build.md](docs/build.md).

By following this lifecycle, SeBS allows you to define, deploy, and benchmark serverless functions in a standardized and reproducible way.

# Using an Experiment

While invoking single functions is useful for testing and debugging, SeBS also allows you to define and run experiments. Experiments are collections of benchmarks that are executed in a specific order, often with varying configurations, to evaluate different aspects of serverless platforms.

To invoke an experiment, you can use the `sebs.py experiment invoke` command. You'll need to provide an experiment configuration file.

```bash
python3 sebs.py experiment invoke --config <experiment_config_file>
```

For example, to run an experiment defined in `experiments/my_experiment.json`:

```bash
python3 sebs.py experiment invoke --config experiments/my_experiment.json
```

Experiments are typically used for tasks such as:

*   **Performance Evaluation:** Comparing the performance of different functions or configurations across various platforms.
*   **Cost Estimation:** Analyzing the cost implications of running benchmarks with different resource allocations or invocation patterns.
*   **Cold Start Analysis:** Investigating the impact of cold starts on function performance.

SeBS experiments provide a powerful way to automate complex benchmarking scenarios and gather comprehensive data. For a more detailed explanation of experiments, including how to define their configuration and the various options available, please refer to [docs/experiments.md](docs/experiments.md).
