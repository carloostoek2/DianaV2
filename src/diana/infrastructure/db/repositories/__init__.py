"""SQLAlchemy repository adapters implementing application/cognitive ports."""

from __future__ import annotations

from diana.infrastructure.db.repositories.approvals import SqlPendingApprovalStore
from diana.infrastructure.db.repositories.deliveries import SqlPendingDeliveryStore
from diana.infrastructure.db.repositories.escalations import SqlEscalationStore
from diana.infrastructure.db.repositories.history import SqlMessageHistoryRepo
from diana.infrastructure.db.repositories.calibration_data import (
    SqlCalibrationDataSource,
)
from diana.infrastructure.db.repositories.learning_metrics import (
    SqlLearningMetricsRepo,
)
from diana.infrastructure.db.repositories.metrics_data import SqlMetricsDataSource
from diana.infrastructure.db.repositories.owner_marks import SqlOwnerMarkStore
from diana.infrastructure.db.repositories.persona_versions import (
    PersonaVersionRepo,
    persona_version_orm_to_record,
)
from diana.infrastructure.db.repositories.system_config import SqlSystemConfigStore
from diana.infrastructure.db.repositories.contexts import ContextsRepo
from diana.infrastructure.db.repositories.traces import SqlTraceStore
from diana.infrastructure.db.repositories.turns import SqlTurnStore
from diana.infrastructure.db.repositories.vips import SqlVipStore, vip_orm_to_record
from diana.infrastructure.db.repositories.emotional_signal import (
    SqlEmotionalSignalLogRepo,
    emotional_signal_log_orm_to_record,
)
from diana.infrastructure.db.repositories.ephemeral_events import (
    EphemeralEventRepo,
    ephemeral_event_orm_to_record,
)
from diana.infrastructure.db.repositories.turn_category import (
    SqlTurnCategoryLogRepo,
    turn_category_log_orm_to_record,
)
from diana.infrastructure.db.repositories.vip_mood_state import (
    SqlVipMoodStateRepo,
    vip_mood_state_orm_to_record,
)
from diana.infrastructure.db.repositories.vip_profile import (
    SqlVipProfileRepo,
    vip_profile_orm_to_record,
)
from diana.infrastructure.db.repositories.vip_profile_history import (
    SqlVipProfileHistoryRepo,
    vip_profile_history_orm_to_record,
)
from diana.infrastructure.db.repositories.vip_trust_budget import (
    SqlVipTrustBudgetRepo,
    vip_trust_budget_orm_to_record,
)
from diana.infrastructure.db.repositories.link_events import (
    SqlLinkEventStore,
    link_event_orm_to_record,
)

__all__ = [
    "SqlCalibrationDataSource",
    "ContextsRepo",
    "EphemeralEventRepo",
    "ephemeral_event_orm_to_record",
    "SqlEmotionalSignalLogRepo",
    "SqlEscalationStore",
    "SqlLearningMetricsRepo",
    "SqlLinkEventStore",
    "SqlMetricsDataSource",
    "SqlMessageHistoryRepo",
    "SqlOwnerMarkStore",
    "SqlPendingApprovalStore",
    "SqlPendingDeliveryStore",
    "SqlSystemConfigStore",
    "SqlTraceStore",
    "SqlTurnCategoryLogRepo",
    "SqlTurnStore",
    "SqlVipMoodStateRepo",
    "SqlVipProfileHistoryRepo",
    "SqlVipProfileRepo",
    "SqlVipStore",
    "SqlVipTrustBudgetRepo",
    "PersonaVersionRepo",
    "vip_orm_to_record",
    "persona_version_orm_to_record",
    "emotional_signal_log_orm_to_record",
    "link_event_orm_to_record",
    "turn_category_log_orm_to_record",
    "vip_mood_state_orm_to_record",
    "vip_profile_history_orm_to_record",
    "vip_profile_orm_to_record",
    "vip_trust_budget_orm_to_record",
]
