from sqlalchemy.orm import Session

from ..models import AuditLog, SystemLog


def audit(db: Session, actor_id: int | None, action: str, target_type: str = "", target_id="", detail=None, ip: str = ""):
    db.add(AuditLog(actor_id=actor_id, action=action, target_type=target_type, target_id=str(target_id),
                    detail=detail, ip=ip))


def syslog(db: Session, level: str, source: str, message: str):
    db.add(SystemLog(level=level, source=source, message=message[:4000]))
