#!/usr/bin/env bash

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

#
# Allocate a Kind cluster with Knative, Kourier and a local container registry.
#

init() {
        find_executables
        populate_environment
        define_colors
}

find_executables() {
        KUBECTL=$(find_executable "kubectl")
        KIND=$(find_executable "kind")
        HELM=$(find_executable "helm")
        JQ=$(find_executable "jq")
}

populate_environment() {
        export ARCH="${ARCH:-amd64}"
        export CONTAINER_ENGINE=${CONTAINER_ENGINE:-docker}
        export KUBECONFIG="${KUBECONFIG:-$(dirname "$(realpath "$0")")/bin/kubeconfig.yaml}"
        export TERM="${TERM:-dumb}"
        echo "KUBECONFIG=${KUBECONFIG}"
}

define_colors() {
        # For some reason TERM=dumb results in the tput commands exiting 1.  It must
        # not support that terminal type. A reasonable fallback should be "xterm".
        local TERM="$TERM"
        if [[ -z "$TERM" || "$TERM" == "dumb" ]]; then
                TERM="xterm" # Set TERM to a tput-friendly value when undefined or "dumb".
        fi
        # shellcheck disable=SC2155
        red=$(tput bold)$(tput setaf 1)
        # shellcheck disable=SC2155
        green=$(tput bold)$(tput setaf 2)
        # shellcheck disable=SC2155
        blue=$(tput bold)$(tput setaf 4)
        # shellcheck disable=SC2155
        grey=$(tput bold)$(tput setaf 8)
        # shellcheck disable=SC2155
        yellow=$(tput bold)$(tput setaf 11)
        # shellcheck disable=SC2155
        reset=$(tput sgr0)
}

# find returns the path to an executable by name.
# An environment variable FUNC_TEST_$name takes precidence.
# Next is an executable matching the name in hack/bin/
# (the install location of hack/install-binaries.sh)
# Finally, a matching executable from the current PATH is used.
find_executable() {
        local name="$1" # requested binary name
        local path=""   # the path to output

        # Use the environment variable if defined
        local env=$(echo "FUNC_TEST_$name" | awk '{print toupper($0)}')
        local path="${!env:-}"
        if [[ -x "$path" ]]; then
                echo "$path" &
                return 0
        fi

        # Use the binary installed into hack/bin/ by allocate.sh if
        # it exists.
        path=$(dirname "$(realpath "$0")")"/bin/$name"
        if [[ -x "$path" ]]; then
                echo "$path" &
                return 0
        fi

        # Finally fallback to anything matchin in the current PATH
        path=$(command -v "$name")
        if [[ -x "$path" ]]; then
                echo "$path" &
                return 0
        fi

        echo "Error: ${name} not found." >&2
        return 1
}

set -o errexit
set -o nounset
set -o pipefail

set_versions() {
        # Note: Kubernetes Version node image per Kind releases (full hash is suggested):
        # https://github.com/kubernetes-sigs/kind/releases
        kind_node_version=v1.29.2@sha256:51a1434a5397193442f0be2a297b488b6c919ce8a3931be0ce822606ea5ca245
        knative_serving_version="v$(get_latest_release_version "knative" "serving")"
        knative_eventing_version="v$(get_latest_release_version "knative" "eventing")"
        contour_version="v$(get_latest_release_version "knative-extensions" "net-contour")"
}

main() {
        echo "${blue}Allocating${reset}"

        set_versions
        kubernetes
        loadbalancer

        echo "${blue}Beginning Cluster Configuration${reset}"
        echo "Tasks will be executed in parallel.  Logs will be prefixed:"
        echo "svr:  Serving, DNS and Networking"
        echo "evt:  Eventing and Namespace"
        echo "reg:  Local Registry"
        echo ""

        (
                set -o pipefail
                (serving && dns && networking) 2>&1 | sed -e 's/^/svr /'
        ) &
        (
                set -o pipefail
                (eventing && namespace) 2>&1 | sed -e 's/^/evt /'
        ) &
        (
                set -o pipefail
                registry 2>&1 | sed -e 's/^/reg /'
        ) &

        local job
        for job in $(jobs -p); do
                wait "$job"
        done

        next_steps

        echo -e "\n${green}🎉 DONE${reset}\n"
}

