async function get(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
async function post(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? "{}" : JSON.stringify(body ?? {}),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
function 徽(v) {
  const s = String(v);
  if (s === "对齐" || s === "1" || s === "true" || s.includes("已入") || s === "已钉") return `<span class="徽 绿">${s}</span>`;
  if (s.includes("缺") || s.includes("不符") || s === "0" || s === "false" || s.includes("拒收") || s.includes("漂")) return `<span class="徽 红">${s}</span>`;
  return `<span class="徽 灰">${s}</span>`;
}
function 表(headers, rows, mapRow) {
  if (!rows || !rows.length) return '<div class="空">暂无数据</div>';
  return `<div class="表绕"><table><thead><tr>${headers.map(h=>`<th>${h}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(r=>`<tr>${mapRow(r)}</tr>`).join("")}</tbody></table></div>`;
}
function 统计(items) {
  return `<div class="统计">${items.map(([n,v])=>`<div class="格"><div class="数">${v}</div><div class="名">${n}</div></div>`).join("")}</div>`;
}

// 双边幂等键（切流账册形态）前端组件
async function 幂等水位条() {
  const w = await get("/api/幂等/水位");
  return `<div class="标签行">
    <span class="标签">幂等形态：<b>${w.形态标记}</b></span>
    <span class="标签">账册钉号：${w.账册钉号数}</span>
    <span class="标签">现行流水：${w.现行流水条数}</span>
    <span class="标签">只读归档：${w.归档条数}（本形态恒 0）</span>
    <span class="标签">幂等拒收史：${w.拒收史条数}</span>
  </div>`;
}

async function 幂等查询盒(轨别) {
  const 编号 = document.getElementById("幂查号").value.trim();
  const out = document.getElementById("幂查果");
  if (!编号) { out.innerHTML = '<div class="空">输入事件编号再查</div>'; return; }
  const q = await get(`/api/幂等/查?事件编号=${encodeURIComponent(编号)}${轨别 ? `&轨别=${encodeURIComponent(轨别)}` : ""}`);
  out.innerHTML = 表(
    ["事件编号","轨别","valid","形态标记","状态","拒因","归档键","现行条数"],
    [q],
    r => `<td>${r.事件编号}</td><td>${r.轨别||"-"}</td><td>${徽(r.valid)}</td>
      <td>${r.形态标记}</td><td>${徽(r.状态)}</td><td>${r.拒因 ? 徽(r.拒因) : "-"}</td>
      <td>${r.归档键 || "-"}（归档${r.归档行数}行）</td><td>${r.现行条数}</td>`
  );
}

function 装载摘要(r) {
  const 条 = [];
  条.push(`<div class="条信息">批次 <b>${r.批次编号}</b>（${r.轨别}轨）· 幂等形态：${r.形态标记 || "切流账册"}</div>`);
  条.push(统计([["入流", r.入流], ["幂等拒收", r.幂等拒收 || 0], ["校验驳回", r.驳回 || 0], ["跳过", r.跳过 || 0]]));
  if (r.明细 && r.明细.length) {
    条.push(表(
      ["事件编号","业务键","命运","说明"],
      r.明细,
      x => `<td>${x.事件编号||"-"}</td><td>${x.业务键||"-"}</td>
        <td>${x.命运 ? 徽(x.命运) : "-"}</td><td>${x.说明||""}</td>`
    ));
  }
  return 条.join("");
}
