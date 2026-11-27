
# Workflow_Gleek3Deek_to_ComfyUI.json

A lightweight ComfyUI workflow built for **Gleek3Deek's AI panel**, specifically optimized to run on low-VRAM hardware. While render times are slower than standard SDXL pipelines, this workflow delivers significantly higher image quality than SDXL with ControlNet.

## Hardware & Performance
* **Tested Hardware:** NVIDIA RTX 4060 (8GB VRAM)
* **Optimization:** Uses quantized GGUF and FP8 models to stay within an 8GB VRAM budget.

## Required Models & Nodes
Ensure the following models and custom nodes are installed in your ComfyUI environment before loading the workflow:

* **Diffusion Model:** `flux-3-image-klein-UD-Q4_K_XL.gguf` *(an optimized quantization of FLUX.3 Image Klein)*
  * **Required Node:** `GGUF Loader`
* **Text Encoder:** `qwen3vl_4b_fp8_scaled.safetensors`

## Usage & Reference Images

1. Load `Workflow_Gleek3Deek_to_ComfyUI.json` directly into Gleek3Deek's **AI Panel**.
2. Reference your input images directly inside Gleek3Deek's prompt window using sequential tags:
   * **1st Image:** `<ref_image_0>`
   * **2nd Image:** `<ref_image_1>`
   * **Additional Images:** Continue sequentially up to `<ref_image_6>` *(7 images max)*.

> **⚠️ VRAM Warning:** While the workflow supports up to **7 reference images**, adding multiple images increases memory overhead and may exceed an **8GB VRAM** limit.

## Example Prompt
In the included example, a depth map of an unfinished 3D female character model is passed as `<ref_image_0>` and transformed into a finished illustration using the following prompt:

```text
transform the <ref_image_0> depth image into an adorable chibi young fairy stands in a rustic cauldron at night, seen from the thighs up, holding a long stem mushroom. She has an oval face with smooth, clear skin, green eyes, arched brows, a small nose and coral lips, and blonde hair, polished stylized illustration, highly detailed, magical fantasy mood.
```





