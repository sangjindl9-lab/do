from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Announcement, Device, Faq, LegalDoc, Product
from ..services import settings_store
from ..seed import NOTICE

router = APIRouter(prefix="/api/public", tags=["public"])


def product_view(p: Product) -> dict:
    return {c.name: getattr(p, c.name) for c in Product.__table__.columns}


@router.get("/site")
def site(db: Session = Depends(get_db)):
    pay = settings_store.payment_state(db)
    return {"name": settings_store.get(db, "site.name"), "name_en": "Google Auto Tester", "notice": NOTICE,
            "support_email": settings_store.get(db, "site.support_email"),
            "locales": settings_store.get(db, "site.locales").split(","),
            "payment": {"enabled": pay["enabled"], "mode": pay["mode"], "provider": pay["provider"]},
            "google_login": bool(settings_store.get(db, "google.client_id") and settings_store.get(db, "google.client_secret"))}


@router.get("/products")
def products(db: Session = Depends(get_db)):
    rows = db.scalars(select(Product).where(Product.is_active.is_(True)).order_by(Product.sort, Product.id))
    return [product_view(p) for p in rows]


@router.get("/devices")
def supported_devices(db: Session = Depends(get_db)):
    """지원 기기 안내: 실제 등록된 실기기(모의 장비 제외)만 집계한다."""
    rows = db.execute(select(Device.manufacturer, Device.model, Device.android_version, Device.resolution, func.count())
                      .where(Device.is_mock.is_(False), Device.enabled.is_(True))
                      .group_by(Device.manufacturer, Device.model, Device.android_version, Device.resolution)
                      .order_by(func.count().desc())).all()
    return {"total": sum(r[4] for r in rows),
            "models": [{"manufacturer": m, "model": md, "android_version": a, "resolution": r, "count": n} for m, md, a, r, n in rows]}


@router.get("/announcements")
def announcements(db: Session = Depends(get_db)):
    rows = db.scalars(select(Announcement).where(Announcement.is_published.is_(True))
                      .order_by(Announcement.pinned.desc(), Announcement.id.desc()).limit(100))
    return [{"id": a.id, "title": a.title, "body": a.body, "pinned": a.pinned, "created_at": a.created_at} for a in rows]


@router.get("/faqs")
def faqs(locale: str = "ko", db: Session = Depends(get_db)):
    rows = db.scalars(select(Faq).where(Faq.is_published.is_(True), Faq.locale == locale).order_by(Faq.sort, Faq.id)).all()
    if not rows and locale != "ko":
        rows = db.scalars(select(Faq).where(Faq.is_published.is_(True), Faq.locale == "ko").order_by(Faq.sort, Faq.id)).all()
    return [{"id": f.id, "question": f.question, "answer": f.answer} for f in rows]


@router.get("/legal/{key}")
def legal(key: str, locale: str = "ko", db: Session = Depends(get_db)):
    doc = db.scalar(select(LegalDoc).where(LegalDoc.key == key, LegalDoc.locale == locale)) or \
        db.scalar(select(LegalDoc).where(LegalDoc.key == key, LegalDoc.locale == "ko"))
    if not doc:
        raise HTTPException(404, "문서를 찾을 수 없습니다.")
    return {"key": doc.key, "title": doc.title, "body": doc.body, "updated_at": doc.updated_at}
