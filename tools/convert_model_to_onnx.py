"""
Real-ESRGAN x4plus anime 6B (.pth)  ->  .onnx   (ekbar chalate hobe)

1) pip install torch onnx basicsr
2) Download: https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth
   (ei script er pashe rakhun)
3) python convert_model_to_onnx.py
4) Toiri hoa .onnx file ta website er  models/  folder e rakhun  (size ~17 MB, Cloudflare Pages limit 25 MiB er niche)
"""
import torch
from basicsr.archs.rrdbnet_arch import RRDBNet

model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=6, num_grow_ch=32, scale=4)
ckpt = torch.load("RealESRGAN_x4plus_anime_6B.pth", map_location="cpu")
model.load_state_dict(ckpt.get("params_ema", ckpt.get("params", ckpt)), strict=True)
model.eval()

torch.onnx.export(
    model, torch.rand(1, 3, 64, 64), "RealESRGAN_x4plus_anime_6B.onnx",
    opset_version=17, input_names=["input"], output_names=["output"],
    dynamic_axes={"input": {2: "h", 3: "w"}, "output": {2: "H", 3: "W"}},
)
print("Done: RealESRGAN_x4plus_anime_6B.onnx")
