// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

#include <cstdint>

#include <aws/core/utils/memory/stl/AWSString.h>
#include <aws/s3/S3Client.h>
#include <aws/s3/model/GetObjectRequest.h>

#include "utils.hpp"

namespace sebs {

class Storage
{
public:
  Aws::S3::S3Client _client;

  Storage(Aws::S3::S3Client && client):
    _client(client)
  {}

  static Storage get_client();

  uint64_t download_file(Aws::String const &bucket,
                          Aws::String const &key,
                          int &required_retries,
                          bool report_dl_time,
                          Aws::IOStream &output_stream);

  /*
    * Downloads a file from S3
    * @param bucket The S3 bucket name
    * @param key The S3 object key
    * @return A tuple containing the file content as a string and the elapsed
    * time in microseconds.
    * If the download fails, an empty string and 0 are returned.
  */
  std::tuple<std::string, uint64_t> download_file(Aws::String const &bucket,
                          Aws::String const &key);


  template<typename F>
  std::tuple<uint64_t, uint64_t> download_stream(
      Aws::String const &bucket, Aws::String const &key, F && f
  )
  {
    Aws::S3::Model::GetObjectRequest request;
    request.WithBucket(bucket).WithKey(key);

    auto bef = timeSinceEpochMicrosec();
    Aws::S3::Model::GetObjectOutcome outcome = this->_client.GetObject(request);
    if (!outcome.IsSuccess()) {
      std::cerr << "Error: GetObject: " << outcome.GetError().GetMessage() << std::endl;
      return {0, 0};
    }
    uint64_t finished_download = timeSinceEpochMicrosec();

    auto bef_compute = timeSinceEpochMicrosec();
    f(outcome.GetResult().GetBody());
    uint64_t finished_compute = timeSinceEpochMicrosec();

    return {finished_download - bef, finished_compute - bef_compute};
  }

  uint64_t upload_random_file(Aws::String const &bucket,
                          Aws::String const &key,
                          bool report_dl_time,
                          char * data,
                          size_t data_size);

};

};

