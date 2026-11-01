"""
Printable Greeting Card PDF Generator  (v3)
-------------------------------------------
Coloring image diye fold-kora greeting card er printable PDF banay.

  Right panel = Front cover (coloring image)
  Left  panel = Back cover  (badge: "Coloring & Creation by: ......" + "Made with Love")

"Made with Love" line e readymade template bachte pare, naile nijer moto
likhte pare (emoji shoho). Emoji gulo black & white line art hoye print hoy.

Low-resolution image hole auto-enhance kore (Basic upscale ba AI Real-ESRGAN).

Requirements:  pip install reportlab pillow
Optional AI:   Real-ESRGAN ncnn-vulkan folder ta 'realesrgan' naame is script er pashe rakhun.
"""

import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from functools import lru_cache

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageTk
from reportlab.lib.pagesizes import A4, letter, landscape
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# ---------------------------------------------------------------- settings
PAGE_SIZES = {"Letter (8.5 x 11 in)": letter, "A4 (210 x 297 mm)": A4}
CARD_W = 10 * inch           # card er total width (khola obosthay)
CARD_H = 7 * inch            # card er height
PANEL_PADDING = 0.25 * inch  # front image er chardike faka jayga
MIN_DPI = 150                # er kom hole low-quality warning
TARGET_DPI = 300             # enhance korle eta target
ENHANCE_BELOW = 200          # er kom DPI hole tabei upscale hobe
MAX_SCALE = 4                # maximum koto gun boro kora hobe
ENHANCE_METHODS = {
    "Basic (fast, offline)": "basic",
    "AI - Real-ESRGAN (best quality)": "ai",
}
CUT_COLOR = (0.7, 0.7, 0.7)
TEXT_COLOR = (0.4, 0.4, 0.4)

DEFAULT_LABEL = "Coloring & Creation by:"

# Readymade "Made with Love" templates (nijer moto likhleo hobe)
TAGLINE_TEMPLATES = [
    "Made with Love",
    "Made with Love \u2764\ufe0f",
    "Made with Love \u2728",
    "Made with Love \U0001F338",
    "Made with Love & Crayons \U0001F58D\ufe0f",
    "Made with Love & Joy \U0001F60A",
    "Made with Love, Just for You \U0001F49D",
    "Made with Love \U0001F3A8",
    "Handmade with Love \U0001F33F",
    "Crafted with Love & Care",
    "Happy Coloring! \U0001F308",
    "Thank You for Coloring \U0001F98B",
    "A Little Gift of Love \U0001F381",
]

# Quick-insert emoji buttons
QUICK_EMOJIS = ["\u2764\ufe0f", "\u2B50", "\U0001F338", "\U0001F3A8", "\u2728",
                "\U0001F495", "\U0001F308", "\U0001F98B", "\U0001F381", "\U0001F60A"]


# ------------------------------------------------------------------ fonts
_fonts = {}


def ensure_fonts():
    """Unicode TTF font khuje register kore. Na pele Helvetica (Latin only)."""
    if "pair" in _fonts:
        return _fonts["pair"]

    candidates = [
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
        ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
        ("/System/Library/Fonts/Supplemental/Arial.ttf",
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ]
    pair = ("Helvetica", "Helvetica-Bold")
    for regular, bold in candidates:
        if os.path.exists(regular) and os.path.exists(bold):
            try:
                pdfmetrics.registerFont(TTFont("CardFont", regular))
                pdfmetrics.registerFont(TTFont("CardFont-Bold", bold))
                pair = ("CardFont", "CardFont-Bold")
                break
            except Exception:
                continue
    _fonts["pair"] = pair
    return pair


@lru_cache(maxsize=1)
def load_emoji_font():
    """System er color-emoji font khuje (font, size) dey. Na pele None."""
    candidates = [
        ("C:/Windows/Fonts/seguiemj.ttf", 128),                              # Windows
        ("/System/Library/Fonts/Apple Color Emoji.ttc", 160),                # macOS
        ("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", 109),          # Linux
        ("/usr/share/fonts/noto/NotoColorEmoji.ttf", 109),
        ("/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf", 109),
        ("/usr/share/fonts/truetype/noto-color-emoji/NotoColorEmoji.ttf", 109),
    ]
    for path, size in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size), size
            except Exception:
                continue
    return None


