# Documentation for tech enthusiasts

The generation pipeline for X-Ray images is currently the following:

* The background of the input image is removed
* A vision-language model is analysing the image and creating a prompt for the image generation model
* A [Chroma](https://huggingface.co/lodestones/Chroma1-HD) image-to-image pipeline gets both the VLM-generated prompt and the original input image. It loads the standard Chroma LoRA plus the X-Ray LoRA directly, and the generation prompt includes the `x-ray` trigger word so the X-Ray style is applied in the same pass that adds the "realistic" skeleton.
* The image is converted to greyscale.
* A watermark with information about the TBK is added.
