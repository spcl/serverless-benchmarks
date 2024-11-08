import os

def function_name(
    fname: str,
    language: str,
    version: str,
    trigger: str
):
    app_name = os.getenv('APP_NAME')
    full_name = f"{app_name}_{fname}_{language}_{version}-{trigger}"
    full_name = full_name.replace(".", "_")

    return full_name

def object_path(path: str, key: str):
    app_name = os.getenv('APP_NAME')
    path = f"{app_name}-{path}/{key}"
    path = path.replace("_", "-")

    return path
