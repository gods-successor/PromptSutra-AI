"""PromptSutra AI: same-origin FastAPI server for frontend and JSON API."""
import hashlib
import hmac
import logging
import secrets
import smtplib
import threading
import time
from datetime import timedelta
from email.message import EmailMessage
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, func, delete
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from .config import ROOT, settings
from .database import (Base, engine, get_db, utcnow, User, AuthIdentity, LoginSession,
                       EmailOtp, Conversation, Message, Prompt, PromptVersion, uid)
from . import ai

logger = logging.getLogger(__name__)

if settings.environment == 'production':
    if len(settings.app_secret) < 32 or settings.app_secret.startswith('CHANGE_'):
        raise RuntimeError('Production requires a secure random APP_SECRET (32+ chars).')
    if not settings.secure_cookies:
        raise RuntimeError('Production requires SECURE_COOKIES=true and HTTPS.')
    if not settings.smtp_host:
        raise RuntimeError('Production email OTP requires SMTP configuration.')

app = FastAPI(title='PromptSutra AI', docs_url='/api/docs', redoc_url=None)
Base.metadata.create_all(bind=engine)  # Local starter; use migrations when evolving schema.

class CSRFProtection(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path.startswith('/api/') and request.method in ('POST', 'PATCH', 'PUT', 'DELETE'):
            expected = request.cookies.get('ps_csrf', '')
            supplied = request.headers.get('X-CSRF-Token', '')
            if not expected or not supplied or not hmac.compare_digest(expected, supplied):
                return JSONResponse(status_code=403, content={'detail': 'Security token missing. Refresh the page.'})
        return await call_next(request)

app.add_middleware(CSRFProtection)

# Lightweight per-process throttling for local use. Use Redis / gateway limiting for multi-worker deployment.
_buckets = {}
_bucket_lock = threading.Lock()

def throttle(key: str, max_hits: int, window: int):
    now = time.monotonic()
    with _bucket_lock:
        hits = [value for value in _buckets.get(key, []) if now - value < window]
        if len(hits) >= max_hits:
            raise HTTPException(status_code=429, detail='Too many requests. Please try again later.')
        hits.append(now)
        _buckets[key] = hits


def client_ip(request: Request):
    # Do NOT trust X-Forwarded-For unless app is behind a controlled reverse proxy.
    return request.client.host if request.client else 'unknown'


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


def otp_hash(challenge_id: str, code: str):
    return hmac.new(settings.app_secret.encode(), f'{challenge_id}:{code}'.encode(), hashlib.sha256).hexdigest()


def current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get('ps_session', '')
    if not token:
        raise HTTPException(status_code=401, detail='Please sign in.')
    row = db.get(LoginSession, digest(token))
    if row is None or row.expires_at < utcnow():
        raise HTTPException(status_code=401, detail='Session expired. Please sign in.')
    user = db.get(User, row.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail='Please sign in.')
    return user


def public_user(user: User):
    return {'id': user.id, 'email': user.email, 'name': user.display_name}


def set_login_cookie(response: Response, db: Session, user: User):
    token = secrets.token_urlsafe(48)
    db.add(LoginSession(id=digest(token), user_id=user.id, expires_at=utcnow()+timedelta(days=settings.session_days)))
    db.commit()
    response.set_cookie('ps_session', token, httponly=True, secure=settings.secure_cookies,
                        samesite='strict', max_age=settings.session_days*86400, path='/')


def get_or_create_user(db: Session, email: str, name: str):
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, display_name=name[:120])
        db.add(user)
        db.flush()
    return user


@app.get('/api/health')
def health():
    return {'ok': True, 'service': 'PromptSutra AI'}


@app.get('/api/config')
def public_config():
    firebase_ready = all(settings.firebase_web_config.values()) and bool(settings.firebase_service_account)
    return {
        'google_login_enabled': firebase_ready,
        'firebase': settings.firebase_web_config if firebase_ready else {},
        'email_mode': ('smtp' if settings.smtp_host else 'development-console' if settings.environment == 'development' else 'unavailable'),
        'gemini_configured': bool(settings.gemini_api_key),
        'phone_login_enabled': False,
    }


