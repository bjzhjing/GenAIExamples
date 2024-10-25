import os
import subprocess
import json
import argparse
import yaml

def run_kubectl_command(command):
    """Run a kubectl command and return the output."""
    try:
        result = subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {command}\n{e.stderr}")
        exit(1)

def get_all_nodes():
    """Get the list of all nodes in the Kubernetes cluster."""
    command = ["kubectl", "get", "nodes", "-o", "json"]
    output = run_kubectl_command(command)
    nodes = json.loads(output)
    return [node['metadata']['name'] for node in nodes['items']]

def add_labels_to_nodes(node_count=None, label=None, node_names=None):
    """Add a label to the specified number of nodes or to specified nodes."""

    if node_names:
        # Add label to the specified nodes
        for node_name in node_names:
            add_label_to_node(node_name, label)
    else:
        # Fetch the node list and label the specified number of nodes
        all_nodes = get_all_nodes()
        if node_count is None or node_count > len(all_nodes):
            print(f"Error: Node count exceeds the number of available nodes ({len(all_nodes)} available).")
            sys.exit(1)

        selected_nodes = all_nodes[:node_count]
        for node_name in selected_nodes:
            add_label_to_node(node_name, label)

def clear_labels_from_nodes(label):
    """Clear the specified label from all nodes that have it."""
    all_nodes = get_all_nodes()
    label_key = label.split('=')[0]  # Extract key from 'key=value' format

    for node_name in all_nodes:
        # Check if the node has the label by inspecting its metadata
        command = ["kubectl", "get", "node", node_name, "-o", "json"]
        node_info = run_kubectl_command(command)
        node_metadata = json.loads(node_info)

        # Check if the label exists on this node
        labels = node_metadata['metadata'].get('labels', {})
        if label_key in labels:
            # Remove the label from the node
            command = ["kubectl", "label", "node", node_name, f"{label_key}-"]
            print(f"Removing label {label_key} from node {node_name}...")
            run_kubectl_command(command)
            print(f"Label {label_key} removed from node {node_name} successfully.")
        else:
            print(f"Label {label_key} not found on node {node_name}, skipping.")

def add_helm_repo(repo_name, repo_url, namespace):
    """Add Helm repo if it doesn't exist."""
    command = ["helm", "repo", "add", repo_name, repo_url]
    try:
        subprocess.run(command, check=True)
        print(f"Added Helm repo {repo_name} from {repo_url}.")
    except subprocess.CalledProcessError:
        print(f"Helm repo {repo_name} already exists.")

