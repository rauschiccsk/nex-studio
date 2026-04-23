"""ICC-wide system settings — runtime-mutable key-value store.

Backs the Settings page's "ICC" tab. Current keys:

* ``github_org`` — GitHub organisation used to auto-fill
  ``repo_url`` on the new-project form as ``{github_org}/{slug}``.

Defaults live in :mod:`backend.services.system_setting` so a fresh
install resolves known keys without needing a seed migration. A row
in this table represents a runtime override of the default.
"""

from sqlalchemy import TIMESTAMP, Column, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from backend.db.models.base import Base


class SystemSetting(Base):
    """Single ICC-wide configuration key/value pair.

    Intentionally does not inherit :class:`TimestampMixin` — only the
    time and author of the last change matter for this table. A
    ``created_at`` would be meaningless noise for a key-value store
    that defaults come from code and rows appear only on first edit.
    """

    __tablename__ = "system_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    updated_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    updated_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
