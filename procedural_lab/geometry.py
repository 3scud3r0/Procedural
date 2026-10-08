"""Renderer-independent scene plus CPU SVG/PNG previews, standard library only."""

import html
import math
import re
import struct
import zlib


def vector(value, size=3):
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise ValueError(f"expected {size} coordinates")
    result = [float(v) for v in value]
    if any(not math.isfinite(v) or abs(v) > 1e6 for v in result):
        raise ValueError("coordinates must be finite and within +/- 1e6")
    return result


def color(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError("color must be #RRGGBB")
    return value.lower()


class Scene:
    def __init__(self, max_objects=10000):
        self.objects = []
        self.max_objects = max_objects
        self.background = "#111821"

    def add(self, kind, position=(0, 0, 0), color="#c5de91", name=None, **parameters):
        if len(self.objects) >= self.max_objects:
            raise ValueError("scene object limit exceeded")
        node = {
            "id": len(self.objects),
            "kind": kind,
            "position": vector(position),
            "color": globals()["color"](color),
            "name": str(name or kind),
            **parameters,
        }
        self.objects.append(node)
        return node

    def box(self, size=(1, 1, 1), **options):
        size = vector(size)
        if any(v <= 0 for v in size):
            raise ValueError("box size must be positive")
        return self.add("box", size=size, **options)

    def sphere(self, radius=1, **options):
        radius = float(radius)
        if not math.isfinite(radius) or not 0 < radius <= 1e6:
            raise ValueError("radius must be positive and finite")
        return self.add("sphere", radius=radius, **options)

    def line(self, points, width=1, **options):
        if not isinstance(points, (list, tuple)) or not 2 <= len(points) <= 10000:
            raise ValueError("line requires 2..10000 points")
        width = float(width)
        if not math.isfinite(width) or width <= 0:
            raise ValueError("line width must be positive")
        return self.add("line", points=[vector(p) for p in points], width=width, **options)

    def to_dict(self):
        return {
            "schema": "procedural.scene/1",
            "background": self.background,
            "objects": self.objects,
        }


def _project(point):
    x, y, z = point
    return (x - z) * 0.8660254, (x + z) * 0.5 - y


def primitives(scene, width=960, height=640):
    """Isometric projection with automatic framing and painter ordering."""
    shapes = []
    for obj in scene["objects"]:
        x, y, z = obj["position"]
        depth = x + y + z
        base = {"color": obj["color"], "depth": depth, "name": obj["name"]}
        if obj["kind"] == "sphere":
            shapes.append(
                {**base, "type": "circle", "center": _project((x, y, z)), "radius": obj["radius"]}
            )
        elif obj["kind"] == "box":
            a, b, c = (s / 2 for s in obj["size"])
            vertices = [
                _project((x + dx * a, y + dy * b, z + dz * c))
                for dx, dy, dz in [
                    (-1, -1, -1),
                    (1, -1, -1),
                    (1, 1, -1),
                    (-1, 1, -1),
                    (-1, -1, 1),
                    (1, -1, 1),
                    (1, 1, 1),
                    (-1, 1, 1),
                ]
            ]
            for face, shade in [((0, 1, 2, 3), 0.72), ((1, 5, 6, 2), 0.88), ((3, 2, 6, 7), 1.0)]:
                shapes.append(
                    {
                        **base,
                        "type": "polygon",
                        "points": [vertices[i] for i in face],
                        "shade": shade,
                    }
                )
        elif obj["kind"] == "line":
            points = [_project((x + p[0], y + p[1], z + p[2])) for p in obj["points"]]
            shapes.append({**base, "type": "line", "points": points, "width": obj["width"]})
    bounds = []
    for shape in shapes:
        if shape["type"] == "circle":
            x, y = shape["center"]
            r = shape["radius"]
            bounds.extend([(x - r, y - r), (x + r, y + r)])
        else:
            bounds.extend(shape["points"])
    if not bounds:
        return []
    xs, ys = zip(*bounds)
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    scale = min((width - 64) / max(1, max(xs) - min(xs)), (height - 64) / max(1, max(ys) - min(ys)))

    def screen(p):
        return (p[0] - cx) * scale + width / 2, (p[1] - cy) * scale + height / 2

    for shape in shapes:
        if shape["type"] == "circle":
            shape["center"] = screen(shape["center"])
            shape["radius"] *= scale
        else:
            shape["points"] = [screen(p) for p in shape["points"]]
    return sorted(shapes, key=lambda s: s["depth"])


def svg(scene, width=960, height=640):
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="100%" height="100%" fill="{color(scene["background"])}"/>',
    ]
    for shape in primitives(scene, width, height):
        fill = color(shape["color"])
        title = html.escape(shape["name"])
        if shape["type"] == "circle":
            x, y = shape["center"]
            parts.append(
                f'<circle cx="{x:.3f}" cy="{y:.3f}" r="{shape["radius"]:.3f}" fill="{fill}" stroke="#101820"><title>{title}</title></circle>'
            )
        else:
            points = " ".join(f"{x:.3f},{y:.3f}" for x, y in shape["points"])
            if shape["type"] == "line":
                parts.append(
                    f'<polyline points="{points}" fill="none" stroke="{fill}" stroke-width="{shape["width"]}"><title>{title}</title></polyline>'
                )
            else:
                parts.append(
                    f'<polygon points="{points}" fill="{fill}" fill-opacity="{shape["shade"]}" stroke="#101820"><title>{title}</title></polygon>'
                )
    return ("\n".join(parts) + "\n</svg>\n").encode()


