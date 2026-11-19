import numpy as np

from app.embedders import BasicEmbedder
from app.scoring import compute_stats
from app.vision import select_scan_frames, sharpness

from .conftest import draw_object, make_video, png_bytes

RED = (200, 50, 40)
BLUE = (40, 80, 200)


def files(*imgs):
    return [("photos", (f"p{i}.png", png_bytes(im), "image/png")) for i, im in enumerate(imgs)]


def test_scoring_bad_product_ranks_lower():
    bad = compute_stats([
        {"rating": 2, "broke": 1, "broken_part": "Ир ", "months_used": 2},
        {"rating": 1, "broke": 1, "broken_part": "ир", "months_used": 4},
        {"rating": 2, "broke": 1, "broken_part": "бариул", "months_used": 3},
    ])
    good = compute_stats([{"rating": 5, "broke": 0}, {"rating": 4, "broke": 0}, {"rating": 5, "broke": 0}])
    assert good["score"] > bad["score"]
    assert bad["top_broken_parts"][0] == {"part": "ир", "count": 2, "share": 2 / 3}
    assert bad["median_months_to_fail"] == 3
    assert compute_stats([])["score"] is None


def test_basic_embedder_tells_objects_apart():
    e = BasicEmbedder()
    a, a_lit, b = e.embed([draw_object(RED), draw_object(RED, light=0.8), draw_object(BLUE, "ellipse")])
    assert a @ a_lit > a @ b
    assert a @ a_lit > 0.9


def test_scan_frame_selection_drops_blur_and_duplicates():
    sharp_frames = [draw_object(RED, angle=a) for a in range(0, 180, 6)]  # 30 өнцөг
    blurry = [draw_object(RED, angle=a, blur=6) for a in range(3, 180, 30)]
    dupes = [draw_object(RED, angle=0)] * 10
    frames = sharp_frames + blurry + dupes
    chosen = select_scan_frames(frames, BasicEmbedder(), max_frames=8)
    assert 2 <= len(chosen) <= 8
    blur_level = max(sharpness(f) for f in blurry)
    assert all(f.sharpness > blur_level for f in chosen)
    # давхардсан кадр сонгогдохгүй
    embs = np.stack([f.embedding for f in chosen])
    sims = embs @ embs.T
    assert (sims[~np.eye(len(chosen), dtype=bool)] < 0.999).all()


def test_full_flow_scan_search_review(client, tmp_path):
    video = make_video(tmp_path / "scan.avi", [draw_object(RED, angle=a) for a in range(0, 360, 8)])
    with open(video, "rb") as fh:
        r = client.post("/api/products", data={"name": "Peeler A", "category": "Kitchen", "price": "8000", "barcode": "4901234567894"},
                        files=[("video", ("scan.avi", fh, "video/x-msvideo"))])
    assert r.status_code == 201, r.text
    a = r.json()["id"]
    assert r.json()["images_added"] >= 3

    r = client.post("/api/products", data={"name": "Peeler B", "category": "Kitchen", "price": "15000"},
                    files=files(draw_object(BLUE, "ellipse")))
    b = r.json()["id"]

    # Өөр өнцөг, бүдэг гэрэлтэй зургаар хайхад A олдоно
    r = client.post("/api/search/image", files=files(draw_object(RED, angle=123, light=0.85)))
    res = r.json()["results"]
    assert res[0]["id"] == a and res[0]["is_match"] is True
    assert next(x for x in res if x["id"] == b)["is_match"] is False

    # Баркодоор яг таарна
    r = client.post("/api/search/image", files=files(draw_object(BLUE, "ellipse")), data={"barcode": "4901234567894"})
    assert r.json()["results"][0]["id"] == a and r.json()["results"][0]["match_by"] == "barcode"
    assert client.get("/api/products", params={"barcode": "4901234567894"}).json()[0]["id"] == a

    for _ in range(3):
        assert client.post(f"/api/products/{a}/reviews", json={
            "rating": 2, "broke": True, "broken_part": "blade", "months_used": 2,
            "would_buy_again": False, "better_alt_id": b}).status_code == 201
        client.post(f"/api/products/{b}/reviews", json={"rating": 5, "months_used": 12, "would_buy_again": True})

    d = client.get(f"/api/products/{a}").json()
    assert d["product"]["stats"]["fail_rate"] == 1
    assert d["product"]["stats"]["top_broken_parts"][0]["part"] == "blade"
    assert d["rank"] == 2 and d["category_size"] == 2
    assert d["better_alternatives"][0]["id"] == b
    assert d["recommended_instead"][0] == {**d["recommended_instead"][0], "id": b, "votes": 3}
    assert all(img["source"] == "scan" for img in d["product"]["images"])
    assert client.get(f"/api/products/{a}/parts").json() == ["blade"]
    assert [x["id"] for x in client.get("/api/products", params={"category": "Kitchen"}).json()] == [b, a]

    img_url = d["product"]["images"][0]["url"]
    assert client.get(img_url).headers["content-type"] == "image/jpeg"


def test_rejects_bad_input(client):
    assert client.post("/api/products", data={"name": "", "category": "x"}).status_code == 422
    assert client.post("/api/products", data={"name": "x", "category": "y"},
                       files=[("photos", ("a.png", b"not an image", "image/png"))]).status_code == 400
    pid = client.post("/api/products", data={"name": "x", "category": "y", "barcode": "123"}).json()["id"]
    assert client.post("/api/products", data={"name": "z", "category": "y", "barcode": "123"}).status_code == 409
    assert client.post(f"/api/products/{pid}/reviews", json={"rating": 9}).status_code == 422
    assert client.post("/api/products/9999/reviews", json={"rating": 3}).status_code == 404
    assert client.post(f"/api/products/{pid}/scan",
                       files=[("video", ("v.mp4", b"garbage", "video/mp4"))]).status_code == 400
