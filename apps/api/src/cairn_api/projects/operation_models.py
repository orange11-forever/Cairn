from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, LargeBinary, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cairn_api.db.base import Base


class ProjectOperation(Base):
    __tablename__ = "project_operations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "project_id"], ["projects.org_id", "projects.id"], ondelete="CASCADE"
        ),
        Index(
            "ix_project_operations_scope_created",
            "org_id",
            "project_id",
            "owner_id",
            "created_at",
            "id",
        ),
    )

    org_id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    request_digest: Mapped[bytes] = mapped_column(LargeBinary(32))
    details: Mapped[dict[str, object]] = mapped_column(JSONB)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