# ------------------------------------------------------------ emoji logic
_BASE = (r"[\U0001F000-\U0001FAFF\u2300-\u23FF\u2600-\u27BF\u2B00-\u2BFF"
         r"\u3030\u303D\u3297\u3299]")
EMOJI_RE = re.compile(
    rf"{_BASE}[\U0001F3FB-\U0001F3FF]?\uFE0F?(?:\u200D{_BASE}\uFE0F?)*"
)


def split_rich_text(text):
    """'Love \u2764\ufe0f' -> [('text','Love '), ('emoji','\u2764\ufe0f')]"""
    parts, pos = [], 0
    for m in EMOJI_RE.finditer(text):
        if m.start() > pos:
            parts.append(("text", text[pos:m.start()]))
        parts.append(("emoji", m.group()))
        pos = m.end()
    if pos < len(text):
        parts.append(("text", text[pos:]))
    return parts


def to_line_art(img):
    """
    Color emoji (RGBA) ke thick black outline + ভেতরের edge e convert kore.
    Pure black & transparent -- kono gray shade nei.
    """
    size = img.size
    alpha = img.split()[3]
    mask = alpha.point(lambda a: 255 if a > 100 else 0)

    k = max(2, size[0] // 36) * 2 + 1                       # outline thickness (odd)
    outer = ImageChops.subtract(mask.filter(ImageFilter.MaxFilter(k)), mask)

    white = Image.new("RGB", size, (255, 255, 255))
    white.paste(img.convert("RGB"), mask=alpha)
    edges = white.convert("L").filter(ImageFilter.FIND_EDGES)
    edges = edges.point(lambda v: 255 if v > 45 else 0)
    edges = edges.filter(ImageFilter.MaxFilter(3))
    edges = ImageChops.darker(edges, mask.filter(ImageFilter.MinFilter(k)))  # shudhu bhetore

    lines = ImageChops.lighter(outer, edges)
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    out.paste(Image.new("RGBA", size, (0, 0, 0, 255)), mask=lines)
    return out


@lru_cache(maxsize=128)
def render_emoji(ch, lineart=True):
    """Ekta emoji ke PIL RGBA image banay. Font na thakle None."""
    loaded = load_emoji_font()
    if loaded is None:
        return None
    font, size = loaded
    ch = ch.replace("\ufe0f", "")
    canvas_img = Image.new("RGBA", (size * 4, size * 2), (0, 0, 0, 0))
    ImageDraw.Draw(canvas_img).text((size // 2, size // 4), ch, font=font,
                                    embedded_color=True)
    bbox = canvas_img.split()[3].getbbox()
    if not bbox:
        return None
    img = canvas_img.crop(bbox)
    side = max(img.size) + 8
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
    square = square.resize((256, 256), Image.LANCZOS)
    return to_line_art(square) if lineart else square


# --------------------------------------------------------- drawing helpers
def draw_heart(c, cx, cy, s):
    p = c.beginPath()
    p.moveTo(cx, cy - s)
    p.curveTo(cx - 1.25 * s, cy - 0.1 * s, cx - 1.0 * s, cy + 0.95 * s, cx - 0.5 * s, cy + 0.95 * s)
    p.curveTo(cx - 0.2 * s, cy + 0.95 * s, cx, cy + 0.72 * s, cx, cy + 0.5 * s)
    p.curveTo(cx, cy + 0.72 * s, cx + 0.2 * s, cy + 0.95 * s, cx + 0.5 * s, cy + 0.95 * s)
    p.curveTo(cx + 1.0 * s, cy + 0.95 * s, cx + 1.25 * s, cy - 0.1 * s, cx, cy - s)
    p.close()
    c.drawPath(p, stroke=1, fill=0)


def draw_star(c, cx, cy, r):
    p = c.beginPath()
    for i in range(10):
        ang = math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.45
        x, y = cx + rad * math.cos(ang), cy + rad * math.sin(ang)
        p.moveTo(x, y) if i == 0 else p.lineTo(x, y)
    p.close()
    c.drawPath(p, stroke=1, fill=0)


def draw_rich_line(c, text, cx, y, size, max_w, font, lineart, warnings):
    """Text + emoji ekta line e center kore ankhe."""
    items = []
    for kind, value in split_rich_text(text):
        if kind == "text":
            items.append(("text", value, 0))
        else:
            img = render_emoji(value, lineart)
            if img is None:
                msg = "Emoji font paoa jayni, emoji gulo print hoyni."
                if msg not in warnings:
                    warnings.append(msg)
                continue
            items.append(("emoji", img, 0))

    def total_width(sz):
        return sum(stringWidth(v, font, sz) if k == "text" else sz * 1.15
                   for k, v, _ in items)

    width = total_width(size)
    if width > max_w:                       # lomba hole font chhoto kore fit
        size *= max_w / width
        width = total_width(size)

    x = cx - width / 2
    c.setFillColorRGB(0, 0, 0)
    for kind, value, _ in items:
        if kind == "text":
            c.setFont(font, size)
            c.drawString(x, y, value)
            x += stringWidth(value, font, size)
        else:
            h = size * 1.1
            c.drawImage(ImageReader(value), x + size * 0.025, y - size * 0.2,
                        width=h, height=h, mask="auto")
            x += size * 1.15


def draw_back_cover(c, px, py, pw, ph, opts, warnings):
    """Left panel e back-cover badge ankhe."""
    regular, bold = ensure_fonts()
    cx, cy = px + pw / 2, py + ph / 2
    bw, bh = 3.7 * inch, 2.7 * inch
    x0, y0 = cx - bw / 2, cy - bh / 2

    c.setStrokeColorRGB(0, 0, 0)
    c.setLineJoin(1)
    c.setLineWidth(3)                                   # bahirer mota frame
    c.roundRect(x0, y0, bw, bh, 0.28 * inch)
    c.setLineWidth(1.2)                                 # bhetorer patla frame
    inset = 0.1 * inch
    c.roundRect(x0 + inset, y0 + inset, bw - 2 * inset, bh - 2 * inset, 0.2 * inch)

    inner_w = bw - 0.9 * inch

    # 1. Label
    label = opts.get("label") or DEFAULT_LABEL
    draw_rich_line(c, label, cx, y0 + bh - 0.7 * inch, 13, inner_w, bold, opts["lineart"], warnings)

    # 2. Dotted name line
    c.setLineWidth(1.6)
    c.setLineCap(1)
    c.setDash(0.1, 5)
    line_y = y0 + bh - 1.35 * inch
    c.line(x0 + 0.5 * inch, line_y, x0 + bw - 0.5 * inch, line_y)
    c.setDash()
    c.setLineCap(0)

    # 3. Icon
    c.setLineWidth(2.2)
    icon_y = y0 + 0.98 * inch
    if opts["icon"] == "heart":
        draw_heart(c, cx, icon_y, 0.17 * inch)
    elif opts["icon"] == "star":
        draw_star(c, cx, icon_y, 0.2 * inch)

    # 4. "Made with Love" (template ba custom)
    tagline = opts.get("tagline") or ""
    if tagline.strip():
        draw_rich_line(c, tagline.strip(), cx, y0 + 0.45 * inch, 12, inner_w,
                       regular, opts["lineart"], warnings)


# --------------------------------------------------------------- PDF logic
def load_image(path):
    """Image load kore RGB te convert kore. Transparent PNG white background pabe."""
    img = Image.open(path)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        return background
    return img.convert("RGB")


def effective_dpi(img, box_w, box_h, mode):
    iw, ih = img.size
    pts_per_px = (max if mode == "fill" else min)(box_w / iw, box_h / ih)
    return 72 / pts_per_px


# ------------------------------------------------------- image enhancement
def app_dir():
    if getattr(sys, "frozen", False):                  # .exe hole
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def front_box():
    """Front cover er image box (width, height) points e."""
    return CARD_W / 2 - 2 * PANEL_PADDING, CARD_H - 2 * PANEL_PADDING


def dpi_for_size(iw, ih, mode):
    bw, bh = front_box()
    pts_per_px = (max if mode == "fill" else min)(bw / iw, bh / ih)
    return 72 / pts_per_px


def find_realesrgan():
    """realesrgan-ncnn-vulkan executable khuje. Na pele None."""
    name = "realesrgan-ncnn-vulkan" + (".exe" if platform.system() == "Windows" else "")
    for folder in (os.path.join(app_dir(), "realesrgan"), app_dir()):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    return shutil.which(name)


def run_realesrgan(img):
    """Real-ESRGAN (anime model, line art er jonno bhalo) diye 4x upscale."""
    exe = find_realesrgan()
    if not exe:
        raise RuntimeError("Real-ESRGAN paoa jayni")
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "in.png"), os.path.join(tmp, "out.png")
        img.save(src)
        kwargs = {}
        if platform.system() == "Windows":
            kwargs["creationflags"] = 0x08000000            # CREATE_NO_WINDOW
        proc = subprocess.run(
            [exe, "-i", src, "-o", dst, "-n", "realesrgan-x4plus-anime", "-s", "4", "-f", "png"],
            cwd=os.path.dirname(exe), capture_output=True, timeout=600, **kwargs)
        if proc.returncode != 0 or not os.path.exists(dst):
            raise RuntimeError("Real-ESRGAN run hoyni")
        return Image.open(dst).convert("RGB").copy()


def clean_lineart(img):
    """Gray noise/ঝাপসা muche line gulo kalo, background pure shada kore."""
    g = ImageOps.autocontrast(img.convert("L"), cutoff=1)
    g = g.filter(ImageFilter.UnsharpMask(radius=2, percent=120, threshold=3))
    lo, hi = 110, 175                                        # ei range er bhetore soft edge
    lut = [0 if v <= lo else 255 if v >= hi else int((v - lo) * 255 / (hi - lo)) for v in range(256)]
    return g.point(lut).convert("RGB")


def enhance_image(img, mode, method, cleanup, warnings):
    """
    Dpi ENHANCE_BELOW er kom hole TARGET_DPI porjonto upscale kore (max MAX_SCALE gun), cleanup chaile line clean kore.
    Returns (image, method_used ba None)
    """
    iw, ih = img.size
    dpi = dpi_for_size(iw, ih, mode)
    used = None
    if dpi < ENHANCE_BELOW:
        factor = min(TARGET_DPI / dpi, MAX_SCALE)
        new_size = (round(iw * factor), round(ih * factor))
        if method == "ai":
            try:
                img = run_realesrgan(img)
                used = "AI"
            except Exception as e:
                warnings.append(f"AI upscale hoyni ({e}). Basic upscale use kora hoyeche.")
        img = img.resize(new_size, Image.LANCZOS)
        if used is None:
            img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=80, threshold=2))
            used = "Basic"
    if cleanup:
        img = clean_lineart(img)
    return img, used