@app.get('/api/auth/csrf')
def csrf(request: Request, response: Response):
    token = request.cookies.get('ps_csrf') or secrets.token_urlsafe(32)
    response.set_cookie('ps_csrf', token, httponly=False, secure=settings.secure_cookies,
                        samesite='strict', max_age=86400, path='/')
    return {'token': token}


class EmailRequest(BaseModel):
    email: EmailStr

class OtpVerify(BaseModel):
    email: EmailStr
    otp: str = Field(pattern=r'^\d{6}$')

class GoogleVerify(BaseModel):
    id_token: str = Field(min_length=40, max_length=12000)


def send_otp(email: str, code: str):
    if not settings.smtp_host:
        if settings.environment != 'development':
            raise HTTPException(503, 'Email sending is not configured.')
        # Deliberately printed to LOCAL backend terminal, not browser or API.
        print(f'\n[LOCAL DEVELOPMENT ONLY] OTP for {email}: {code}\n', flush=True)
        return
    if not settings.email_from:
        raise HTTPException(503, 'Set EMAIL_FROM in .env.')
    message = EmailMessage()
    message['Subject'] = 'PromptSutra AI — Your verification code'
    message['From'] = settings.email_from
    message['To'] = email
    message.set_content(f'Your PromptSutra AI verification code is {code}. It expires in 5 minutes. Never share it.')
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=12) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)
    except Exception:
        logger.exception('Email delivery failed')
        raise HTTPException(502, 'Email delivery failed. Check SMTP settings.') from None


@app.post('/api/auth/email/request')
def request_otp(payload: EmailRequest, request: Request, db: Session = Depends(get_db)):
    email = str(payload.email).lower()
    throttle('otp-ip-'+client_ip(request), 10, 900)
    throttle('otp-email-'+digest(email), 4, 900)
    latest = db.scalar(select(EmailOtp).where(EmailOtp.email==email).order_by(EmailOtp.created_at.desc()))
    if latest and (utcnow()-latest.created_at).total_seconds() < 60:
        raise HTTPException(429, 'Wait 60 seconds before requesting another code.')
    challenge = EmailOtp(id=uid(), email=email, code_hash='', expires_at=utcnow()+timedelta(minutes=5))
    code = f'{secrets.randbelow(1_000_000):06d}'
    challenge.code_hash = otp_hash(challenge.id, code)
    send_otp(email, code)
    db.add(challenge)
    db.commit()
    return {'message': 'Code sent.' if settings.smtp_host else 'Local test: read the OTP in your Python server terminal.'}


@app.post('/api/auth/email/verify')
def verify_otp(payload: OtpVerify, response: Response, request: Request, db: Session = Depends(get_db)):
    email = str(payload.email).lower()
    throttle('verify-ip-'+client_ip(request), 25, 900)
    latest = db.scalar(select(EmailOtp).where(EmailOtp.email==email).order_by(EmailOtp.created_at.desc()))
    if not latest or latest.consumed or latest.expires_at < utcnow() or latest.attempts >= 5:
        raise HTTPException(400, 'Invalid or expired code. Request a new code.')
    latest.attempts += 1
    if not hmac.compare_digest(latest.code_hash, otp_hash(latest.id, payload.otp)):
        db.commit()
        raise HTTPException(400, 'Incorrect code.')
    latest.consumed = True
    user = get_or_create_user(db, email, email.split('@')[0].replace('.', ' ').title())
    db.flush()
    set_login_cookie(response, db, user)
    return {'user': public_user(user)}


