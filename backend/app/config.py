"""Тохиргоо. Бүх тоо (тариф, шимтгэл, хязгаар) эндээс эсвэл .env файлаас өөрчлөгдөнө."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="UNAA_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://unaa:unaa@localhost:5432/unaa"

    # --- Нууц түлхүүрүүд: жинхэнэ орчинд заавал .env-ээр солино ---
    jwt_secret: str = "dev-only-change-me-dev-only-change-me"
    jwt_ttl_minutes: int = 60 * 24 * 30
    # Баримт бичгийн зургийг шифрлэх Fernet түлхүүр (хоосон бол dev түлхүүр үүсгэнэ)
    file_encryption_key: str = ""
    upload_dir: str = "./uploads"
    max_upload_bytes: int = 8 * 1024 * 1024

    # --- SMS ---
    # "dev": кодыг хариунд буцаана (зөвхөн туршилт). "provider": жинхэнэ SMS үйлчилгээ.
    sms_mode: str = "dev"
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5

    # --- Төлбөр ---
    # "dev": туршилтын цэнэглэлт нээлттэй. "provider": зөвхөн төлбөрийн системийн мэдэгдлээр.
    payments_mode: str = "dev"

    # --- Үнэ (бүгд жишээ тоо, төгрөгөөр) ---
    taxi_rate_per_km: int = 2000
    min_fare: int = 1500
    # Машинд суусан зорчигчийн тоо -> нэг суудлын үнэ таксины үнийн хэдэн хувь байх
    shared_factors: dict[int, float] = {1: 0.70, 2: 0.55, 3: 0.45, 4: 0.40}
    # Лааны гол: үндсэн үнээс доош/дээш хэлбэлзэх ердийн хүрээ
    band_low: float = 0.80
    band_high: float = 1.20
    # Тохирсон цэгээс өмнө буусан үед авах доод хувь
    early_exit_min_fraction: float = 0.30

    # --- Шимтгэл: (хэсгийн дээд хязгаар, хувь). None = хязгааргүй. Хэсэг тус бүрд тооцно. ---
    commission_brackets: list[tuple[int | None, float]] = [
        (5_000, 0.10),
        (20_000, 0.07),
        (None, 0.05),
    ]

    # --- Тааруулалт ---
    pickup_radius_m: int = 300  # зорчигч жолоочийн маршрутаас хэр хол зогсож болох
    dropoff_radius_m: int = 1500  # очих газар маршрутаас хэр хол байж болох (маршрут дээр буулгана)
    min_shared_m: int = 500  # хамт явах хамгийн бага зай
    request_ttl_minutes: int = 30
    tune_count: int = 8  # апп дахь аялгуу/өнгөний тоо
    tune_radius_m: int = 1000  # энэ зайд байгаа хосууд өөр аялгуутай байна

    # --- Хязгаарууд ---
    max_topup_per_day: int = 500_000
    max_payout_per_day: int = 1_000_000
    max_guests_per_booking: int = 6


@lru_cache
def get_settings() -> Settings:
    return Settings()
