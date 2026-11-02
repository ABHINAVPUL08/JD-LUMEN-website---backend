import json
import sqlite3
from datetime import datetime, timedelta, timezone

from app.config import DATA_DIR, DB_PATH


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SEED_JOBS = [
    {
        "id": "frontend",
        "title": "Frontend Developer",
        "department": "Engineering",
        "type": "Full-time",
        "location": "Hybrid",
        "experience": "0–2 years",
        "description": "Build modern, responsive web applications and intuitive user interfaces.",
        "requirements": [
            "React and TypeScript",
            "HTML, CSS and Tailwind CSS",
            "Responsive UI development",
            "REST API integration",
        ],
    },
    {
        "id": "ai-developer",
        "title": "AI Automation Developer",
        "department": "AI & Automation",
        "type": "Full-time",
        "location": "Remote",
        "experience": "0–3 years",
        "description": "Create intelligent automation workflows, AI assistants and software integrations.",
        "requirements": [
            "Python or JavaScript",
            "API integrations",
            "AI agents and automation workflows",
            "Database fundamentals",
        ],
    },
    {
        "id": "designer",
        "title": "UI/UX Designer",
        "department": "Design",
        "type": "Internship",
        "location": "Hybrid",
        "experience": "Fresher",
        "description": "Design professional, accessible and user-friendly digital experiences.",
        "requirements": [
            "Figma",
            "Wireframing and prototyping",
            "Design systems",
            "Responsive web and mobile design",
        ],
    },
    {
        "id": "backend",
        "title": "Backend Developer",
        "department": "Engineering",
        "type": "Full-time",
        "location": "Remote",
        "experience": "1–3 years",
        "description": "Build reliable backend services, databases and secure application APIs.",
        "requirements": [
            "Node.js or Python",
            "REST APIs",
            "SQL databases",
            "Authentication fundamentals",
        ],
    },
]


def init_db() -> None:
    with connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS inquiries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                company TEXT NOT NULL,
                service TEXT NOT NULL,
                industry TEXT NOT NULL,
                message TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                email_sent INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                department TEXT NOT NULL,
                type TEXT NOT NULL,
                location TEXT NOT NULL,
                experience TEXT NOT NULL,
                description TEXT NOT NULL,
                requirements TEXT NOT NULL,
                is_open INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                phone TEXT NOT NULL DEFAULT '',
                experience TEXT NOT NULL DEFAULT '',
                skills TEXT NOT NULL DEFAULT '',
                password_hash TEXT NOT NULL,
                resume_original TEXT,
                resume_stored TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                candidate_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (candidate_id) REFERENCES candidates(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_sessions (
                token TEXT PRIMARY KEY,
                admin_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (admin_id) REFERENCES admins(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL,
                job_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Applied',
                resume_original TEXT,
                resume_stored TEXT,
                created_at TEXT NOT NULL,
                UNIQUE (candidate_id, job_id),
                FOREIGN KEY (candidate_id) REFERENCES candidates(id),
                FOREIGN KEY (job_id) REFERENCES jobs(id)
            )
            """
        )
        existing = connection.execute("SELECT COUNT(*) AS count FROM jobs").fetchone()
        if existing["count"] == 0:
            connection.executemany(
                """
                INSERT INTO jobs (
                    id, title, department, type, location, experience, description, requirements
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        job["id"],
                        job["title"],
                        job["department"],
                        job["type"],
                        job["location"],
                        job["experience"],
                        job["description"],
                        json.dumps(job["requirements"]),
                    )
                    for job in SEED_JOBS
                ],
            )


def insert_inquiry(inquiry: dict) -> int:
    created_at = now()
    with connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO inquiries (
                name, email, company, service, industry, message, source, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                inquiry["name"],
                inquiry["email"],
                inquiry["company"],
                inquiry["service"],
                inquiry["industry"],
                inquiry["message"],
                inquiry["source"],
                created_at,
            ),
        )
        return int(cursor.lastrowid)