def create_values_yaml(with_rerank, num_nodes, hftoken, modeldir, tune=False):
    """Create a values.yaml file based on the provided configuration."""

    # Prepare node selector from args.label
    node_selector = {args.label.split('=')[0]: args.label.split('=')[1]} if args.label else {}

    # Construct the base values dictionary
    values = {
        "global": {
            "HUGGINGFACEHUB_API_TOKEN": hftoken,  # Use passed token
            "modelUseHostPath": modeldir  # Use passed model directory
        },
        "tei": {
            "accelDevice": "gaudi",  # Default accelDevice
            "image": {
                "repository": "ghcr.io/huggingface/tei-gaudi",  # Default repository
                "tag": "latest"  # Default tag
            },
            "nodeSelector": node_selector
        },
        "teirerank": {
            "accelDevice": "gaudi",  # Default accelDevice
            "image": {
                "repository": "ghcr.io/huggingface/tei-gaudi",  # Default repository
                "tag": "latest"  # Default tag
            },
            "nodeSelector": node_selector
        },
        "tgi": {
            "accelDevice": "gaudi",  # Default accelDevice
            "image": {
                "repository": "ghcr.io/huggingface/tgi-gaudi",  # Default repository
                "tag": "2.0.5"  # Default tag
            },
            "nodeSelector": node_selector
        },
        "data-prep": {
            "nodeSelector": node_selector
        },
        "redis-vector-db": {
            "nodeSelector": node_selector
        },
        "retriever": {
            "nodeSelector": node_selector
        },
    }

    # If without rerank, add specific image details
    if not with_rerank:
        values["chatqna"] = {
            "image": {
                "repository": "opea/chatqna-without-rerank",
                "pullPolicy": "IfNotPresent",
                "tag": "latest"
            },
            "nodeSelector": node_selector  # Fill nodeSelector
        }

    default_replicas = [
        {"name": "chatqna", "replicaCount": 2},
        {"name": "tei", "replicaCount": 1},
        {"name": "teirerank", "replicaCount": 1} if with_rerank else None,
        {"name": "tgi", "replicaCount": 6 if with_rerank else 7},
        {"name": "data-prep", "replicaCount": 1},
        {"name": "redis-vector-db", "replicaCount": 1},
        {"name": "retriever", "replicaCount": 2},
    ]

    if num_nodes > 1:
        # Scale replicas based on number of nodes
        replicas = [
            {"name": "chatqna", "replicaCount": 1 * num_nodes},
            {"name": "tei", "replicaCount": 1 * num_nodes},
            {"name": "teirerank", "replicaCount": 1} if with_rerank else None,
            {"name": "tgi", "replicaCount": (8 * num_nodes - 2) if with_rerank else (8 * num_nodes - 1)},
            {"name": "data-prep", "replicaCount": 1},
            {"name": "redis-vector-db", "replicaCount": 1},
            {"name": "retriever", "replicaCount": 1 * num_nodes},
        ]
    else:
        replicas = default_replicas

    # Remove None values for rerank disabled
    replicas = [r for r in replicas if r]

    # Update values.yaml with replicas
    for replica in replicas:
        service_name = replica["name"]
        if service_name in values:
            values[service_name]["replicaCount"] = replica["replicaCount"]
        else:
            values[service_name] = {"replicaCount": replica["replicaCount"], "nodeSelector": node_selector}

    # Prepare resource configurations based on tuning
    resources = []
    if tune:
        resources = [
            {"name": "chatqna", "resources": {"limits": {"cpu": "16", "memory": "8000Mi"}, "requests": {"cpu": "16", "memory": "8000Mi"}}},
            {"name": "tei", "resources": {"limits": {"cpu": "80", "memory": "20000Mi"}, "requests": {"cpu": "80", "memory": "20000Mi"}}},
            {"name": "teirerank", "resources": {"limits": {"habana.ai/gaudi": 1}}} if with_rerank else None,
            {"name": "tgi", "resources": {"limits": {"habana.ai/gaudi": 1}}},
            {"name": "retriever", "resources": {"requests": {"cpu": "8", "memory": "8000Mi"}}},
        ]
        resources = [r for r in resources if r]

    # Add resources for each service if tuning
    if tune:
        for resource in resources:
            service_name = resource["name"]
            if service_name in values:
                values[service_name]["resources"] = resource["resources"]
            else:
                values[service_name] = {"resources": resource["resources"], "nodeSelector": node_selector}

        # Add extraCmdArgs for tgi service with default values
        default_cmd_args = [
            {"name": "--max-input-length", "value": 1280},
            {"name": "--max-total-tokens", "value": 2048},
            {"name": "--max-batch-total-tokens", "value": 65536},
            {"name": "--max-batch-prefill-tokens", "value": 4096}
        ]

        if "tgi" in values:
            values["tgi"]["extraCmdArgs"] = default_cmd_args

    # Write values to a YAML file
    with open('values.yaml', 'w') as file:
        yaml.dump(values, file)

    print("values.yaml has been created successfully.")

