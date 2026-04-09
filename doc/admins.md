# Documentation for system administrators

## Hardware Requirements

Currently these are the requirements for running the application.
* A rather small virtual machine
	* 2 vCPUs should be enough
	* 8 GB RAM should be enough
	* Needs to be accessible from both the network where the hospital is operating and from the GPU runner
* Access to a persistently available, supported Storage backend. This is currently limited to a Seafile instance (in Heidelberg: [HeiBox](https://heibox.uni-heidelberg.de))
* An NVidia GPU with 80GB VRAM on some machine - not directly on above VM!

If you do not have 80GB of VRAM, there is possibilities to split this up onto multiple GPUs or trim down, but they might require work on the code or might affect generation results:
* You can switch to a cheaper/quantized VLM
* You can use a cloud-hosted VLM, any OpenAI-compatible API works. This will also be much more cost effective - we did not do it, because we ran into problems with rate limiting on the mistral.ai free tier.
* You can distribute VLM and generation to different devices
* The current Chroma workflow already applies the X-Ray LoRA directly, so only one image generation pipeline needs to stay resident.

## Virtual machine Setup

We recommend a setup with `docker`, which reduces the software requirements on the VM to a minimum. First, get the code:

```bash
git clone https://github.com/ssciwr/tbk-app.git
cd tbk-app
```

Then, copy and adapt the configuration files to your needs:
```bash
mv .env.example .env
mv ./backend/.env.example ./backend/.env
```

Then, start the service:
```bash
docker compose -f compose.prod.yaml up -d --build
```

Optionally, you can register this as a system.d service by adjusting [teddy-app.service](teddy-app.service) and placing it in `/etc/systemd/system/teddy-app.service`. Then, run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now teddy-app.service
sudo systemctl status teddy-app.service
```

## GPU Runner Setup

There is three separate services that need to be setup:
* The image generator service from our code: It regularly polls the backend for jobs and submits the results back to it
* A VLM inference server e.g. via `vllm`

### Image generator service

There is currently no Docker setup for the GPU runner code. An installation of Python (tested version: `3.11`) is required, preferrably in an isolated environment.

```bash
git clone https://github.com/ssciwr/tbk-app.git
cd tbk-app
python -m pip install ./runner
python -m pip install -r runner/requirements-chroma.txt
```

Next we need to ensure that we have all required models downloaded and placed in `runner/assets`.

* `chroma-unlocked-v44-detail-calibrated.safetensors` from [lodestones/Chroma](https://huggingface.co/lodestones/Chroma/tree/main). Note that in the meantime, the Chroma-1 model has released and it is not strictly required to load from a checkpoint anymore. However, we did not want to change the pipeline we have had good experiences with without detailed analysis of the results.
* `Hyper-Chroma-Turbo-Alpha-16steps-lora.safetensors` from https://www.runninghub.ai/model/public/1931558060911996929
* `x-ray_schnell_v3.safetensors` from your selected Flux Schnell X-Ray LoRA source


You can then run the generation service with the `tbk-runner` executable. An overview of options:

```
Usage: tbk-runner [OPTIONS]

Options:
  --workflow [chroma|dummy]  Workflow implementation to run.  [required]
  --server TEXT              Backend base URL (for example
                             http://backend:8000).  [required]
  --password TEXT            Shared worker password used to obtain backend
                             auth tokens.  [required]
  --debug                    Enable workflow debug mode (writes intermediate
                             artifacts when supported).
  --no-watermark             Skip watermark generation and overlay.
  --vlm-server TEXT          VLM base URL.
  --vlm-server-key TEXT      VLM API key.
  --vlm-model-name TEXT      VLM model name.
  --help                     Show this message and exit.
```

### VLM Inference Server

The VLM inference server is used to analyse the input image and write a prompt that describes the desired anatomic output in detail. While in theory, any vision-language model is capable of doing this, we observed quite some differences about how the VLMs are able to reason about anatomy. This is mostly likely related to the differences in their training data. In our experience, [mistralai/Ministral-3-14B-Instruct-2512](https://huggingface.co/mistralai/Ministral-3-14B-Instruct-2512) works very well.

Here is an example deployment on an A100-80GB using [vllm](https://vllm.ai/):

```bash
vllm serve mistralai/Ministral-3-14B-Instruct-2512 --port 9080  --max-model-len 3000 --gpu-memory-utilization 0.5 --limit-mm-per-prompt.video 0 --mm-encoder-tp-mode data --mm-processor-cache-gb 0 --tokenizer_mode mistral --config_format mistral --load_format mistral --enable-auto-tool-choice --tool-call-parser mistral
```

## Storage Configuration

An important design idea of the application was that the entire setup of VM and GPU runner is only required during the teddy bear hospital itself, but images are stored persistently elsewhere. The QR codes handed out to the children directly resolve to these storage URLs without requiring the backend.

Currently, only two storage backends are implemented:
* [Seafile](https://www.seafile.com/en/home/)
* Local filesystem storage (intended for debugging)

Additional storage backends (e.g. NextCloud, S3 Buckets etc.) are possible, but would require somebody capable and willing to implement them.

### Setup of the Seafile backend

You need to configure `backend/.env` to point to the correct SeaFile instance. The following two libraries are needed:

* `SEAFILE_URL`
* `SEAFILE_LIBRARY_NAME`

Additionally you need to provide one of the following:

* `SEAFILE_REPO_TOKEN` (preferred if your Seafile API runs version >= 12): This can be generated directly in the UI library settings.
* `SEAFILE_ACCOUNT_TOKEN` (preferred for Seafile API version 11): This can be generated directly in the UI account settings ("Web API Auth Token")
* `SEAFILE_USERNAME`/`SEAFILE_PASSWORD`: Discouraged due to potential leaking of credentials.
