# Copyright (C) 2024 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

import os
from enum import Enum, auto

import yaml

def configure_node_selectors(values, node_selector, deploy_config):
    """Configure node selectors for all services."""
    for service_name, config in deploy_config["services"].items():
        if service_name == "backend":
            values["nodeSelector"] = {key: value for key, value in node_selector.items()}
        elif service_name == "llm":
            engine = config.get("engine", "tgi")
            values[engine] = {"nodeSelector": {key: value for key, value in node_selector.items()}}
        else:
            values[service_name] = {"nodeSelector": {key: value for key, value in node_selector.items()}}
    return values

def configure_replica(values, deploy_config):
    """Get replica configuration based on example type and node count."""
    for service_name, config in deploy_config["services"].items():
        if not config.get("instance_num"):
            continue
            
        if service_name == "llm":
            engine = config.get("engine", "tgi")
            values[engine]["replicaCount"] = config["instance_num"]
        elif service_name == "backend":
            values["replicaCount"] = config["instance_num"]
        else:
            values[service_name]["replicaCount"] = config["instance_num"]

    return values

def get_output_filename(num_nodes, with_rerank, example_type, device, action_type):
    """Generate output filename based on configuration."""
    rerank_suffix = "with-rerank-" if with_rerank else ""
    action_suffix = "deploy-" if action_type == 0 else "update-" if action_type == 1 else ""

    return f"{example_type}-{num_nodes}-{device}-{action_suffix}{rerank_suffix}values.yaml"

def configure_resources(values, deploy_config):
    """Configure resources when tuning is enabled."""
    resource_configs = []
    
    for service_name, config in deploy_config["services"].items():
        resources = {}
        if deploy_config["device"] == "gaudi" and config.get("cards_per_instance", 0) > 1:
            resources = {
                "limits": {"habana.ai/gaudi": config["cards_per_instance"]},
                "requests": {"habana.ai/gaudi": config["cards_per_instance"]},
            }
        else:
            limits = {}
            requests = {}
            
            # Only add CPU if cores_per_instance has a value
            if config.get("cores_per_instance"):
                limits["cpu"] = config["cores_per_instance"]
                requests["cpu"] = config["cores_per_instance"]
                
            # Only add memory if memory_capacity has a value
            if config.get("memory_capacity"):
                limits["memory"] = config["memory_capacity"]
                requests["memory"] = config["memory_capacity"]
                
            # Only create resources if we have any limits/requests
            if limits and requests:
                resources["limits"] = limits
                resources["requests"] = requests

        if resources:
            if service_name == "llm":
                engine = config.get("engine", "tgi")
                resource_configs.append({
                    "name": engine,
                    "resources": resources,
                })
            else:
                resource_configs.append({
                    "name": service_name,
                    "resources": resources,
                })

    for config in [r for r in resource_configs if r]:
        service_name = config["name"]
        if service_name == "backend":
            values["resources"] = config["resources"]
        elif service_name in values:
            values[service_name]["resources"] = config["resources"]

    return values

def configure_extra_cmd_args(values, deploy_config):
    """Configure extra command line arguments for services."""
    for service_name, config in deploy_config["services"].items():
        extra_cmd_args = []
        
        for param in ["max_batch_size", "max_input_length", "max_total_tokens", 
                     "max_batch_total_tokens", "max_batch_prefill_tokens"]:
            if config.get(param):
                extra_cmd_args.extend([f"--{param.replace('_', '-')}", str(config[param])])

        if extra_cmd_args:
            if service_name == "llm":
                engine = config.get("engine", "tgi")
                if engine not in values:
                    values[engine] = {}
                values[engine]["extraCmdArgs"] = extra_cmd_args
            else:
                if service_name not in values:
                    values[service_name] = {}
                values[service_name]["extraCmdArgs"] = extra_cmd_args

    return values

def configure_models(values, deploy_config):
    """Configure model settings for services."""
    for service_name, config in deploy_config["services"].items():
        # Skip if no model_id defined or service is disabled
        if not config.get("model_id") or config.get("enabled") is False:
            continue
            
        if service_name == "llm":
            # For LLM service, use its engine as the key
            engine = config.get("engine", "tgi")
            values[engine]["LLM_MODEL_ID"] = config.get("model_id")
        elif service_name == "tei":
            values[service_name]["EMBEDDING_MODEL_ID"] = config.get("model_id")
        elif service_name == teirerank:
            values[service_name]["RERANK_MODEL_ID"] = config.get("model_id")
            
    return values

