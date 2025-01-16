# Copyright (C) 2024 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys

import yaml
from generate_helm_values import generate_helm_values


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
    return [node["metadata"]["name"] for node in nodes["items"]]


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
    label_key = label.split("=")[0]  # Extract key from 'key=value' format

    # If specific nodes are provided, use them; otherwise, get all nodes
    nodes_to_clear = node_names if node_names else get_all_nodes()

    for node_name in nodes_to_clear:
        # Check if the node has the label by inspecting its metadata
        command = ["kubectl", "get", "node", node_name, "-o", "json"]
        node_info = run_kubectl_command(command)
        node_metadata = json.loads(node_info)

        # Check if the label exists on this node
        labels = node_metadata["metadata"].get("labels", {})
        if label_key in labels:
            # Remove the label from the node
            command = ["kubectl", "label", "node", node_name, f"{label_key}-"]
            print(f"Removing label {label_key} from node {node_name}...")
            run_kubectl_command(command)
            print(f"Label {label_key} removed from node {node_name} successfully.")
        else:
            print(f"Label {label_key} not found on node {node_name}, skipping.")


def install_helm_release(release_name, chart_name, namespace, values_file, deploy_config):
    """Deploy a Helm release with a specified name and chart.

    Parameters:
    - release_name: The name of the Helm release.
    - chart_name: The Helm chart name or path.
    - namespace: The Kubernetes namespace for deployment.
    - values_file: The user values file for deployment.
    - deploy_config: The deployment configuration dictionary.
    """
    device_type = deploy_config.get("device", "gaudi")
    version = deploy_config.get("version", "1.1.0")

    # Check if the namespace exists; if not, create it
    try:
        command = ["kubectl", "get", "namespace", namespace]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print(f"Namespace '{namespace}' does not exist. Creating it...")
        command = ["kubectl", "create", "namespace", namespace]
        subprocess.run(command, check=True)
        print(f"Namespace '{namespace}' created successfully.")

    # Handle device-specific and rerank values files
    hw_values_file = None
    rerank_values_file = None
    untar_dir = None

    if device_type == "gaudi":
        print("Device type is gaudi. Pulling Helm chart to get values files...")
        
        # Get LLM engine from config
        llm_engine = deploy_config.get("services", {}).get("llm", {}).get("engine", "tgi")
        
        # Combine chart_name with fixed prefix
        chart_pull_url = f"oci://ghcr.io/opea-project/charts/{chart_name}"

        # Pull and untar the chart
        subprocess.run(["helm", "pull", chart_pull_url, "--version", version, "--untar"], check=True)

        current_dir = os.getcwd()
        untar_dir = os.path.join(current_dir, chart_name)
        
        if os.path.isdir(untar_dir):
            # Get device-specific values file
            hw_values_file = os.path.join(untar_dir, f"gaudi-{llm_engine}-values.yaml")
            if not os.path.exists(hw_values_file):
                print(f"Warning: {hw_values_file} not found")
                hw_values_file = None
            else:
                print(f"Device-specific values file found: {hw_values_file}")
            
            # Check if rerank is enabled and get rerank values file
            if deploy_config.get("services", {}).get("teirerank", {}).get("enabled", False):
                rerank_values_file = os.path.join(untar_dir, "norerank-values.yaml")
                if not os.path.exists(rerank_values_file):
                    print(f"Warning: {rerank_values_file} not found")
                    rerank_values_file = None
                else:
                    print(f"Rerank values file found: {rerank_values_file}")
        else:
            print(f"Error: Could not find untarred directory for {chart_name}")
            return

    try:
        # Prepare the Helm install command
        command = ["helm", "install", release_name, chart_name, "--namespace", namespace]

        # Append values files in order
        if hw_values_file:
            command.extend(["-f", hw_values_file])
        if rerank_values_file:
            command.extend(["-f", rerank_values_file])
        command.extend(["-f", values_file])

        # Execute the Helm install command
        print(f"Running command: {' '.join(command)}")
        subprocess.run(command, check=True)
        print("Deployment initiated successfully.")
    
    except subprocess.CalledProcessError as e:
        print(f"Error occurred while deploying Helm release: {e}")
    finally:
        # Cleanup: Remove the untarred directory
        if untar_dir and os.path.isdir(untar_dir):
            print(f"Removing temporary directory: {untar_dir}")
            shutil.rmtree(untar_dir)
            print("Temporary directory removed successfully.")


def uninstall_helm_release(release_name, namespace=None):
    """Uninstall a Helm release and clean up resources, optionally delete the namespace if not 'default'."""
    # Default to 'default' namespace if none is specified
    if not namespace:
        namespace = "default"

    try:
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


