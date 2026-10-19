"""Conversation reads with the rail's derived live-process count."""

LIVE_JOIN = (
    "SELECT c.*,COUNT(a.id) live_count,t.status task_status,t.round task_round,"
    "r.name task_root_name,COALESCE(i.name,t.implementer_preset) task_implementer_name,"
    "CASE WHEN t.policy='none' THEN 'none' WHEN t.policy='captain' THEN "
    "COALESCE((SELECT name FROM attachments WHERE conv_id=t.root_id AND is_lead=1 "
    "ORDER BY created_at,id LIMIT 1),'captain') "
    "ELSE COALESCE(v.name,t.policy) END task_reviewer_name "
    "FROM conversations c LEFT JOIN task_reviews t ON t.conv_id=c.id "
    "LEFT JOIN conversations r ON r.id=t.root_id "
    "LEFT JOIN attachments i ON i.id=t.implementer_id "
    "LEFT JOIN attachments v ON v.id=t.reviewer_id "
    "LEFT JOIN attachments a "
    "ON a.conv_id=c.id AND a.status IN ('starting','running') "
)
ACTIVE_CONVERSATIONS = LIVE_JOIN + (
    "WHERE c.archived_at IS NULL GROUP BY c.id ORDER BY c.created_at DESC"
)
ARCHIVED_CONVERSATIONS = LIVE_JOIN + (
    "WHERE c.archived_at IS NOT NULL GROUP BY c.id ORDER BY c.archived_at DESC"
)
CONVERSATION_BY_ID = LIVE_JOIN + "WHERE c.id=? GROUP BY c.id"
