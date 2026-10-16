import sqlite3
import shutil
import os

db_path = "data/jobs.db"
backup_path = "data/backup_before_purge.db"

# 1. Back up database
shutil.copyfile(db_path, backup_path)
print(f"Database backed up to {backup_path} ({os.path.getsize(backup_path)} bytes)")

# 2. Check counts before
conn = sqlite3.connect(db_path)
cur = conn.cursor()
before_count = cur.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
unknown_count = cur.execute("SELECT COUNT(*) FROM jobs WHERE job_id LIKE 'li-unknown-%'").fetchone()[0]
print(f"Total rows before: {before_count}")
print(f"Fake li-unknown rows before: {unknown_count}")

# 3. Purge
cur.execute("DELETE FROM jobs WHERE job_id LIKE 'li-unknown-%'")
conn.commit()

# 4. Check counts after
after_count = cur.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
print(f"Total rows after: {after_count}")
remaining_rows = cur.execute("SELECT platform, job_id, status FROM jobs").fetchall()
print("Remaining rows:")
for r in remaining_rows:
    print(" ", r)
conn.close()
