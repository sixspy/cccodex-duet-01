"""左右装载公共核：双边幂等键（切流账册形态）在此落地。

硬约束：
- 幂等跨左右：事件编号在账册全局唯一，查重/写流水/写账册/写拒收史同事务同成败。
- 两路并发同号：进程锁串行化 + 账册主键兜底，不得现行双行。
- 二次同号整票拒收：现行流水不增行，拒因入拒收史可回读。
"""
from __future__ import annotations

import json
import sqlite3
import uuid

from app.db import 连接
from app.seed import 此刻
from app.services import 校验, 幂等

轨配置 = {
    "左": {"表": "左轨流水", "默认源": "渠甲", "命运": "已入左", "批次前缀": "左批"},
    "右": {"表": "右轨流水", "默认源": "核乙", "命运": "已入右", "批次前缀": "右批"},
}


def 装(轨别: str, 体: dict) -> dict:
    cfg = 轨配置[轨别]
    批次 = 体.get("批次编号") or f"{cfg['批次前缀']}-{uuid.uuid4().hex[:8]}"
    事件 = 体.get("事件") or []
    报告 = {
        "批次编号": 批次,
        "轨别": 轨别,
        "形态标记": 幂等.形态(),
        "入流": 0,
        "跳过": 0,
        "驳回": 0,
        "幂等拒收": 0,
        "明细": [],
    }
    for e in 校验.校验批次(体):
        报告["明细"].append({"命运": "批次预检", "说明": e})

    # 整批持锁：两路并发同号在此串行，账册主键再兜底
    with 幂等.装载锁():
        conn = 连接()
        try:
            for ev in 事件:
                行错 = 校验.校验事件(ev)
                if 行错:
                    报告["驳回"] += 1
                    报告["明细"].append({"命运": "驳回-校验", "说明": ";".join(行错)})
                    continue
                编号 = ev.get("事件编号")
                键 = ev.get("业务键")
                if not 编号 or not 键:
                    报告["驳回"] += 1
                    报告["明细"].append({"命运": "驳回-缺字段", "事件": ev})
                    continue

                # 跨左右轨查重（替代原先只查本轨流水的角标式判断）
                撞 = 幂等.查重(conn, 编号, 键, 轨别)
                if 撞:
                    幂等.记拒收(conn, 编号, 键, 轨别, 批次, 撞["拒因"])
                    报告["幂等拒收"] += 1
                    报告["驳回"] += 1
                    报告["明细"].append({
                        "事件编号": 编号,
                        "业务键": 键,
                        "命运": 撞["拒因"],
                        "在轨别": 撞["在轨别"],
                        "在业务键": 撞["在业务键"],
                        "说明": f"账册已钉于{撞['在轨别']}轨，现行不增行",
                    })
                    continue

                源 = ev.get("源键") or cfg["默认源"]
                if not conn.execute(
                    "SELECT 1 FROM 源登记 WHERE 源键=? AND 轨别=?", (源, 轨别)
                ).fetchone():
                    报告["驳回"] += 1
                    报告["明细"].append({"事件编号": 编号, "命运": f"驳回-未知{轨别}源"})
                    continue

                金额 = int(ev.get("金额分", 0))
                事件时 = ev.get("事件时") or 此刻()
                处理时 = ev.get("处理时") or 此刻()

                # 账册钉号与流水插入同事务；保存点兜底竞态，不污染整批
                conn.execute("SAVEPOINT 入流")
                try:
                    幂等.钉入(conn, 编号, 键, 轨别, 源, 批次)
                    conn.execute(
                        f"""INSERT INTO {cfg['表']}(事件编号,业务键,金额分,源键,事件时,处理时,命运,批次编号)
                            VALUES (?,?,?,?,?,?,?,?)""",
                        (编号, 键, 金额, 源, 事件时, 处理时, cfg["命运"], 批次),
                    )
                except sqlite3.IntegrityError:
                    conn.execute("ROLLBACK TO SAVEPOINT 入流")
                    撞 = 幂等.查重(conn, 编号, 键, 轨别)
                    拒因 = 撞["拒因"] if 撞 else "幂等拒收-并发同号"
                    if 撞:
                        幂等.记拒收(conn, 编号, 键, 轨别, 批次, 拒因)
                    报告["幂等拒收"] += 1
                    报告["驳回"] += 1
                    报告["明细"].append({
                        "事件编号": 编号,
                        "业务键": 键,
                        "命运": 拒因,
                        "说明": "并发同号竞态兜底，现行不增行",
                    })
                    continue
                conn.execute("RELEASE SAVEPOINT 入流")
                报告["入流"] += 1
                报告["明细"].append({"事件编号": 编号, "业务键": 键, "命运": cfg["命运"]})

            # 同批次编号重灌（如固定夹具名二次装载）：覆盖回执而非撞主键；流水是否增由账册幂等决定
            conn.execute(
                "INSERT INTO 装载批次(编号,轨别,时刻,报告) VALUES (?,?,?,?) "
                "ON CONFLICT(编号) DO UPDATE SET 时刻=excluded.时刻, 报告=excluded.报告",
                (批次, 轨别, 此刻(), json.dumps(报告, ensure_ascii=False)),
            )
            conn.commit()
            return 报告
        finally:
            conn.close()