_enh_cache = {"key": None, "val": None}      # preview + generate e ekbar-i enhance hoy


def generate_pdf(image_path, output_path, page_size=letter, mode="fit", back=None, enhance=None):
    """
    mode = "fit"  -> pura image dekha jabe (aspect ratio thik)
    mode = "fill" -> panel bhore jabe, kinara crop hobe
    back = None ba dict: {"label","tagline","icon":"heart|star|none","lineart":bool}
    enhance = None ba dict: {"method":"basic|ai","cleanup":bool}
    Returns: {"dpi", "dpi_before", "enhanced" (None/'Basic'/'AI'), "warnings": [str]}
    """
    page_w, page_h = landscape(page_size)
    if CARD_W > page_w or CARD_H > page_h:
        raise ValueError("Card page er cheye boro, page size check korun.")

    left = (page_w - CARD_W) / 2
    bottom = (page_h - CARD_H) / 2
    mid_x = left + CARD_W / 2
    warnings = []

    img = load_image(image_path)
    dpi_before = dpi_for_size(*img.size, mode)
    used = None
    if enhance:
        key = (image_path, os.path.getmtime(image_path), mode,
               enhance["method"], enhance["cleanup"])
        if _enh_cache["key"] == key:
            img, used, cached_warn = _enh_cache["val"]
            warnings.extend(cached_warn)
        else:
            enh_warn = []
            img, used = enhance_image(img, mode, enhance["method"], enhance["cleanup"], enh_warn)
            _enh_cache.update(key=key, val=(img, used, enh_warn))
            warnings.extend(enh_warn)

    c = canvas.Canvas(output_path, pagesize=(page_w, page_h))
    c.setTitle("Printable Greeting Card")
    c.setAuthor("Greeting Card Generator")

    # 1. Cut border (solid)
    c.setLineWidth(1)
    c.setStrokeColorRGB(*CUT_COLOR)
    c.rect(left, bottom, CARD_W, CARD_H)

    # 2. Fold line (dotted)
    c.setDash(4, 4)
    c.line(mid_x, bottom, mid_x, bottom + CARD_H)
    c.setDash()

    # 3. Right panel = front cover image
    box_x = mid_x + PANEL_PADDING
    box_y = bottom + PANEL_PADDING
    box_w = CARD_W / 2 - 2 * PANEL_PADDING
    box_h = CARD_H - 2 * PANEL_PADDING

    iw, ih = img.size
    scale = (max if mode == "fill" else min)(box_w / iw, box_h / ih)
    dw, dh = iw * scale, ih * scale
    dx = box_x + (box_w - dw) / 2
    dy = box_y + (box_h - dh) / 2

    c.saveState()
    clip = c.beginPath()
    clip.rect(box_x, box_y, box_w, box_h)
    c.clipPath(clip, stroke=0, fill=0)
    c.drawImage(ImageReader(img), dx, dy, width=dw, height=dh)
    c.restoreState()

    # 4. Left panel = back cover badge
    if back:
        draw_back_cover(c, left, bottom, CARD_W / 2, CARD_H, back, warnings)

    # 5. Instruction text
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(*TEXT_COLOR)
    c.drawCentredString(page_w / 2, bottom - 0.3 * inch,
                        "Print at 100% scale  |  Cut along solid line  |  Fold at center dotted line")

    c.showPage()
    c.save()
    return {"dpi": effective_dpi(img, box_w, box_h, mode), "dpi_before": dpi_before,
            "enhanced": used, "warnings": warnings}


