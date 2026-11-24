import hashlib, hmac, base64, json, secrets, time
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from .config import get_settings
from .db import get_db
from . import models

oauth = OAuth2PasswordBearer(tokenUrl='/api/auth/login')

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + '=' * ((4 - len(value) % 4) % 4))

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return 'scrypt$16384$8$1$' + _b64(salt) + '$' + _b64(digest)

def verify_password(password: str, stored: str) -> bool:
    try:
        alg, n, r, p, salt, digest = stored.split('$')
        if alg != 'scrypt':
            return False
        actual = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=len(_unb64(digest)))
        return hmac.compare_digest(actual, _unb64(digest))
    except Exception:
        return False

def create_token(user):
    from .config import ensure_secret
    ensure_secret()
    secret = get_settings().app_secret_key
    if secret in ('unsafe-development-key-change-me', '') or secret.startswith('REPLACE'):
        raise RuntimeError('APP_SECRET_KEY is not configured. Restart the app so it can generate one.')
    header = _b64(json.dumps({'alg': 'HS256', 'typ': 'JWT'}, separators=(',', ':')).encode())
    payload = _b64(json.dumps({
        'sub': str(user.id),
        'role': user.role,
        'org': user.organization_id,
        'exp': int(time.time()) + 43200
    }, separators=(',', ':')).encode())
    body = header + '.' + payload
    signature = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return body + '.' + signature

def current_user(token: str = Depends(oauth), db: Session = Depends(get_db)):
    try:
        header, payload, signature = token.split('.')
        body = header + '.' + payload
        expected = _b64(hmac.new(get_settings().app_secret_key.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError('bad signature')
        claims = json.loads(_unb64(payload))
        if int(claims['exp']) < int(time.time()):
            raise ValueError('expired')
        uid = int(claims['sub'])
    except Exception:
        raise HTTPException(401, 'Invalid or expired token', headers={'WWW-Authenticate': 'Bearer'})
    user = db.get(models.User, uid)
    if not user:
        raise HTTPException(401, 'User no longer exists')
    return user

def project_for_user(db: Session, project_id: int, user: models.User):
    p = db.query(models.Project).filter_by(id=project_id).first()
    if not p or p.organization_id != user.organization_id:
        raise HTTPException(404, 'Project not found')
    return p

def require_admin(user: models.User = Depends(current_user)):
    if user.role != 'admin':
        raise HTTPException(403, 'Administrator role required')
    return user
