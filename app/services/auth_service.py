"""Authentication & Authorization Service — DB-level permissions

Permission model
────────────────
  db_onboard    – global (connection_id=NULL): can register new databases
                  per-DB: admin of that database (manage users, reindex, query)
  db_reindex    – per-DB: can reindex and query that database
  prompt_query  – per-DB: can only query that database

Hierarchy (per-DB):  db_onboard  ⊃  db_reindex  ⊃  prompt_query

A user may hold different permissions on different databases.
When someone registers a new DB they automatically become its admin.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.models import User, UserPermission
from app.config import Settings

# ── Config ────────────────────────────────────────────
_settings = Settings()
SECRET_KEY = _settings.JWT_SECRET
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 5

VALID_PERMISSIONS = {"db_onboard", "db_reindex", "prompt_query"}

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Password helpers ──────────────────────────────────
def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── Permission helpers ────────────────────────────────
def get_user_perms_dict(db: Session, user_id: int) -> Dict[str, List[str]]:
    """Return permission map.

    Keys: ``"*"`` for global, ``"<connection_id>"`` for per-DB.
    Values: list of permission strings.

    Example::

        {"*": ["db_onboard"], "3": ["db_onboard", "db_reindex", "prompt_query"]}
    """
    rows = db.query(UserPermission).filter(UserPermission.user_id == user_id).all()
    perms: Dict[str, List[str]] = {}
    for r in rows:
        key = "*" if r.connection_id is None else str(r.connection_id)
        perms.setdefault(key, [])
        if r.permission not in perms[key]:
            perms[key].append(r.permission)
    return perms


# ── JWT helpers ───────────────────────────────────────
def create_access_token(user_id: int, username: str, perms: Dict[str, List[str]]) -> str:
    expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": str(user_id),
        "username": username,
        "perms": perms,
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


def create_user(db: Session, username: str, password: str) -> User:
    """Create a user with **no** permissions (clean slate)."""
    if not username or not password:
        raise ValueError("Username and password are required")
    if get_user_by_username(db, username):
        raise ValueError(f"Username '{username}' already exists")

    user = User(username=username, password_hash=hash_password(password), is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def set_db_permissions(
    db: Session,
    user_id: int,
    connection_id: Optional[int],
    permissions: List[str],
):
    """Replace **all** permissions for *user_id* on *connection_id*.

    ``connection_id=None`` targets the global scope.
    """
    bad = set(permissions) - VALID_PERMISSIONS
    if bad:
        raise ValueError(f"Invalid permissions: {bad}")

    if connection_id is None:
        db.query(UserPermission).filter(
            UserPermission.user_id == user_id,
            UserPermission.connection_id.is_(None),
        ).delete(synchronize_session="fetch")
    else:
        db.query(UserPermission).filter(
            UserPermission.user_id == user_id,
            UserPermission.connection_id == connection_id,
        ).delete(synchronize_session="fetch")

    for perm in set(permissions):
        db.add(UserPermission(user_id=user_id, permission=perm, connection_id=connection_id))
    db.commit()


def grant_all_on_connection(db: Session, user_id: int, connection_id: int):
    """Give *user_id* all three permissions on *connection_id*."""
    set_db_permissions(db, user_id, connection_id, list(VALID_PERMISSIONS))


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    """Return ``User`` if credentials valid, else ``None``."""
    user = get_user_by_username(db, username)
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