# Retrieve latest version from given Knative repository tags
# On 'main' branch the latest released version is returned
# On 'release-x.y' branch the latest patch version for 'x.y.*' is returned
# Similar to hack/library.sh get_latest_knative_yaml_source()
function get_latest_release_version() {
        local org_name="$1"
        local repo_name="$2"
        local major_minor=""
        if is_release_branch; then
                local branch_name
                branch_name="$(current_branch)"
                major_minor="${branch_name##release-}"
        fi
        local version
        version="$(git ls-remote --tags --ref https://github.com/"${org_name}"/"${repo_name}".git |
                grep "${major_minor}" |
                cut -d '-' -f2 |
                cut -d 'v' -f2 |
                sort -Vr |
                head -n 1)"
        echo "${version}"
}

# Returns whether the current branch is a release branch.
function is_release_branch() {
        [[ $(current_branch) =~ ^release-[0-9\.]+$ ]]
}

# Returns the current branch.
# Taken from knative/hack. The function covers Knative CI use cases and local variant.
function current_branch() {
        local branch_name=""
        # Get the branch name from Prow's env var, see https://github.com/kubernetes/test-infra/blob/master/prow/jobs.md.
        # Otherwise, try getting the current branch from git.
        ((${IS_PROW:-})) && branch_name="${PULL_BASE_REF:-}"
        [[ -z "${branch_name}" ]] && branch_name="${GITHUB_BASE_REF:-}"
        [[ -z "${branch_name}" ]] && branch_name="$(git rev-parse --abbrev-ref HEAD)"
        echo "${branch_name}"
}

kubernetes() {
        cat <<EOF | $KIND create cluster --name=func --kubeconfig="${KUBECONFIG}" --wait=60s --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    image: kindest/node:${kind_node_version}
    extraPortMappings:
    - containerPort: 80
      hostPort: 80
      listenAddress: "127.0.0.1"
    - containerPort: 433
      hostPort: 443
      listenAddress: "127.0.0.1"
    - containerPort: 30022
      hostPort: 30022
      listenAddress: "127.0.0.1"
containerdConfigPatches:
- |-
  [plugins."io.containerd.grpc.v1.cri".registry.mirrors."localhost:50000"]
    endpoint = ["http://func-registry:5000"]
  [plugins."io.containerd.grpc.v1.cri".registry.mirrors."registry.default.svc.cluster.local:5000"]
    endpoint = ["http://func-registry:5000"]
  [plugins."io.containerd.grpc.v1.cri".registry.mirrors."ghcr.io"]
    endpoint = ["http://func-registry:5000"]
  [plugins."io.containerd.grpc.v1.cri".registry.mirrors."quay.io"]
    endpoint = ["http://func-registry:5000"]
EOF
        sleep 10
        $KUBECTL wait pod --for=condition=Ready -l '!job-name' -n kube-system --timeout=5m
        echo "${green}✅ Kubernetes${reset}"
}

serving() {
        echo "${blue}Installing Serving${reset}"
        echo "Version: ${knative_serving_version}"

        $KUBECTL apply --filename https://github.com/knative/serving/releases/download/knative-$knative_serving_version/serving-crds.yaml

        sleep 2
        $KUBECTL wait --for=condition=Established --all crd --timeout=5m

        curl -L -s https://github.com/knative/serving/releases/download/knative-$knative_serving_version/serving-core.yaml | $KUBECTL apply -f -

        sleep 2
        $KUBECTL wait pod --for=condition=Ready -l '!job-name' -n knative-serving --timeout=5m

        $KUBECTL get pod -A
        echo "${green}✅ Knative Serving${reset}"
}

dns() {
        echo "${blue}Configuring DNS${reset}"

        i=0
        n=10
        while :; do
                $KUBECTL patch configmap/config-domain \
                        --namespace knative-serving \
                        --type merge \
                        --patch '{"data":{"127.0.0.1.sslip.io":""}}' && break

                ((i += 1))
                if ((i >= n)); then
                        echo "Unable to set knative domain"
                        exit 1
                fi
                echo 'Retrying...'
                sleep 5
        done
        echo "${green}✅ DNS${reset}"
}

loadbalancer() {
        echo "${blue}Installing Load Balancer (Metallb)${reset}"
        $KUBECTL apply -f "https://raw.githubusercontent.com/metallb/metallb/v0.13.7/config/manifests/metallb-native.yaml"
        sleep 5
        $KUBECTL wait --namespace metallb-system \
                --for=condition=ready pod \
                --selector=app=metallb \
                --timeout=300s

        local kind_addr
        kind_addr="$($CONTAINER_ENGINE container inspect func-control-plane | jq '.[0].NetworkSettings.Networks.kind.IPAddress' -r)"

        echo "Setting up address pool."
        $KUBECTL apply -f - <<EOF
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: example
  namespace: metallb-system
spec:
  addresses:
  - ${kind_addr}-${kind_addr}
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: empty
  namespace: metallb-system
EOF
        echo "${green}✅ Loadbalancer${reset}"
}

