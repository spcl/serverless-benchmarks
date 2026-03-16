# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
#include <rapidjson/document.h>
#include <rapidjson/writer.h>
#include <rapidjson/stringbuffer.h>

#include <boost/uuid/uuid_generators.hpp>
#include <boost/uuid/uuid.hpp>
#include <boost/uuid/uuid_io.hpp>

#include <iostream>
#include <vector>
#include <fstream>
#include <sstream>

#include "utils.hpp"
#include "storage.hpp"

#include <torch/torch.h>
#include <torch/script.h>

#include <opencv2/imgproc/imgproc.hpp>
#include <opencv2/opencv.hpp>

#define kIMAGE_SIZE 224
#define kCHANNELS 3

std::vector<std::string> load_class_labels(const std::string& json_path);

// Global model to persist between invocations
static bool model_initialized = false;
static torch::jit::script::Module model;
static std::vector<std::string> class_labels = load_class_labels("imagenet_class_index.json");

// Load ImageNet class labels
std::vector<std::string> load_class_labels(const std::string& json_path)
{
  std::ifstream file(json_path);
  if (!file.is_open())
  {
    std::cerr << "Failed to open class index file: " << json_path << std::endl;
    return std::vector<std::string>{};
  }

  std::string content((std::istreambuf_iterator<char>(file)),
                       std::istreambuf_iterator<char>());

  rapidjson::Document doc;
  doc.Parse(content.c_str());

  if (doc.HasParseError() || !doc.IsObject())
  {
    std::cerr << "Failed to parse class index file: " << json_path << std::endl;
    return std::vector<std::string>{};
  }

  std::vector<std::string> labels(doc.MemberCount());
  for (auto& m : doc.GetObject())
  {
    int idx = std::stoi(m.name.GetString());
    if (m.value.IsArray() && m.value.Size() >= 2)
    {
      labels[idx] = m.value[1].GetString();
    }
  }

  return labels;
}

bool load_and_preprocess_image(const std::string& image_data, cv::Mat& processed_image)
{
  // Decode image from memory
  std::vector<char> vectordata(image_data.begin(), image_data.end());
  cv::Mat image = cv::imdecode(cv::Mat(vectordata), cv::IMREAD_COLOR);

  if (image.empty() || !image.data)
  {
    return false;
  }

  // Convert BGR to RGB
  cv::cvtColor(image, image, cv::COLOR_BGR2RGB);

  // Resize to 256 maintaining aspect ratio
  int w = image.size().width, h = image.size().height;
  cv::Size scale((int)256 * ((float)w) / h, 256);
  cv::resize(image, image, scale);

  // Center crop to 224x224
  w = image.size().width;
  h = image.size().height;
  int crop_x = (w - kIMAGE_SIZE) / 2;
  int crop_y = (h - kIMAGE_SIZE) / 2;
  image = image(cv::Range(crop_y, crop_y + kIMAGE_SIZE),
                cv::Range(crop_x, crop_x + kIMAGE_SIZE));

  // Convert to float and normalize to [0, 1]
  image.convertTo(processed_image, CV_32FC3, 1.0f / 255.0f);

  return true;
}

void load_model_if_needed(
  sebs::Storage& client,
  uint64_t& model_download_time, uint64_t& model_process_time,
  const std::string& bucket, const std::string& model_path
)
{
  if (!model_initialized)
  {
    auto download_result = client.download_file(bucket, model_path);
    std::string model_data = std::get<0>(download_result);
    model_download_time = std::get<1>(download_result);

    if (model_data.empty())
    {
      std::cerr << "Failed to download model from storage: "
        << model_path << " from bucket: "
        << bucket << std::endl;
      return;
    }

    try {

      std::tie(model_download_time, model_process_time) = client.download_stream(
        bucket, model_path, [&](std::istream & model_data) mutable {
          std::cout << "Loading ResNet50 model" << std::endl;
          model = torch::jit::load(model_data);
          model.eval();
        }
      );

    }
    catch (const c10::Error &e)
    {
      std::cerr << "Error loading model: " << e.what() << std::endl;
      return;
    }
    model_initialized = true;
    //auto model_process_end = timeSinceEpochMicrosec();
    //model_process_time = model_process_end - model_process_start;
  }
  else
  {
    model_download_time = 0;
    model_process_time = 0;
  }
}

