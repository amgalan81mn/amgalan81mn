import io
import os

os.environ["BARAA_NO_DEFAULT_APP"] = "1"

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.embedders import BasicEmbedder  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path):
    app = create_app(":memory:", tmp_path / "media", BasicEmbedder())
    with TestClient(app) as c:
        yield c


def draw_object(color, shape="rect", angle=0.0, light=1.0, size=(480, 360), blur=0):
    """Цагаан дэвсгэр дээрх энгийн "бараа". angle: эргүүлэлт, light: гэрлийн хүч."""
    w, h = size
    img = np.full((h, w, 3), 245, np.uint8)
    c = (w // 2, h // 2)
    if shape == "rect":
        box = cv2.boxPoints((c, (w * 0.55, h * 0.3), angle)).astype(np.int32)
        cv2.fillPoly(img, [box], color)
        # бариул
        cv2.circle(img, (int(c[0] + np.cos(np.radians(angle)) * w * 0.3), int(c[1] + np.sin(np.radians(angle)) * w * 0.3)),
                   int(h * 0.08), (40, 40, 40), -1)
    else:
        cv2.ellipse(img, c, (int(w * 0.25), int(h * 0.3)), angle, 0, 360, color, -1)
    img = np.clip(img.astype(np.float32) * light, 0, 255).astype(np.uint8)
    if blur:
        img = cv2.GaussianBlur(img, (0, 0), blur)
    return img


def png_bytes(rgb):
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, "PNG")
    return buf.getvalue()


def make_video(path, frames, fps=15):
    h, w = frames[0].shape[:2]
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
    for f in frames:
        vw.write(cv2.cvtColor(f, cv2.COLOR_RGB2BGR))
    vw.release()
    return path