networking() {
        echo "${blue}Installing Ingress Controller (Contour)${reset}"
        echo "Version: ${contour_version}"

        echo "Installing a configured Contour."
        $KUBECTL apply -f "https://github.com/knative/net-contour/releases/download/knative-${contour_version}/contour.yaml"
        sleep 5
        $KUBECTL wait pod --for=condition=Ready -l '!job-name' -n contour-external --timeout=10m

        echo "Installing the Knative Contour controller."
        $KUBECTL apply -f "https://github.com/knative/net-contour/releases/download/knative-${contour_version}/net-contour.yaml"
        sleep 5
        $KUBECTL wait pod --for=condition=Ready -l '!job-name' -n knative-serving --timeout=10m

        echo "Configuring Knative Serving to use Contour."
        $KUBECTL patch configmap/config-network \
                --namespace knative-serving \
                --type merge \
                --patch '{"data":{"ingress-class":"contour.ingress.networking.knative.dev"}}'

        $KUBECTL wait pod --for=condition=Ready -l '!job-name' -n contour-external --timeout=10m
        $KUBECTL wait pod --for=condition=Ready -l '!job-name' -n knative-serving --timeout=10m
        echo "${green}✅ Ingress${reset}"
}

eventing() {
        echo "${blue}Installing Eventing${reset}"
        echo "Version: ${knative_eventing_version}"

        $KUBECTL apply --filename https://github.com/knative/eventing/releases/download/knative-$knative_eventing_version/eventing-crds.yaml
        sleep 2
        $KUBECTL wait --for=condition=Established --all crd --timeout=5m

        curl -L -s https://github.com/knative/eventing/releases/download/knative-$knative_eventing_version/eventing-core.yaml | $KUBECTL apply -f -
        sleep 2
        $KUBECTL wait pod --for=condition=Ready -l '!job-name' -n knative-eventing --timeout=5m

        $KUBECTL get pod -A
        echo "${green}✅ Knative Eventing${reset}"
}

namespace() {
        echo "${blue}Creating Namespace${reset}"

        $KUBECTL create namespace func
        $KUBECTL label namespace func knative-eventing-injection=enabled
        $KUBECTL label namespace func knative-serving-injection=enabled
        echo "${green}✅ Namespace${reset}"
}

registry() {
        echo "${blue}Local Registry${reset}"

        local kind_addr
        kind_addr="$($CONTAINER_ENGINE container inspect func-control-plane | jq '.[0].NetworkSettings.Networks.kind.IPAddress' -r)"
        $KUBECTL apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: func-registry
  namespace: func
  labels:
    k8s-app: func-registry
spec:
  containers:
  - name: registry
    image: registry:2
    resources: {}
    ports:
    - containerPort: 5000
      hostPort: 5000
      protocol: TCP
  nodeSelector:
    kubernetes.io/hostname: func-control-plane
EOF
        echo "${green}✅ Registry${reset}"
}

next_steps() {
        echo "${blue}Next Steps${reset}"

        echo "To access the cluster and manage resources, use:"
        echo "$ export KUBECONFIG=\"$(dirname "$(realpath "$0")")/kubeconfig\""
        echo "$ $KUBECTL get pod --namespace func"
        echo "$ $KUBECTL get service --namespace func"
        echo "$ $KUBECTL get svc --namespace knative-serving"
        echo "$ $KUBECTL get svc --namespace knative-eventing"
        echo "$ $KUBECTL get all --all-namespaces"
        echo "$ $KUBECTL get pods --all-namespaces"
        echo "$ $KUBECTL describe configmaps config-domain --namespace knative-serving"
        echo "Remember to remove the resources to save space with:"
        echo "$ kind delete cluster --name func"
        echo "$ kubectl delete namespace func"
        echo "$ kubectl delete namespace knative-serving"
        echo "$ kubectl delete namespace knative-eventing"
        echo "$ kubectl delete namespace contour-external"
        echo "$ kubectl delete namespace metallb-system"
        echo "To check for available CLI upgrades, use:"
        echo "$ kind upgrade check latest"
        echo "$ kubectl version --client"
}

init
main