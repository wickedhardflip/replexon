"""FastAPI dependency functions for database sessions and authentication."""

from typing import Generator, Optional

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as DBSession

from app.database import SessionLocal
from app.models.user import Session, User


def get_db() -> Generator[DBSession, None, None]:
    """Yield a database session, closing it when done."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    request: Request,
    session_token: Optional[str] = Cookie(None),
    db: DBSession = Depends(get_db),
) -> User:
    """Get the currently authenticated user from the session cookie."""
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )

    session = (
        db.query(Session)
        .filter(Session.id == session_token)
        .first()
    )

    if not session or session.is_expired:
        if session:
            db.delete(session)
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )

    return session.user
