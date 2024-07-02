import subprocess
import shutil

def run_command(command, check=True):
    try:
        subprocess.run(command, shell=True, check=check)
    except subprocess.CalledProcessError as e:
        print(f"Error occurred: {e}")
        exit(1)

def is_installed(command):
    return shutil.which(command) is not None

def install_minikube():
    if is_installed("minikube"):
        print("Minikube is already installed.")
    else:
        print("Installing Minikube...")
        run_command("curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64")
        run_command("sudo install minikube-linux-amd64 /usr/local/bin/minikube && rm minikube-linux-amd64")

def install_kubectl():
    if is_installed("kubectl"):
        print("kubectl is already installed.")
    else:
        print("Installing kubectl...")
        run_command('curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"')
        run_command('curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl.sha256"')
        run_command('echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check')
        run_command("sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl")

def install_cosign():
    if is_installed("cosign"):
        print("Cosign is already installed.")
    else:
        print("Installing Cosign...")
        run_command('curl -O -L "https://github.com/sigstore/cosign/releases/latest/download/cosign-linux-amd64"')
        run_command('sudo mv cosign-linux-amd64 /usr/local/bin/cosign')
        run_command('sudo chmod +x /usr/local/bin/cosign')

def install_jq():
    if is_installed("jq"):
        print("jq is already installed.")
    else:
        print("Installing jq...")
        run_command('sudo apt-get update && sudo apt-get install -y jq')

def install_knative():
    print("Extracting images from the manifest and verifying signatures...")
    run_command(
        'curl -sSL https://github.com/knative/serving/releases/download/knative-v1.14.1/serving-core.yaml '
        '| grep "gcr.io/" | awk \'{print $2}\' | sort | uniq '
        '| xargs -n 1 cosign verify -o text '
        '--certificate-identity=signer@knative-releases.iam.gserviceaccount.com '
        '--certificate-oidc-issuer=https://accounts.google.com'
    )

    print("Installing Knative Serving component...")
    run_command('kubectl apply -f https://github.com/knative/serving/releases/download/knative-v1.14.1/serving-crds.yaml')
    run_command('kubectl apply -f https://github.com/knative/serving/releases/download/knative-v1.14.1/serving-core.yaml')

    print("Installing Knative Kourier networking layer...")
    run_command('kubectl apply -f https://github.com/knative/net-kourier/releases/download/knative-v1.14.0/kourier.yaml')
    run_command('kubectl patch configmap/config-network '
                '--namespace knative-serving '
                '--type merge '
                '--patch \'{"data":{"ingress-class":"kourier.ingress.networking.knative.dev"}}\'')

    print("Fetching External IP address or CNAME...")
    run_command('kubectl --namespace kourier-system get service kourier')

    print("Verifying Knative Serving installation...")
    run_command('kubectl get pods -n knative-serving')

def main():
    install_minikube()
    install_kubectl()
    install_cosign()
    install_jq()
    install_knative()

if __name__ == "__main__":
    main()
