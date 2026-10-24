"""Generate synthetic, clearly fake sample documents in seed/sample_docs/ (no real logos).
    uv run scripts/make_sample_docs.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "seed" / "sample_docs"


def font(size: int):
    for name in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def stamp(d: ImageDraw.ImageDraw, w: int) -> None:
    d.text((20, 10), "SAMPLE - FAKE DOCUMENT FOR DEMO", fill="#c00", font=font(22))


def paystub(path: Path, start: str, end: str, pay_date: str, ytd: str) -> None:
    img = Image.new("RGB", (1000, 640), "#fbfaf5")
    d = ImageDraw.Draw(img)
    stamp(d, 1000)
    d.text((40, 50), "Green Valley Landscaping LLC", fill="#1d4d2b", font=font(36))
    d.text((40, 95), "12 Fictional Way, Springfield, MA 01104", fill="#333", font=font(20))
    d.text((40, 140), "EARNINGS STATEMENT", fill="#000", font=font(26))
    rows = [("Employee", "Carlos Rivera"), ("Pay period", f"{start} to {end}"), ("Pay date", pay_date),
            ("Hours worked", "80.00"), ("Rate", "$16.50 / hour"), ("Gross pay", "$1,320.00"),
            ("Taxes and deductions", "-$215.00"), ("Net pay", "$1,105.00"), ("Gross YTD", ytd)]
    y = 195
    for k, v in rows:
        d.text((60, y), k, fill="#444", font=font(24))
        d.text((480, y), v, fill="#000", font=font(24))
        y += 44
    img.save(path, quality=88)


def earnings_screenshot(path: Path) -> None:
    img = Image.new("RGB", (720, 1280), "#ffffff")
    d = ImageDraw.Draw(img)
    stamp(d, 720)
    d.rectangle([0, 50, 720, 170], fill="#ff6a3d")
    d.text((40, 85), "RouteRunner  (fake app)", fill="#fff", font=font(40))
    d.text((40, 220), "Earnings", fill="#111", font=font(44))
    d.text((40, 290), "Nov 1 - Nov 30, 2026", fill="#555", font=font(30))
    d.text((40, 370), "$1,162.40", fill="#111", font=font(80))
    rows = [("Deliveries", "212"), ("Active time", "104 hr 10 min"), ("Base pay", "$701.20"),
            ("Tips", "$431.20"), ("Promotions", "$30.00"), ("Total", "$1,162.40")]
    y = 520
    for k, v in rows:
        d.text((40, y), k, fill="#333", font=font(32))
        d.text((460, y), v, fill="#111", font=font(32))
        d.line([40, y + 55, 680, y + 55], fill="#ddd", width=2)
        y += 80
    d.text((40, 1100), "Driver: Maria S.", fill="#555", font=font(28))
    img.save(path)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    paystub(OUT / "paystub_carlos_1.jpg", "11/01/2026", "11/14/2026", "11/20/2026", "$29,040.00")
    paystub(OUT / "paystub_carlos_2.jpg", "11/15/2026", "11/28/2026", "12/04/2026", "$30,360.00")
    earnings_screenshot(OUT / "earnings_maria.png")
    print("wrote", ", ".join(p.name for p in sorted(OUT.iterdir())))


if __name__ == "__main__":
    main()
