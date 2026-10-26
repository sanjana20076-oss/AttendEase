"""Short-lived, account/enrollment-bound step-up access to faculty records."""
import hashlib

from flask import current_app, session

import clock

GRANT_KEY = "_faculty_records_access"


def clear_records_access():
    session.pop(GRANT_KEY, None)


def enrollment_digest(connection, faculty_id):
    rows = connection.execute(
        """SELECT fe.embedding_id, fe.embedding_data FROM faculty_face_embeddings fe
           JOIN faculty f ON f.faculty_id = fe.faculty_id
           WHERE fe.faculty_id = ? AND fe.is_active = 1 AND f.is_active = 1
           ORDER BY fe.embedding_id""", (faculty_id,),
    ).fetchall()
    if not rows:
        return None
    digest = hashlib.sha256()
    for row in rows:
        digest.update(str(row["embedding_id"]).encode("ascii"))
        digest.update(b":")
        digest.update(row["embedding_data"])
    return digest.hexdigest()


def verification_ttl():
    return max(30, min(900, int(current_app.config.get("FACULTY_RECORDS_VERIFICATION_TTL", 300))))


def grant_records_access(faculty_id, digest):
    now = clock.local_now().timestamp()
    session[GRANT_KEY] = {"faculty_id": int(faculty_id), "verified_at": now, "enrollment": digest}
    return now + verification_ttl()


def records_access_expiry(connection, faculty_id):
    grant = session.get(GRANT_KEY)
    if not isinstance(grant, dict) or grant.get("faculty_id") != faculty_id:
        clear_records_access()
        return None
    try:
        verified_at = float(grant["verified_at"])
    except (KeyError, TypeError, ValueError):
        clear_records_access()
        return None
    elapsed = clock.local_now().timestamp() - verified_at
    digest = enrollment_digest(connection, faculty_id)
    if not 0 <= elapsed < verification_ttl() or digest is None or digest != grant.get("enrollment"):
        clear_records_access()
        return None
    return verified_at + verification_ttl()
