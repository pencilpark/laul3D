"""App icon in the Pencil Park colors: the bust rendered by icon.py on the macOS icon grid (824 px rounded square, flat #CF1149).

Blender -b --factory-startup -P icon.py -- bust.png
python compose.py bust.png app-icon.png app-icon-square.png
"""
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

SIZE, BOX, RADIUS = 1024, 824, 185
ACCENT = (207, 17, 73, 255)


def place_bust(canvas, bust, height, bottom):
    bust = bust.crop(bust.getbbox())
    bust = bust.resize((round(bust.width * height / bust.height), height), Image.LANCZOS)
    canvas.alpha_composite(bust, ((SIZE - bust.width) // 2, bottom - bust.height))


def main():
    bust = Image.open(sys.argv[1]).convert("RGBA")
    off = (SIZE - BOX) // 2
    shape = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(shape).rounded_rectangle([off, off, off + BOX - 1, off + BOX - 1], RADIUS, fill=255)

    icon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    shadow = ImageChops.offset(shape, 0, 10).filter(ImageFilter.GaussianBlur(14)).point(lambda a: int(a * 0.4))
    icon.paste((0, 0, 0, 255), (0, 0), shadow)
    plate = Image.new("RGBA", (SIZE, SIZE), ACCENT)
    icon.paste(plate, (0, 0), shape)
    place_bust(icon, bust, 600, off + BOX - 70)
    icon.save(sys.argv[2])

    square = Image.new("RGBA", (SIZE, SIZE), ACCENT)
    place_bust(square, bust, 740, SIZE - 80)
    square.save(sys.argv[3])


if __name__ == "__main__":
    main()