def open_file(path):
    system = platform.system()
    if system == "Windows":
        os.startfile(path)  # noqa: S606
    elif system == "Darwin":
        subprocess.run(["open", path], check=False)
    else:
        subprocess.run(["xdg-open", path], check=False)


# ------------------------------------------------------------------- GUI
class CardApp:
    BG = "#f4f6f8"

    def __init__(self, root):
        self.root = root
        self.root.title("Printable Card Generator")
        self.root.geometry("480x930")
        self.root.resizable(False, False)
        self.root.config(bg=self.BG)

        self.image_path = ""
        self.preview_img = None

        self.page_var = tk.StringVar(value=list(PAGE_SIZES)[0])
        self.mode_var = tk.StringVar(value="fit")
        self.open_var = tk.BooleanVar(value=True)

        self.back_var = tk.BooleanVar(value=True)
        self.label_var = tk.StringVar(value=DEFAULT_LABEL)
        self.icon_var = tk.StringVar(value="Heart")
        self.tagline_var = tk.StringVar(value=TAGLINE_TEMPLATES[0])
        self.lineart_var = tk.BooleanVar(value=True)

        self.enh_var = tk.BooleanVar(value=True)
        self.method_var = tk.StringVar(value=list(ENHANCE_METHODS)[0])
        self.clean_var = tk.BooleanVar(value=True)
        self.img_size = None

        self._build_ui()
        self.mode_var.trace_add("write", lambda *a: self.update_quality())
        self.enh_var.trace_add("write", lambda *a: self.update_quality())

    # ---- UI
    def _build_ui(self):
        bg = self.BG
        tk.Label(self.root, text="Greeting Card PDF Generator",
                 font=("Arial", 15, "bold"), bg=bg, fg="#222").pack(pady=(14, 6))

        tk.Button(self.root, text="Select Coloring Image (PNG/JPG)",
                  command=self.select_image, font=("Arial", 10, "bold"),
                  bg="#4CAF50", fg="white", activebackground="#43A047",
                  padx=12, pady=7, cursor="hand2", relief="flat").pack(pady=4)

        self.path_label = tk.Label(self.root, text="No file selected",
                                   font=("Arial", 9), bg=bg, fg="gray", wraplength=420)
        self.path_label.pack()

        self.preview = tk.Label(self.root, text="Preview", bg="white", fg="#aaa",
                                width=26, height=7, relief="solid", bd=1)
        self.preview.pack(pady=8)

        # --- Front/page options
        opts = tk.Frame(self.root, bg=bg)
        opts.pack(pady=2)
        tk.Label(opts, text="Page size:", bg=bg).grid(row=0, column=0, sticky="e", padx=4, pady=2)
        ttk.Combobox(opts, textvariable=self.page_var, values=list(PAGE_SIZES),
                     state="readonly", width=22).grid(row=0, column=1, pady=2)
        tk.Label(opts, text="Image mode:", bg=bg).grid(row=1, column=0, sticky="e", padx=4, pady=2)
        modes = tk.Frame(opts, bg=bg)
        modes.grid(row=1, column=1, sticky="w")
        tk.Radiobutton(modes, text="Fit", variable=self.mode_var, value="fit", bg=bg).pack(side="left")
        tk.Radiobutton(modes, text="Fill (crop)", variable=self.mode_var, value="fill", bg=bg).pack(side="left")

        # --- Back cover options
        box = tk.LabelFrame(self.root, text=" Back cover ", bg=bg, padx=10, pady=6)
        box.pack(fill="x", padx=16, pady=8)

        tk.Checkbutton(box, text="Add back cover badge", variable=self.back_var,
                       bg=bg, command=self._toggle_back).grid(row=0, column=0, columnspan=2, sticky="w")

        tk.Label(box, text="Top text:", bg=bg).grid(row=1, column=0, sticky="e", pady=3)
        self.label_entry = ttk.Entry(box, textvariable=self.label_var, width=32)
        self.label_entry.grid(row=1, column=1, sticky="w", pady=3)

        tk.Label(box, text="Icon:", bg=bg).grid(row=2, column=0, sticky="e", pady=3)
        self.icon_cb = ttk.Combobox(box, textvariable=self.icon_var, state="readonly",
                                    values=["Heart", "Star", "None"], width=10)
        self.icon_cb.grid(row=2, column=1, sticky="w", pady=3)

        tk.Label(box, text="Bottom text:", bg=bg).grid(row=3, column=0, sticky="e", pady=3)
        self.tagline_cb = ttk.Combobox(box, textvariable=self.tagline_var,
                                       values=TAGLINE_TEMPLATES, width=30)  # editable
        self.tagline_cb.grid(row=3, column=1, sticky="w", pady=3)
        tk.Label(box, text="(template bachun ba nijer moto likhun)", bg=bg, fg="gray",
                 font=("Arial", 8)).grid(row=4, column=1, sticky="w")

        emo = tk.Frame(box, bg=bg)
        emo.grid(row=5, column=0, columnspan=2, pady=4)
        for e in QUICK_EMOJIS:
            tk.Button(emo, text=e, font=("Segoe UI Emoji", 11), width=2, relief="flat",
                      command=lambda x=e: self._insert_emoji(x)).pack(side="left", padx=1)

        self.lineart_chk = tk.Checkbutton(box, text="Emoji black & white line art (coloring-friendly)",
                                          variable=self.lineart_var, bg=bg)
        self.lineart_chk.grid(row=6, column=0, columnspan=2, sticky="w")

        self._back_widgets = [self.label_entry, self.icon_cb, self.tagline_cb, self.lineart_chk]

        # --- Image quality / enhance
        qbox = tk.LabelFrame(self.root, text=" Image quality ", bg=bg, padx=10, pady=6)
        qbox.pack(fill="x", padx=16, pady=4)
        self.quality_label = tk.Label(qbox, text="Select an image to check print quality",
                                      bg=bg, fg="gray", font=("Arial", 9, "bold"))
        self.quality_label.pack(anchor="w")
        tk.Checkbutton(qbox, text=f"Enhance image (upscale if below {ENHANCE_BELOW} DPI)",
                       variable=self.enh_var, bg=bg).pack(anchor="w")
        row = tk.Frame(qbox, bg=bg)
        row.pack(anchor="w")
        tk.Label(row, text="Method:", bg=bg).pack(side="left")
        ttk.Combobox(row, textvariable=self.method_var, values=list(ENHANCE_METHODS),
                     state="readonly", width=30).pack(side="left", padx=4)
        ai_ok = find_realesrgan() is not None
        tk.Label(qbox, bg=bg, font=("Arial", 8),
                 text="AI engine found" if ai_ok else "AI engine not found - Basic will be used",
                 fg="#2e7d32" if ai_ok else "#c62828").pack(anchor="w")
        tk.Checkbutton(qbox, text="Clean lines (pure black & white, removes gray noise)",
                       variable=self.clean_var, bg=bg).pack(anchor="w")

        # --- Actions
        tk.Checkbutton(self.root, text="Open PDF after saving", variable=self.open_var, bg=bg).pack()

        btns = tk.Frame(self.root, bg=bg)
        btns.pack(pady=8)
        self.prev_btn = tk.Button(btns, text="Preview PDF", command=self.preview_pdf,
                                  font=("Arial", 10, "bold"), bg="#9E9E9E", fg="white",
                                  padx=12, pady=8, state=tk.DISABLED, cursor="hand2", relief="flat")
        self.prev_btn.pack(side="left", padx=6)
        self.gen_btn = tk.Button(btns, text="Generate PDF Card", command=self.gen_pdf_action,
                                 font=("Arial", 11, "bold"), bg="#2196F3", fg="white",
                                 activebackground="#1E88E5", padx=16, pady=8,
                                 state=tk.DISABLED, cursor="hand2", relief="flat")
        self.gen_btn.pack(side="left", padx=6)
        self.status_label = tk.Label(self.root, text="", bg=bg, fg="#555", font=("Arial", 9))
        self.status_label.pack()

    def _toggle_back(self):
        state = "normal" if self.back_var.get() else "disabled"
        for w in self._back_widgets:
            w.config(state=state)
        if self.back_var.get():
            self.icon_cb.config(state="readonly")

    def _insert_emoji(self, emoji):
        if self.back_var.get():
            self.tagline_cb.insert(tk.INSERT, emoji)
            self.tagline_cb.focus_set()

    # ---- actions
    def update_quality(self):
        if not self.img_size:
            return
        dpi = dpi_for_size(*self.img_size, self.mode_var.get())
        if dpi >= ENHANCE_BELOW:
            text, color = f"Print quality: Good (~{int(dpi)} DPI)", "#2e7d32"
        elif dpi >= MIN_DPI:
            text, color = f"Print quality: Fair (~{int(dpi)} DPI)", "#ef6c00"
        else:
            text, color = f"Print quality: LOW (~{int(dpi)} DPI)", "#c62828"
        if dpi < ENHANCE_BELOW and self.enh_var.get():
            text += "  ->  will be enhanced"
        self.quality_label.config(text=text, fg=color)

    def select_image(self):
        path = filedialog.askopenfilename(filetypes=[("Image Files", "*.png *.jpg *.jpeg")])
        if not path:
            return
        try:
            with Image.open(path) as im:
                size = im.size
                thumb = im.convert("RGB")
                thumb.thumbnail((200, 130))
            self.preview_img = ImageTk.PhotoImage(thumb)
        except Exception as e:
            messagebox.showerror("Error", f"Image open kora jayni:\n{e}")
            return
        self.image_path = path
        self.img_size = size
        self.preview.config(image=self.preview_img, text="", width=0, height=0)
        self.path_label.config(text=f"Selected: {os.path.basename(path)}", fg="black")
        self.gen_btn.config(state=tk.NORMAL)
        self.prev_btn.config(state=tk.NORMAL)
        self.update_quality()

        if dpi_for_size(*size, self.mode_var.get()) < ENHANCE_BELOW and not self.enh_var.get():
            if messagebox.askyesno("Low resolution",
                                   "Image er resolution kom, print e jhapsha hobe.\n"
                                   "Auto-enhance chalu korbo?"):
                self.enh_var.set(True)

    def _back_options(self):
        if not self.back_var.get():
            return None
        return {
            "label": self.label_var.get().strip(),
            "tagline": self.tagline_var.get(),
            "icon": self.icon_var.get().lower(),
            "lineart": self.lineart_var.get(),
        }

    def _collect(self):
        """Tk variable gulo main thread e pore nei (thread-safe)."""
        enhance = None
        if self.enh_var.get():
            enhance = {"method": ENHANCE_METHODS[self.method_var.get()],
                       "cleanup": self.clean_var.get()}
        return dict(image_path=self.image_path,
                    page_size=PAGE_SIZES[self.page_var.get()],
                    mode=self.mode_var.get(),
                    back=self._back_options(),
                    enhance=enhance)

    def _set_busy(self, busy):
        state = tk.DISABLED if busy else tk.NORMAL
        self.gen_btn.config(state=state)
        self.prev_btn.config(state=state)
        self.status_label.config(text="Working... (AI upscale may take a minute)" if busy else "")

    def _run_async(self, output, preview):
        params = self._collect()
        self._set_busy(True)

        def work():
            try:
                result, err = generate_pdf(output_path=output, **params), None
            except Exception as e:
                result, err = None, e
            self.root.after(0, lambda: self._finish(result, err, output, preview))

        threading.Thread(target=work, daemon=True).start()

    def _finish(self, result, err, output, preview):
        self._set_busy(False)
        if err:
            messagebox.showerror("Error", f"PDF toiri kora jayni:\n{err}")
            return
        if preview:
            try:
                open_file(output)
            except Exception:
                pass
            return

        info, warn = [], list(result["warnings"])
        if result["enhanced"]:
            info.append(f"Enhanced ({result['enhanced']}): ~{int(result['dpi_before'])} "
                        f"-> ~{int(result['dpi'])} DPI")
        if result["dpi"] < MIN_DPI:
            warn.append(f"Image resolution kom (~{int(result['dpi'])} DPI). "
                        f"Print e jhapsha dekhate pare. Boro image use korun.")

        msg = f"PDF saved:\n{output}"
        if info:
            msg += "\n\n" + "\n".join(info)
        if warn:
            messagebox.showwarning("Saved (with notes)", msg + "\n\n" + "\n".join(warn))
        else:
            messagebox.showinfo("Success!", msg)

        if self.open_var.get():
            try:
                open_file(output)
            except Exception:
                pass

    def preview_pdf(self):
        self._run_async(os.path.join(tempfile.gettempdir(), "card_preview.pdf"), preview=True)

    def gen_pdf_action(self):
        output = filedialog.asksaveasfilename(
            defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
            initialfile="printable_greeting_card.pdf")
        if output:
            self._run_async(output, preview=False)


if __name__ == "__main__":
    root = tk.Tk()
    CardApp(root)
    root.mainloop()
