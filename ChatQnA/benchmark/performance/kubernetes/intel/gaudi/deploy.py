# Copyright (C) 2024 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

import os
import subprocess
import json
import argparse
import yaml
from create_values_yaml import create_values_yaml

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

def add_label_to_node(node_name, label):
    """Add a label to the specified node."""
    command = ["kubectl", "label", "node", node_name, label, "--overwrite"]
    print(f"Labeling node {node_name} with {label}...")
    run_kubectl_command(command)
    print(f"Label {label} added to node {node_name} successfully.")

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

def clear_labels_from_nodes(label, node_names=None):
    """Clear the specified label from specific nodes if provided, otherwise from all nodes."""
    label_key = label.split('=')[0]  # Extract key from 'key=value' format

    # If specific nodes are provided, use them; otherwise, get all nodes
    nodes_to_clear = node_names if node_names else get_all_nodes()

    for node_name in nodes_to_clear:
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

def install_helm_release(release_name, chart_name, namespace, hftoken, modeldir, values_file=None):
    """Deploy a Helm release with specified name and chart."""

    # Check if the namespace exists; if not, create it
    try:
        # Check if the namespace exists
        command = ["kubectl", "get", "namespace", namespace]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        # Namespace does not exist, create it
        print(f"Namespace '{namespace}' does not exist. Creating it...")
        command = ["kubectl", "create", "namespace", namespace]
        subprocess.run(command, check=True)
        print(f"Namespace '{namespace}' created successfully.")

    # Prepare the Helm install command
    command = [
        "helm", "install", release_name, chart_name,
        "--namespace", namespace,
        "--set", f"global.HUGGINGFACEHUB_API_TOKEN={hftoken}",
        "--set", f"global.modelUseHostPath={modeldir}"
    ]

    # Append custom values file if provided
    if values_file and os.path.exists(values_file):
        command.extend(["-f", values_file])

    # Execute the Helm install command
    try:
        print(f"Running command: {' '.join(command)}")  # Print full command for debugging
        subprocess.run(command, check=True)
        print("Deployment initiated successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Error occurred while deploying Helm release: {e}")

def uninstall_helm_release(release_name, namespace=None, label=None, node_names=None):
    """Uninstall a Helm release and clean up resources, optionally delete the namespace if not 'default'."""
    # Default to 'default' namespace if none is specified
    if not namespace:
        namespace = "default"

    try:
        # If node_count and label are specified, clear the labels from the nodes
        if label:
            print("Clearing node labels...")
            clear_labels_from_nodes(label, node_names)

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
    parser = argparse.ArgumentParser(description="Manage Helm Deployment.")
    parser.add_argument("--release-name", type=str, default="chatqna",
                        help="The Helm release name created during deployment (default: chatqna).")
    parser.add_argument("--chart-name", type=str, default="opea/chatqna",
                        help="The chart name to deploy (default: opea/chatqna).")
    parser.add_argument("--namespace", default="default",
                        help="Kubernetes namespace (default: default).")
    parser.add_argument("--hftoken",
                        help="Hugging Face API token (required unless --uninstall is specified).")
    parser.add_argument("--modeldir",
                        help="Model directory, mounted as volumes for service access to pre-downloaded models (required unless --uninstall is specified).")
    parser.add_argument("--repo-url", default="https://opea-project.github.io/GenAIInfra",
                        help="Helm repository URL (default: https://opea-project.github.io/GenAIInfra).")
    parser.add_argument("--user-values",
                        help="Path to a user-specified values.yaml file.")
    parser.add_argument("--create-values-only", action="store_true",
                        help="Only create the values.yaml file without deploying.")
    parser.add_argument("--uninstall", action="store_true",
                        help="Uninstall the Helm release.")
    parser.add_argument("--num-nodes", type=int, default=1,
                        help="Number of nodes to use (default: 1).")
    parser.add_argument("--node-names", nargs='*',
                        help="Optional specific node names to label.")
    parser.add_argument("--label", default="node-type=opea",
                        help="Label to add to nodes (default: node-type=opea).")
    parser.add_argument("--with-rerank", action="store_true",
                        help="Include rerank service in the deployment.")
    parser.add_argument("--tuned", action="store_true",
                        help="Modify resources for services and change extraCmdArgs when creating values.yaml.")

    args = parser.parse_args()

    # Validate required arguments based on the action
    if not args.uninstall:
        if not args.hftoken or not args.modeldir:
            parser.error("--hftoken and --modeldir are required unless --uninstall is specified.")

    # Check if the uninstall flag is set
    if args.uninstall:
        uninstall_helm_release(args.release_name, args.namespace, args.label, args.node_names)
        return

    # Add Helm repo
    add_helm_repo("opea", args.repo_url, args.namespace)

    # Add labels to nodes
    add_labels_to_nodes(args.num_nodes, args.label, args.node_names)

    # Use provided values.yaml or create a new one
    if args.user_values:
        # If user-specified values.yaml is provided, deploy with it
        values_file_path = args.user_values
    else:
        # Prepare node selector from args.label
        node_selector = {args.label.split('=')[0]: args.label.split('=')[1]} if args.label else {}
        # Otherwise, create a new values.yaml using create_values_yaml function
        values_file_path = create_values_yaml(
            with_rerank=args.with_rerank,
            num_nodes=args.num_nodes,
            hftoken=args.hftoken,
            modeldir=args.modeldir,
            node_selector=node_selector,
            tune=args.tuned
        )

    # Deploy if the user did not specify --create-values-only
    if not args.create_values_only:
        install_helm_release(
                args.release_name,
                args.chart_name,
                args.namespace,
                args.hftoken,
                args.modeldir,
                values_file_path)

if __name__ == "__main__":
    main()