def mark_email_sent(inquiry_id: int) -> None:
    with connect() as connection:
        connection.execute(
            "UPDATE inquiries SET email_sent = 1 WHERE id = ?",
            (inquiry_id,),
        )


def _job_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "department": row["department"],
        "type": row["type"],
        "location": row["location"],
        "experience": row["experience"],
        "description": row["description"],
        "requirements": json.loads(row["requirements"]),
    }


def _candidate_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "phone": row["phone"],
        "experience": row["experience"],
        "skills": row["skills"],
        "resumeName": row["resume_original"] or "",
    }


def list_jobs() -> list[dict]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, title, department, type, location, experience, description, requirements
            FROM jobs
            WHERE is_open = 1
            ORDER BY rowid
            """
        ).fetchall()
    return [_job_dict(row) for row in rows]


def job_id_taken(job_id: str) -> bool:
    with connect() as connection:
        row = connection.execute(
            "SELECT id FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    return row is not None


def get_job(job_id: str) -> dict | None:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT id, title, department, type, location, experience, description, requirements
            FROM jobs
            WHERE id = ? AND is_open = 1
            """,
            (job_id,),
        ).fetchone()
    if row is None:
        return None
    return _job_dict(row)


def get_candidate_by_email(email: str) -> dict | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM candidates WHERE email = ?",
            (email,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)


def get_candidate_record(candidate_id: int) -> dict | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM candidates WHERE id = ?",
            (candidate_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)


def insert_candidate(candidate: dict) -> dict:
    with connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO candidates (
                name, email, phone, experience, skills, password_hash,
                resume_original, resume_stored, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate["name"],
                candidate["email"],
                candidate["phone"],
                candidate["experience"],
                candidate["skills"],
                candidate["password_hash"],
                candidate.get("resume_original"),
                candidate.get("resume_stored"),
                now(),
            ),
        )
        row = connection.execute(
            "SELECT * FROM candidates WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return _candidate_dict(row)


def create_session(candidate_id: int, token: str) -> None:
    expires_at = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat(timespec="seconds")
    with connect() as connection:
        connection.execute(
            "INSERT INTO sessions (token, candidate_id, expires_at) VALUES (?, ?, ?)",
            (token, candidate_id, expires_at),
        )


def get_candidate_by_token(token: str) -> dict | None:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT candidates.*
            FROM sessions
            JOIN candidates ON candidates.id = sessions.candidate_id
            WHERE sessions.token = ? AND sessions.expires_at > ?
            """,
            (token, now()),
        ).fetchone()
    if row is None:
        return None
    return _candidate_dict(row)


def delete_session(token: str) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM sessions WHERE token = ?", (token,))


def list_applications(candidate_id: int) -> list[dict]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT applications.id, applications.job_id, applications.status,
                   applications.created_at, jobs.title
            FROM applications
            JOIN jobs ON jobs.id = applications.job_id
            WHERE applications.candidate_id = ?
            ORDER BY applications.id DESC
            """,
            (candidate_id,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "jobId": row["job_id"],
            "jobTitle": row["title"],
            "status": row["status"],
            "appliedAt": row["created_at"],
        }
        for row in rows
    ]


def insert_application(candidate_id: int, job_id: str, resume_original: str | None, resume_stored: str | None) -> dict:
    with connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO applications (
                candidate_id, job_id, resume_original, resume_stored, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (candidate_id, job_id, resume_original, resume_stored, now()),
        )
        row = connection.execute(
            """
            SELECT applications.id, applications.job_id, applications.status,
                   applications.created_at, jobs.title
            FROM applications
            JOIN jobs ON jobs.id = applications.job_id
            WHERE applications.id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
    return {
        "id": row["id"],
        "jobId": row["job_id"],
        "jobTitle": row["title"],
        "status": row["status"],
        "appliedAt": row["created_at"],
    }


def admin_exists(email: str) -> bool:
    with connect() as connection:
        row = connection.execute(
            "SELECT id FROM admins WHERE email = ?",
            (email,),
        ).fetchone()
    return row is not None


def insert_admin(name: str, email: str, password_hash: str) -> None:
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO admins (name, email, password_hash, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (name, email, password_hash, now()),
        )


def get_admin_by_email(email: str) -> dict | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM admins WHERE email = ?",
            (email,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)


def create_admin_session(admin_id: int, token: str) -> None:
    expires_at = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat(timespec="seconds")
    with connect() as connection:
        connection.execute(
            "INSERT INTO admin_sessions (token, admin_id, expires_at) VALUES (?, ?, ?)",
            (token, admin_id, expires_at),
        )


def get_admin_by_token(token: str) -> dict | None:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT admins.id, admins.name, admins.email
            FROM admin_sessions
            JOIN admins ON admins.id = admin_sessions.admin_id
            WHERE admin_sessions.token = ? AND admin_sessions.expires_at > ?
            """,
            (token, now()),
        ).fetchone()
        if row is None:
            return None
        return dict(row)


