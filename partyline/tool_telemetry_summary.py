"""Aggregate in SQLite so a 30-day tree summary never loads every call into Python."""


def query(line_count, group):
    flags = ("then", "refresh", "query", "more")
    # Only fixed SQL fragments are interpolated; all caller values are bound parameters.
    labels = ["json_extract(metrics,'$.tool') AS tool"]
    for name in ("sub_op", "action", *flags):
        expression = f"json_extract(metrics,'$.{name}')" if group == "sub_op" else (
            "''" if name in ("sub_op", "action") else "0")
        labels.append(f'{expression} AS "{name}"')
    keys = 'tool, sub_op, action, "then", refresh, query, more'
    return f"""WITH samples AS (
        SELECT {', '.join(labels)},
            json_extract(metrics,'$.estimated_tokens') + COALESCE((
                SELECT SUM(COALESCE(json_extract(value,'$.estimated_tokens'),0))
                FROM json_each(metrics,'$.images')),0) AS tokens,
            (SELECT COUNT(*) FROM json_each(metrics,'$.images')
                WHERE json_type(value,'$.estimated_tokens')='null') AS unknown_images,
            json_extract(metrics,'$.is_error') AS is_error,
            json_extract(metrics,'$.latency_ms') AS latency_ms
        FROM tool_calls WHERE conv_id IN ({','.join('?' for _ in range(line_count))}) AND timestamp >= ?
    ), ranked AS (
        SELECT *, COUNT(*) OVER (PARTITION BY {keys}) AS n,
            ROW_NUMBER() OVER (PARTITION BY {keys} ORDER BY tokens) AS token_rank,
            ROW_NUMBER() OVER (PARTITION BY {keys} ORDER BY latency_ms) AS latency_rank
        FROM samples
    ) SELECT {keys}, COUNT(*) AS calls, SUM(tokens) AS total_estimated_tokens,
        MAX(CASE WHEN token_rank=(n+1)/2 THEN tokens END) AS p50_estimated_tokens,
        MAX(CASE WHEN token_rank=(n*95+99)/100 THEN tokens END) AS p95_estimated_tokens,
        MAX(tokens) AS max_estimated_tokens, SUM(is_error) AS errors,
        MAX(CASE WHEN latency_rank=(n+1)/2 THEN latency_ms END) AS p50_latency_ms,
        SUM(unknown_images) AS unknown_images
    FROM ranked GROUP BY {keys} ORDER BY total_estimated_tokens DESC, tool, sub_op, action"""
