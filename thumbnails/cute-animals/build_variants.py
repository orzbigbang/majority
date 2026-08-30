from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).parent
REFS = ROOT / "references"
W, H = 1792, 1024
FONT_REGULAR = r"C:\Windows\Fonts\msyh.ttc"
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"

ANIMALS = [
    ("sitting-rabbit.png", "兔子", "RABBIT"),
    ("sitting-cat.png", "猫咪", "CAT"),
    ("swimming-turtle.png", "海龟", "TURTLE"),
    ("elephant-alone.png", "大象", "ELEPHANT"),
]


def font(size: int, bold: bool = False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size)


def recoloured_asset(filename: str, max_size: tuple[int, int], colour: str) -> Image.Image:
    src = Image.open(REFS / filename).convert("RGBA")
    alpha = src.getchannel("A")
    bbox = alpha.getbbox()
    if bbox:
        alpha = alpha.crop(bbox)
    alpha.thumbnail(max_size, Image.Resampling.LANCZOS)
    out = Image.new("RGBA", alpha.size, colour)
    out.putalpha(alpha)
    return out


def paste_centred(canvas: Image.Image, asset: Image.Image, box: tuple[int, int, int, int]):
    x0, y0, x1, y1 = box
    x = x0 + (x1 - x0 - asset.width) // 2
    y = y0 + (y1 - y0 - asset.height) // 2
    canvas.alpha_composite(asset, (x, y))


def rounded(draw: ImageDraw.ImageDraw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def candidate_warm():
    im = Image.new("RGBA", (W, H), "#F7F1E7")
    d = ImageDraw.Draw(im)
    d.text((96, 64), "可爱动物图鉴", font=font(104, True), fill="#172033")
    d.text((101, 187), "FREE ANIMALS  ·  FOUR FRIENDLY SILHOUETTES", font=font(26), fill="#647083")
    rounded(d, (1490, 70, 1696, 134), 32, "#2563EB")
    d.text((1537, 84), "SVG  /  CC0", font=font(24, True), fill="#FFFFFF")

    colours = ["#F4A9A8", "#9CC7F5", "#F5D66F", "#9ED6B8"]
    left, gap, card_w, card_h, top = 96, 28, 379, 620, 300
    for i, ((filename, cn, en), bg) in enumerate(zip(ANIMALS, colours)):
        x = left + i * (card_w + gap)
        rounded(d, (x, top, x + card_w, top + card_h), 48, bg)
        asset = recoloured_asset(filename, (285, 385), "#172033")
        paste_centred(im, asset, (x + 40, top + 45, x + card_w - 40, top + 445))
        d.text((x + 34, top + 500), cn, font=font(42, True), fill="#172033")
        d.text((x + 36, top + 554), en, font=font(22, True), fill="#172033")
    im.convert("RGB").save(ROOT / "candidate_01_four_cards_warm.png", optimize=True)


def candidate_split():
    im = Image.new("RGBA", (W, H), "#F4F7FC")
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 590, H), fill="#2563EB")
    d.text((76, 185), "可爱", font=font(116, True), fill="#FFFFFF")
    d.text((76, 315), "动物图鉴", font=font(92, True), fill="#FFFFFF")
    d.text((82, 456), "四个轮廓\n四种小性格", font=font(38), fill="#DCE9FF", spacing=18)
    d.text((82, 858), "FREE ANIMALS", font=font(24, True), fill="#FFFFFF")
    d.text((82, 898), "SVG COLLECTION", font=font(22), fill="#DCE9FF")

    colours = ["#F8BBB6", "#A7D2F7", "#F7DB79", "#A8DCBE"]
    positions = [(650, 70), (1166, 70), (650, 530), (1166, 530)]
    for (filename, cn, en), bg, (x, y) in zip(ANIMALS, colours, positions):
        rounded(d, (x, y, x + 468, y + 405), 42, bg)
        asset = recoloured_asset(filename, (255, 270), "#152038")
        paste_centred(im, asset, (x + 32, y + 30, x + 436, y + 295))
        d.text((x + 28, y + 319), cn, font=font(36, True), fill="#152038")
        d.text((x + 250, y + 331), en, font=font(18, True), fill="#35415A")
    im.convert("RGB").save(ROOT / "candidate_02_four_cards_split.png", optimize=True)


