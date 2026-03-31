# Documentation for "doctors"

The pipeline for each child has five stages. Completing one stage will typically bring you directly to the next stage, but you can also jump between the stages in the user interface. You can have multiple cases "in-flight", but it also makes a lot of sense to process the children sequentially.

### Stage 1: Patient Data

* You should take a QR code sticker from your supply and scan it with the Webcam until it autofills the "QR-Code Content" field
* Fill out the metadata about child name and animal name. This information will be
	* Used later to display the cases (useful if you split the work: One welcomes the children, one shows them results)
	* Is put into a watermark on the final result
* Note that the "Animal type" field is optional, but you can use it to give a hint to the generation workflow. Use this when you get something obscure and amorphous. It is typically not required for standard stuff like bears. Write this one in english, because all prompting to models under the hood happens in english.

### Stage 2: Acquire image

* Place the animal into the X-Ray and take a picture. For debugging purposes, you can also upload a file from disk instead.
* After acquiring a picture you can crop it by clicking on the edit pen in the overlay
* For best results:
	* Try to capture the animal from a pose that shows its distinct features best (maybe have some cushions or wedges to support this)
	* Always crop the picture so that it fully features the animal.
* Once done, hit the Accept button in the overlay.

### Stage 3: Review X-Ray

There will always be three images generated. The reasons for this is that generative AI can produce hallucinations that are not only weird, but might also scare children when looking at them. When you like one image, you can hit accept and proceed. There is no need to wait for completion of all three candidates. If none of the generated images is any good, you can hit retry generation or you might want to consider starting from scratch and take another picture.

### Stage 4: Apply fractures

This stage is optional. If you just want to present the X-Ray, you can hit Accept and proceed directly to stage 5.

If you want to apply a fracture, you can mark the area where you want to remove the bone with the pencil tool and potentially correct it with the eraser tool. Clicking on the wand will "remove the bone". This time, there is no fancy generative AI involved, but rather simple image manipulation. If you do not like the result, just discard it and restart or continue.

### Stage 5: Review results

Use this as needed to discuss with the children. It might be worth to have an additional child-facing monitor for this.
