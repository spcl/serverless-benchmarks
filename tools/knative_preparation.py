# This Script can be used to spinup a knative enabled kubernetes cluster (We are using Minikube here, you can also use k3s).

import logging
import subprocess
import shutil
import os
import stat

def run_command(command, check=True):
    try:
        subprocess.run(command, check=check)
    except subprocess.CalledProcessError as e:
        logging.error(f"Error occurred: {e}")
        exit(1)

def is_installed(command):
    return shutil.which(command) is not None

def install_minikube():
    if is_installed("minikube"):
        print("Minikube is already installed.")
    else:
        print("Installing Minikube...")
        run_command("curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64")
        run_command("install minikube-linux-amd64 ~/.local/bin/minikube && rm minikube-linux-amd64")

def install_kubectl():
    if is_installed("kubectl"):
        print("kubectl is already installed.")
    else:
        print("Installing kubectl...")
        run_command('curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"')
        run_command('curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl.sha256"')
        run_command('echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check')
        run_command("install kubectl ~/.local/bin/kubectl")

def install_cosign():
    if is_installed("cosign"):
        print("Cosign is already installed.")
    else:
        print("Installing Cosign...")
        run_command('curl -O -L "https://github.com/sigstore/cosign/releases/latest/download/cosign-linux-amd64"')
        run_command('install cosign-linux-amd64 ~/.local/bin/cosign')
        os.chmod(os.path.expanduser('~/.local/bin/cosign'), stat.S_IXUSR | stat.S_IRUSR | stat.S_IWUSR)

def install_knative():
    logging.info("Extracting images from the manifest and verifying signatures...")
    run_command(
        'curl -sSL https://github.com/knative/serving/releases/download/knative-v1.14.1/serving-core.yaml '
        '| grep "gcr.io/" | awk \'{print $2}\' | sort | uniq '
        '| xargs -n 1 cosign verify -o text '
        '--certificate-identity=signer@knative-releases.iam.gserviceaccount.com '
        '--certificate-oidc-issuer=https://accounts.google.com'
    )

    logging.info("Installing Knative Serving component...")
    run_command('kubectl apply -f https://github.com/knative/serving/releases/download/knative-v1.14.1/serving-crds.yaml')
    run_command('kubectl apply -f https://github.com/knative/serving/releases/download/knative-v1.14.1/serving-core.yaml')

    logging.info("Installing Knative Kourier networking layer...")
    run_command('kubectl apply -f https://github.com/knative/net-kourier/releases/download/knative-v1.14.0/kourier.yaml')
    run_command('kubectl patch configmap/config-network '
                '--namespace knative-serving '
                '--type merge '
                '--patch \'{"data":{"ingress-class":"kourier.ingress.networking.knative.dev"}}\'')

    logging.info("Fetching External IP address or CNAME...")
    run_command('kubectl --namespace kourier-system get service kourier')

    logging.info("Verifying Knative Serving installation...")
    run_command('kubectl get pods -n knative-serving')

def main():
    install_minikube()
    install_kubectl()
    install_cosign()
    install_knative()

if __name__ == "__main__":
    main()
