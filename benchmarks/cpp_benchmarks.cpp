#include <iostream>
#include <fstream>
#include <sstream>
#include <vector>
#include <string>
#include <cstdlib>
#include <cstdio>
#include <chrono>
#include <iomanip>

#include <benchmark/benchmark.h>
#include <aws/core/Aws.h>
#include <aws/core/utils/json/JsonValue.h>
#include <aws/lambda/LambdaClient.h>
#include <aws/lambda/model/CreateFunctionRequest.h>
#include <aws/lambda/model/InvokeRequest.h>
#include <aws/lambda/model/DeleteFunctionRequest.h>

std::map<std::string, std::map<std::string, double>> overall_results;

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

// Run the benchmarking loop
for (auto _ : state) {
  std::ostringstream benchmark_out;
  int benchmark_ret = benchmark::RunSpecifiedCommand(run_cmd, &benchmark_out);
  if (benchmark_ret != 0) {
    std::cerr << "Failed to run C++ benchmark:\n" << benchmark_out.str() << std::endl;
    return;
  }

  Aws::Lambda::Model::InvokeRequest invokeRequest;
  invokeRequest.SetFunctionName("cpp_benchmark");
  invokeRequest.SetInvocationType(Aws::Lambda::Model::InvocationType::RequestResponse);
  invokeRequest.SetPayload(benchmark_out.str());

  auto invokeOutcome = lambdaClient.Invoke(invokeRequest);
  if (!invokeOutcome.IsSuccess()) {
    std::cerr << "Failed to invoke Lambda function: " << invokeOutcome.GetError().GetMessage() << std::endl;
    return;
  }

  Aws::String result = invokeOutcome.GetResult().GetPayload().AsString();
  Aws::Utils::Json::JsonValue jsonResult(result.c_str());

  for (const auto& benchmark : jsonResult.GetObject()) {
    std::string benchmark_name = benchmark.GetName();
    double benchmark_time = benchmark.GetValue().AsDouble() / benchmark::kNumIterations;

    overall_results[benchmark_name]["aws_lambda"] = benchmark_time;
  }
}
