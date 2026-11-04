"""Local lexical memory, inspired by dsh-fish-memory (see NOTICE.md).

This is a MaiBot-specific implementation, not the upstream JavaScript plugin.
SQLite connections are short lived; callers run all methods in worker threads.
"""
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
import hashlib
import json
import math
import re
import sqlite3
import time

import jieba

STOP = set("我 你 他 她 它 我们 你们 他们 自己 这个 那个 什么 怎么 为什么 哪个 多少 时候 现在 今天 昨天 明天 之前 以后 刚才 记得 记住 记忆 知道 喜欢 请问 可以 就是 还是 一个 一些 一下 真的 没有 不是 但是 然后 如果 所以 还有 比较 觉得 事情 聊天 你好 在吗 哈哈 嗯嗯".split())
SECRET = re.compile(r"(?:sk-[A-Za-z0-9_-]{8,}|密码|验证码|密钥|api\s*key|access.?token|身份证|银行卡|\b\d{17}[\dXx]\b)", re.I)
CN_TIME = timezone(timedelta(hours=8))


def tokens(text: str) -> set[str]:
    terms = {w.lower().strip() for w in jieba.cut(text, HMM=False)
            if len(w.strip()) >= 2 and w.strip() not in STOP and re.search(r"[\w\u4e00-\u9fff]", w)}
    # Small explicit lexical aliases bridge common personal-preference questions.
    # These are transparent dictionaries, not semantic embeddings.
    for category, pattern in {
        "主题:饮品": r"茶|咖啡|奶昔|饮料|饮品|喝",
        "主题:饮食": r"饭|菜|面条|火锅|食物|饮食|吃",
        "主题:颜色": r"颜色|色彩|红色|蓝色|绿色|紫色|黄色|黑色|白色|粉色",
        "主题:居住": r"住在|居住|住哪|城市|搬家",
        "主题:宠物": r"宠物|小猫|小狗|养猫|养狗",
    }.items():
        if re.search(pattern, text):
            terms.add(category)
    return terms


