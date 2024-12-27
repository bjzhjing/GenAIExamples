import yaml
import subprocess
import sys
import os
import copy
import argparse

def read_yaml(file_path):
    try:
        with open(file_path, 'r') as file:
            return yaml.safe_load(file)
    except Exception as e:
        print(f"Error reading YAML file: {e}")
        return None

def construct_deploy_config(deploy_config, target_node, max_batch_size=None):
    """
    Construct a new deploy config based on the target node number and optional max_batch_size.
    
    Args:
        deploy_config: Original deploy config dictionary
        target_node: Target node number to match in the node array
        max_batch_size: Optional specific max_batch_size value to use
    
    Returns:
        A new deploy config with single values for node and instance_num
    """
    # Deep copy the original config to avoid modifying it
    new_config = copy.deepcopy(deploy_config)
    
    # Get the node array and validate
    nodes = deploy_config.get('node')
    if not isinstance(nodes, list):
        raise ValueError("deploy_config['node'] must be an array")
        
    # Find the index of the target node
    try:
        node_index = nodes.index(target_node)
    except ValueError:
        raise ValueError(f"Target node {target_node} not found in node array {nodes}")
    
    # Set the single node value
    new_config['node'] = target_node
    
    # Update instance_num for each service based on the same index
    for service_name, service_config in new_config.get('services', {}).items():
        if 'instance_num' in service_config:
            instance_nums = service_config['instance_num']
            if isinstance(instance_nums, list):
                if len(instance_nums) != len(nodes):
                    raise ValueError(
                        f"instance_num array length ({len(instance_nums)}) for service {service_name} "
                        f"doesn't match node array length ({len(nodes)})"
                    )
                service_config['instance_num'] = instance_nums[node_index]
    
    # Update max_batch_size if specified
    if max_batch_size is not None and 'llm' in new_config['services']:
        new_config['services']['llm']['max_batch_size'] = max_batch_size
    
    return new_config

def main(yaml_file, target_node=None):
    """
    Main function to process deployment configuration.
    
    Args:
        yaml_file: Path to the YAML configuration file
        target_node: Optional target number of nodes to deploy. If not specified, will process all nodes.
    """
    config = read_yaml(yaml_file)
    if config is None:
        print("Failed to read YAML file.")
        return None

    deploy_config = config['deploy']
    benchmark_config = config['benchmark']

    # Extract chart name from the YAML file name
    chart_name = os.path.splitext(os.path.basename(yaml_file))[0]

    # Get the node array
    nodes = deploy_config.get('node', [])
    if not isinstance(nodes, list):
        print("Error: deploy_config['node'] must be an array")
        return None

    # If target_node is specified, only process that node
    # Otherwise, process all nodes in the array
    nodes_to_process = [target_node] if target_node is not None else nodes

    for node in nodes_to_process:
        try:
            # Skip if target_node is specified but doesn't match current node
            if target_node is not None and node != target_node:
                continue

            print(f"\nProcessing configuration for {node} nodes...")
            
            # Get max_batch_size array if it exists
            max_batch_sizes = deploy_config.get('services', {}).get('llm', {}).get('max_batch_size', [])
            if not isinstance(max_batch_sizes, list):
                max_batch_sizes = [max_batch_sizes]
            
            # Iterate through max_batch_sizes
            for i, max_batch_size in enumerate(max_batch_sizes):
                print(f"\nProcessing max_batch_size: {max_batch_size}")
                
                # Construct new deploy config
                new_deploy_config = construct_deploy_config(deploy_config, node, max_batch_size)
                
                # Write the new deploy config to a temporary file
                temp_config_file = f"temp_deploy_config_{node}_{max_batch_size}.yaml"
                try:
                    with open(temp_config_file, 'w') as f:
                        yaml.dump(new_deploy_config, f)
                    
                    if i == 0:
                        # First iteration: full deployment
                        cmd = [
                            'python3', 
                            'deploy.py', 
                            '--deploy-config', 
                            temp_config_file,
                            '--chart-name',
                            chart_name
                        ]
                    else:
                        # Subsequent iterations: update services with config change
                        cmd = [
                            'python3', 
                            'deploy.py', 
                            '--deploy-config', 
                            temp_config_file,
                            '--chart-name',
                            chart_name,
                            '--update-service',
                            'llm'
                        ]
                    
                    print(f"{'Deploying' if i == 0 else 'Updating'} configuration for {node} nodes with max_batch_size {max_batch_size}...")
                    result = subprocess.run(cmd, check=True)
                    
                    if result.returncode != 0:
                        print(f"{'Deployment' if i == 0 else 'Update'} failed for {node} nodes configuration")
                        break  # Skip remaining max_batch_sizes for this node
                        
                except Exception as e:
                    print(f"Error during {'deployment' if i == 0 else 'update'} for {node} nodes with max_batch_size {max_batch_size}: {str(e)}")
                    break  # Skip remaining max_batch_sizes for this node
                finally:
                    # Clean up the temporary file
                    if os.path.exists(temp_config_file):
                        os.remove(temp_config_file)
                    
        except ValueError as e:
            print(f"Error processing configuration for {node} nodes: {str(e)}")
            continue

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy and benchmark with specific node configuration.")
    parser.add_argument("yaml_file", help="Path to the YAML configuration file")
    parser.add_argument("--target-node", type=int, help="Optional: Target number of nodes to deploy. If not specified, will process all nodes.", default=None)
    
    args = parser.parse_args()
    main(args.yaml_file, args.target_node)
