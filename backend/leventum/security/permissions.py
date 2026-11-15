"""Rollen → Rechte. Im Code statt in der DB: versioniert und testbar."""
ALL = "*"

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {ALL},  # inkl. system:backup, document:purge (nur Administrator)
    "verwaltung": {"dashboard:read", "master:read", "master:write", "task:read", "task:write", "repair:read", "repair:write", "document:read", "document:write"},
    "buchhaltung": {"dashboard:read", "master:read", "finance:read", "finance:write", "document:read", "document:write"},
    "objektbetreuung": {"dashboard:read", "master:read", "task:read", "task:write", "repair:read", "repair:write", "document:read", "document:write"},
    "lesend": {"dashboard:read", "master:read", "finance:read", "task:read", "repair:read", "document:read"},
}

ROLES = {
    "admin": "Administrator",
    "verwaltung": "Verwaltung",
    "buchhaltung": "Buchhaltung",
    "objektbetreuung": "Objektbetreuung",
    "lesend": "Lesender Zugriff",
}


def has_permission(role_code: str, permission: str) -> bool:
    perms = ROLE_PERMISSIONS.get(role_code, set())
    return ALL in perms or permission in perms
