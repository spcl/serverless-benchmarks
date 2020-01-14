import subprocess

def execute(cmd):

    ret = subprocess.run(cmd.split(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if ret.returncode:
        raise RuntimeError('Running {} failed!\n Output: {}'.format(cmd, ret.stdout.decode('utf-8')))

def login(secrets):

    appId = secrets.get('appId')
    tenant = secrets.get('tenant')
    password = secrets.get('password')

    # create service principal
    if not appId or not tenant or not password:
        pass

    execute('az login -u {0} --service-principal --tenant {1} -p {2}'.format(appId, tenant, password))
