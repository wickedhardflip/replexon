"""Authentication service: password hashing and session management."""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy.orm import Session as DBSession

from app.models.user import Session, User

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a password using Argon2id."""
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash."""
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def create_session(db: DBSession, user: User, days: int = 30) -> Session:
    """Create a new session for the given user."""
    session = Session(
        id=secrets.token_hex(32),
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=days),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def delete_session(db: DBSession, session_token: str) -> None:
    """Delete a session by its token."""
    session = db.query(Session).filter(Session.id == session_token).first()
    if session:
        db.delete(session)
        db.commit()


def cleanup_expired_sessions(db: DBSession) -> int:
    """Remove all expired sessions. Returns count deleted."""
    now = datetime.now(timezone.utc)
    count = db.query(Session).filter(Session.expires_at < now).delete()
    db.commit()
    return count


def authenticate_user(db: DBSession, username: str, password: str) -> Optional[User]:
    """Authenticate a user by username and password. Returns User or None."""
    user = db.query(User).filter(User.username == username).first()
    if not user:
        _ph.hash("dummy-password")
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