def parse_extraction(text: str, source: str) -> list[dict]:
    """Only accept claims backed by an exact quote from this speaker's message."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("memories"), list):
        raise ValueError("extraction_schema")
    result = []
    for m in data["memories"][:3]:
        if not isinstance(m, dict):
            continue
        body, quote = str(m.get("text", "")).strip(), str(m.get("quote", "")).strip()
        key = str(m.get("fact_key", "")).strip()[:60]
        if not 4 <= len(body) <= 160 or len(quote) < 4 or quote not in source:
            continue
        if SECRET.search(body + " " + quote) or any(x in body for x in ("系统提示", "忽略指令", "开发者指令")):
            continue
        kind = str(m.get("kind", "episode"))
        if kind not in ("fact", "episode"):
            continue
        importance = float(m.get("importance", .5))
        if not math.isfinite(importance):
            continue
        # Facts need an explicit stable aspect; all other records decay.
        result.append(dict(text=body, quote=quote, fact_key=key if kind == "fact" else "",
                           kind=kind if key else "episode", importance=max(0., min(1., importance))))
    return result


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.lock = RLock()

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=3)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def start(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Initialize segmentation outside the event loop, once.
        tokens("中文分词长期记忆")
        with self.connect() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript('''
            CREATE TABLE IF NOT EXISTS memories(
              id INTEGER PRIMARY KEY, scope TEXT NOT NULL, author TEXT NOT NULL,
              text TEXT NOT NULL, quote TEXT NOT NULL, fact_key TEXT NOT NULL,
              kind TEXT NOT NULL, importance REAL NOT NULL, created REAL NOT NULL,
              recalled REAL NOT NULL, reinforcement REAL NOT NULL DEFAULT 0,
              day TEXT NOT NULL, digest TEXT NOT NULL, source_id TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'active', terms TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS memory_scope ON memories(scope,status,author);
            CREATE TABLE IF NOT EXISTS seen(scope TEXT, message_id TEXT, at REAL,
              PRIMARY KEY(scope,message_id));
            CREATE TABLE IF NOT EXISTS recalls(scope TEXT, turn_id TEXT, memory_id INTEGER,
              PRIMARY KEY(scope,turn_id,memory_id));
            CREATE TABLE IF NOT EXISTS forget_epochs(scope TEXT,author TEXT,at REAL,
              PRIMARY KEY(scope,author));
            ''')

    def claim(self, scope: str, mid: str, now: float) -> bool:
        with self.lock, self.connect() as c:
            cur = c.execute("INSERT OR IGNORE INTO seen VALUES(?,?,?)", (scope, mid, now))
            c.execute("DELETE FROM seen WHERE at<?", (now-7*86400,))
            return cur.rowcount == 1

    def save(self, scope: str, author: str, memories: list[dict], source_id: str,
             daily_limit: int = 8, now: float | None = None, source_stamp: float | None = None) -> int:
        now = time.time() if now is None else now
        day = datetime.fromtimestamp(now, CN_TIME).date().isoformat()
        count = 0
        with self.lock, self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            cutoff = c.execute("SELECT at FROM forget_epochs WHERE scope=? AND author=?", (scope, author)).fetchone()
            if cutoff and (source_stamp if source_stamp is not None else now) <= cutoff[0]:
                return 0
            used = c.execute("SELECT COUNT(*) FROM memories WHERE scope=? AND author=? AND day=?",
                             (scope, author, day)).fetchone()[0]
            for m in memories:
                digest = hashlib.sha256(m["text"].encode()).hexdigest()
                if c.execute("SELECT 1 FROM memories WHERE scope=? AND author=? AND digest=? AND status='active'",
                             (scope, author, digest)).fetchone():
                    continue
                if used >= daily_limit:
                    break
                # Fact replacement is confined to this speaker in this visibility scope.
                if m["fact_key"]:
                    c.execute("UPDATE memories SET status='superseded' WHERE scope=? AND author=? AND fact_key=? AND status='active'",
                              (scope, author, m["fact_key"]))
                c.execute("""INSERT INTO memories(scope,author,text,quote,fact_key,kind,importance,
                          created,recalled,day,digest,source_id,terms) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (scope, author, m["text"], m["quote"], m["fact_key"], m["kind"], m["importance"],
                           now, now, day, digest, source_id, json.dumps(sorted(tokens(m["text"]+" "+m["quote"])), ensure_ascii=False)))
                used += 1
                count += 1
        return count

    def recall(self, scope: str, query: str, turn_id: str, *, author: str = "",
               half_life: float = 30, max_items: int = 6, max_chars: int = 800,
               now: float | None = None) -> list[dict]:
        now = time.time() if now is None else now
        q = tokens(query)
        if not q:
            return []
        with self.lock, self.connect() as c:
            rows = [dict(r) for r in c.execute("SELECT * FROM memories WHERE scope=? AND status='active' ORDER BY id DESC LIMIT 3000", (scope,))]
            # "我" queries must not turn another group member's preference into this user's.
            if author and re.search(r"我|本人", query):
                rows = [r for r in rows if r["author"] == author]
            df = Counter(w for r in rows for w in json.loads(r["terms"]))
            scored = []
            for r in rows:
                terms = set(json.loads(r["terms"]))
                shared = q & terms
                if not shared:
                    continue
                weights = {w: math.log(1 + (len(rows)+1)/(df[w]+1)) for w in q}
                evidence = sum(weights[w] for w in shared)/sum(weights.values())
                # One concrete uncommon term is allowed; generic overlaps aren't.
                if evidence < .30 or (len(shared) == 1 and len(next(iter(shared))) < 2):
                    continue
                half = half_life * (0.5 + 1.5*r["importance"]) * (1 + min(r["reinforcement"], 5)*.2)
                fresh = 1. if r["kind"] == "fact" else 2 ** (-max(0, now-r["recalled"])/(half*86400))
                score = evidence*(.05+.95*fresh)*(.7+.3*r["importance"])
                if score < .12:
                    continue
                r.update(score=round(score, 4), evidence=round(evidence, 4))
                scored.append(r)
            selected, size = [], 0
            for r in sorted(scored, key=lambda x: x["score"], reverse=True):
                if len(selected) >= max_items:
                    break
                if size + len(r["text"]) + 45 > max_chars:
                    continue
                size += len(r["text"]) + 45
                selected.append(r)
                # Retries of the same turn cannot repeatedly reinforce a memory.
                if c.execute("INSERT OR IGNORE INTO recalls VALUES(?,?,?)", (scope, turn_id, r["id"])).rowcount:
                    c.execute("UPDATE memories SET recalled=?,reinforcement=MIN(5,reinforcement+0.2) WHERE id=?", (now, r["id"]))
            return selected

    def forget(self, scope: str, author: str, keyword: str) -> int:
        if not 1 <= len(keyword) <= 160:
            return 0
        with self.lock, self.connect() as c:
            c.execute("INSERT INTO forget_epochs VALUES(?,?,?) ON CONFLICT(scope,author) DO UPDATE SET at=excluded.at",
                      (scope, author, time.time()))
            ids = [r["id"] for r in c.execute("SELECT id,text,quote FROM memories WHERE scope=? AND author=?", (scope, author)) if keyword in r["text"] or keyword in r["quote"]]
            # Explicit forgetting removes the content, unlike passive decay.
            for mid in ids:
                c.execute("DELETE FROM recalls WHERE memory_id=?", (mid,))
                c.execute("DELETE FROM memories WHERE id=?", (mid,))
            return len(ids)

    def overview(self):
        with self.connect() as c:
            return [dict(r) for r in c.execute("SELECT scope,status,COUNT(*) AS count FROM memories GROUP BY scope,status")]

    def list_recent(self):
        with self.connect() as c:
            return [dict(r) for r in c.execute("SELECT id,scope,author,text,kind,status,created FROM memories ORDER BY id DESC LIMIT 100")]
