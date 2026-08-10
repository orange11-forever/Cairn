from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from cairn_api.db.base import Base


class ResourceAclEntry(Base):
    __tablename__ = "resource_acl_entries"
    __table_args__ = (
        CheckConstraint("resource_type IN ('project')", name="resource_type"),
        CheckConstraint(
            "principal_type IN ('org','role','user','group')",
            name="principal_type",
        ),
        CheckConstraint(
            "permission IN ('read','write','manage')",
            name="permission",
        ),
        CheckConstraint(
            "length(principal_id) > 0",
            name="principal_id_nonempty",
        ),
        CheckConstraint(
            "(granted_by_type = 'user' AND granted_by_id IS NOT NULL) OR "
            "(granted_by_type = 'system' AND granted_by_id IS NULL)",
            name="granted_actor",
        ),
        CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_type IS NULL "
            "AND revoked_by_id IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_type = 'user' "
            "AND revoked_by_id IS NOT NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_type = 'system' "
            "AND revoked_by_id IS NULL)",
            name="revoked_actor",
        ),
        Index(
            "uq_resource_acl_entries_active_principal",
            "org_id",
            "resource_type",
            "resource_id",
            "principal_type",
            "principal_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index(
            "ix_resource_acl_entries_org_resource_active",
            "org_id",
            "resource_type",
            "resource_id",
            "granted_at",
            "id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index(
            "ix_resource_acl_entries_org_principal_active",
            "org_id",
            "principal_type",
            "principal_id",
            "resource_type",
            "resource_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index(
            "ix_resource_acl_entries_org_resource_granted",
            "org_id",
            "resource_type",
            "resource_id",
            "granted_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    org_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
    )
    resource_type: Mapped[str] = mapped_column(String(32))
    resource_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    principal_type: Mapped[str] = mapped_column(String(16))
    principal_id: Mapped[str] = mapped_column(String(64))
    permission: Mapped[str] = mapped_column(String(16))
    granted_by_type: Mapped[str] = mapped_column(String(16))
    granted_by_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    revoked_by_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    revoked_by_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
