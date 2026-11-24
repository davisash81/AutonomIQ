"""Subscription plan definitions and limit checks."""
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy.orm import Session
from . import models

PLANS = {
    "starter": {
        "name": "Starter",
        "price_monthly": 99,
        "price_annual": 990,
        "max_users": 3,
        "max_projects": 5,
        "ai_calls_per_month": 50,
        "description": "Small shops doing occasional commissioning"
    },
    "professional": {
        "name": "Professional",
        "price_monthly": 199,
        "price_annual": 1990,
        "max_users": 25,
        "max_projects": 100,
        "ai_calls_per_month": 500,
        "description": "Most HVAC and controls companies"
    },
    "enterprise": {
        "name": "Enterprise",
        "price_monthly": 399,
        "price_annual": 3990,
        "max_users": 999,
        "max_projects": 9999,
        "ai_calls_per_month": 2000,
        "description": "Larger firms and multi-location teams"
    }
}

def get_plan(org: models.Organization) -> dict:
    return PLANS.get(org.plan or "starter", PLANS["starter"])

def _reset_ai_if_needed(org: models.Organization, db: Session):
    now = datetime.now(timezone.utc)
    if not org.ai_calls_reset_at or (now - org.ai_calls_reset_at).days >= 30:
        org.ai_calls_this_month = 0
        org.ai_calls_reset_at = now
        db.commit()

def check_can_add_user(db: Session, org: models.Organization):
    plan = get_plan(org)
    count = db.query(models.User).filter_by(organization_id=org.id).count()
    if count >= plan["max_users"]:
        raise HTTPException(402, f"User limit reached ({plan['max_users']} on {plan['name']} plan). Upgrade to add more.")

def check_can_add_project(db: Session, org: models.Organization):
    plan = get_plan(org)
    count = db.query(models.Project).filter_by(organization_id=org.id).count()
    if count >= plan["max_projects"]:
        raise HTTPException(402, f"Project limit reached ({plan['max_projects']} on {plan['name']} plan). Upgrade to add more.")

def check_can_use_ai(db: Session, org: models.Organization):
    plan = get_plan(org)
    _reset_ai_if_needed(org, db)
    if org.ai_calls_this_month >= plan["ai_calls_per_month"]:
        raise HTTPException(402, f"Monthly AI limit reached ({plan['ai_calls_per_month']} on {plan['name']} plan). Upgrade or wait for reset.")

def record_ai_call(db: Session, org: models.Organization):
    org.ai_calls_this_month = (org.ai_calls_this_month or 0) + 1
    db.commit()

def usage_summary(db: Session, org: models.Organization) -> dict:
    plan = get_plan(org)
    _reset_ai_if_needed(org, db)
    return {
        "plan": org.plan or "starter",
        "plan_name": plan["name"],
        "price_monthly": plan["price_monthly"],
        "price_annual": plan["price_annual"],
        "users": db.query(models.User).filter_by(organization_id=org.id).count(),
        "max_users": plan["max_users"],
        "projects": db.query(models.Project).filter_by(organization_id=org.id).count(),
        "max_projects": plan["max_projects"],
        "ai_calls": org.ai_calls_this_month or 0,
        "ai_calls_limit": plan["ai_calls_per_month"],
        "status": org.plan_status or "active"
    }
