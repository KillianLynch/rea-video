"""rea-video: reverse engineer how a video was made, shot by shot."""

import os

# Set this before any submodule can initialize ONNX Runtime, including OCR.
os.environ["ORT_DISABLE_TELEMETRY"] = "1"

__version__ = "0.1.0"
SCHEMA = "rea_video.breakdown.v1"
