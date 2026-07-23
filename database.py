#!/usr/bin/env python3
import sqlite3
from datetime import datetime, timedelta


class DownloadDB:
    def __init__(self, db_path="scraper.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_id TEXT UNIQUE,
                username TEXT,
                file TEXT,
                type TEXT,
                date TEXT,
                downloaded_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS accounts_stats (
                username TEXT PRIMARY KEY,
                total_downloads INTEGER DEFAULT 0,
                last_use TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_username ON downloads(username)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_downloaded_at ON downloads(downloaded_at)")
        conn.commit()
        conn.close()
    
    def is_downloaded(self, media_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM downloads WHERE media_id = ?", (media_id,))
        result = cursor.fetchone()
        conn.close()
        return result is not None
    
    def add_download(self, data):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO downloads (media_id, username, file, type, date) VALUES (?, ?, ?, ?, ?)",
                          (data['media_id'], data['username'], data['file'], data['type'], data['date']))
            cursor.execute("INSERT INTO accounts_stats (username, total_downloads, last_use) VALUES (?, 1, ?) ON CONFLICT(username) DO UPDATE SET total_downloads = total_downloads + 1, last_use = ?",
                          (data['username'], datetime.now().isoformat(), datetime.now().isoformat()))
            conn.commit()
        except sqlite3.IntegrityError:
            pass
        finally:
            conn.close()
    
    def get_stats(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM downloads")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT username) FROM downloads")
        profiles = cursor.fetchone()[0]
        cursor.execute("SELECT MAX(downloaded_at) FROM downloads")
        last = cursor.fetchone()[0]
        conn.close()
        return {'total': total, 'profiles': profiles, 'last_download': last, 'disk_usage': self._get_disk_usage()}
    
    def get_account_downloads(self, username):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM downloads WHERE username = ?", (username,))
        result = cursor.fetchone()[0]
        conn.close()
        return result
    
    def get_recent_downloads(self, limit=10):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT file, username, type, downloaded_at FROM downloads ORDER BY downloaded_at DESC LIMIT ?", (limit,))
        results = [{'file': r[0], 'profile': r[1], 'type': r[2], 'date': r[3]} for r in cursor.fetchall()]
        conn.close()
        return results
    
    def get_top_profiles(self, limit=10):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT username, COUNT(*) as count FROM downloads GROUP BY username ORDER BY count DESC LIMIT ?", (limit,))
        results = [{'username': r[0], 'count': r[1]} for r in cursor.fetchall()]
        conn.close()
        return results
    
    def get_downloads_by_day(self, days=7):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT DATE(downloaded_at) as day, COUNT(*) as count FROM downloads WHERE downloaded_at >= DATE('now', ?) GROUP BY day ORDER BY day", (f'-{days} days',))
        results = {r[0]: r[1] for r in cursor.fetchall()}
        conn.close()
        return results
    
    def get_performance_stats(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM downloads WHERE downloaded_at >= DATETIME('now', '-24 hours')")
        last_24h = cursor.fetchone()[0]
        conn.close()
        return {'last_24h': last_24h, 'avg_per_hour': round(last_24h / 24, 1) if last_24h > 0 else 0}
    
    def clear_cache(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        month_ago = (datetime.now() - timedelta(days=30)).isoformat()
        cursor.execute("DELETE FROM downloads WHERE downloaded_at < ?", (month_ago,))
        conn.commit()
        conn.close()
    
    def _get_disk_usage(self):
        try:
            import shutil
            usage = shutil.disk_usage("downloads")
            return f"{usage.used / (1024**3):.1f} GB"
        except:
            return "N/A"
