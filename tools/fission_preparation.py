import subprocess


def run_minikube(vm_driver="docker"):
    try:
        kube_status = subprocess.run(
            "minikube status".split(), stdout=subprocess.PIPE
        )

        # if minikube is already running,
        # error will be raised to prevent to be started minikube again.
        subprocess.run(
            "grep Stopped".split(),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            input=kube_status.stdout,
        )
        try:
            print("Starting minikube...")
            subprocess.run(
                f"minikube start --vm-driver={vm_driver}".split(), check=True
            )
        except subprocess.CalledProcessError:
            raise ChildProcessError

    except subprocess.CalledProcessError:
        try:
            subprocess.run(
                "grep unusually".split(),
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                input=kube_status.stdout,
            )
            print("Starting minikube...")
            subprocess.run(
                f"minikube start --vm-driver={vm_driver}".split(), check=True
            )
        except subprocess.CalledProcessError:
            print("Minikube already working")
        pass
    except ChildProcessError:
        print("ERROR: COULDN'T START MINIKUBE")
        exit(1)


def install_fission_using_helm(k8s_namespace="fission"):
    fission_url = "https://github.com/fission/fission/releases/download/1.9.0/fission-all-1.9.0.tgz"  # noqa: E501

    try:
        k8s_namespaces = subprocess.run(
            "kubectl get namespace".split(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            f"grep {k8s_namespace}".split(),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            input=k8s_namespaces.stdout,
        )
        print("fission namespace already exist")
    except (subprocess.CalledProcessError):
        print(
            f'No proper fission namespace.Installing Fission as "{k8s_namespace}.."'
        )
        subprocess.run(
            f"kubectl create namespace {k8s_namespace}".split(), check=True
        )
        subprocess.run(
            f"helm install --namespace {k8s_namespace} \
                --name-template fission {fission_url}".split(),
            check=True,
        )


def install_fission_cli():
    try:
        subprocess.run(
            ["fission"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=True,
        )
    except subprocess.CalledProcessError:  # fission cli is not installed
        print("No fission CLI - installing...")
        available_os = {"darwin": "osx", "linux": "linux"}
        import platform

        fission_cli_url = (
            f"https://github.com/fission/fission/releases/download/1.9.0/fission-cli-"  # noqa: E501
            f"{available_os[platform.system().lower()]}"
        )

        subprocess.run(
            f"curl -Lo fission {fission_cli_url} \
            && chmod +x fission \
            && sudo mv fission /usr/local/bin/",
            stdout=subprocess.DEVNULL,
            check=True,
            shell=True,
        )


def check_if_k8s_installed():
    try:
        subprocess.run(
            "kubectl".split(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except subprocess.CalledProcessError:
        print('ERROR: "kubectl" required.')
        exit(1)


def check_if_fission_cli_installed(throws_error=False):
    try:
        subprocess.run(
            ["fission"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=True,
        )
    except subprocess.CalledProcessError:  # fission cli is not installed
        if not throws_error:
            print('ERROR: "fission" not installed or installed incorrectly.')
            exit(1)
        else:
            raise subprocess.CalledProcessError


def check_if_helm_installed():
    try:
        subprocess.run(
            "helm version".split(),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        print('ERROR: "helm" required.')
        exit(1)


def check_if_minikube_installed():
    try:
        subprocess.run(
            "minikube version".split(),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        print('ERROR: "minikube" required.')
        exit(1)


def stop_minikube():
    try:
        subprocess.run(
            "minikube stop".split(),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        print('ERROR: couldn\'t stop minikube.')
        exit(1)
