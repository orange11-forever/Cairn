from dataclasses import dataclass
from enum import StrEnum


class MembershipRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class ProjectPermission(StrEnum):
    READ = "read"
    WRITE = "write"
    MANAGE = "manage"


class PrincipalType(StrEnum):
    ORG = "org"
    ROLE = "role"
    USER = "user"
    GROUP = "group"


class ActorType(StrEnum):
    USER = "user"
    SYSTEM = "system"


class ResourceType(StrEnum):
    PROJECT = "project"


@dataclass(frozen=True)
class PrincipalRef:
    principal_type: PrincipalType
    principal_id: str
