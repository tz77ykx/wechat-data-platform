const FLASK = "http://localhost:5001";

function age(ts) {
  if (!ts) return "";
  const s = Math.floor((Date.now() - ts) / 1000);
  if (s < 60) return `${s}s前`;
  if (s < 3600) return `${Math.floor(s/60)}m前`;
  return `${Math.floor(s/3600)}h前`;
}

function setRow(valId, dotId, val, ts) {
  const vEl = document.getElementById(valId);
  const dEl = document.getElementById(dotId);
  if (!val) {
    vEl.textContent = "未检测";
    dEl.className = "dot no";
    return;
  }
  const isOld = ts && (Date.now() - ts) > 2 * 3600 * 1000;
  vEl.textContent = val.length > 20 ? val.slice(0, 20) + "…" : val;
  vEl.title = val;
  dEl.className = "dot " + (isOld ? "old" : "ok");
}

async function refresh() {
  const stored = await chrome.storage.local.get(["wx_token", "wx_token_ts", "wx_fingerprint", "wx_fp_ts"]);
  setRow("v-token", "d-token", stored.wx_token, stored.wx_token_ts);
  setRow("v-fp", "d-fp", stored.wx_fingerprint, stored.wx_fp_ts);

  const cookies = await chrome.cookies.getAll({ domain: "mp.weixin.qq.com" });
  const dEl = document.getElementById("d-cookie");
  const vEl = document.getElementById("v-cookie");
  if (cookies.length === 0) {
    vEl.textContent = "未登录";
    dEl.className = "dot no";
  } else {
    vEl.textContent = `${cookies.length} 个`;
    dEl.className = "dot ok";
  }
}

// ── 凭证同步 ──────────────────────────────────────────────────
document.getElementById("btn").addEventListener("click", async () => {
  const btn = document.getElementById("btn");
  const msg = document.getElementById("msg");
  btn.disabled = true;
  btn.textContent = "同步中…";
  msg.className = "info";
  msg.textContent = "";

  try {
    const stored = await chrome.storage.local.get(["wx_token", "wx_fingerprint"]);
    const cookies = await chrome.cookies.getAll({ domain: "mp.weixin.qq.com" });

    if (!stored.wx_token) {
      msg.className = "err";
      msg.textContent = "❌ Token 未检测，请先打开微信后台页面";
      return;
    }
    if (cookies.length === 0) {
      msg.className = "err";
      msg.textContent = "❌ 未检测到 Cookie，请先登录微信后台";
      return;
    }

    const cookieStr = cookies.map(c => `${c.name}=${c.value}`).join("; ");
    const res = await fetch(`${FLASK}/api/sync-credentials`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        token: stored.wx_token || "",
        fingerprint: stored.wx_fingerprint || "",
        cookies: cookieStr,
      }),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data.ok) {
      msg.className = "ok";
      msg.textContent = "✅ 同步成功！";
    } else {
      throw new Error(data.error || "未知错误");
    }
  } catch (e) {
    msg.className = "err";
    msg.textContent = "❌ " + e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "⬆️ 一键同步到本地工具";
  }
});

// ── 批量下载：发指令给 background，轮询进度 ──────────────────
let pollTimer = null;

function showSelection(selected) {
  document.getElementById("dl-period").value = selected.preset;
  document.getElementById("dl-start").value = selected.start_date;
  document.getElementById("dl-end").value = selected.end_date;
  document.getElementById("dl-mode").value = selected.download_mode;
}

function readSelection() {
  return DownloadSelection.validate({
    start_date: document.getElementById("dl-start").value,
    end_date: document.getElementById("dl-end").value,
    download_mode: document.getElementById("dl-mode").value,
  });
}

function rememberSelection() {
  try {
    return chrome.storage.local.set({ download_selection: {
      ...readSelection(), preset: document.getElementById("dl-period").value,
    } });
  } catch (_) {
    // 日期正在输入时保留上次完整选择，开始下载时再显示校验信息。
  }
}

const selectionReady = (async () => {
  const stored = await chrome.storage.local.get("download_selection");
  try {
    showSelection(DownloadSelection.resolve(stored.download_selection || {}));
  } catch (_) {
    showSelection(DownloadSelection.resolve());
  }
})();