def update_service(release_name, namespace, deploy_config, chart_name):
    """Update the deployment using helm upgrade with new values.
    
    Args:
        release_name: The helm release name
        namespace: The kubernetes namespace
        deploy_config: The deployment configuration
        chart_name: The chart name for the deployment
    """
    try:
        print(f"Generating new values for deployment update")
        
        # Generate new values file
        node_selector = {"node-type": "opea-benchmark"}  # Using default label
        result = generate_helm_values(
            example_type=chart_name,
            node_selector=node_selector,
            deploy_config=deploy_config
        )
        
        if result["status"] != "success":
            raise ValueError(f"Failed to generate values file: {result['message']}")
            
        values_file = result["filepath"]
        
        print(f"Updating deployment using new values file")
        
        # Construct helm upgrade command
        command = [
            "helm",
            "upgrade",
            release_name,
            chart_name,
            "--namespace",
            namespace,
            "-f",
            values_file
        ]        
        # Execute helm upgrade
        print(f"Running command: {' '.join(command)}")
        subprocess.run(command, check=True)
        
        print(f"Deployment updated successfully")
        
    except subprocess.CalledProcessError as e:
        print(f"Error updating deployment: {e}")
        raise
    except Exception as e:
        print(f"Error during update: {e}")
        raise
    finally:
        # Cleanup temporary values file
        if 'values_file' in locals() and os.path.exists(values_file):
            os.remove(values_file)


def main():
    parser = argparse.ArgumentParser(description="Manage Helm Deployment.")
    parser.add_argument(
        "--chart-name",
        type=str,
        default="chatqna",
        help="The chart name to deploy (default: chatqna).",
    )
    parser.add_argument("--namespace", default="default", help="Kubernetes namespace (default: default).")
    parser.add_argument("--hf-token", help="Hugging Face API token.")
    parser.add_argument(
        "--model-dir", help="Model directory, mounted as volumes for service access to pre-downloaded models"
    )
    parser.add_argument("--user-values", help="Path to a user-specified values.yaml file.")
    parser.add_argument("--deploy-config", help="Path to a deploy config yaml file.")
    parser.add_argument(
        "--create-values-only", action="store_true", help="Only create the values.yaml file without deploying."
    )
    parser.add_argument("--uninstall", action="store_true", help="Uninstall the Helm release.")
    parser.add_argument("--add-label", action="store_true", help="Add label to specified nodes if this flag is set.")
    parser.add_argument(
        "--delete-label", action="store_true", help="Delete label from specified nodes if this flag is set."
    )
    parser.add_argument(
        "--label", default="node-type=opea-benchmark", help="Label to add/delete (default: node-type=opea-benchmark)."
    )
    parser.add_argument("--update-service", action="store_true", help="Update the deployment with new configuration.")

    args = parser.parse_args()

    # Load deploy_config first if provided
    deploy_config = None
    if args.deploy_config:
        try:
            with open(args.deploy_config, 'r') as f:
                deploy_config = yaml.safe_load(f)
                
            # Only override necessary arguments from deploy_config
            if deploy_config:
                args.model_dir = deploy_config.get("modelUseHostPath", args.model_dir)
                args.hf_token = deploy_config.get("HUGGINGFACEHUB_API_TOKEN", args.hf_token)
                    
        except Exception as e:
            parser.error(f"Failed to load deploy_config: {str(e)}")
            return

    # Node labeling management
    if args.add_label:
        if not deploy_config:
            parser.error("--deploy-config is required for node labeling")
        node_names = deploy_config.get("node_names", [])
        num_nodes = deploy_config.get("node", 1)
        add_labels_to_nodes(num_nodes, args.label, node_names)
        return
    elif args.delete_label:
        if not deploy_config:
            parser.error("--deploy-config is required for node labeling")
        node_names = deploy_config.get("node_names", [])
        clear_labels_from_nodes(args.label, node_names)
        return

    # Uninstall Helm release if specified
    if args.uninstall:
        uninstall_helm_release(args.chart_name, args.namespace)
        return

    # Handle service update if specified
    if args.update_service:
        if not args.deploy_config:
            parser.error("--deploy-config is required for service update")
            
        try:
            update_service(
                args.chart_name,  # Use chart_name as release_name
                args.namespace,
                deploy_config,
                args.chart_name
            )
            return
        except Exception as e:
            parser.error(f"Failed to update deployment: {str(e)}")
            return

    # Prepare values.yaml if not uninstalling
    if args.user_values:
        values_file_path = args.user_values
    else:
        if not args.deploy_config:
            parser.error("--deploy-config is required")

        node_selector = {args.label.split("=")[0]: args.label.split("=")[1]}
        
        # Use generate_helm_values with deploy_config
        result = generate_helm_values(
            example_type=args.chart_name,
            node_selector=node_selector,
            deploy_config=deploy_config
        )

        # Check result status
        if result["status"] == "success":
            values_file_path = result["filepath"]
        else:
            parser.error(f"Failed to generate values.yaml: {result['message']}")
            return

    # Read back the generated YAML file for verification
    with open(values_file_path, "r") as file:
        print("Generated YAML contents:")
        print(file.read())

    # Deploy unless --create-values-only is specified
    if not args.create_values_only:
        install_helm_release(
            args.chart_name,  # Use chart_name as release_name
            args.chart_name,
            args.namespace,
            values_file_path,
            deploy_config
        )


if __name__ == "__main__":
    main()
