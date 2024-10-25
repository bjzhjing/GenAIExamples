## Table of Contents

- [Deployment](#deployment)
  - [Prerequisites](#prerequisites)
  - [Deployment Scenarios](#deployment-scenarios)
    - [Case 1. Without Rerank](#case-1-without-rerank)
- [Benchmark](#benchmark)

## Deployment

### Prerequisites

- Kubernetes installation: Use [kubespray](https://github.com/opea-project/docs/blob/main/guide/installation/k8s_install/k8s_install_kubespray.md) or other official Kubernetes installation guides.
- Helm installation: Follow the [Helm documentation](https://helm.sh/docs/intro/install/#helm) to install Helm.
- Setup Hugging Face Token
  To access models and APIs from Hugging Face, set your token as environment variable.
  ```bash
  export HFTOKEN="insert-your-huggingface-token-here"
  ```
- Prepare Shared Models
  Downloading models simultaneously to multiple nodes in your cluster can overload resources such as network bandwidth, memory and storage. To prevent resource exhaustion, it's recommended to preload the models in advance.
  ```bash
  pip install -U "huggingface_hub[cli]"
  sudo mkdir -p /mnt/models
  sudo chmod 777 /mnt/models
  huggingface-cli download --cache-dir /mnt/models Intel/neural-chat-7b-v3-3
  export MODELDIR=/mnt/models
  ```
  Once the models are downloaded, you can consider the following methods for sharing them across nodes:
  - Persistent Volume Claim (PVC): This is the recommended approach for production setups. For more details on using PVC, refer to [PVC](https://github.com/opea-project/GenAIInfra/blob/main/helm-charts/README.md#using-persistent-volume).
  - Local Host Path: For simpler testing, ensure that each node involved in the deployment follows the steps above to locally prepare the models. After preparing the models, use `--set global.modelUseHostPath=${MODELDIR}` in the deployment command.

### Deployment Scenarios

#### Case 1. Without Rerank

Deploy Command (with node number, label, Hugging Face token, model directory specified):
```bash
python script.py \
    --hftoken YOUR_HF_TOKEN \
    --modeldir /path/to/modeldir \
    --num-nodes 1 \
    --label node-type=chatqna-opea
```
Uninstall Command:
```bash
python script.py --uninstall
```

## Benchmark

To benchmark the deployed `opea/chatqna`, refer to the [GenAIEval](https://github.com/opea-project/GenAIEval) repository and the [benchmark](https://github.com/opea-project/GenAIEval/tree/main/evals/benchmark) page to set up the benchmarking tools. Adjust the the parameters in [benchmark.yaml](benchmark.yaml) and place it in the same directory as [benchmark.py](https://github.com/opea-project/GenAIEval/blob/main/evals/benchmark/benchmark.py). Then run the benchmark using the following command:

```bash
python benchmark.py
```

