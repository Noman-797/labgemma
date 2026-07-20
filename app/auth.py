from typing import Annotated

import bcrypt
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def get_current_user(request: Request, db: Annotated[Session, Depends(get_db)]) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.get(User, user_id)