document.getElementById("dl-period").addEventListener("change", () => {
  const preset = document.getElementById("dl-period").value;
  if (preset !== "custom") {
    showSelection(DownloadSelection.resolve({ preset, download_mode: document.getElementById("dl-mode").value }));
  }
  rememberSelection();
});
for (const id of ["dl-start", "dl-end"]) {
  document.getElementById(id).addEventListener("change", () => {
    document.getElementById("dl-period").value = "custom";
    rememberSelection();
  });
}
document.getElementById("dl-mode").addEventListener("change", rememberSelection);

function updateUI(p) {
  const btn = document.getElementById("btn-download");
  const progress = document.getElementById("dl-progress");
  for (const id of ["dl-period", "dl-start", "dl-end", "dl-mode"]) {
    document.getElementById(id).disabled = Boolean(p && p.running);
  }

  if (!p || !p.msg) {
    progress.textContent = "";
    btn.disabled = false;
    btn.textContent = "📥 开始批量下载";
    return;
  }

  progress.textContent = p.msg;
  progress.className = p.running ? "" : (p.error || p.failed > 0 ? "err" : "ok");

  if (p.running) {
    btn.disabled = true;
    btn.textContent = `下载中 ${p.current}/${p.total}`;
  } else {
    btn.disabled = false;
    btn.textContent = "📥 开始批量下载";
    // 停止轮询
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }
}

function startPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(() => {
    chrome.runtime.sendMessage({ action: "get-progress" }, (p) => {
      updateUI(p);
    });
  }, 1000);
}

document.getElementById("btn-download").addEventListener("click", async () => {
  try {
    await selectionReady;
    const selection = readSelection();
    await rememberSelection();
    chrome.runtime.sendMessage({ action: "start-batch-download", selection }, (resp) => {
      if (resp && resp.ok) {
        updateUI({ running: true, current: 0, total: 0, done: 0, failed: 0, msg: "启动中..." });
        startPolling();
      } else {
        updateUI({ running: false, error: true, msg: resp?.error || "扩展后台未响应，请重新加载扩展" });
      }
    });
  } catch (error) {
    updateUI({ running: false, error: true, msg: error.message });
  }
});

// 页面打开时检查是否有正在运行的下载
chrome.runtime.sendMessage({ action: "get-progress" }, (p) => {
  if (p && p.running) {
    updateUI(p);
    startPolling();
  } else if (p && p.msg) {
    updateUI(p);
  }
});

// ── 正文抓取 ────────────────────────────────────────────────
let contentPollTimer = null;

function updateContentUI(p) {
  const btn = document.getElementById("btn-content");
  const progress = document.getElementById("content-progress");
  if (!p || !p.msg) {
    progress.textContent = "";
    btn.disabled = false;
    btn.textContent = "📄 批量抓取正文";
    return;
  }
  progress.textContent = p.msg;
  progress.style.color = p.running ? "#555" : (p.failed > 0 ? "#c5221f" : "#2d7a40");
  if (p.running) {
    btn.disabled = true;
    btn.textContent = `抓取中 ${p.current}/${p.total}`;
  } else {
    btn.disabled = false;
    btn.textContent = "📄 批量抓取正文";
    if (contentPollTimer) { clearInterval(contentPollTimer); contentPollTimer = null; }
  }
}

function startContentPolling() {
  if (contentPollTimer) return;
  contentPollTimer = setInterval(() => {
    chrome.runtime.sendMessage({ action: "get-content-progress" }, updateContentUI);
  }, 1000);
}

document.getElementById("btn-content").addEventListener("click", () => {
  chrome.runtime.sendMessage({ action: "start-fetch-content" }, (resp) => {
    if (resp && resp.ok) {
      updateContentUI({ running: true, current: 0, total: 0, done: 0, failed: 0, msg: "启动中..." });
      startContentPolling();
    }
  });
});

chrome.runtime.sendMessage({ action: "get-content-progress" }, (p) => {
  if (p && p.running) { updateContentUI(p); startContentPolling(); }
  else if (p && p.msg) { updateContentUI(p); }
});

refresh();
