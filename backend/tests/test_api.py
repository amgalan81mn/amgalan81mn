from pathlib import Path

from sqlalchemy import select

from app.models import AuditLog, Document, User

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-image-bytes" * 4
USER_DOCS = ["selfie", "id_front", "id_back"]
CAR_DOCS = ["vehicle_certificate", "car_front", "car_back", "car_side", "car_interior"]


def login(client, phone: str) -> dict:
    code = client.post("/auth/otp/request", json={"phone": phone}).json()["dev_code"]
    r = client.post("/auth/otp/verify", json={"phone": phone, "code": code})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def upload(client, h, url: str, data: bytes = PNG):
    return client.post(url, headers=h, files={"file": ("x.png", data, "image/png")})


def make_admin(client, db, phone="99000001") -> dict:
    h = login(client, phone)
    db.scalars(select(User).where(User.phone == f"+976{phone}")).one().is_admin = True
    db.commit()
    return h


def submit_identity(client, h, register_no="УБ90010112"):
    r = client.put(
        "/me/identity", headers=h, json={"last_name": "Бат", "first_name": "Дорж", "register_no": register_no}
    )
    assert r.status_code == 200, r.text
    for kind in USER_DOCS:
        assert upload(client, h, f"/me/documents/{kind}").status_code == 200
    assert client.post("/me/identity/submit", headers=h).status_code == 200


def test_login_rejects_wrong_code_and_bad_phone(client):
    assert client.post("/auth/otp/request", json={"phone": "123"}).status_code == 422
    client.post("/auth/otp/request", json={"phone": "99112233"})
    assert client.post("/auth/otp/verify", json={"phone": "99112233", "code": "000000x"}).status_code == 400
    assert client.post("/auth/otp/request", json={"phone": "+976 9911-2233"}).status_code == 429  # 30 сек
    assert client.get("/me").status_code == 401


def test_full_driver_registration_flow(client, db):
    h = login(client, "99112233")
    admin = make_admin(client, db)
    assert client.get("/me", headers=h).json()["can_drive"] is False

    # Зураг дутуу үед илгээж болохгүй
    client.put("/me/identity", headers=h, json={"last_name": "Бат", "first_name": "Дорж", "register_no": "уб90010112"})
    r = client.post("/me/identity/submit", headers=h)
    assert r.status_code == 400 and set(r.json()["detail"]["missing"]) == set(USER_DOCS)
    submit_identity(client, h)
    assert client.get("/me", headers=h).json()["register_no"] == "УБ90010112"
    # Шалгагдаж байх үед өөрчилж болохгүй
    assert upload(client, h, "/me/documents/selfie").status_code == 409

    # Машин: буруу дугаар, зураг дутуу, дараа нь бүрэн
    bad = {"plate": "12УБА", "make": "Toyota", "model": "Prius", "color": "Цагаан", "seats": 4}
    assert client.post("/me/vehicles", headers=h, json=bad).status_code == 422
    v = client.post("/me/vehicles", headers=h, json={**bad, "plate": "1234 уба"}).json()
    assert v["plate"] == "1234УБА" and set(v["missing_documents"]) == set(CAR_DOCS)
    assert client.post(f"/me/vehicles/{v['id']}/submit", headers=h).status_code == 400
    for kind in CAR_DOCS:
        assert upload(client, h, f"/me/vehicles/{v['id']}/documents/{kind}").status_code == 200
    assert client.post(f"/me/vehicles/{v['id']}/submit", headers=h).json()["status"] == "pending"

    # Жолоочийн мэдээлэл
    driver = {
        "license_no": "A1234567",
        "bank_name": "Хаан банк",
        "bank_account_no": "5001234567",
        "bank_account_holder": "Бат Дорж",
    }
    assert client.put("/me/driver", headers=h, json=driver).status_code == 200
    assert client.post("/me/driver/submit", headers=h).status_code == 400  # үнэмлэхний зураг алга
    assert upload(client, h, "/me/documents/driver_license").status_code == 200
    assert client.post("/me/driver/submit", headers=h).json()["status"] == "pending"

    # Админ биш хүн шалгалтын хэсэгт орж чадахгүй
    assert client.get("/admin/reviews", headers=h).status_code == 403
    reviews = client.get("/admin/reviews", headers=admin).json()
    uid = reviews["identities"][0]["user_id"]
    assert len(reviews["identities"][0]["documents"]) == 4 and len(reviews["vehicles"][0]["documents"]) == 5

    # Хувийн бүртгэл зөвшөөрөгдөөгүй байхад жолоочийг зөвшөөрөхгүй
    assert client.post(f"/admin/drivers/{uid}/review", headers=admin, json={"approve": True}).status_code == 409
    assert client.post(f"/admin/users/{uid}/identity/review", headers=admin, json={"approve": False}).status_code == 422
    for url in (f"/admin/users/{uid}/identity/review", f"/admin/drivers/{uid}/review"):
        assert client.post(url, headers=admin, json={"approve": True}).status_code == 200
    assert client.get("/me", headers=h).json()["can_drive"] is False  # машин хараахан зөвшөөрөгдөөгүй
    assert client.post(f"/admin/vehicles/{v['id']}/review", headers=admin, json={"approve": True}).status_code == 200
    assert client.get("/me", headers=h).json()["can_drive"] is True

    # Хаагдсан хэрэглэгч юу ч хийж чадахгүй
    client.post(f"/admin/users/{uid}/block", headers=admin, json={"blocked": True, "reason": "туршилт"})
    assert client.get("/me", headers=h).status_code == 403


