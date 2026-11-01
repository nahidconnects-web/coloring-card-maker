# Coloring Card Maker

Turns a coloring page into a printable folding greeting card (front = your image, back = badge
"Coloring & Creation by: ..... / Made with Love"). Two versions:

| Folder | What | How to run |
|---|---|---|
| `web/` | Browser app (single `index.html`), free to host | Deploy to Cloudflare Pages |
| `desktop/` | Python + tkinter app | `pip install -r desktop/requirements.txt` then `python desktop/greeting_card_generator.py` |
| `tools/` | Model helpers | see below |

## Web app: deploy on Cloudflare Pages (free)
1. Push this repo to GitHub.
2. Cloudflare Dashboard -> Workers & Pages -> Create -> Pages -> Connect to Git -> pick this repo.
3. Build command: *(leave empty)*. Build output directory: `web`.
4. Deploy. Every `git push` redeploys automatically.

## AI Enhance (optional, best for line art)
Uses Real-ESRGAN x4plus anime 6B (ONNX) running in the browser.
- `python tools/download_model.py` saves the model to `web/models/` (17 MB, below GitHub's file limit and Cloudflare Pages' 25 MiB per-file limit). Commit it with the repo.
- Without the file the app downloads the public Hugging Face copy instead.
- `tools/convert_model_to_onnx.py` is only needed if you want to build the ONNX file yourself from the official `.pth`.

The desktop app can use the `realesrgan-ncnn-vulkan` program (put it in a `realesrgan/` folder next to the script); otherwise it uses the built-in Basic enhance.

## Credits
Real-ESRGAN (c) 2021 Xintao Wang, BSD-3-Clause: https://github.com/xinntao/Real-ESRGAN
ONNX export used by the web fallback: https://huggingface.co/skillsafe-ai/realesrgan-x4plus-anime-6b