def candidate_dark():
    im = Image.new("RGBA", (W, H), "#111827")
    d = ImageDraw.Draw(im)
    title = "可爱动物图鉴"
    title_font = font(102, True)
    bbox = d.textbbox((0, 0), title, font=title_font)
    d.text(((W - (bbox[2] - bbox[0])) // 2, 58), title, font=title_font, fill="#FFFFFF")
    subtitle = "MEET FOUR QUIET LITTLE FRIENDS"
    sub_font = font(24, True)
    sb = d.textbbox((0, 0), subtitle, font=sub_font)
    d.text(((W - (sb[2] - sb[0])) // 2, 184), subtitle, font=sub_font, fill="#9FB5D7")

    colours = ["#FF8F86", "#6EB9F7", "#FFD75E", "#72D59C"]
    left, gap, card_w, card_h, top = 96, 28, 379, 650, 292
    for i, ((filename, cn, en), bg) in enumerate(zip(ANIMALS, colours)):
        x = left + i * (card_w + gap)
        rounded(d, (x, top, x + card_w, top + card_h), 54, bg)
        rounded(d, (x + 26, top + 24, x + 132, top + 70), 23, "#111827")
        d.text((x + 51, top + 34), f"0{i + 1}", font=font(20, True), fill="#FFFFFF")
        asset = recoloured_asset(filename, (285, 400), "#111827")
        paste_centred(im, asset, (x + 36, top + 90, x + card_w - 36, top + 486))
        d.text((x + 34, top + 518), cn, font=font(42, True), fill="#111827")
        d.text((x + 36, top + 574), en, font=font(21, True), fill="#27334C")
    im.convert("RGB").save(ROOT / "candidate_03_four_cards_dark.png", optimize=True)


def candidate_no_text_warm():
    im = Image.new("RGBA", (W, H), "#F7F1E7")
    d = ImageDraw.Draw(im)
    colours = ["#F4A9A8", "#9CC7F5", "#F5D66F", "#9ED6B8"]
    left, gap, card_w, card_h, top = 76, 24, 392, 876, 74
    for i, ((filename, _, _), bg) in enumerate(zip(ANIMALS, colours)):
        x = left + i * (card_w + gap)
        rounded(d, (x, top, x + card_w, top + card_h), 58, bg)
        asset = recoloured_asset(filename, (305, 650), "#172033")
        paste_centred(im, asset, (x + 34, top + 60, x + card_w - 34, top + card_h - 60))
    im.convert("RGB").save(ROOT / "candidate_01_four_cards_warm_no_text.png", optimize=True)


def candidate_no_text_grid():
    im = Image.new("RGBA", (W, H), "#F4F7FC")
    d = ImageDraw.Draw(im)
    colours = ["#F8BBB6", "#A7D2F7", "#F7DB79", "#A8DCBE"]
    positions = [(90, 72), (916, 72), (90, 532), (916, 532)]
    for (filename, _, _), bg, (x, y) in zip(ANIMALS, colours, positions):
        rounded(d, (x, y, x + 786, y + 420), 54, bg)
        asset = recoloured_asset(filename, (500, 330), "#152038")
        paste_centred(im, asset, (x + 65, y + 36, x + 721, y + 384))
    im.convert("RGB").save(ROOT / "candidate_02_four_cards_grid_no_text.png", optimize=True)


def candidate_no_text_dark():
    im = Image.new("RGBA", (W, H), "#111827")
    d = ImageDraw.Draw(im)
    colours = ["#FF8F86", "#6EB9F7", "#FFD75E", "#72D59C"]
    left, gap, card_w, card_h, top = 74, 24, 393, 824, 100
    for i, ((filename, _, _), bg) in enumerate(zip(ANIMALS, colours)):
        x = left + i * (card_w + gap)
        rounded(d, (x, top, x + card_w, top + card_h), 58, bg)
        asset = recoloured_asset(filename, (310, 620), "#111827")
        paste_centred(im, asset, (x + 32, top + 54, x + card_w - 32, top + card_h - 54))
    im.convert("RGB").save(ROOT / "candidate_03_four_cards_dark_no_text.png", optimize=True)


if __name__ == "__main__":
    candidate_warm()
    candidate_split()
    candidate_dark()
    candidate_no_text_warm()
    candidate_no_text_grid()
    candidate_no_text_dark()
    for name in (
        "candidate_01_four_cards_warm.png",
        "candidate_02_four_cards_split.png",
        "candidate_03_four_cards_dark.png",
    ):
        preview = Image.open(ROOT / name).convert("RGB")
        preview.thumbnail((300, 172), Image.Resampling.LANCZOS)
        preview.save(ROOT / name.replace(".png", "_300px.png"), optimize=True)
    for name in (
        "candidate_01_four_cards_warm_no_text.png",
        "candidate_02_four_cards_grid_no_text.png",
        "candidate_03_four_cards_dark_no_text.png",
    ):
        preview = Image.open(ROOT / name).convert("RGB")
        preview.thumbnail((300, 172), Image.Resampling.LANCZOS)
        preview.save(ROOT / name.replace(".png", "_300px.png"), optimize=True)
