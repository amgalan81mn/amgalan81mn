"""Өгөгдлийн бүтэц: хэрэглэгч, жолооч, машин, баримт бичиг, хэтэвч, гүйлгээний дэвтэр."""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    JSON,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


def _enum(cls: type[enum.Enum]) -> Enum:
    return Enum(cls, native_enum=False, length=32, values_callable=lambda e: [m.value for m in e])


class ReviewStatus(str, enum.Enum):
    none = "none"  # мэдээллээ бүрэн оруулаагүй
    pending = "pending"  # админы шалгалт хүлээж байна
    approved = "approved"
    rejected = "rejected"


class DocumentKind(str, enum.Enum):
    selfie = "selfie"
    id_front = "id_front"
    id_back = "id_back"
    driver_license = "driver_license"
    vehicle_certificate = "vehicle_certificate"
    car_front = "car_front"
    car_back = "car_back"
    car_side = "car_side"
    car_interior = "car_interior"


USER_DOCUMENTS = {DocumentKind.selfie, DocumentKind.id_front, DocumentKind.id_back}
DRIVER_DOCUMENTS = {DocumentKind.driver_license}
VEHICLE_DOCUMENTS = {
    DocumentKind.vehicle_certificate,
    DocumentKind.car_front,
    DocumentKind.car_back,
    DocumentKind.car_side,
    DocumentKind.car_interior,
}
# Бусад хэрэглэгчид харуулж болох зургууд. Бусад нь зөвхөн эзэн болон админд.
PUBLIC_DOCUMENTS = {
    DocumentKind.selfie,
    DocumentKind.car_front,
    DocumentKind.car_back,
    DocumentKind.car_side,
    DocumentKind.car_interior,
}


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    phone: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    last_name: Mapped[str | None] = mapped_column(String(80))
    first_name: Mapped[str | None] = mapped_column(String(80))
    register_no: Mapped[str | None] = mapped_column(String(10), unique=True)
    identity_status: Mapped[ReviewStatus] = mapped_column(_enum(ReviewStatus), default=ReviewStatus.none)
    identity_reject_reason: Mapped[str | None] = mapped_column(String(300))
    is_admin: Mapped[bool] = mapped_column(default=False)
    is_blocked: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    driver: Mapped["DriverProfile | None"] = relationship(
        back_populates="user", uselist=False, foreign_keys="DriverProfile.user_id"
    )
    documents: Mapped[list["Document"]] = relationship(back_populates="user")


class OtpCode(Base):
    __tablename__ = "otp_codes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    phone: Mapped[str] = mapped_column(String(16), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DriverProfile(Base):
    __tablename__ = "driver_profiles"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    license_no: Mapped[str] = mapped_column(String(32))
    # Мөнгө татах данс: эзэмшигчийн нэр бүртгэлтэй нэртэй таарах ёстой (админ шалгана)
    bank_name: Mapped[str | None] = mapped_column(String(60))
    bank_account_no: Mapped[str | None] = mapped_column(String(34))
    bank_account_holder: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[ReviewStatus] = mapped_column(_enum(ReviewStatus), default=ReviewStatus.none)
    reject_reason: Mapped[str | None] = mapped_column(String(300))
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="driver", foreign_keys=[user_id])


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    plate: Mapped[str] = mapped_column(String(8), unique=True)
    make: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(40))
    color: Mapped[str] = mapped_column(String(30))
    seats: Mapped[int] = mapped_column(Integer)  # зорчигчид өгөх суудлын тоо
    status: Mapped[ReviewStatus] = mapped_column(_enum(ReviewStatus), default=ReviewStatus.none)
    reject_reason: Mapped[str | None] = mapped_column(String(300))
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    documents: Mapped[list["Document"]] = relationship(back_populates="vehicle")

    __table_args__ = (CheckConstraint("seats between 1 and 8", name="vehicle_seats_range"),)


