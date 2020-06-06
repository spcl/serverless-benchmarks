#!/usr/bin/env bash
if ! minikube version
then
  echo "ERROR: \"minikube\" required."
  exit 1
fi
minikube start --vm-driver=docker
if ! kubectl version
then
  echo "ERROR: \"kubectl\" required."
  exit 1
fi
if ! helm version
then
  echo "ERROR: \"helm\" required."
  exit 1
fi
export FISSION_NAMESPACE=fission-local-suu
if ! kubectl get namespace | grep $FISSION_NAMESPACE
then
  echo "No proper fission namespace... Installing Fission as ${FISSION_NAMESPACE}..."
  kubectl create namespace $FISSION_NAMESPACE
  helm install --namespace $FISSION_NAMESPACE --name-template fission https://github.com/fission/fission/releases/download/1.9.0/fission-all-1.9.0.tgz
fi
if ! fission > /dev/null 2>&1
then
  echo "No fission CLI - installing..."
  case $(uname | tr '[:upper:]' '[:lower:]') in
    linux*)
      export FISSION_OS_NAME=linux
      ;;
    darwin*)
      export FISSION_OS_NAME=osx
      ;;
  esac
  curl -Lo fission https://github.com/fission/fission/releases/download/1.9.0/fission-cli-${FISSION_OS_NAME} && chmod +x fission && sudo mv fission /usr/local/bin/
fi
echo "Fission is ready to use"
