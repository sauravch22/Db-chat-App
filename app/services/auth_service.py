"""Authentication & Authorization Service

Permissions:
  db_onboard    – register new databases
  db_reindex    – trigger reindex on existing databases
  prompt_query  – use the chat / prompt endpoint and view charts

A user may hold any combination of these permissions.
"""

from datetime import datetime, timedelta
from typing import List, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.models import User, UserPermission

# ── Config ────────────────────────────────────────────
SECRET_KEY = "dbchat-jwt-secret-change-in-production-2026"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 5

VALID_PERMISSIONS = {"db_onboard", "db_reindex", "prompt_query"}

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Password helpers ──────────────────────────────────
def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── JWT helpers ───────────────────────────────────────
def create_access_token(user_id: int, username: str, permissions: List[str]) -> str:
    expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": str(user_id),
        "username": username,
        "permissions": permissions,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """Return decoded payload or None on any failure."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


# ── User CRUD helpers ─────────────────────────────────
def get_user_by_username(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == username).first()


def get_user_permissions(db: Session, user_id: int) -> List[str]:
    perms = db.query(UserPermission).filter(UserPermission.user_id == user_id).all()
    return [p.permission for p in perms]


def create_user(db: Session, username: str, password: str, permissions: List[str]) -> User:
    """Create a user with the given permissions. Raises ValueError on bad input."""
    if not username or not password:
        raise ValueError("Username and password are required")
    if get_user_by_username(db, username):
        raise ValueError(f"Username '{username}' already exists")

    bad = set(permissions) - VALID_PERMISSIONS
    if bad:
        raise ValueError(f"Invalid permissions: {bad}")

    user = User(
        username=username,
        password_hash=hash_password(password),
        is_active=True,
    )
    db.add(user)
    db.flush()  # get user.id

    for perm in set(permissions):
        db.add(UserPermission(user_id=user.id, permission=perm))

    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    """Return User if credentials valid, else None."""
    user = get_user_by_username(db, username)
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
