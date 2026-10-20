"""What a trial changed in the store.

Every table has an `id` primary key, so a snapshot is {table: {id: row}} and the diff
compares rows by id. The diff is plain JSON (strings, numbers, None), so it can be
written into the trace and stored with the results.
"""

import sqlite3


def snapshot(conn: sqlite3.Connection) -> dict[str, dict[str, dict]]:
    tables = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    return {
        table: {str(row["id"]): dict(row)
                for row in conn.execute(f"SELECT * FROM {table} ORDER BY id")}
        for table in tables
    }


def diff(before: dict, after: dict) -> dict:
    """{table: {"insert": [rows], "delete": [rows], "update": {id: {column: [old, new]}}}}.

    Only tables that changed appear.
    """
    out = {}
    for table in sorted(set(before) | set(after)):
        old, new = before.get(table, {}), after.get(table, {})
        inserted = [new[key] for key in new if key not in old]
        deleted = [old[key] for key in old if key not in new]
        updated = {
            key: {col: [old[key][col], new[key].get(col)]
                  for col in old[key] if old[key][col] != new[key].get(col)}
            for key in old if key in new and old[key] != new[key]
        }
        if inserted or deleted or updated:
            out[table] = {"insert": inserted, "delete": deleted, "update": updated}
    return out
