"""双边幂等键（切流账册形态）验收测试。

覆盖题面硬约束：
- 首次入左成功；同号再入左：现行不增、拒收史可回读拒因；
- 同号灌入右轨：另一轨不得写入（跨轨幂等），对齐键半边漂可识别；
- 同号并发：现行不得双行；
- 现行条数与归档条数可分开（切流账册形态归档恒 0）；
- 只读接口字段：事件编号、轨别、拒因/归档键、形态标记、valid；
- 左装→右装→对齐差对拍 happy path 不被破坏。
"""
import os
import threading
from pathlib import Path

_tmp = Path(__file__).resolve().parent / "_tmp"
_tmp.mkdir(exist_ok=True)
os.environ["数据目录"] = str(_tmp)
os.environ["夹具目录"] = str(Path(__file__).resolve().parents[2] / "fixtures")

from app import seed
from app.db import 连接
from app.services import 左装载, 右装载, 对齐, 结论, 目录, 幂等
from app.modules.双边幂等键 import 形态标记, 因_同轨重灌, 因_异轨撞号, 因_键漂移


def setup_function():
    db = _tmp / "对拍.db"
    if db.exists():
        db.unlink()
    seed.初始化库()


def _左事件(编号="e1", 键="K1", 金额=100):
    return {"事件": [{"事件编号": 编号, "业务键": 键, "金额分": 金额,
                     "源键": "渠甲", "事件时": "2026-11-23T10:00:00Z"}]}


def _右事件(编号="e1", 键="K1", 金额=100):
    return {"事件": [{"事件编号": 编号, "业务键": 键, "金额分": 金额,
                     "源键": "核乙", "事件时": "2026-11-23T10:00:01Z"}]}


def _现行条数(编号):
    conn = 连接()
    try:
        左 = conn.execute("SELECT COUNT(*) AS c FROM 左轨流水 WHERE 事件编号=?", (编号,)).fetchone()["c"]
        右 = conn.execute("SELECT COUNT(*) AS c FROM 右轨流水 WHERE 事件编号=?", (编号,)).fetchone()["c"]
        return 左 + 右
    finally:
        conn.close()


def test_首次入左成功():
    r = 左装载.装一批(_左事件())
    assert r["入流"] == 1
    assert r["幂等拒收"] == 0
    assert r["形态标记"] == 形态标记
    assert len(目录.左列表()) == 1
    q = 幂等.只读查询("e1")
    assert q["valid"] is True
    assert q["轨别"] == "左"
    assert q["状态"] == "已钉"
    assert q["形态标记"] == "切流账册"


def test_同号再入左现行不增且拒因可回读():
    左装载.装一批(_左事件())
    r2 = 左装载.装一批(_左事件())
    assert r2["入流"] == 0
    assert r2["幂等拒收"] == 1
    assert r2["明细"][-1]["命运"] == 因_同轨重灌
    assert len(目录.左列表()) == 1  # 现行不增行
    q = 幂等.只读查询("e1", "左")
    assert q["valid"] is True
    assert 因_同轨重灌 in q["拒因"]
    assert q["拒收次数"] == 1
    assert q["现行条数"] == 1
    assert q["归档键"] == "" and q["归档行数"] == 0  # 切流账册：无归档
    史 = 幂等.拒收史列表()
    assert len(史) == 1 and 史[0]["拒因"] == 因_同轨重灌


def test_同号灌右轨另一轨不得写入():
    左装载.装一批(_左事件())
    r = 右装载.装一批(_右事件())
    assert r["入流"] == 0
    assert r["幂等拒收"] == 1
    assert r["明细"][-1]["命运"] == 因_异轨撞号
    assert len(目录.右列表()) == 0   # 右轨未写入
    assert _现行条数("e1") == 1       # 全局只有左轨一行
    q = 幂等.只读查询("e1", "右")
    assert 因_异轨撞号 in q["拒因"]


def test_对齐键半边漂识别():
    左装载.装一批(_左事件(键="K1"))
    # 同事件编号换业务键再灌左
    r = 左装载.装一批(_左事件(键="K9"))
    assert r["幂等拒收"] == 1
    assert r["明细"][-1]["命运"] == 因_键漂移
    assert "半边漂" in r["明细"][-1]["命运"] or "漂" in r["明细"][-1]["命运"]
    q = 幂等.只读查询("e1")
    assert q["业务键"] == "K1"  # 账册保留首次对齐键，未漂


