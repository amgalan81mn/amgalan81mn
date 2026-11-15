"""Тушаалын мөрийн хэрэгсэл.  python -m app.cli make-admin 99112233"""

import sys

from sqlalchemy import select

from .db import SessionLocal
from .models import User
from .security import normalize_phone


def make_admin(phone: str) -> None:
    with SessionLocal() as db:
        user = db.scalars(select(User).where(User.phone == normalize_phone(phone))).first()
        if user is None:
            sys.exit("Ийм дугаартай хэрэглэгч алга. Эхлээд апп-аар нэвтэрч бүртгүүлнэ үү.")
        user.is_admin = True
        db.commit()
        print(f"{user.phone} админ боллоо")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "make-admin":
        make_admin(sys.argv[2])
    else:
        sys.exit("Хэрэглээ: python -m app.cli make-admin <утасны дугаар>")
