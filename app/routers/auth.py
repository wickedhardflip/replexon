"""Authentication routes: login and logout."""

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session as DBSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.services.auth_service import authenticate_user, create_session, delete_session
from app.utils.security import generate_csrf_token, validate_csrf_token

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Display the login form."""
    return templates.TemplateResponse(
        "pages/login.html",
        {"request": request, "csrf_token": generate_csrf_token()},
    )


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    db: DBSession = Depends(get_db),
):
    """Process login form submission."""
    if not validate_csrf_token(csrf_token):
        return templates.TemplateResponse(
            "pages/login.html",
            {
                "request": request,
                "error": "Invalid form submission. Please try again.",
                "csrf_token": generate_csrf_token(),
            },
            status_code=400,
        )

    user = authenticate_user(db, username, password)
    if not user:
        return templates.TemplateResponse(
            "pages/login.html",
            {
                "request": request,
                "error": "Invalid username or password.",
                "csrf_token": generate_csrf_token(),
                "username": username,
            },
            status_code=401,
        )

    session = create_session(db, user)
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(
        key="session_token",
        value=session.id,
        httponly=True,
        samesite="lax",
        max_age=30 * 24 * 3600,
    )
    return response


@router.get("/logout")
async def logout(
    request: Request,
    response: Response,
    db: DBSession = Depends(get_db),
):
    """Log out the current user."""
    session_token = request.cookies.get("session_token")
    if session_token:
        delete_session(db, session_token)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session_token")
    return response
