from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone
from pathlib import Path
import csv, io, re, secrets
from .db import Base, engine, get_db
from . import models, ai, documents, commissioning, bas
from .config import get_settings, ensure_secret
from .security import hash_password, verify_password, create_token, current_user, project_for_user, require_admin
from .plans import check_can_add_project, check_can_use_ai, record_ai_call, usage_summary, PLANS

ensure_secret()
try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    print(f"[AutonomIQ] Database init warning: {e}")
    print("[AutonomIQ] Continuing — tables may already exist or path is not writable.")
app = FastAPI(
    title='AutonomIQ BAS Commissioning Platform',
    version='1.1.0',
    description='Multi-company AI-assisted HVAC/BAS commissioning platform. No control writes are exposed.'
)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in settings.cors_origins.split(',') if x.strip()],
    allow_credentials=True,
    allow_methods=['GET', 'POST', 'PUT', 'DELETE'],
    allow_headers=['Authorization', 'Content-Type']
)
WEB = Path(__file__).resolve().parent.parent / 'web'

class RegisterIn(BaseModel):
    email: str
    password: str = Field(min_length=12)
    organization_name: str = Field(min_length=2, max_length=200)
    organization_slug: Optional[str] = None
    invite_code: Optional[str] = None

class ProjectIn(BaseModel):
    name: str
    client: str = ''
    site: str = ''
    timezone: str = 'America/New_York'
    soo_revision: str = 'Rev 1'
    soo_text: str = ''

class EquipmentIn(BaseModel):
    tag: str
    kind: str
    parent_tag: str = ''
    location: str = ''
    manufacturer: str = ''
    model: str = ''
    metadata: dict = {}

class PointIn(BaseModel):
    equipment_tag: str
    name: str
    function: str = ''
    units: str = ''
    protocol: str = 'unmapped'
    address: str = ''
    object_type: str = ''
    object_instance: Optional[int] = None
    writable: bool = False
    description: str = ''

class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    project_id: int

class SOOIn(BaseModel):
    project_id: int

class TrendIn(BaseModel):
    point_id: int
    value: float
    quality: str = 'good'
    sampled_at: Optional[datetime] = None

class RuleReviewIn(BaseModel):
    status: str = Field(pattern='^(draft|approved|rejected)$')
    engineer_notes: str = ''

class TestDefinitionIn(BaseModel):
    logic: str = Field(default='all', pattern='^(all|any)$')
    conditions: list[dict] = Field(min_length=1, max_length=100)

def slugify(name: str) -> str:
    s = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return s[:100] or 'company'

@app.get('/api/health')
def health():
    return {
        'status': 'ok',
        'service': 'autonomiq-bas',
        'version': '1.1.0',
        'multi_tenant': True,
        'ai_configured': bool(settings.openai_api_key),
        'ai_model': settings.openai_model,
        'bas_adapter': settings.bas_adapter,
        'control_writes_enabled': False
    }

@app.get('/api')
def api_root():
    return {'name': 'AutonomIQ BAS', 'docs': '/docs', 'web': '/'}

@app.get('/', include_in_schema=False)
def home():
    return FileResponse(WEB / 'index.html')

@app.post('/api/auth/register')
def register(data: RegisterIn, db: Session = Depends(get_db)):
    if not settings.allow_self_registration:
        raise HTTPException(403, 'Self-registration is disabled')
    existing_orgs = db.query(models.Organization).count()
    code = None
    if settings.require_invite_code and existing_orgs > 0:
        if not data.invite_code or not data.invite_code.strip():
            raise HTTPException(403, 'An invite code is required to create a company')
        code = db.query(models.InviteCode).filter_by(code=data.invite_code.strip().upper()).first()
        if not code:
            raise HTTPException(403, 'Invalid invite code')
        if code.used_by_org_id:
            raise HTTPException(403, 'This invite code has already been used')
        if code.expires_at and code.expires_at < datetime.now(timezone.utc):
            raise HTTPException(403, 'This invite code has expired')
    if db.query(models.User).filter_by(email=data.email.lower().strip()).first():
        raise HTTPException(409, 'Email already registered')
    slug = (data.organization_slug or slugify(data.organization_name)).lower()
    if db.query(models.Organization).filter_by(slug=slug).first():
        raise HTTPException(409, 'Organization slug already in use — choose another or join an existing company')
    org = models.Organization(name=data.organization_name.strip(), slug=slug)
    db.add(org)
    db.flush()
    user = models.User(
        email=data.email.lower().strip(),
        password_hash=hash_password(data.password),
        role='admin',
        organization_id=org.id
    )
    db.add(user)
    if code:
        code.used_by_org_id = org.id
        code.used_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return {'access_token': create_token(user), 'token_type': 'bearer', 'organization': {'id': org.id, 'name': org.name, 'slug': org.slug}}

