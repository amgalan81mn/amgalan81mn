# Бараа Толь — сервер (Python / FastAPI)

## Ажиллуулах

Python 3.11 буюу түүнээс дээш хувилбар шаардлагатай.

```bash
cd backend
```

```bash
python -m venv .venv
```

```bash
source .venv/bin/activate      # Windows: .venv\Scripts\activate
```

```bash
pip install -r requirements-dev.txt
```

```bash
uvicorn app.main:app --reload
```

http://localhost:8000/docs хаягаар бүх API-г хөтөч дээрээс шууд туршиж болно.

Тест ажиллуулах:

```bash
pytest
```

## Зураг таних загвар

| `EMBEDDER` | Тайлбар |
|---|---|
| `basic` (өгөгдмөл) | Өнгө + дүрсний энгийн хээ. Татах зүйлгүй. Зөвхөн туршилтад зориулсан, бодит зурагт сул. |
| `dinov2` | DINOv2 загвар. Өнцөг, гэрэл, сүүдэр өөр байсан ч ижил барааг таньдаг. Доорх командаар суулгана. |

```bash
pip install -r requirements-ml.txt
```

```bash
EMBEDDER=dinov2 uvicorn app.main:app
```

Анх ажиллуулахад huggingface.co-оос ~90MB жин татна (`dinov2-small`).
"Ижил бараа" гэж үзэх босгыг бодит зургаар тохируулах хэрэгтэй: `MATCH_THRESHOLD_DINOV2` (өгөгдмөл 0.6).
Загвар бүр өөрийн хээг тусад нь хадгалдаг тул загвар солиход хуучин зургуудын хээг дахин тооцоолно (дараагийн алхам).

Бусад тохиргоо: `DATA_DIR` (өгөгдлийн сан, зургууд хадгалагдах хавтас; өгөгдмөл нь `backend/data`), `CORS_ORIGINS`.

## API

| Арга | Зам | Юу хийх |
|---|---|---|
| POST | `/api/products` | Бараа нэмэх (form: нэр, ангилал, баркод, үнэ…, `photos[]`, `video`) |
| POST | `/api/products/{id}/scan` | Тал бүрээс бичсэн видео. Тод, өөр өнцгийн кадрыг автоматаар сонгоно |
| POST | `/api/products/{id}/photos` | Нэмэлт зураг |
| POST | `/api/search/image` | Зураг (+ баркод)-аар хайх |
| GET | `/api/products` | Жагсаалт (`q`, `category`, `barcode`, `sort=score\|value\|reviews\|fail_rate\|new`) |
| GET | `/api/products/{id}` | Дэлгэрэнгүй: оноо, байр, эвдрэлийн статистик, илүү дээр сонголтууд, сэтгэгдлүүд |
| POST | `/api/products/{id}/reviews` | Туршлага бичих |
| GET | `/api/categories` | Ангиллууд |

## Бүтэц

```
app/main.py        API, зургийн хээний индекс
app/vision.py      Зураг унших, тодролт, видеоноос кадр сонгох
app/embedders.py   basic ба DINOv2 хээ гаргагч
app/scoring.py     Оноо, эвдрэлийн статистик
app/db.py          SQLite схем
tests/             Тестүүд (зохиомол зураг, видеогоор)
```
