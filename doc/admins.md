# Documentation for system administrators

## Hardware Requirements

Currently these are the requirements for running the application.
* A rather small virtual machine
	* 2 vCPUs should be enough
	* 8 GB RAM should be enough
	* Needs to be accessible from both the network where the hospital is operating and from the GPU runner
* Access to a persistently available, supported Storage backend. This is currently limited to a Seafile instance (in Heidelberg: [HeiBox](https://heibox.uni-heidelberg.de))
* An NVidia GPU with ~40GB VRAM on some machine - not directly on above VM!

If you do not have 40GB of VRAM, there is possibilities to trim this down, but they might require work on the code or might affect generation results. Please get in touch if you need this.

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

There are two things that need to be available on the runner side:
* The image generator service from our code. It regularly polls the backend for jobs and submits the results back to it.
* Outbound network access to the MistralAI API plus a valid API key for the VLM prompt-generation step.

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
* `DD-xray-v1.safetensors` from https://civitai.com/models/231655/xray-xl-lora


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
  --mistral-api-key TEXT     Mistral API key used for VLM prompt generation.
  --help                     Show this message and exit.
```

Example invocation for the Chroma workflow:

```bash
tbk-runner \
  --workflow chroma \
  --server http://backend:8000 \
  --password YOUR_SHARED_PASSWORD \
  --mistral-api-key YOUR_MISTRAL_API_KEY
```

### MistralAI VLM Access

Due to the the high VRAM demands, we have decided to move away from on-premise VLMs, but
use the MistralAI API instead. The choice of MistralAI was made because its models showed very
good capabilities to reason about anatomy (e.g. compared to chinese models). The used model
currently (April 2026) costs 0.17EUR/1M tokens which is enough for >500 input images.

The MistralAI setup as of April 2026 is:
* Subscribe to the "Scaling Plan" for Mistral AI Studio. No subscription cost, but credit card details required.
* Create an API key at https://admin.mistral.ai/organization/api-keys
* Supply this API key via `--mistral-api-key`.

Because of this flow, the GPU runner host needs outbound HTTPS access to the MistralAI API endpoints.

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
