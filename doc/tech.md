# Documentation for tech enthusiasts

The generation pipeline for X-Ray images is currently the following:

* The background of the input image is removed
* A vision-language model is analysing the image and creating a prompt for the image generation model
* A [Chroma](https://huggingface.co/lodestones/Chroma1-HD) image-to-image pipeline that gets both the VLM-generated prompt and the original input image. In this step, a "realistic" skeleton is added to the image.
* An [SDXL](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0)-based [LoRA Adapter trained on X-Ray images](https://civitai.com/models/231655/xray-xl-lora) is used to strengthen the visual X-Ray style.
* The image is converted to greyscale.
* A watermark with information about the TBK is added.
