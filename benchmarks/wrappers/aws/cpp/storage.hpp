
#include <cstdint>
#include <string>
#include <initializer_list>

#include <aws/core/utils/memory/stl/AWSString.h>
#include <aws/s3/S3Client.h>

class Storage
{
  Aws::S3::S3Client _client;
public:

  Storage(Aws::S3::S3Client && client):
    _client(client)
  {}

  static Storage get_client();

  std::string key_join(std::initializer_list<std::string> paths);

  uint64_t download_file(Aws::String const &bucket,
                          Aws::String const &key,
                          int &required_retries,
                          bool with_backoff = false);

  uint64_t upload_file(Aws::String const &bucket,
                          Aws::String const &key,
                          int size, char* pBuf);

};

