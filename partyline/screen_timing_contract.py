"""Fixed, content-free timing vocabulary accepted by tool-call telemetry."""
import math
from typing import Annotated, Literal

from pydantic import Field

SERVER = ('server_total_ms', 'window_lock_ms', 'target_ms', 'send_ms', 'helper_roundtrip_ms',
          'barrier_ms', 'diff_ms', 'answer_ms', 'snapshot_store_ms', 'request_queue_ms',
          'image_store_ms')
HELPER = ('total_ms', 'action_total_ms', 'task_queue_ms', 'worker_queue_ms', 'initialize_ms',
          'target_ms', 'foreground_ms', 'uia_ms', 'gate_lock_ms', 'post_read_ms', 'barrier_ms',
          'walk_ms', 'nodes', 'com_calls', 'read_ms', 'process_start_ms', 'child_read_ms',
          'reply_ms', 'audit_ms', 'window_check_ms', 'capture_ms', 'encode_ms',
          'cdp_roundtrip_sum_ms', 'cdp_commands', 'ax_tree_ms', 'ax_nodes', 'ax_mapping_ms',
          'dom_mapping_ms', 'renderer_fence_ms', 'mapped_nodes', 'target_proof_ms',
          'dispatch_proof_ms', 'settle_wait_ms', 'point_settle_ms', 'point_total_ms', 'serialize_ms')
KEYS = (*SERVER, *('helper_' + key for key in HELPER), 'helper_barrier_stop')
STOP = ('quiet', 'unchanged', 'unsupported', 'deadline')
TimingKey = Literal[*KEYS]
TimingValue = Annotated[float, Field(ge=0, le=86400000)] | Literal[*STOP]


def extract(value):
    """Only the top-level screen timing leaves a tool result; never labels or observation text."""
    if not isinstance(value, dict) or not isinstance(value.get('timing'), dict):
        return {}
    result = {}
    for key, item in value['timing'].items():
        if key == 'helper_barrier_stop' and item in STOP:
            result[key] = item
        elif key in KEYS and type(item) in (int, float) and math.isfinite(item) and 0 <= item <= 86400000:
            result[key] = item
    return result