def delete_admin_session(token: str) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))


def list_admin_applications() -> list[dict]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT applications.id, applications.status, applications.created_at,
                   applications.resume_original, applications.resume_stored,
                   jobs.id AS job_id, jobs.title AS job_title,
                   candidates.name, candidates.email, candidates.phone,
                   candidates.experience, candidates.skills
            FROM applications
            JOIN candidates ON candidates.id = applications.candidate_id
            JOIN jobs ON jobs.id = applications.job_id
            ORDER BY applications.id DESC
            """
        ).fetchall()
        return [
            {
                "id": row["id"],
                "status": row["status"],
                "appliedAt": row["created_at"],
                "resumeName": row["resume_original"] or "",
                "hasResume": bool(row["resume_stored"]),
                "jobId": row["job_id"],
                "jobTitle": row["job_title"],
                "name": row["name"],
                "email": row["email"],
                "phone": row["phone"],
                "experience": row["experience"],
                "skills": row["skills"],
            }
            for row in rows
        ]


def get_application_resume(application_id: int) -> dict | None:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT resume_original, resume_stored
            FROM applications
            WHERE id = ?
            """,
            (application_id,),
        ).fetchone()
        if row is None or not row["resume_stored"]:
            return None
        return {
            "name": row["resume_original"] or "resume",
            "stored": row["resume_stored"],
        }


def update_application_status(application_id: int, status: str) -> bool:
    with connect() as connection:
        cursor = connection.execute(
            "UPDATE applications SET status = ? WHERE id = ?",
            (status, application_id),
        )
    return cursor.rowcount > 0


def list_all_jobs() -> list[dict]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, title, department, type, location, experience,
                   description, requirements, is_open
            FROM jobs
            ORDER BY rowid
            """
        ).fetchall()
    return [_job_dict(row) | {"isOpen": bool(row["is_open"])} for row in rows]


def insert_job(job: dict) -> None:
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO jobs (
                id, title, department, type, location, experience,
                description, requirements, is_open
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job["id"],
                job["title"],
                job["department"],
                job["type"],
                job["location"],
                job["experience"],
                job["description"],
                json.dumps(job["requirements"]),
                1 if job["is_open"] else 0,
            ),
        )


def update_job(job_id: str, job: dict) -> bool:
    with connect() as connection:
        cursor = connection.execute(
            """
            UPDATE jobs
            SET title = ?, department = ?, type = ?, location = ?, experience = ?,
                description = ?, requirements = ?, is_open = ?
            WHERE id = ?
            """,
            (
                job["title"],
                job["department"],
                job["type"],
                job["location"],
                job["experience"],
                job["description"],
                json.dumps(job["requirements"]),
                1 if job["is_open"] else 0,
                job_id,
            ),
        )
    return cursor.rowcount > 0


def list_inquiries() -> list[dict]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, name, email, company, service, industry, message,
                   source, created_at, email_sent
            FROM inquiries
            ORDER BY id DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def set_candidate_resume(candidate_id: int, original: str, stored: str) -> None:
    with connect() as connection:
        connection.execute(
            """
            UPDATE candidates
            SET resume_original = ?, resume_stored = ?
            WHERE id = ?
            """,
            (original, stored, candidate_id),
        )