@app.post('/api/auth/google')
def google_login(payload: GoogleVerify, response: Response, db: Session = Depends(get_db)):
    if not settings.firebase_service_account or not all(settings.firebase_web_config.values()):
        raise HTTPException(503, 'Google login is not configured. Use email OTP.')
    try:
        import firebase_admin
        from firebase_admin import credentials, auth
        if not firebase_admin._apps:
            firebase_admin.initialize_app(credentials.Certificate(settings.firebase_service_account))
        claims = auth.verify_id_token(payload.id_token)
        if not claims.get('email_verified') or not claims.get('email'):
            raise ValueError('Email not verified')
        if claims.get('firebase', {}).get('sign_in_provider') != 'google.com':
            raise ValueError('Expected Google sign-in')
    except Exception:
        raise HTTPException(401, 'Google token verification failed. Check Firebase configuration.') from None
    email = claims['email'].lower()
    user = get_or_create_user(db, email, claims.get('name') or email.split('@')[0])
    existing = db.scalar(select(AuthIdentity).where(AuthIdentity.provider=='firebase-google', AuthIdentity.subject==claims['uid']))
    if existing and existing.user_id != user.id:
        raise HTTPException(403, 'Google account is linked to another user.')
    if not existing:
        db.add(AuthIdentity(user_id=user.id, provider='firebase-google', subject=claims['uid']))
    db.flush()
    set_login_cookie(response, db, user)
    return {'user': public_user(user)}


@app.get('/api/auth/me')
def me(user: User = Depends(current_user)):
    return {'user': public_user(user)}


@app.post('/api/auth/logout')
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get('ps_session')
    if token:
        db.execute(delete(LoginSession).where(LoginSession.id==digest(token)))
        db.commit()
    response.delete_cookie('ps_session', path='/', samesite='strict', secure=settings.secure_cookies)
    return {'ok': True}


class ConversationCreate(BaseModel):
    category: str = Field(default='General', max_length=60)

class ConversationPatch(BaseModel):
    title: str = Field(min_length=1, max_length=150)

class ChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)

class GenerateRequest(BaseModel):
    detail: str = Field(default='Detailed', max_length=30)
    tone: str = Field(default='Professional', max_length=40)
    language: str = Field(default='English', max_length=30)
    platform: str = Field(default='Any AI', max_length=40)

class RefineRequest(BaseModel):
    instruction: str = Field(min_length=3, max_length=2000)

class PromptPatch(BaseModel):
    favorite: bool | None = None
    content: str | None = Field(default=None, min_length=5, max_length=25000)


def own_conversation(db, cid, user):
    c = db.get(Conversation, cid)
    if not c or c.user_id != user.id:
        raise HTTPException(404, 'Conversation not found.')
    return c


def own_prompt(db, pid, user):
    p = db.get(Prompt, pid)
    if not p or p.user_id != user.id:
        raise HTTPException(404, 'Prompt not found.')
    return p


def message_dict(m):
    return {'id': m.id, 'role': m.role, 'content': m.content, 'created_at': m.created_at.isoformat()+'Z'}


def convo_dict(c):
    return {'id': c.id, 'title': c.title, 'category': c.category, 'ready': c.ready, 'updated_at': c.updated_at.isoformat()+'Z'}


def prompt_dict(p):
    return {'id': p.id, 'title': p.title, 'content': p.content, 'category': p.category,
            'favorite': p.favorite, 'conversation_id': p.conversation_id,
            'created_at': p.created_at.isoformat()+'Z', 'version': max([v.number for v in p.versions], default=1)}


