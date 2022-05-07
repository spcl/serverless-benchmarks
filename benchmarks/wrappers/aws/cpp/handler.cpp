
#include <aws/core/Aws.h>
#include <aws/lambda-runtime/runtime.h>
#include <aws/s3/S3Client.h>


aws::lambda_runtime::invocation_response handler(aws::lambda_runtime::invocation_request const &req);

int main()
{
    Aws::SDKOptions options;
    Aws::InitAPI(options);
    {
        aws::lambda_runtime::run_handler(handler);
    }
    Aws::ShutdownAPI(options);
    return 0;
}

