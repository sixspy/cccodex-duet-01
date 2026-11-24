from fastapi import APIRouter, HTTPException
from app.services import 目录, 左装载, 右装载, 对齐, 结论, 夹具, 统计, 说明, 幂等

路由 = APIRouter()

@路由.get("/api/概览")
def api_概览():
    return 目录.概览()

@路由.get("/api/轨规")
def api_轨规():
    return 目录.轨规()

@路由.post("/api/轨规")
def api_改轨规(体: dict):
    return 目录.改轨规(体)

@路由.get("/api/源登记")
def api_源():
    return 目录.源列表()

@路由.get("/api/左轨")
def api_左():
    return 目录.左列表()

@路由.get("/api/右轨")
def api_右():
    return 目录.右列表()

@路由.get("/api/对齐差")
def api_差():
    return 目录.差列表()

@路由.get("/api/悬账单")
def api_悬():
    return 目录.悬列表()

@路由.get("/api/对拍结论")
def api_结论列表():
    return 目录.结论列表()

@路由.get("/api/夹具")
def api_夹具():
    return 夹具.列表()

@路由.post("/api/左轨/装载")
def api_左装(体: dict):
    return 左装载.装一批(体)

@路由.post("/api/右轨/装载")
def api_右装(体: dict):
    return 右装载.装一批(体)

@路由.post("/api/左轨/夹具/{名}")
def api_左夹(名: str):
    try:
        return 左装载.装一批(夹具.读取(名))
    except FileNotFoundError:
        raise HTTPException(404, 名)

@路由.post("/api/右轨/夹具/{名}")
def api_右夹(名: str):
    try:
        return 右装载.装一批(夹具.读取(名))
    except FileNotFoundError:
        raise HTTPException(404, 名)

# 固定路径 + body 传夹具名：规避根静态 Mount 对带路径参数 POST 的 405
@路由.post("/api/左轨/夹具装")
def api_左夹装(体: dict):
    名 = 体.get("夹具名")
    try:
        return 左装载.装一批(夹具.读取(名))
    except FileNotFoundError:
        raise HTTPException(404, 名)

@路由.post("/api/右轨/夹具装")
def api_右夹装(体: dict):
    名 = 体.get("夹具名")
    try:
        return 右装载.装一批(夹具.读取(名))
    except FileNotFoundError:
        raise HTTPException(404, 名)

@路由.post("/api/对齐/跑")
def api_对齐():
    return 对齐.跑对齐()

@路由.post("/api/对拍结论/跑")
def api_结论():
    return 结论.跑一次()


@路由.get("/api/统计/左命运")
def api_左命运():
    return 统计.左命运()

@路由.get("/api/统计/右命运")
def api_右命运():
    return 统计.右命运()

@路由.get("/api/统计/差型")
def api_差型():
    return 统计.差型分布()

@路由.get("/api/统计/悬边")
def api_悬边():
    return 统计.悬边分布()


@路由.get("/api/仓情")
def api_仓情():
    return 说明.仓情()


@路由.get("/api/幂等/查")
def api_幂等查(事件编号: str, 轨别: str | None = None):
    """幂等只读接口：事件编号、轨别、拒因或归档键、形态标记、valid。"""
    return 幂等.只读查询(事件编号, 轨别)

@路由.get("/api/幂等/账册")
def api_幂等账册():
    return {"形态标记": 幂等.形态(), "行": 幂等.账册列表()}

@路由.get("/api/幂等/拒收史")
def api_幂等拒收史():
    return {"形态标记": 幂等.形态(), "行": 幂等.拒收史列表()}

@路由.get("/api/幂等/水位")
def api_幂等水位():
    return 幂等.账册水位()

@路由.get("/api/空桩")
def api_空桩():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "modules"
    空 = []
    落实 = []
    if root.is_dir():
        for p in sorted(root.iterdir()):
            if not (p.is_dir() and p.name != "__pycache__" and (p / "__init__.py").is_file()):
                continue
            文 = (p / "__init__.py").read_text(encoding="utf-8")
            # 空桩文件只有模块 docstring + NAME；含实质实现即视为已落实
            if "空桩" in 文 and len(文.strip().splitlines()) <= 4:
                空.append(p.name)
            else:
                落实.append(p.name)
    return {"空桩": 空, "条数": len(空), "已落实": 落实}