@app.post('/api/conversations')
def new_conversation(payload: ConversationCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = Conversation(user_id=user.id, category=payload.category)
    db.add(c); db.commit()
    return {'conversation': convo_dict(c)}


@app.get('/api/conversations')
def list_conversations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = db.scalars(select(Conversation).where(Conversation.user_id==user.id).order_by(Conversation.updated_at.desc()).limit(100)).all()
    return {'conversations': [convo_dict(c) for c in items]}


@app.get('/api/conversations/{cid}')
def get_conversation(cid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = own_conversation(db, cid, user)
    return {'conversation': convo_dict(c), 'messages': [message_dict(m) for m in c.messages]}


@app.patch('/api/conversations/{cid}')
def edit_conversation(cid: str, payload: ConversationPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = own_conversation(db, cid, user)
    c.title = payload.title.strip(); c.updated_at = utcnow(); db.commit()
    return {'conversation': convo_dict(c)}


@app.delete('/api/conversations/{cid}')
def delete_conversation(cid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = own_conversation(db, cid, user)
    # Remove associated prompts to keep SQLite and PostgreSQL consistent.
    for p in db.scalars(select(Prompt).where(Prompt.conversation_id==cid)).all():
        db.delete(p)
    db.flush(); db.delete(c); db.commit()
    return {'ok': True}


@app.post('/api/conversations/{cid}/messages')
def send_message(cid: str, payload: ChatRequest, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    throttle('chat-user-'+user.id, 16, 60)
    c = own_conversation(db, cid, user)
    if len(c.messages) >= 80:
        raise HTTPException(400, 'This chat is full. Start a new conversation.')
    text = payload.content.strip()
    if not text:
        raise HTTPException(422, 'Message cannot be empty.')
    m = Message(conversation_id=c.id, role='user', content=text)
    db.add(m)
    if c.title == 'New conversation':
        c.title = (text[:55] + ('…' if len(text)>55 else ''))
    c.updated_at = utcnow()
    db.commit()
    db.refresh(c)
    reply = ai.interview(c.messages, c.category)
    response_message = Message(conversation_id=c.id, role='assistant', content=reply.assistant_message)
    db.add(response_message); c.ready = reply.ready_to_generate; c.updated_at = utcnow(); db.commit()
    return {'message': message_dict(response_message), 'ready': c.ready, 'conversation': convo_dict(c)}


@app.post('/api/conversations/{cid}/generate')
def generate(cid: str, payload: GenerateRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = own_conversation(db, cid, user)
    if not any(m.role=='user' for m in c.messages):
        raise HTTPException(400, 'Explain your goal in the chat first.')
    throttle('gen-user-'+user.id, 8, 600)
    content = ai.generate_prompt(c.messages, c.category, payload.detail, payload.tone, payload.language, payload.platform)
    title = c.title if c.title!='New conversation' else 'Generated Prompt'
    p = Prompt(user_id=user.id, conversation_id=c.id, title=title, category=c.category, content=content)
    db.add(p); db.flush()
    db.add(PromptVersion(prompt_id=p.id, number=1, content=content))
    db.commit(); db.refresh(p)
    return {'prompt': prompt_dict(p)}


@app.get('/api/prompts')
def list_prompts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    prompts = db.scalars(select(Prompt).where(Prompt.user_id==user.id).order_by(Prompt.created_at.desc()).limit(100)).all()
    return {'prompts': [prompt_dict(p) for p in prompts]}


@app.get('/api/prompts/{pid}')
def get_prompt(pid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {'prompt': prompt_dict(own_prompt(db, pid, user))}


@app.patch('/api/prompts/{pid}')
def edit_prompt(pid: str, payload: PromptPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = own_prompt(db, pid, user)
    if payload.favorite is not None: p.favorite = payload.favorite
    if payload.content is not None and payload.content.strip() != p.content:
        p.content = payload.content.strip()
        db.add(PromptVersion(prompt_id=p.id, number=max([v.number for v in p.versions], default=0)+1, content=p.content))
    db.commit(); db.refresh(p)
    return {'prompt': prompt_dict(p)}


@app.post('/api/prompts/{pid}/refine')
def refine(pid: str, payload: RefineRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    throttle('gen-user-'+user.id, 8, 600)
    p = own_prompt(db, pid, user)
    new_content = ai.refine_prompt(p.content, payload.instruction)
    p.content = new_content
    db.add(PromptVersion(prompt_id=p.id, number=max([v.number for v in p.versions], default=0)+1, content=new_content))
    db.commit(); db.refresh(p)
    return {'prompt': prompt_dict(p)}


@app.get('/api/prompts/{pid}/versions')
def versions(pid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = own_prompt(db, pid, user)
    return {'versions': [{'number': v.number, 'content': v.content, 'created_at': v.created_at.isoformat()+'Z'} for v in p.versions]}


@app.delete('/api/prompts/{pid}')
def delete_prompt(pid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = own_prompt(db, pid, user)
    db.delete(p); db.commit()
    return {'ok': True}


# Mount static site only after /api routes.
app.mount('/', StaticFiles(directory=str(ROOT/'frontend'), html=True), name='frontend')
