# Teddy Bear Hospital X-Ray Application

The Teddy Bear Hospital project transforms images of stuffed animals into "pseudo x-ray images" using AI diffusion technology. The resulting images are used on-site and can also be later accessed online, allowing children to take their "x-rayed" stuffed animal home as a unique souvenir.

## Features

* Image-to-image generation pipeline for X-Rays of plush toys
* Web application for "patient management" and pipelining
* Review pipeline to filter hallucinations and "not-safe-for-children" X-Ray images
* QR-code based patient tracking
* Persistent cloud storage via QR code for "take home" pictures without on-site printing
* "Bone breaking" as post-processing on the X-Ray
* Separate GPU runner architecture

## Documentation

Documentation exists for a variety of relevant personas:

* [Organizers of teddy bear hospital](./doc/organizers.md)
* [System Administrators](./doc/admins.md)
* [Doctors at teddy bear hospital](./doc/doctors.md)
* [Tech Enthusiasts](./doc/tech.md)

## License information

The web app, as well as the runner are provided under the terms of the MIT license.

**Please note that this application is only meant to be used on plush toys. Usage with other images might violate the licensing terms of the used models.**

Licenses of the used models:
* [Chroma](https://huggingface.co/lodestones/Chroma/tree/main): Apache 2.0 License
* The X-Ray LoRA used by the runner is loaded from `x-ray_schnell_v3.safetensors`; check the source/model documentation for its exact license terms.
