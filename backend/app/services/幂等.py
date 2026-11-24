"""双边幂等键（切流账册形态）：跨左右轨的事件编号查重、拒收与回读。

工程形态二选一，本仓全局只落「切流账册」一边：
- 账册钉已入事件编号；二次同号整票拒收，拒收史可回读拒因，现行流水不增行。
- 不做「双写两轨 + 只读归档」形态，故无归档表，归档键/归档行数恒空/0。
- 查重、写流水、写账册、写拒收史在同一把进程互斥锁与同一事务内同成败。
"""
from __future__ import annotations

import threading
from app.db import 连接
from app.seed import 此刻
from app.modules.双边幂等键 import 形态标记, 因_同轨重灌, 因_异轨撞号, 因_键漂移

# 单进程 uvicorn 下的装载互斥：两路并发同号串行化，配合账册主键双保险。
_装载锁 = threading.RLock()

# 账册/拒收史建表由 seed.初始化库 统一执行，此处仅提供 DDL 片段。
账册建表 = """
CREATE TABLE IF NOT EXISTS 幂等账册 (
  事件编号 TEXT PRIMARY KEY,
  业务键 TEXT NOT NULL,
  轨别 TEXT NOT NULL,
  源键 TEXT NOT NULL,
  批次编号 TEXT NOT NULL DEFAULT '',
  状态 TEXT NOT NULL DEFAULT '已钉',
  入流时刻 TEXT NOT NULL,
  拒收次数 INTEGER NOT NULL DEFAULT 0,
  末次拒收时刻 TEXT NOT NULL DEFAULT '',
  末次拒因 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 幂等拒收史 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  事件编号 TEXT NOT NULL,
  业务键 TEXT NOT NULL DEFAULT '',
  轨别 TEXT NOT NULL,
  批次编号 TEXT NOT NULL DEFAULT '',
  拒因 TEXT NOT NULL,
  时刻 TEXT NOT NULL
);
"""


def 形态() -> str:
    return 形态标记


def 回灌账册(conn) -> int:
    """库初始化/老库升级：把已在现行流水里的事件编号补钉进账册。返回补钉条数。"""
    n = 0
    for 轨别, 表, 命运 in (("左", "左轨流水", "已入左"), ("右", "右轨流水", "已入右")):
        for r in conn.execute(f"SELECT * FROM {表}").fetchall():
            cur = conn.execute(
                "INSERT OR IGNORE INTO 幂等账册(事件编号,业务键,轨别,源键,批次编号,状态,入流时刻) "
                "VALUES (?,?,?,?,?,'已钉',?)",
                (r["事件编号"], r["业务键"], 轨别, r["源键"], r["批次编号"], r["处理时"]),
            )
            n += cur.rowcount
    return n


def 查重(conn, 编号: str, 业务键: str, 轨别: str) -> dict | None:
    """账册查重。命中返回含拒因的 dict，未命中返回 None。"""
    钉 = conn.execute("SELECT * FROM 幂等账册 WHERE 事件编号=?", (编号,)).fetchone()
    if not 钉:
        return None
    if 钉["业务键"] != 业务键:
        因 = 因_键漂移
    elif 钉["轨别"] == 轨别:
        因 = 因_同轨重灌
    else:
        因 = 因_异轨撞号
    return {
        "事件编号": 编号,
        "业务键": 业务键,
        "在轨别": 钉["轨别"],
        "在业务键": 钉["业务键"],
        "拒因": 因,
    }


def 记拒收(conn, 编号: str, 业务键: str, 轨别: str, 批次: str, 拒因: str) -> None:
    时刻 = 此刻()
    conn.execute(
        "UPDATE 幂等账册 SET 拒收次数=拒收次数+1, 末次拒收时刻=?, 末次拒因=? WHERE 事件编号=?",
        (时刻, 拒因, 编号),
    )
    conn.execute(
        "INSERT INTO 幂等拒收史(事件编号,业务键,轨别,批次编号,拒因,时刻) VALUES (?,?,?,?,?,?)",
        (编号, 业务键, 轨别, 批次, 拒因, 时刻),
    )


