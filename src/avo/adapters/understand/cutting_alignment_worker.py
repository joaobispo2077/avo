"""Optional runtime entrypoint. Never import AVO or provision network resources."""

from __future__ import annotations

import importlib.metadata
import json
import socket
import sys
import wave


def _deny_network(*_args, **_kwargs):
    raise RuntimeError("cutting alignment worker forbids network/downloads")


def execute(request):
    socket.create_connection = _deny_network
    socket.socket.connect = _deny_network
    socket.socket.connect_ex = _deny_network
    if importlib.metadata.version("whisperx") != request["expectedVersion"]:
        raise RuntimeError("optional WhisperX runtime version mismatch")
    import nltk
    import numpy as np
    import torch
    import whisperx

    nltk.download = _deny_network
    nltk.data.path = [request["nltkData"]]
    resource = "portuguese" if request["language"] == "pt" else "english"
    nltk.data.find(f"tokenizers/punkt_tab/{resource}/")
    torch.set_num_threads(1)
    with wave.open(request["audioPath"], "rb") as stream:
        if (
            stream.getframerate() != 16000
            or stream.getnchannels() != 1
            or stream.getsampwidth() != 2
        ):
            raise RuntimeError("alignment requires explicit mono 16 kHz signed PCM")
        audio = (
            np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").astype(
                np.float32
            )
            / 32768
        )
    model, metadata = whisperx.load_align_model(
        language_code=request["language"],
        device="cpu",
        model_name=request["modelPath"],
        model_cache_only=True,
    )
    result = whisperx.align(
        request["segments"],
        model,
        metadata,
        audio,
        "cpu",
        interpolate_method="ignore",
        return_char_alignments=True,
    )
    return {"raw": result, "dictionary": metadata["dictionary"]}


if __name__ == "__main__":
    print(json.dumps(execute(json.load(sys.stdin)), allow_nan=False))