def test_同号并发不得现行双行():
    结果 = []

    def 灌左():
        结果.append(左装载.装一批(_左事件()))

    def 灌右():
        结果.append(右装载.装一批(_右事件()))

    t1 = threading.Thread(target=灌左)
    t2 = threading.Thread(target=灌右)
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert _现行条数("e1") == 1  # 不得双行
    入流 = [x for x in 结果 if x["入流"] == 1]
    拒收 = [x for x in 结果 if x["幂等拒收"] == 1]
    assert len(入流) == 1 and len(拒收) == 1


def test_同号并发同侧也不双行():
    结果 = []

    def 灌():
        结果.append(左装载.装一批(_左事件()))

    ts = [threading.Thread(target=灌) for _ in range(5)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert _现行条数("e1") == 1
    assert sum(x["入流"] for x in 结果) == 1
    assert sum(x["幂等拒收"] for x in 结果) == 4


def test_现行与归档条数分开():
    左装载.装一批(_左事件())
    左装载.装一批(_左事件())  # 二次同号拒收
    w = 幂等.账册水位()
    assert w["形态标记"] == "切流账册"
    assert w["现行流水条数"] == 1
    assert w["归档条数"] == 0          # 切流账册形态归档恒 0
    assert w["账册钉号数"] == 1
    assert w["拒收史条数"] == 1
    # 概览同样能分开
    o = 目录.概览()
    assert o["现行流水条数"] == 1 and o["归档条数"] == 0


def test_未见号只读接口valid为假():
    q = 幂等.只读查询("nope")
    assert q["valid"] is False
    assert q["事件编号"] == "nope"
    assert q["形态标记"] == "切流账册"
    assert q["归档行数"] == 0


def test_老库回灌账册():
    # 先造一笔流水再重新初始化（模拟老库升级）
    左装载.装一批(_左事件(编号="old1"))
    seed.初始化库()
    q = 幂等.只读查询("old1")
    assert q["valid"] is True and q["轨别"] == "左"
    # 回灌后同号仍被拒
    r = 左装载.装一批(_左事件(编号="old1"))
    assert r["幂等拒收"] == 1


def test_固定批次编号重灌覆盖回执不炸主键():
    体 = {"批次编号": "固定批-1", "事件": [
        {"事件编号": "b1", "业务键": "K1", "金额分": 100, "源键": "渠甲", "事件时": "2026-11-23T10:00:00Z"}]}
    左装载.装一批(体)
    r2 = 左装载.装一批(体)  # 同批次编号 + 同事件编号
    assert r2["入流"] == 0 and r2["幂等拒收"] == 1
    assert len(目录.左列表()) == 1  # 现行仍不增
    conn = 连接()
    try:
        # 装载批次只有一行（覆盖而非新增）
        n = conn.execute("SELECT COUNT(*) AS c FROM 装载批次 WHERE 编号='固定批-1'").fetchone()["c"]
        assert n == 1
    finally:
        conn.close()


def test_左右装载后对齐对拍happy_path不破():
    左装载.装一批({
        "事件": [
            {"事件编号": "a1", "业务键": "K1", "金额分": 100, "源键": "渠甲", "事件时": "2026-11-23T10:00:00Z"},
            {"事件编号": "a2", "业务键": "K2", "金额分": 200, "源键": "渠甲", "事件时": "2026-11-23T10:00:01Z"},
        ]
    })
    右装载.装一批({
        "事件": [
            {"事件编号": "b1", "业务键": "K1", "金额分": 100, "源键": "核乙", "事件时": "2026-11-23T10:00:00Z"},
            {"事件编号": "b2", "业务键": "K3", "金额分": 50, "源键": "核乙", "事件时": "2026-11-23T10:00:02Z"},
        ]
    })
    r = 对齐.跑对齐()
    assert r["对齐"] == 1
    assert r["悬账"] >= 2
    g = 结论.跑一次()
    assert g["是否通过"] is True
    # 差型中文状态仍在
    差型 = {x["差型"] for x in 目录.差列表()}
    assert {"对齐", "右缺", "左缺"} <= 差型