class Document(Base):
    """Шифрлэгдэж хадгалагдсан зураг. Өгөгдлийн санд зөвхөн зам, хэш хадгална."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    vehicle_id: Mapped[str | None] = mapped_column(ForeignKey("vehicles.id"), index=True)
    kind: Mapped[DocumentKind] = mapped_column(_enum(DocumentKind))
    path: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(40))
    sha256: Mapped[str] = mapped_column(String(64))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="documents")
    vehicle: Mapped[Vehicle | None] = relationship(back_populates="documents")


class AuditLog(Base):
    """Админы үйлдэл, хувийн баримт үзсэн бүртгэл."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(60))
    target: Mapped[str] = mapped_column(String(120))
    detail: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------- Мөнгө


class AccountKind(str, enum.Enum):
    user_wallet = "user_wallet"
    platform_revenue = "platform_revenue"  # шимтгэлийн орлого
    clearing = "clearing"  # банк/төлбөрийн системтэй тулгах данс (цэнэглэлт, таталт)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[AccountKind] = mapped_column(_enum(AccountKind))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), unique=True)
    balance: Mapped[int] = mapped_column(BigInteger, default=0)
    held: Mapped[int] = mapped_column(BigInteger, default=0)  # түгжигдсэн дүн (balance-ийн дотор)

    __table_args__ = (
        CheckConstraint("held >= 0", name="account_held_nonneg"),
        # Хэрэглэгчийн хэтэвч хасах руу орохгүй, түгжсэн дүн үлдэгдлээс хэтрэхгүй
        CheckConstraint("kind != 'user_wallet' or balance >= held", name="wallet_covers_holds"),
    )


class TxKind(str, enum.Enum):
    topup = "topup"
    trip_settlement = "trip_settlement"
    payout = "payout"
    payout_reversal = "payout_reversal"


class LedgerTx(Base):
    """Нэг гүйлгээ. Мөрүүдийн нийлбэр үргэлж 0. Хэзээ ч засахгүй, устгахгүй."""

    __tablename__ = "ledger_txs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[TxKind] = mapped_column(_enum(TxKind))
    # Нэг үйлдэл хоёр удаа ирсэн ч (төлбөрийн мэдэгдэл, офлайнаас дахин илгээсэн) нэг л бичигдэнэ
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    reference: Mapped[str | None] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    entries: Mapped[list["LedgerEntry"]] = relationship(back_populates="tx")


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tx_id: Mapped[str] = mapped_column(ForeignKey("ledger_txs.id"), index=True)
    account_id: Mapped[str] = mapped_column(String(64), ForeignKey("accounts.id"), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)  # + орлого, - зарлага

    tx: Mapped[LedgerTx] = relationship(back_populates="entries")


class HoldKind(str, enum.Enum):
    trip = "trip"
    offline_reserve = "offline_reserve"  # 2-р шат: интернетгүй үед зарцуулах нөөц


class HoldStatus(str, enum.Enum):
    active = "active"
    settled = "settled"
    released = "released"


class Hold(Base):
    """Хэтэвчинд түгжсэн дүн. Аялал дуусахад хэсэгчлэн эсвэл бүтнээр суутгаж, үлдсэнийг чөлөөлнө."""

    __tablename__ = "holds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(String(64), ForeignKey("accounts.id"), index=True)
    kind: Mapped[HoldKind] = mapped_column(_enum(HoldKind))
    amount: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[HoldStatus] = mapped_column(_enum(HoldStatus), default=HoldStatus.active)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    reference: Mapped[str | None] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("amount > 0", name="hold_amount_positive"),)


class PayoutStatus(str, enum.Enum):
    pending = "pending"  # хэтэвчнээс хасагдсан, банк руу шилжүүлэхийг хүлээж байна
    paid = "paid"
    failed = "failed"  # банк буцаасан, мөнгийг хэтэвчинд буцаасан


class Payout(Base):
    __tablename__ = "payouts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[PayoutStatus] = mapped_column(_enum(PayoutStatus), default=PayoutStatus.pending)
    bank_account_no: Mapped[str] = mapped_column(String(34))
    bank_account_holder: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("amount > 0", name="payout_amount_positive"),)


# ---------------------------------------------------------------- Аялал


class RouteStatus(str, enum.Enum):
    active = "active"
    ended = "ended"