@app.post('/api/auth/login')
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter_by(email=form.username.lower().strip()).first()
    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(401, 'Invalid credentials')
    return {'access_token': create_token(user), 'token_type': 'bearer'}

@app.get('/api/auth/me')
def me(user=Depends(current_user), db: Session = Depends(get_db)):
    org = db.get(models.Organization, user.organization_id)
    return {
        'id': user.id,
        'email': user.email,
        'role': user.role,
        'organization': {'id': org.id, 'name': org.name, 'slug': org.slug} if org else None
    }

def audit(db, user, action, project_id=None, detail=None):
    db.add(models.AuditEvent(
        organization_id=user.organization_id,
        project_id=project_id,
        user_id=user.id,
        action=action,
        details=detail or {}
    ))
    db.commit()

def project_dict(p):
    return {
        'id': p.id, 'name': p.name, 'client': p.client, 'site': p.site,
        'timezone': p.timezone, 'soo_revision': p.soo_revision, 'soo_text': p.soo_text,
        'created_at': p.created_at, 'updated_at': p.updated_at
    }

@app.get('/api/projects')
def list_projects(db: Session = Depends(get_db), user=Depends(current_user)):
    rows = db.query(models.Project).filter_by(organization_id=user.organization_id).order_by(desc(models.Project.updated_at)).all()
    return [project_dict(p) for p in rows]

