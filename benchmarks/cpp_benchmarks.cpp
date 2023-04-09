#include <iostream>
#include <fstream>
#include <sstream>
#include <vector>
#include <string>
#include <cstdlib>
#include <cstdio>
#include <chrono>
#include <iomanip>

// Include the benchmark library
#include <benchmark/benchmark.h>

// Include the AWS SDK
#include <aws/core/Aws.h>
#include <aws/core/utils/json/JsonValue.h>
#include <aws/lambda/LambdaClient.h>
#include <aws/lambda/model/CreateFunctionRequest.h>
#include <aws/lambda/model/InvokeRequest.h>
#include <aws/lambda/model/DeleteFunctionRequest.h>

// Define a map to store the benchmark results
std::map<std::string, std::map<std::string, double>> overall_results;

// Define the setup function for the benchmark
void setup(benchmark::State& state) {
  // Set up compile and run commands for the C++ benchmark
  std::vector<std::string> compile_cmd = {"g++", "-std=c++11", "-O3", "-DNDEBUG", "-I./benchmark/include", "cpp_benchmark.cpp", "-o", "cpp_benchmark"};
  std::vector<std::string> run_cmd = {"./cpp_benchmark", "--benchmark_format=json"};

  // Compile the C++ benchmark
  std::ostringstream compile_out;
  int compile_ret = benchmark::RunSpecifiedCommand(compile_cmd, &compile_out);
  if (compile_ret != 0) {
    std::cerr << "Failed to compile C++ benchmark:\n" << compile_out.str() << std::endl;
    return;
  }

  // Set up the Lambda client
  Aws::SDKOptions options;
  Aws::InitAPI(options);
  Aws::Client::ClientConfiguration clientConfig;
  Aws::Lambda::LambdaClient lambdaClient(clientConfig);

  // Build the request to create the Lambda function
  Aws::Lambda::Model::CreateFunctionRequest createRequest;
  createRequest.SetFunctionName("cpp_benchmark");
  createRequest.SetRuntime("provided");
  createRequest.SetRole("arn:aws:iam::123456789012:role/lambda-role");
  createRequest.SetHandler("cpp_benchmark.handler");
  createRequest.SetCode(Aws::Lambda::Model::FunctionCode().WithZipFile("path/to/cpp_benchmark.zip"));

  // Create the Lambda function
  auto createOutcome = lambdaClient.CreateFunction(createRequest);
  if (!createOutcome.IsSuccess()) {
    std::cerr << "Failed to create Lambda function: " << createOutcome.GetError().GetMessage() << std::endl;
    return;
  }

  // Build the request to invoke the Lambda function
  Aws::Lambda::Model::InvokeRequest invokeRequest;
  invokeRequest.SetFunctionName("cpp_benchmark");
  invokeRequest.SetInvocationType(Aws::Lambda::Model::InvocationType::RequestResponse);

  // Invoke the Lambda function and store the results
  auto invokeOutcome = lambdaClient.Invoke(invokeRequest);
  if (!invokeOutcome.IsSuccess()) {
    std::cerr << "Failed to invoke Lambda function: " << invokeOutcome.GetError().GetMessage() << std::endl;
    return;
  }

  // Parse the output of the Lambda function and store the results
  Aws::String result = invokeOutcome.GetResult().GetPayload().AsString();
  Aws::Utils::Json::JsonValue jsonResult(result.c_str());

  for (const auto& benchmark : jsonResult.GetObject()) {
    std::string benchmark_name = benchmark.GetName();
    double benchmark_time = benchmark.GetValue().AsDouble() / benchmark::kNumIterations;

    overall_results[benchmark_name]["cpp"] = benchmark_time;
  }

   // Delete the Lambda function
  Aws::Lambda::Model::DeleteFunctionRequest deleteRequest;
  deleteRequest.SetFunctionName("cpp_benchmark");
  lambdaClient.DeleteFunction(deleteRequest);

  // Print the benchmark results
  std::cout << "Benchmark Results:\n";
  std::cout << std::setw(20) << std::left << "Benchmark Name" << std::setw(15) << std::right << "Local (ms)" << std::setw(15) << std::right << "AWS Lambda (ms)" << std::endl;
  std::cout << "------------------------------------------------------\n";
  for (const auto& benchmark : overall_results) {
    std::cout << std::setw(20) << std::left << benchmark.first << std::fixed << std::setprecision(2) << std::setw(15) << std::right << benchmark.second["cpp"] << std::setw(15) << std::right << benchmark.second["aws_lambda"] << std::endl;
  }

  // Shut down the AWS SDK
  Aws::ShutdownAPI(options);
}

BENCHMARK(setup);

