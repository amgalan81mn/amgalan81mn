# Dohulehu — Android апп

## Ажиллуулах

1. [Flutter](https://docs.flutter.dev/get-started/install) болон Android Studio суулгана.
2. Серверийг асаана (`../README.md`).
3. Android утсаа USB-ээр холбоод (эсвэл эмулятор асаагаад):

```
cd app
flutter pub get
flutter run --dart-define=API_BASE=http://<компьютерийн-IP>:8000
```

- Эмулятор дээр `API_BASE` өгөхгүй бол `http://10.0.2.2:8000` (компьютерийн localhost) руу холбогдоно.
- Жинхэнэ утас компьютертэй нэг Wi-Fi-д байх ёстой. Серверийг `uvicorn app.main:app --host 0.0.0.0` гэж асаана.
- Google маршрут: `--dart-define=GOOGLE_MAPS_KEY=...`. Түлхүүргүй бол маршрут шулуун шугам болно (туршилт).
- Газрын зураг OpenStreetMap дээр (түлхүүр шаардахгүй).

## Хоёр утсаар турших

Нэг утсаар жолооч, нөгөөгөөр зорчигч болж нэвтэрнэ. Жолоочийн бүртгэлийг админ зөвшөөрөх ёстой: `/docs` хуудаснаас
`/admin/...` хүсэлтүүдийг ашиглана (админ эрх: `python -m app.cli make-admin <дугаар>`).

## Тест

```
flutter analyze
flutter test
```
