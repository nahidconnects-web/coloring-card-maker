"""Downloads the Real-ESRGAN x4plus anime 6B ONNX model into web/models/ and verifies it.

Usage (from the repo root):  python tools/download_model.py
"""
import hashlib
import os
import urllib.request

URL = "https://huggingface.co/skillsafe-ai/realesrgan-x4plus-anime-6b/resolve/main/model.onnx"
SHA256 = "9a029dae374b2cd4c3eb2dbbed857e22e6d785687c767aa12828e7356b9fb378"
DEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web", "models",
                    "RealESRGAN_x4plus_anime_6B.onnx")

print("Downloading model (about 17 MB)...")
urllib.request.urlretrieve(URL, DEST)
digest = hashlib.sha256(open(DEST, "rb").read()).hexdigest()
if digest != SHA256:
    os.remove(DEST)
    raise SystemExit(f"Checksum mismatch ({digest}). File removed. The upstream file may have changed.")
print("OK, saved and verified:", os.path.normpath(DEST))
