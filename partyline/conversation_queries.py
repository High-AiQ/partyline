"""Conversation reads with the rail's derived live-process count."""

LIVE_JOIN = (
    "SELECT c.*,COUNT(a.id) live_count FROM conversations c LEFT JOIN attachments a "
    "ON a.conv_id=c.id AND a.status IN ('starting','running') "
)
ACTIVE_CONVERSATIONS = LIVE_JOIN + (
    "WHERE c.archived_at IS NULL GROUP BY c.id ORDER BY c.created_at DESC"
)
ARCHIVED_CONVERSATIONS = LIVE_JOIN + (
    "WHERE c.archived_at IS NOT NULL GROUP BY c.id ORDER BY c.archived_at DESC"
)
CONVERSATION_BY_ID = LIVE_JOIN + "WHERE c.id=? GROUP BY c.id"
