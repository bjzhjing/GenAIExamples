# ChatQnA Benchmarking

This folder contains a collection of Kubernetes manifest files for deploying the ChatQnA service across scalable nodes. It includes a comprehensive [benchmarking tool](https://github.com/opea-project/GenAIEval/blob/main/evals/benchmark/README.md) that enables throughput analysis to assess inference performance.

By following this guide, you can run benchmarks on your deployment and share the results with the OPEA community.

## Purpose

We aim to run these benchmarks and share them with the OPEA community for three primary reasons:

- To offer insights on inference throughput in real-world scenarios, helping you choose the best service or deployment for your needs.
- To establish a baseline for validating optimization solutions across different implementations, providing clear guidance on which methods are most effective for your use case.
- To inspire the community to build upon our benchmarks, allowing us to better quantify new solutions in conjunction with current leading llms, serving frameworks etc.

## Metrics

The benchmark will report the below metrics, including:

- Number of Concurrent Requests
- End-to-End Latency: P50, P90, P99 (in milliseconds)
- End-to-End First Token Latency: P50, P90, P99 (in milliseconds)
- Average Next Token Latency (in milliseconds)
- Average Token Latency (in milliseconds)
- Requests Per Second (RPS)
- Output Tokens Per Second
- Input Tokens Per Second

Results will be displayed in the terminal and saved as CSV file named `1_stats.csv` for easy export to spreadsheets.

## Table of Contents

- [Deployment](#deployment)
  - [Prerequisites](#prerequisites)
  - [Deployment Scenarios](#deployment-scenarios)
    - [Case 1: Baseline Deployment with Rerank](#case-1-baseline-deployment-with-rerank)
    - [Case 2: Baseline Deployment without Rerank](#case-2-baseline-deployment-without-rerank)
    - [Case 3: Tuned Deployment with Rerank](#case-3-tuned-deployment-with-rerank)
- [Benchmark](#benchmark)
  - [Test Configurations](#test-configurations)
  - [Test Steps](#test-steps)
    - [Upload Retrieval File](#upload-retrieval-file)
    - [Run Benchmark Test](#run-benchmark-test)
    - [Data collection](#data-collection)
    - [Benchmark multiple nodes](#benchmark-multiple-nodes)

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

#### Case 1: Baseline Deployment with Rerank

Deploy Command (with node number, Hugging Face token, model directory specified):
```bash
python deploy.py --hftoken $HFTOKEN --modeldir $MODELDIR --num-nodes 2 --with-rerank
```
Uninstall Command:
```bash
python deploy.py --uninstall
```
Create Values YAML File:
```bash
python deploy.py --hftoken $HFTOKEN --modeldir $MODELDIR --node-names satg-opea-4node-0 --namespace $NAMESPACE --with-rerank --create-values-only
```
Deploy Using the Generated Values YAML File:
```bash
python deploy.py --hftoken $HFTOKEN --modeldir $MODELDIR --with-rerank --user-values oob_1_gaudi_with_rerank.yaml
```
#### Case 2: Baseline Deployment without Rerank

```bash
python deploy.py --hftoken $HFTOKEN --modeldir $MODELDIR --num-nodes 2
```
#### Case 3: Tuned Deployment with Rerank

```bash
python deploy.py --hftoken $HFTOKEN --modeldir $MODELDIR --num-nodes 2 --with-rerank --tuned
```

## Benchmark

### Test Configurations

| Key      | Value   |
| -------- | ------- |
| Workload | ChatQnA |
| Tag      | V1.0    |

Models configuration
| Key | Value |
| ---------- | ------------------ |
| Embedding | BAAI/bge-base-en-v1.5 |
| Reranking | BAAI/bge-reranker-base |
| Inference | Intel/neural-chat-7b-v3-3 |

Benchmark parameters
| Key | Value |
| ---------- | ------------------ |
| LLM input tokens | 1024 |
| LLM output tokens | 128 |

Number of test requests for different scheduled node number:
| Node count | Concurrency | Query number |
| ----- | -------- | -------- |
| 1 | 128 | 640 |
| 2 | 256 | 1280 |
| 4 | 512 | 2560 |

More detailed configuration can be found in configuration file [benchmark.yaml](./benchmark.yaml).

### Test Steps

#### Upload Retrieval File

Before running tests, upload a specified file to make sure the llm input have the token length of 1k.

Run the following command to check the cluster ip of dataprep.

```bash
kubectl get svc
```

Substitute the `${cluster_ip}` into the real cluster ip of dataprep microservice as below.

```log
dataprep-svc   ClusterIP   xx.xx.xx.xx    <none>   6007/TCP   5m   app=dataprep-deploy
```

Run the cURL command to upload file:

```bash
cd GenAIEval/evals/benchmark/data
# RAG with Rerank
curl -X POST "http://${cluster_ip}:6007/v1/dataprep" \
     -H "Content-Type: multipart/form-data" \
     -F "files=@./upload_file.txt" \
     -F "chunk_size=3800"
# RAG without Rerank
curl -X POST "http://${cluster_ip}:6007/v1/dataprep" \
     -H "Content-Type: multipart/form-data" \
     -F "files=@./upload_file_no_rerank.txt"
```

#### Run Benchmark Test

Before the benchmark, we can configure the number of test queries and test output directory by:

```bash
export USER_QUERIES="[640, 640, 640, 640]"
export TEST_OUTPUT_DIR="/home/sdp/benchmark_output/node_1"
```

And then run the benchmark by:

```bash
bash benchmark.sh -n 1
```

The argument `-n` refers to the number of test nodes. Note that necessary dependencies will be automatically installed when running benchmark for the first time.

##### Data collection

All the test results will come to this folder `/home/sdp/benchmark_output/node_1` configured by the environment variable `TEST_OUTPUT_DIR` in previous steps.

#### Benchmark multiple nodes

##### 2 node

```bash
export USER_QUERIES="[1280, 1280, 1280, 1280]"
export TEST_OUTPUT_DIR="/home/sdp/benchmark_output/node_2"
```

And then run the benchmark by:

```bash
bash benchmark.sh -n 2
```

##### 4 node

```bash
export USER_QUERIES="[2560, 2560, 2560, 2560]"
export TEST_OUTPUT_DIR="/home/sdp/benchmark_output/node_4"
```

And then run the benchmark by:

```bash
bash benchmark.sh -n 4