def configure_rerank(values, with_rerank, deploy_config, example_type):
    """Configure rerank service"""
    if with_rerank:
        if "teirerank" not in values:
            values["teirerank"] = {"nodeSelector": {key: value for key, value in node_selector.items()}}
        elif "nodeSelector" not in values["teirerank"]:
            values["teirerank"]["nodeSelector"] = {key: value for key, value in node_selector.items()}
    else:
        if example_type == "chatqna":
            values["image"] = {"repository": "opea/chatqna-without-rerank"}
        if "teirerank" not in values:
            values["teirerank"] = {"enabled": False}
        elif "enabled" not in values["teirerank"]:
            values["teirerank"]["enabled"] = False
    return values

def generate_helm_values(example_type, deploy_config, chart_dir, action_type, node_selector=None):
    """Create a values.yaml file based on the provided configuration."""
    if deploy_config is None:
        raise ValueError("deploy_config is required")

    # Ensure the chart_dir exists
    if not os.path.exists(chart_dir):
        return {
            "status": "false",
            "message": f"Chart directory {chart_dir} does not exist"
        }
    
    num_nodes = deploy_config.get("node", 1)
    with_rerank = deploy_config["services"].get("teirerank", {}).get("enabled", False)

    print(f"Generating values for {example_type} example")
    print(f"with_rerank: {with_rerank}")
    print(f"num_nodes: {num_nodes}")
    print(f"node_selector: {node_selector}")

    # Initialize base values
    values = {
        "global": {
            "HUGGINGFACEHUB_API_TOKEN": deploy_config.get("HUGGINGFACEHUB_API_TOKEN", ""),
            "modelUseHostPath": deploy_config.get("modelUseHostPath", ""),
        }
    }

    # Configure components
    values = configure_node_selectors(values, node_selector or {}, deploy_config)
    values = configure_rerank(values, with_rerank, deploy_config, example_type)
    values = configure_replica(values, deploy_config)
    values = configure_resources(values, deploy_config)
    values = configure_extra_cmd_args(values, deploy_config)
    values = configure_models(values, deploy_config)

    device = deploy_config.get("device", "unknown")

    # Generate and write YAML file
    filename = get_output_filename(num_nodes, with_rerank, example_type, device, action_type)
    yaml_string = yaml.dump(values, default_flow_style=False)

    filepath = os.path.join(chart_dir, filename)

    # Write the YAML data to the file
    with open(filepath, "w") as file:
        file.write(yaml_string)

    print(f"YAML file {filepath} has been generated.")
    return {"status": "success", "filepath": filepath}

# Main execution for standalone use of create_values_yaml
if __name__ == "__main__":
    # Example values for standalone execution
    example_type = "chatqna"
    node_selector = {"node-type": "opea-benchmark"}
    chart_dir="."

    # Test deploy_config
    deploy_config = {
        "device": "gaudi",
        "version": "1.1.0",
        "modelUseHostPath": "/mnt/opea-models",
        "HUGGINGFACEHUB_API_TOKEN": "",
        "node": 2,
        "cards_per_node": 8,

        "services": {
            "backend": {
                "instance_num": 2,
                "cores_per_instance": "",  # "4",
                "memory_capacity": "",  # "8Gi"
            },
            "teirerank": {
                "enabled": False,
                "model_id": "",
                "instance_num": 1,
                "cards_per_instance": 1
            },
            "tei": {
                "model_id": "",
                "instance_num": 2,
                "cores_per_instance": "",  # "2",
                "memory_capacity": "",  # "4Gi"
            },
            "llm": {
                "engine": "tgi",
                "model_id": "",
                "instance_num": 16,
                "max_batch_size": 4,
                "max_input_length": "",  # 4096,
                "max_total_tokens": "",  # 8192,
                "cards_per_instance": 1
            },
            "data-prep": {
                "instance_num": 1,
                "cores_per_instance": "",  # "1",
                "memory_capacity": "",  # "2Gi"
            },
            "retriever-usvc": {
                "instance_num": 2,
                "cores_per_instance": "",  # "2",
                "memory_capacity": "",  # "4Gi"
            },
            "redis-vector-db": {
                "instance_num": 1,
                "cores_per_instance": "",  # "2",
                "memory_capacity": "",  # "4Gi"
            }
        }
    }

    result = generate_helm_values(
        example_type=example_type,
        deploy_config=deploy_config,
        chart_dir=chart_dir,
        action_type=0,
        node_selector=node_selector
    )

    # Read back the generated YAML file for verification
    with open(result["filepath"], "r") as file:
        print("Generated YAML contents:")
        print(file.read())