def png(scene, width=960, height=640):
    """Simple CPU rasterizer; flat shading, not WebGL visual parity."""
    if (
        type(width) is not int
        or type(height) is not int
        or not 64 <= width <= 2048
        or not 64 <= height <= 2048
    ):
        raise ValueError("PNG dimensions must be integers in [64, 2048]")
    background = bytes.fromhex(color(scene["background"])[1:])
    pixels = bytearray(background * (width * height))

    def span(y, left, right, rgb):
        if 0 <= y < height:
            left, right = max(0, math.ceil(left)), min(width - 1, math.floor(right))
            if right >= left:
                start = (y * width + left) * 3
                pixels[start : start + (right - left + 1) * 3] = rgb * (right - left + 1)

    for shape in primitives(scene, width, height):
        rgb = bytes(int(v * shape.get("shade", 1)) for v in bytes.fromhex(shape["color"][1:]))
        if shape["type"] == "circle":
            x, y = shape["center"]
            r = shape["radius"]
            for row in range(max(0, math.ceil(y - r)), min(height, math.floor(y + r) + 1)):
                half = math.sqrt(max(0, r * r - (row - y) ** 2))
                span(row, x - half, x + half, rgb)
        elif shape["type"] == "polygon":
            points = shape["points"]
            for row in range(
                max(0, math.ceil(min(y for _, y in points))),
                min(height, math.floor(max(y for _, y in points)) + 1),
            ):
                crossings = []
                for a, b in zip(points, points[1:] + points[:1]):
                    if min(a[1], b[1]) <= row < max(a[1], b[1]):
                        crossings.append(a[0] + (row - a[1]) * (b[0] - a[0]) / (b[1] - a[1]))
                crossings.sort()
                for left, right in zip(crossings[::2], crossings[1::2]):
                    span(row, left, right, rgb)
        else:
            for a, b in zip(shape["points"], shape["points"][1:]):
                count = max(1, int(max(abs(a[0] - b[0]), abs(a[1] - b[1]))))
                radius = max(1, round(shape["width"] / 2))
                for step in range(count + 1):
                    x = a[0] + (b[0] - a[0]) * step / count
                    y = round(a[1] + (b[1] - a[1]) * step / count)
                    for row in range(y - radius, y + radius + 1):
                        span(row, x - radius, x + radius, rgb)

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + pixels[y * width * 3 : (y + 1) * width * 3] for y in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
