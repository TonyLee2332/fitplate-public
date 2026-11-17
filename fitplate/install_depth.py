"""Install the pinned local depth model. Run once after installing requirements."""
from pathlib import Path
from transformers import AutoImageProcessor, AutoModelForDepthEstimation

MODEL='depth-anything/Depth-Anything-V2-Small-hf'
REVISION='5426e4f0f36572d16453bbda7a8389317b1bef99'
CACHE=Path(__file__).resolve().parents[1]/'models'


if __name__ == '__main__':
    try:
        AutoImageProcessor.from_pretrained(MODEL,revision=REVISION,cache_dir=CACHE,use_fast=False,local_files_only=True)
        AutoModelForDepthEstimation.from_pretrained(MODEL,revision=REVISION,cache_dir=CACHE,use_safetensors=True,local_files_only=True)
    except OSError:
        AutoImageProcessor.from_pretrained(MODEL,revision=REVISION,cache_dir=CACHE,use_fast=False)
        AutoModelForDepthEstimation.from_pretrained(MODEL,revision=REVISION,cache_dir=CACHE,use_safetensors=True)
    print('FitPlate depth model is ready.')