def install_chatqna(namespace, hftoken, modeldir, user_values_file=None):
    """Deploy ChatQnA using Helm."""
    command = [
        "helm", "install", "chatqna", "opea/chatqna",
        "--namespace", namespace,
        "--set", f"global.HUGGINGFACEHUB_API_TOKEN={hftoken}",
        "--set", f"global.modelUseHostPath={modeldir}",
        "-f", "values.yaml"
    ]

    # If user provided a values file, add it to the command
    if user_values_file and os.path.exists(user_values_file):
        command.insert(-1, "-f")
        command.insert(-1, user_values_file)

    subprocess.run(command, check=True)
    print("Deployment initiated successfully.")

def uninstall_chatqna(release_name, namespace=None, label=None):
    """Uninstall a Helm release and clean up resources, optionally delete the namespace if not 'default'."""
    # Default to 'default' namespace if none is specified
    if not namespace:
        namespace = "default"

    try:
        # If node_count and label are specified, clear the labels from the nodes
        if label:
            print("Clearing node labels...")
            clear_labels_from_nodes(label)

        # Uninstall the Helm release
        command = ["helm", "uninstall", release_name, "--namespace", namespace]
        print(f"Uninstalling Helm release {release_name} in namespace {namespace}...")
        run_kubectl_command(command)
        print(f"Helm release {release_name} uninstalled successfully.")

        # If the namespace is specified and not 'default', delete it
        if namespace != "default":
            print(f"Deleting namespace {namespace}...")
            delete_namespace_command = ["kubectl", "delete", "namespace", namespace]
            run_kubectl_command(delete_namespace_command)
            print(f"Namespace {namespace} deleted successfully.")
        else:
            print("Namespace is 'default', skipping deletion.")

    except subprocess.CalledProcessError as e:
        print(f"Error occurred while uninstalling Helm release or deleting namespace: {e}")


def main():
    parser = argparse.ArgumentParser(description="Manage ChatQnA Helm Deployment.")
    parser.add_argument("--release-name", type=str, default="chatqna",
                        help="The Helm release name created during deployment (default: chatqna).")
    parser.add_argument("--namespace", default="default",
                        help="Kubernetes namespace (default: default).")
    parser.add_argument("--hftoken", required=True,
                        help="Hugging Face API token.")
    parser.add_argument("--modeldir", required=True,
                        help="Model directory, mounted as volumes for service access to pre-downloaded models.")
    parser.add_argument("--repo-url", default="https://opea-project.github.io/GenAIInfra",
                        help="Helm repository URL (default: https://opea-project.github.io/GenAIInfra).")
    parser.add_argument("--user-values",
                        help="Path to a user-specified values.yaml file.")
    parser.add_argument("--create-values-only", action="store_true",
                        help="Only create the values.yaml file without deploying.")
    parser.add_argument("--uninstall", action="store_true",
                        help="Uninstall ChatQnA.")
    parser.add_argument("--num-nodes", type=int, default=1,
                        help="Number of nodes to use (default: 1).")
    parser.add_argument("--node-names", nargs='*',
                        help="Optional specific node names to label.")
    parser.add_argument("--label", default="chatqna=value",
                        help="Label to add to nodes (default: chatqna=value).")
    parser.add_argument("--with-rerank", action="store_true",
                        help="Include rerank service in ChatQnA.")
    parser.add_argument("--tuned", action="store_true",
                        help="Modify resources for services and change TGI extraCmdArgs when creating values.yaml.")

    args = parser.parse_args()

    # Check if the uninstall flag is set
    if args.uninstall:
        uninstall_chatqna(args.release_name, args.namespace, args.label)
        return

    # Add Helm repo
    add_helm_repo("opea", args.repo_url, args.namespace)

    # Add labels to nodes
    add_labels_to_nodes(args.num_nodes, args.label, args.node_names)

    # Otherwise, proceed with deployment logic
    create_values_yaml(
        with_rerank=args.with_rerank,
        num_nodes=args.num_nodes,
        tune=args.tune
    )

    # Deploy if the user did not specify --create-values-only
    if not args.create_values_only:
        install_chatqna(args.namespace, args.hftoken, args.modeldir)

if __name__ == "__main__":
    main()