std::pair<int, std::string> recognize_image(cv::Mat& image)
{

  // Preprocess and run inference
  auto input_tensor = torch::from_blob(image.data, {1, kIMAGE_SIZE, kIMAGE_SIZE, kCHANNELS});
  input_tensor = input_tensor.permute({0, 3, 1, 2});

  // Normalize with ImageNet mean and std
  input_tensor[0][0] = input_tensor[0][0].sub_(0.485).div_(0.229);
  input_tensor[0][1] = input_tensor[0][1].sub_(0.456).div_(0.224);
  input_tensor[0][2] = input_tensor[0][2].sub_(0.406).div_(0.225);

  // Run inference
  torch::Tensor output = model.forward({input_tensor}).toTensor();

  // Get top prediction
  auto max_result = output.max(1);
  int predicted_idx = std::get<1>(max_result).item<int>();

  std::string class_name = "";
  if (predicted_idx >= 0 && predicted_idx < (int)class_labels.size())
  {
    class_name = class_labels[predicted_idx];
  }

  std::cout << "Predicted class: " << predicted_idx << " - " << class_name << std::endl;

  return {predicted_idx, class_name};
}

rapidjson::Document function(const rapidjson::Value& request)
{
  static sebs::Storage client = sebs::Storage::get_client();

  if (!request.HasMember("bucket") || !request["bucket"].IsObject())
  {
    rapidjson::Document error;
    error.SetObject();
    error.AddMember("error", "Bucket object is not valid.", error.GetAllocator());
    return error;
  }

  const auto& bucket_obj = request["bucket"];
  std::string bucket_name = bucket_obj["bucket"].GetString();
  std::string input_prefix = bucket_obj["input"].GetString();
  std::string model_prefix = bucket_obj["model"].GetString();

  const auto& object_obj = request["object"];
  std::string input_key = object_obj["input"].GetString();
  std::string model_key = object_obj["model"].GetString();

  // Download image from storage
  std::string input_path = input_prefix + "/" + input_key;
  auto download_result = client.download_file(bucket_name, input_path);
  std::string image_data = std::get<0>(download_result);
  uint64_t image_download_time = std::get<1>(download_result);

  if (image_data.empty())
  {
    rapidjson::Document error;
    error.SetObject();
    error.AddMember(
      "error",
      rapidjson::Value(
        ("Failed to download image from storage: " + input_path).c_str(),
        error.GetAllocator()
      ),
      error.GetAllocator()
    );
    return error;
  }

  uint64_t model_download_time = 0;
  uint64_t model_process_time = 0;
  // Hardcoded model path - we use a different ResNet format than Python.
  std::string model_path = model_prefix + "/resnet50.pt";

  load_model_if_needed(client, model_download_time, model_process_time, bucket_name, model_path);

  if (!model_initialized)
  {
    rapidjson::Document error;
    error.SetObject();
    error.AddMember("error", "Failed to load model", error.GetAllocator());
    return error;
  }

  // Process image and run inference (separate timer like Python)
  auto process_start = timeSinceEpochMicrosec();

  // Preprocess the image
  cv::Mat processed_image;
  if (!load_and_preprocess_image(image_data, processed_image))
  {
    rapidjson::Document error;
    error.SetObject();
    error.AddMember("error", "Failed to load and preprocess image", error.GetAllocator());
    return error;
  }

  // Run inference
  auto [predicted_idx, class_name] = recognize_image(processed_image);

  auto process_end = timeSinceEpochMicrosec();
  uint64_t process_time = process_end - process_start;

  if (predicted_idx < 0)
  {
    rapidjson::Document error;
    error.SetObject();
    error.AddMember("error", "Image recognition failed", error.GetAllocator());
    return error;
  }

  rapidjson::Document val;
  val.SetObject();
  auto& alloc = val.GetAllocator();

  rapidjson::Value result(rapidjson::kObjectType);
  result.AddMember("idx", predicted_idx, alloc);
  result.AddMember("class", rapidjson::Value(class_name.c_str(), alloc), alloc);
  val.AddMember("result", result, alloc);

  rapidjson::Value measurements(rapidjson::kObjectType);
  measurements.AddMember("download_time", (int64_t)(image_download_time + model_download_time), alloc);
  measurements.AddMember("compute_time", (int64_t)(process_time + model_process_time), alloc);
  measurements.AddMember("model_time", (int64_t)model_process_time, alloc);
  measurements.AddMember("model_download_time", (int64_t)model_download_time, alloc);
  val.AddMember("measurement", measurements, alloc);

  return val;
}