@app.post('/api/projects')
def create_project(data: ProjectIn, db: Session = Depends(get_db), user=Depends(current_user)):
    org = db.get(models.Organization, user.organization_id)
    check_can_add_project(db, org)
    p = models.Project(organization_id=user.organization_id, owner_id=user.id, **data.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    audit(db, user, 'project.created', p.id, {'name': p.name})
    return project_dict(p)

@app.get('/api/projects/{pid}')
def get_project(pid: int, db: Session = Depends(get_db), user=Depends(current_user)):
    p = project_for_user(db, pid, user)
    equip = [equipment_dict(x) for x in db.query(models.Equipment).filter_by(project_id=pid).all()]
    points = [point_dict(x) for x in db.query(models.Point).filter_by(project_id=pid).all()]
    rules = [rule_dict(x) for x in db.query(models.SequenceRule).filter_by(project_id=pid).all()]
    docs = [{'id': d.id, 'filename': d.filename, 'created_at': d.created_at} for d in db.query(models.ProjectDocument).filter_by(project_id=pid).all()]
    return {**project_dict(p), 'equipment': equip, 'points': points, 'rules': rules, 'documents': docs}

@app.put('/api/projects/{pid}')
def update_project(pid: int, data: ProjectIn, db: Session = Depends(get_db), user=Depends(current_user)):
    p = project_for_user(db, pid, user)
    for k, v in data.model_dump().items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    audit(db, user, 'project.updated', pid)
    return project_dict(p)

@app.delete('/api/projects/{pid}')
def delete_project(pid: int, db: Session = Depends(get_db), user=Depends(current_user)):
    p = project_for_user(db, pid, user)
    db.delete(p)
    db.commit()
    audit(db, user, 'project.deleted', pid)
    return {'deleted': True}

def equipment_dict(x):
    return {'id': x.id, 'tag': x.tag, 'kind': x.kind, 'parent_tag': x.parent_tag, 'location': x.location, 'manufacturer': x.manufacturer, 'model': x.model, 'metadata': x.metadata_json}

def point_dict(x):
    return {'id': x.id, 'equipment_tag': x.equipment_tag, 'name': x.name, 'function': x.function, 'units': x.units, 'protocol': x.protocol, 'address': x.address, 'object_type': x.object_type, 'object_instance': x.object_instance, 'writable': x.writable, 'description': x.description}

def rule_dict(x):
    return {'id': x.id, 'rule_key': x.rule_key, 'title': x.title, 'operating_condition': x.operating_condition, 'expected_behavior': x.expected_behavior, 'required_points': x.required_points, 'timing_seconds': x.timing_seconds, 'severity': x.severity, 'source_excerpt': x.source_excerpt, 'confidence': x.confidence, 'status': x.status, 'engineer_notes': x.engineer_notes, 'test_definition': x.test_definition}

@app.post('/api/projects/{pid}/equipment')
def add_equipment(pid: int, data: EquipmentIn, db: Session = Depends(get_db), user=Depends(current_user)):
    project_for_user(db, pid, user)
    x = models.Equipment(project_id=pid, **data.model_dump())
    db.add(x)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(409, 'Equipment tag already exists in this project')
    db.refresh(x)
    audit(db, user, 'equipment.created', pid, {'tag': x.tag})
    return equipment_dict(x)

@app.post('/api/projects/{pid}/points')
def add_point(pid: int, data: PointIn, db: Session = Depends(get_db), user=Depends(current_user)):
    project_for_user(db, pid, user)
    payload = data.model_dump()
    payload['writable'] = False
    x = models.Point(project_id=pid, **payload)
    db.add(x)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(409, 'Point name already exists in this project')
    db.refresh(x)
    audit(db, user, 'point.created', pid, {'point': x.name})
    return point_dict(x)

@app.post('/api/projects/{pid}/points/import-csv')
async def import_points(pid: int, file: UploadFile = File(...), db: Session = Depends(get_db), user=Depends(current_user)):
    project_for_user(db, pid, user)
    raw = await file.read(5_000_001)
    if len(raw) > 5_000_000:
        raise HTTPException(413, 'CSV exceeds 5 MB')
    rows = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    added, errors = [], []
    for i, r in enumerate(rows, 2):
        try:
            tag = (r.get('equipment_tag') or r.get('equipment') or '').strip()
            name = (r.get('name') or r.get('point') or '').strip()
            if not tag or not name:
                raise ValueError('equipment_tag and name are required')
            if not db.query(models.Equipment).filter_by(project_id=pid, tag=tag).first():
                raise ValueError(f'Unknown equipment tag {tag}')
            x = models.Point(
                project_id=pid, equipment_tag=tag, name=name,
                function=r.get('function', ''), units=r.get('units', ''),
                protocol=r.get('protocol', 'unmapped'), address=r.get('address', ''),
                object_type=r.get('object_type', ''),
                object_instance=int(r['object_instance']) if r.get('object_instance', '').isdigit() else None,
                writable=False, description=r.get('description', '')
            )
            db.add(x)
            db.flush()
            added.append(name)
        except Exception as e:
            db.rollback()
            errors.append({'row': i, 'error': str(e)})
    db.commit()
    audit(db, user, 'points.csv_imported', pid, {'added': len(added), 'errors': len(errors)})
    return {'added': added, 'errors': errors}

@app.post('/api/projects/{pid}/documents')
async def upload_document(pid: int, file: UploadFile = File(...), db: Session = Depends(get_db), user=Depends(current_user)):
    project_for_user(db, pid, user)
    raw = await file.read(settings.upload_max_mb * 1024 * 1024 + 1)
    if len(raw) > settings.upload_max_mb * 1024 * 1024:
        raise HTTPException(413, 'File exceeds configured upload limit')
    try:
        extracted = documents.extract(file.filename or 'upload.txt', raw)
    except Exception as e:
        raise HTTPException(400, str(e))
    if not extracted.strip():
        raise HTTPException(422, 'No text extracted. Scanned drawings require OCR not enabled in this build.')
    doc = models.ProjectDocument(project_id=pid, filename=file.filename or 'upload', content_type=file.content_type or '', extracted_text=extracted, uploaded_by=user.id)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    audit(db, user, 'document.uploaded', pid, {'filename': doc.filename})
    return {'id': doc.id, 'filename': doc.filename, 'chars': len(extracted)}

@app.put('/api/projects/{pid}/soo')
def update_soo(pid: int, data: SOOIn, db: Session = Depends(get_db), user=Depends(current_user)):
    p = project_for_user(db, pid, user)
    audit(db, user, 'soo.saved', pid)
    return {'saved': True}

@app.post('/api/ai/interpret-soo')
def interpret_soo(data: SOOIn, db: Session = Depends(get_db), user=Depends(current_user)):
    org = db.get(models.Organization, user.organization_id)
    check_can_use_ai(db, org)
    p = project_for_user(db, data.project_id, user)
    points = db.query(models.Point).filter_by(project_id=p.id).all()
    context = f"Project: {p.name}\nSite: {p.site}\nEquipment tags: " + ", ".join(sorted({pt.equipment_tag for pt in points}))
    context += "\nPoints:\n" + "\n".join(f"- {pt.name} ({pt.equipment_tag}) {pt.units}" for pt in points[:200])
    docs = db.query(models.ProjectDocument).filter_by(project_id=p.id).all()
    context += "\n\nExtracted documents:\n" + "\n---\n".join(d.extracted_text[:8000] for d in docs[:5])
    try:
        result = ai.interpret_sequence(p.soo_text or '', context)
    except Exception as e:
        raise HTTPException(502, f'AI interpretation failed: {e}')
    created = []
    for rule in result.get('rules', []):
        r = models.SequenceRule(
            project_id=p.id,
            rule_key=rule.get('rule_key', ''),
            title=rule.get('title', ''),
            operating_condition=rule.get('operating_condition', ''),
            expected_behavior=rule.get('expected_behavior', ''),
            required_points=rule.get('required_points', []),
            timing_seconds=rule.get('timing_seconds'),
            severity=rule.get('severity', 'info'),
            source_excerpt=rule.get('source_excerpt', ''),
            confidence=float(rule.get('confidence', 0) or 0),
            status='draft'
        )
        db.add(r)
        created.append(r)
    db.commit()
    record_ai_call(db, org)
    audit(db, user, 'ai.interpret_soo', p.id, {'rules_created': len(created)})
    return {'summary': result.get('summary'), 'assumptions': result.get('assumptions', []), 'clarifications': result.get('clarifications', []), 'rules_created': len(created)}

@app.post('/api/ai/chat')
def ai_chat(data: ChatIn, db: Session = Depends(get_db), user=Depends(current_user)):
    org = db.get(models.Organization, user.organization_id)
    check_can_use_ai(db, org)
    p = project_for_user(db, data.project_id, user)
    points = db.query(models.Point).filter_by(project_id=p.id).all()
    rules = db.query(models.SequenceRule).filter_by(project_id=p.id).all()
    context = f"Project: {p.name}\nSOO:\n{p.soo_text or '(none)'}\n\nRules: {len(rules)}\nPoints: {len(points)}"
    try:
        reply = ai.ask(data.message, context)
    except Exception as e:
        raise HTTPException(502, f'AI chat failed: {e}')
    record_ai_call(db, org)
    audit(db, user, 'ai.chat', p.id)
    return {'reply': reply}

@app.put('/api/projects/{pid}/rules/{rid}')
def review_rule(pid: int, rid: int, data: RuleReviewIn, db: Session = Depends(get_db), user=Depends(current_user)):
    project_for_user(db, pid, user)
    r = db.query(models.SequenceRule).filter_by(id=rid, project_id=pid).first()
    if not r:
        raise HTTPException(404, 'Rule not found')
    r.status = data.status
    r.engineer_notes = data.engineer_notes
    db.commit()
    audit(db, user, 'rule.reviewed', pid, {'rule_id': rid, 'status': data.status})
    return rule_dict(r)

@app.put('/api/projects/{pid}/rules/{rid}/test-definition')
def set_test_definition(pid: int, rid: int, data: TestDefinitionIn, db: Session = Depends(get_db), user=Depends(current_user)):
    project_for_user(db, pid, user)
    r = db.query(models.SequenceRule).filter_by(id=rid, project_id=pid).first()
    if not r:
        raise HTTPException(404, 'Rule not found')
    r.test_definition = data.model_dump()
    db.commit()
    audit(db, user, 'rule.test_definition', pid, {'rule_id': rid})
    return rule_dict(r)

@app.post('/api/projects/{pid}/rules/{rid}/run')
def run_test(pid: int, rid: int, db: Session = Depends(get_db), user=Depends(current_user)):
    project_for_user(db, pid, user)
    r = db.query(models.SequenceRule).filter_by(id=rid, project_id=pid).first()
    if not r:
        raise HTTPException(404, 'Rule not found')
    if not r.test_definition or not r.test_definition.get('conditions'):
        raise HTTPException(409, 'Define and review deterministic test conditions before running this rule')
    from .commissioning import evaluate_definition
    names = set()
    for c in r.test_definition['conditions']:
        names.update([c.get('point_name'), c.get('trigger_point'), c.get('response_point')])
    names.discard(None)
    pts = db.query(models.Point).filter(models.Point.project_id == pid, models.Point.name.in_(names)).all()
    by_id = {p.id: p.name for p in pts}
    samples = {n: [] for n in names}
    for t in db.query(models.TrendSample).filter(models.TrendSample.project_id == pid, models.TrendSample.point_id.in_(list(by_id))).order_by(models.TrendSample.sampled_at.asc()).limit(20000).all():
        stamp = t.sampled_at
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        samples[by_id[t.point_id]].append({'value': t.value, 'quality': t.quality, 'sampled_at': stamp})
    result = evaluate_definition(r.test_definition, samples)
    tr = models.TestRun(project_id=pid, rule_id=rid, status=result['status'], result_json=result, evidence_json={'source': 'project trend_samples', 'point_names': sorted(names), 'sample_count': sum(len(v) for v in samples.values())})
    db.add(tr)
    db.commit()
    db.refresh(tr)
    audit(db, user, 'test.executed', pid, {'test_run_id': tr.id, 'rule_id': rid, 'status': tr.status})
    return {'id': tr.id, **result}

@app.post('/api/projects/{pid}/trends')
def ingest_trend(pid: int, data: TrendIn, db: Session = Depends(get_db), user=Depends(current_user)):
    project_for_user(db, pid, user)
    pt = db.query(models.Point).filter_by(id=data.point_id, project_id=pid).first()
    if not pt:
        raise HTTPException(404, 'Point not found in project')
    t = models.TrendSample(project_id=pid, point_id=pt.id, value=data.value, quality=data.quality, sampled_at=data.sampled_at or datetime.now(timezone.utc))
    db.add(t)
    db.commit()
    return {'stored': True, 'point': pt.name, 'value': t.value, 'sampled_at': t.sampled_at}

@app.get('/api/projects/{pid}/tests')
def list_tests(pid: int, db: Session = Depends(get_db), user=Depends(current_user)):
    project_for_user(db, pid, user)
    return [{'id': t.id, 'rule_id': t.rule_id, 'status': t.status, 'result': t.result_json, 'evidence': t.evidence_json, 'executed_at': t.executed_at} for t in db.query(models.TestRun).filter_by(project_id=pid).order_by(desc(models.TestRun.executed_at)).all()]

@app.get('/api/bas/status')
async def bas_status(user=Depends(current_user)):
    try:
        return await bas.get_adapter().health()
    except Exception as e:
        raise HTTPException(503, str(e))

@app.get('/api/bas/discover')
async def bas_discover(user=Depends(current_user)):
    try:
        return await bas.get_adapter().discover()
    except Exception as e:
        raise HTTPException(503, str(e))

@app.get('/api/audit')
def audit_log(limit: int = 100, db: Session = Depends(get_db), user=Depends(current_user)):
    rows = db.query(models.AuditEvent).filter(models.AuditEvent.organization_id == user.organization_id).order_by(desc(models.AuditEvent.created_at)).limit(min(limit, 500)).all()
    return [{'id': x.id, 'project_id': x.project_id, 'action': x.action, 'detail': x.details, 'created_at': x.created_at} for x in rows]

class InviteCreateIn(BaseModel):
    company_name: str = ""
    note: str = ""
    expires_days: Optional[int] = 30

@app.post('/api/admin/invites')
def create_invite(data: InviteCreateIn, db: Session = Depends(get_db), user=Depends(require_admin)):
    code_str = secrets.token_urlsafe(8).upper().replace("-", "").replace("_", "")[:10]
    inv = models.InviteCode(
        code=code_str,
        company_name=data.company_name.strip(),
        created_by=user.id,
        note=data.note.strip(),
        expires_at=datetime.now(timezone.utc).replace(hour=23, minute=59) if data.expires_days else None
    )
    if data.expires_days:
        from datetime import timedelta
        inv.expires_at = datetime.now(timezone.utc) + timedelta(days=data.expires_days)
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return {"code": inv.code, "company_name": inv.company_name, "expires_at": inv.expires_at, "note": inv.note}

@app.get('/api/admin/invites')
def list_invites(db: Session = Depends(get_db), user=Depends(require_admin)):
    rows = db.query(models.InviteCode).order_by(desc(models.InviteCode.created_at)).limit(200).all()
    return [{
        "code": r.code,
        "company_name": r.company_name,
        "used": bool(r.used_by_org_id),
        "used_at": r.used_at,
        "expires_at": r.expires_at,
        "note": r.note,
        "created_at": r.created_at
    } for r in rows]

@app.get('/api/plans')
def list_plans():
    return [{"id": k, **v} for k, v in PLANS.items()]

@app.get('/api/org/usage')
def org_usage(db: Session = Depends(get_db), user=Depends(current_user)):
    org = db.get(models.Organization, user.organization_id)
    return usage_summary(db, org)

class PlanChangeIn(BaseModel):
    plan: str

@app.post('/api/org/plan')
def change_plan(data: PlanChangeIn, db: Session = Depends(get_db), user=Depends(require_admin)):
    if data.plan not in PLANS:
        raise HTTPException(400, 'Unknown plan')
    org = db.get(models.Organization, user.organization_id)
    org.plan = data.plan
    db.commit()
    return usage_summary(db, org)