def test_rejected_identity_can_be_fixed_and_resubmitted(client, db):
    h = login(client, "99112233")
    admin = make_admin(client, db)
    submit_identity(client, h)
    uid = client.get("/me", headers=h).json()["id"]
    r = client.post(
        f"/admin/users/{uid}/identity/review", headers=admin, json={"approve": False, "reason": "Зураг бүдэг"}
    )
    assert r.json()["identity_status"] == "rejected"
    assert client.get("/me", headers=h).json()["identity_reject_reason"] == "Зураг бүдэг"
    assert upload(client, h, "/me/documents/selfie").status_code == 200
    assert client.post("/me/identity/submit", headers=h).json()["identity_status"] == "pending"


def test_duplicate_register_no_and_plate_are_refused(client):
    a, b = login(client, "99112233"), login(client, "88112233")
    body = {"last_name": "А", "first_name": "Б", "register_no": "УБ90010112"}
    assert client.put("/me/identity", headers=a, json=body).status_code == 200
    assert client.put("/me/identity", headers=b, json=body).status_code == 409
    car = {"plate": "1234УБА", "make": "Toyota", "model": "Prius", "color": "Цагаан", "seats": 4}
    assert client.post("/me/vehicles", headers=a, json=car).status_code == 201
    assert client.post("/me/vehicles", headers=b, json=car).status_code == 409


def test_documents_are_encrypted_private_and_audited(client, db, settings):
    owner, other = login(client, "99112233"), login(client, "88112233")
    admin = make_admin(client, db)
    assert upload(client, owner, "/me/documents/id_front", b"not an image").status_code == 415
    doc_id = upload(client, owner, "/me/documents/id_front").json()["id"]

    stored = (Path(settings.upload_dir) / db.get(Document, doc_id).path).read_bytes()
    assert PNG not in stored  # дискэн дээр шифрлэгдсэн
    assert client.get(f"/documents/{doc_id}", headers=owner).content == PNG
    assert client.get(f"/documents/{doc_id}", headers=other).status_code == 404
    assert client.get(f"/documents/{doc_id}", headers=admin).content == PNG
    logs = db.scalars(select(AuditLog).where(AuditLog.action == "view_document")).all()
    assert [log.target for log in logs] == [doc_id]  # зөвхөн админы үзсэн нь бүртгэгдэнэ


def test_wallet_topup_and_payout_rules(client, db):
    h = login(client, "99112233")
    key = {"Idempotency-Key": "topup-0001"}
    for _ in range(2):
        r = client.post("/wallet/topup/dev", headers={**h, **key}, json={"amount": 20_000})
    assert r.json() == {"balance": 20_000, "held": 0, "available": 20_000}
    assert client.post("/wallet/topup/dev", headers=h, json={"amount": 1}).status_code == 422  # түлхүүргүй
    assert [t["amount"] for t in client.get("/wallet/transactions", headers=h).json()] == [20_000]
    # Баталгаажаагүй хүн мөнгө татаж чадахгүй
    r = client.post("/wallet/payouts", headers={**h, "Idempotency-Key": "payout-001"}, json={"amount": 5_000})
    assert r.status_code == 403
    admin = make_admin(client, db)
    assert client.get("/admin/ledger/integrity", headers=admin).json() == {
        "sum_of_balances": 0,
        "accounts_off_ledger": 0,
        "accounts_off_holds": 0,
    }


def test_quote(client):
    q = client.get("/pricing/quote", params={"distance_m": 10_000, "occupancy": 1}).json()
    assert q == {"base_seat_price": 14_000, "band_low": 11_200, "band_high": 16_800, "commission_on_base": 1_130}