class DriverRoute(Base):
    """Жолооч «Замдаа хүн авна» горимыг асаасан нэг удаагийн замнал."""

    __tablename__ = "driver_routes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    driver_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    vehicle_id: Mapped[str] = mapped_column(ForeignKey("vehicles.id"))
    # Google Directions-оос апп авсан маршрутын цэгүүд [[lat, lng], ...]
    polyline: Mapped[list] = mapped_column(JSON)
    length_m: Mapped[int] = mapped_column(Integer)
    # Жолоочийн үнэ: үндсэн тарифыг хэдэн дахин үржүүлэх (1.0 = үндсэн). Хатуу хязгааргүй.
    price_factor: Mapped[float] = mapped_column(Float, default=1.0)
    seats_free: Mapped[int] = mapped_column(Integer)
    progress_m: Mapped[float] = mapped_column(Float, default=0.0)  # жолооч маршрутын хаана явж байна
    last_lat: Mapped[float | None] = mapped_column(Float)
    last_lng: Mapped[float | None] = mapped_column(Float)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[RouteStatus] = mapped_column(_enum(RouteStatus), default=RouteStatus.active, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("seats_free >= 0", name="route_seats_nonneg"),)


class TrackPoint(Base):
    """Аюулгүй байдлын ул мөр: жолоочийн GPS цэг бүр хадгалагдана."""

    __tablename__ = "track_points"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    route_id: Mapped[str] = mapped_column(ForeignKey("driver_routes.id"), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RequestStatus(str, enum.Enum):
    open = "open"
    matched = "matched"
    cancelled = "cancelled"
    expired = "expired"


class RideRequest(Base):
    """Зорчигчийн «авна» захиалга. Үүсэх үед мөнгө түгжигдэнэ."""

    __tablename__ = "ride_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    passenger_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    pickup_lat: Mapped[float] = mapped_column(Float)
    pickup_lng: Mapped[float] = mapped_column(Float)
    dropoff_lat: Mapped[float] = mapped_column(Float)
    dropoff_lng: Mapped[float] = mapped_column(Float)
    direct_m: Mapped[int] = mapped_column(Integer)  # шулуун зай (лавлах)
    seats: Mapped[int] = mapped_column(Integer)  # өөрөө + дагалдагчид
    bid_seat_price: Mapped[int] = mapped_column(Integer)  # нэг суудалд төлөхөд бэлэн дээд үнэ
    hold_id: Mapped[str] = mapped_column(ForeignKey("holds.id"))
    status: Mapped[RequestStatus] = mapped_column(_enum(RequestStatus), default=RequestStatus.open, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        CheckConstraint("seats >= 1", name="request_seats_positive"),
        CheckConstraint("bid_seat_price > 0", name="request_bid_positive"),
    )


class BookingStatus(str, enum.Enum):
    matched = "matched"  # жолооч «авна» дарсан, дуу тоглож байна
    boarded = "boarded"  # зорчигч «Суулаа» дарсан
    completed = "completed"
    cancelled = "cancelled"


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    route_id: Mapped[str] = mapped_column(ForeignKey("driver_routes.id"), index=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("ride_requests.id"), index=True)
    driver_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    passenger_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    seats: Mapped[int] = mapped_column(Integer)
    agreed_seat_price: Mapped[int] = mapped_column(Integer)
    agreed_distance_m: Mapped[int] = mapped_column(Integer)
    occupancy_at_agreement: Mapped[int] = mapped_column(Integer)
    pickup_along_m: Mapped[float] = mapped_column(Float)
    dropoff_along_m: Mapped[float] = mapped_column(Float)
    # Хоёр утсанд зэрэг тоглох аялгуу ба дэлгэцийн өнгө (ойролцоо хосуудад давхцахгүй)
    tune: Mapped[int] = mapped_column(Integer)
    hold_id: Mapped[str] = mapped_column(ForeignKey("holds.id"))
    status: Mapped[BookingStatus] = mapped_column(_enum(BookingStatus), default=BookingStatus.matched, index=True)
    board_along_m: Mapped[float | None] = mapped_column(Float)
    alight_along_m: Mapped[float | None] = mapped_column(Float)
    boarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fare_total: Mapped[int | None] = mapped_column(Integer)
    commission: Mapped[int | None] = mapped_column(Integer)
    cancelled_by: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
