import os

def function_name(
    fname: str,
    language: str,
    version: str,
    trigger: str
):
    app_name = os.getenv('APP_NAME')
    app_name = app_name[:app_name.rfind('-')]

    storage_account = os.getenv('ACCOUNT_ID')
    storage_account = storage_account[7:]

    full_name = f"{app_name}-{fname}-{language}-{version}-{storage_account}-{trigger}"
    full_name = full_name.replace(".", "-")
    full_name = full_name.replace("_", "-")

    return full_name

def object_path(path: str, key: str):
    app_name = os.getenv('APP_NAME')
    path = f"{app_name}-{path}/{key}"
    path = path.replace("_", "-")

    return path
