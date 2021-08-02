
SeBS supports three commercial serverless platforms: AWS Lambda, Azure Functions, and Google Cloud
Functions. 

## AWS Lambda

AWS provides one year of free services, including a significant amount of computing time in AWS Lambda.
To work with AWS, you need to provide access and secret keys to a role with permissions
sufficient to manage functions and S3 resources.
Additionally, the account must have `AmazonAPIGatewayAdministrator` permission to set up
automatically AWS HTTP trigger.
You can provide a [role](https://docs.aws.amazon.com/lambda/latest/dg/lambda-intro-execution-role.html)
with permissions to access AWS Lambda and S3; otherwise, one will be created automatically.
To use a user-defined lambda role, set the name in config JSON - see an example in `config/example.json`.

**Pass the credentials as environmental variables for the first run.** They will be cached for future use.

```
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
```

## Azure Functions

Azure provides a free tier for 12 months.
You need to create an account and add a [service principal](https://docs.microsoft.com/en-us/azure/active-directory/develop/howto-create-service-principal-portal)
to enable non-interactive login through CLI.
Since this process has [an easy, one-step CLI solution](https://docs.microsoft.com/en-us/cli/azure/ad/sp?view=azure-cli-latest#az-ad-sp-create-for-rbac),
we added a small tool **tools/create_azure_credentials** that uses the interactive web-browser
authentication to login into Azure CLI and create a service principal.

```console
Please provide the intended principal name                                                                                                         
XXXXX
Please follow the login instructions to generate credentials...                                                            
To sign in, use a web browser to open the page https://microsoft.com/devicelogin and enter the code YYYYYYY to authenticate.

Login succesfull with user {'name': 'ZZZZZZ', 'type': 'user'}                                          
Created service principal http://XXXXX

AZURE_SECRET_APPLICATION_ID = XXXXXXXXXXXXXXXX
AZURE_SECRET_TENANT = XXXXXXXXXXXX
AZURE_SECRET_PASSWORD = XXXXXXXXXXXXX
```

**Save these credentials - the password is non-retrievable! Provide them to SeBS through environmental variables**,
and we will create additional resources (storage account, resource group) to deploy functions.
We will create a storage account and the resource group and handle access keys.

### Resources

* By default, all functions are allocated in the single resource group.
* Each function has a seperate storage account allocated, following [Azure guidelines](https://docs.microsoft.com/en-us/azure/azure-functions/functions-best-practices#scalability-best-practices).
* All benchmark data is stored in the same storage account.

## Google Cloud Functions

The Google Cloud Free Tier gives free resources. It has two parts:

- A 12-month free trial with $300 credit to use with any Google Cloud services.
- Always Free, which provides limited access to many common Google Cloud resources, free of charge.

You need to create an account and add [service account](https://cloud.google.com/iam/docs/service-accounts) to permit operating on storage and functions.

**Pass the project name and service account's JSON key path in config JSON, see an example in `config/example.json`**

