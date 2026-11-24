from sqlalchemy import String, Integer, Float, Boolean, DateTime, Text, ForeignKey, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone
from .db import Base

def now(): return datetime.now(timezone.utc)

class Organization(Base):
    __tablename__ = 'organizations'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    plan: Mapped[str] = mapped_column(String(30), default='starter')
    plan_status: Mapped[str] = mapped_column(String(20), default='active')
    ai_calls_this_month: Mapped[int] = mapped_column(Integer, default=0)
    ai_calls_reset_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    users = relationship('User', back_populates='organization')
    projects = relationship('Project', back_populates='organization')

class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(30), default='commissioner')
    organization_id: Mapped[int] = mapped_column(ForeignKey('organizations.id'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    organization = relationship('Organization', back_populates='users')

class Project(Base):
    __tablename__ = 'projects'
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('organizations.id'), index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(String(200))
    client: Mapped[str] = mapped_column(String(200), default='')
    site: Mapped[str] = mapped_column(String(300), default='')
    timezone: Mapped[str] = mapped_column(String(80), default='America/New_York')
    soo_revision: Mapped[str] = mapped_column(String(80), default='Rev 1')
    soo_text: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    organization = relationship('Organization', back_populates='projects')
    equipment = relationship('Equipment', cascade='all, delete-orphan')
    documents = relationship('ProjectDocument', cascade='all, delete-orphan')

class Equipment(Base):
    __tablename__ = 'equipment'
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), index=True)
    tag: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(80))
    parent_tag: Mapped[str] = mapped_column(String(120), default='')
    location: Mapped[str] = mapped_column(String(200), default='')
    manufacturer: Mapped[str] = mapped_column(String(120), default='')
    model: Mapped[str] = mapped_column(String(120), default='')
    metadata_json: Mapped[dict] = mapped_column('metadata', JSON, default=dict)
    __table_args__ = (Index('ix_equipment_project_tag', 'project_id', 'tag', unique=True),)

class Point(Base):
    __tablename__ = 'points'
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), index=True)
    equipment_tag: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(200))
    function: Mapped[str] = mapped_column(String(120), default='')
    units: Mapped[str] = mapped_column(String(40), default='')
    protocol: Mapped[str] = mapped_column(String(40), default='unmapped')
    address: Mapped[str] = mapped_column(String(200), default='')
    object_type: Mapped[str] = mapped_column(String(60), default='')
    object_instance: Mapped[int] = mapped_column(Integer, nullable=True)
    writable: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(Text, default='')
    __table_args__ = (Index('ix_points_project_name', 'project_id', 'name', unique=True),)

class ProjectDocument(Base):
    __tablename__ = 'documents'
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120), default='')
    extracted_text: Mapped[str] = mapped_column(Text, default='')
    uploaded_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class SequenceRule(Base):
    __tablename__ = 'sequence_rules'
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), index=True)
    rule_key: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(300))
    operating_condition: Mapped[str] = mapped_column(Text, default='')
    expected_behavior: Mapped[str] = mapped_column(Text, default='')
    required_points: Mapped[list] = mapped_column(JSON, default=list)
    timing_seconds: Mapped[float] = mapped_column(Float, nullable=True)
    severity: Mapped[str] = mapped_column(String(20), default='info')
    source_excerpt: Mapped[str] = mapped_column(Text, default='')
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default='draft')
    engineer_notes: Mapped[str] = mapped_column(Text, default='')
    test_definition: Mapped[dict] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class TestRun(Base):
    __tablename__ = 'test_runs'
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), index=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey('sequence_rules.id'), index=True)
    status: Mapped[str] = mapped_column(String(20))
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_json: Mapped[dict] = mapped_column(JSON, default=dict)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class TrendSample(Base):
    __tablename__ = 'trend_samples'
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), index=True)
    point_id: Mapped[int] = mapped_column(ForeignKey('points.id'), index=True)
    value: Mapped[float] = mapped_column(Float)
    quality: Mapped[str] = mapped_column(String(20), default='good')
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

class AuditEvent(Base):
    __tablename__ = 'audit_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('organizations.id'), index=True, nullable=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), index=True, nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

class InviteCode(Base):
    __tablename__ = 'invite_codes'
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    company_name: Mapped[str] = mapped_column(String(200), default='')
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=True)
    used_by_org_id: Mapped[int] = mapped_column(ForeignKey('organizations.id'), nullable=True)
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    note: Mapped[str] = mapped_column(String(300), default='')
