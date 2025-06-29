
#include <cstdint>

#include <aws/core/utils/memory/stl/AWSString.h>
#include <aws/s3/S3Client.h>

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

  uint64_t upload_random_file(Aws::String const &bucket,
                          Aws::String const &key,
                          bool report_dl_time,
                          Aws::String data);

};

