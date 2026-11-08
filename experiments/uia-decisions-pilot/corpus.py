"""Lossless semantic compaction of repeated JSON snapshots; no artifact imports."""
import copy
import json

from audit import snapshots

FORMAT = 'uia-snapshot-references-v1'


def pack(dataset):
    reads = snapshots(dataset)

    def replace(item):
        if isinstance(item, dict):
            if 'snapshot_id' in item:
                return {'$snapshot_ref': item['snapshot_id']}
            return {k: replace(v) for k, v in item.items()}
        if isinstance(item, list):
            return [replace(v) for v in item]
        return item
    return {'format': FORMAT, 'data': replace(dataset), 'snapshots': reads}


def unpack(value):
    if value.get('format') != FORMAT:
        return value
    reads = value['snapshots']

    def expand(item):
        if isinstance(item, dict):
            if set(item) == {'$snapshot_ref'}:
                read = reads[item['$snapshot_ref']]
                if read.get('snapshot_id') != item['$snapshot_ref']:
                    raise ValueError('snapshot reference mismatch')
                return copy.deepcopy(read)
            return {k: expand(v) for k, v in item.items()}
        if isinstance(item, list):
            return [expand(v) for v in item]
        return item
    return expand(value['data'])


def load(path):
    if path.stat().st_size > 10_000_000:
        raise ValueError('corpus exceeds size limit')
    return unpack(json.loads(path.read_text(encoding='utf-8')))