def 钉入(conn, 编号: str, 业务键: str, 轨别: str, 源: str, 批次: str) -> None:
    """首入：账册钉号。与流水 INSERT 同事务，失败一起回滚。"""
    conn.execute(
        "INSERT INTO 幂等账册(事件编号,业务键,轨别,源键,批次编号,状态,入流时刻) "
        "VALUES (?,?,?,?,?,'已钉',?)",
        (编号, 业务键, 轨别, 源, 批次, 此刻()),
    )


def 装载锁():
    """两路并发同号的互斥锁（重入，整批装载期间持有）。"""
    return _装载锁


def 只读查询(编号: str, 轨别: str | None = None) -> dict:
    """幂等只读接口：事件编号、轨别、拒因或归档键、形态标记、valid。"""
    conn = 连接()
    try:
        钉 = conn.execute("SELECT * FROM 幂等账册 WHERE 事件编号=?", (编号,)).fetchone()
        if not 钉:
            return {
                "事件编号": 编号,
                "轨别": 轨别 or "",
                "valid": False,
                "形态标记": 形态标记,
                "状态": "未见号",
                "拒因": "",
                "归档键": "",
                "归档行数": 0,
                "现行条数": _现行计数(conn, 编号),
            }
        史 = conn.execute(
            "SELECT 拒因, 时刻 FROM 幂等拒收史 WHERE 事件编号=? ORDER BY 编号 DESC LIMIT 1",
            (编号,),
        ).fetchone()
        if 轨别 and 钉["轨别"] != 轨别:
            # 跨轨查询：号在对侧轨，本轨视角即撞号
            拒因 = 史["拒因"] if 史 else 因_异轨撞号
        else:
            拒因 = 史["拒因"] if 史 else 钉["末次拒因"]
        return {
            "事件编号": 编号,
            "轨别": 钉["轨别"],
            "查询轨别": 轨别 or "",
            "valid": True,
            "形态标记": 形态标记,
            "状态": 钉["状态"],
            "业务键": 钉["业务键"],
            "源键": 钉["源键"],
            "批次编号": 钉["批次编号"],
            "入流时刻": 钉["入流时刻"],
            "拒因": 拒因 or "",
            "拒收次数": 钉["拒收次数"],
            "末次拒收时刻": 钉["末次拒收时刻"],
            "归档键": "",          # 切流账册形态无归档
            "归档行数": 0,         # 二次同号后归档恒无行
            "现行条数": _现行计数(conn, 编号),
        }
    finally:
        conn.close()


def _现行计数(conn, 编号: str) -> int:
    左 = conn.execute("SELECT COUNT(*) AS c FROM 左轨流水 WHERE 事件编号=?", (编号,)).fetchone()["c"]
    右 = conn.execute("SELECT COUNT(*) AS c FROM 右轨流水 WHERE 事件编号=?", (编号,)).fetchone()["c"]
    return 左 + 右


def 账册列表(限制: int = 300) -> list[dict]:
    conn = 连接()
    try:
        rows = conn.execute(
            "SELECT * FROM 幂等账册 ORDER BY 入流时刻 DESC LIMIT ?", (限制,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def 拒收史列表(限制: int = 300) -> list[dict]:
    conn = 连接()
    try:
        rows = conn.execute(
            "SELECT * FROM 幂等拒收史 ORDER BY 编号 DESC LIMIT ?", (限制,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def 账册水位() -> dict:
    """轨规策略页/对拍台用：现行与归档条数须能分开。"""
    conn = 连接()
    try:
        钉数 = conn.execute("SELECT COUNT(*) AS c FROM 幂等账册").fetchone()["c"]
        拒收 = conn.execute("SELECT COUNT(*) AS c FROM 幂等拒收史").fetchone()["c"]
        现行 = (
            conn.execute("SELECT COUNT(*) AS c FROM 左轨流水").fetchone()["c"]
            + conn.execute("SELECT COUNT(*) AS c FROM 右轨流水").fetchone()["c"]
        )
        return {
            "形态标记": 形态标记,
            "账册钉号数": 钉数,
            "现行流水条数": 现行,
            "归档条数": 0,          # 切流账册形态：无归档
            "拒收史条数": 拒收,
        }
    finally:
        conn.close()
