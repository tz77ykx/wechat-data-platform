importScripts("download-selection.js");

const FLASK = "http://localhost:5001";

// ── 自动提取 token 和 fingerprint ────────────────────────────
chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    try {
      const url = new URL(details.url);
      const token = url.searchParams.get("token");
      const fingerprint = url.searchParams.get("fingerprint");
      if (token) {
        chrome.storage.local.set({ wx_token: token, wx_token_ts: Date.now() });
      }
      if (fingerprint) {
        chrome.storage.local.set({ wx_fingerprint: fingerprint, wx_fp_ts: Date.now() });
      }
    } catch (_) {}
  },
  { urls: ["https://mp.weixin.qq.com/*"] }
);

// ── 批量下载状态 ──────────────────────────────────────────────
// 存在 storage 里，popup 随时可以读取
function updateProgress(obj) {
  chrome.storage.local.set({ dl_progress: obj });
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

function waitForTabLoad(tabId) {
  return new Promise((resolve) => {
    function listener(tid, changeInfo) {
      if (tid === tabId && changeInfo.status === "complete") {
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    }
    chrome.tabs.onUpdated.addListener(listener);
    setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      resolve();
    }, 15000);
  });
}

// 等待在指定窗口内新开的 tab（点击 target="_blank" 后调用）
function waitForNewTabInWindow(windowId, timeoutMs = 10000) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      chrome.tabs.onCreated.removeListener(listener);
      resolve(null);
    }, timeoutMs);
    function listener(tab) {
      if (tab.windowId === windowId) {
        clearTimeout(timer);
        chrome.tabs.onCreated.removeListener(listener);
        resolve(tab);
      }
    }
    chrome.tabs.onCreated.addListener(listener);
  });
}

async function batchDownload(selection) {
  try {
    const selected = DownloadSelection.validate(selection);
    const range = `${selected.start_date} 至 ${selected.end_date}`;
    updateProgress({ running: true, current: 0, total: 0, done: 0, failed: 0, msg: `正在刷新 ${range} 发布的文章...` });
    // 凭证同步不会更新文章清单。先刷新，失败时不得沿用旧的下载队列。
    const refreshRes = await fetch(`${FLASK}/fetch-msgids`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start_date: selected.start_date, end_date: selected.end_date }),
    });
    const refreshed = await refreshRes.json();
    if (!refreshRes.ok || !refreshed.ok) {
      const reason = refreshed.error || `HTTP ${refreshRes.status}`;
      const hint = /invalid csrf token|invalid session/.test(reason)
        ? "；请刷新已登录的微信后台页面，重新同步凭证后再试"
        : "";
      throw new Error(`文章列表刷新失败，未开始下载：${reason}${hint}`);
    }
    if (refreshed.date_range?.start_date !== selected.start_date || refreshed.date_range?.end_date !== selected.end_date) {
      throw new Error("本地平台尚未应用日期范围，请重启更新后的平台；未开始下载");
    }

    updateProgress({ running: true, current: 0, total: 0, done: 0, failed: 0, msg: "文章列表已刷新，获取待下载列表..." });
    const res = await fetch(`${FLASK}/api/pending-details?${new URLSearchParams(selected)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "获取列表失败");
    if (Object.keys(selected).some(key => data.selection?.[key] !== selected[key])) {
      throw new Error("本地平台返回的下载范围不一致，未开始下载");
    }

    const urls = data.urls || [];
    if (urls.some(item => !item.publish_date || item.publish_date < selected.start_date || item.publish_date > selected.end_date)) {
      throw new Error("下载队列包含日期范围外的文章，未开始下载");
    }
    if (urls.length === 0) {
      updateProgress({ running: false, current: 0, total: 0, done: 0, failed: 0,
        msg: selected.download_mode === "missing" ? `✅ ${range} 没有需要补充详情的文章` : `✅ ${range} 没有可下载的文章` });
      return;
    }

    let done = 0, failed = 0;
    const total = urls.length;

    for (let i = 0; i < total; i++) {
      const item = urls[i];
      updateProgress({
        running: true, current: i + 1, total, done, failed,
        msg: `正在处理 ${i + 1}/${total}：${(item.title || "").slice(0, 20)}`
      });

      try {
        // 打开详情页（后台标签）
        const tab = await chrome.tabs.create({ url: item.detail_url, active: false });

        // 等页面加载完 + 额外 2 秒让 JS 渲染
        await waitForTabLoad(tab.id);
        await sleep(2000);

        // 获取窗口 ID，在点击前注册新 tab 监听
        const tabInfo = await chrome.tabs.get(tab.id);
        const newTabPromise = waitForNewTabInWindow(tabInfo.windowId, 10000);

        // 注入脚本点击"下载数据明细"
        const results = await chrome.scripting.executeScript({
          target: { tabId: tab.id },
          func: () => {
            // 精确匹配
            for (const a of document.querySelectorAll("a")) {
              if (a.textContent.trim() === "下载数据明细") {
                a.click();
                return { ok: true, text: a.textContent.trim() };
              }
            }
            // 次选：含 download=1 的链接
            for (const a of document.querySelectorAll("a")) {
              if (a.href && a.href.includes("download=1")) {
                a.click();
                return { ok: true, text: a.textContent.trim() };
              }
            }
            // 次选：class=target_part
            for (const a of document.querySelectorAll("a.target_part")) {
              a.click();
              return { ok: true, text: a.textContent.trim() };
            }
            return { ok: false, body: document.body.innerText.slice(0, 200) };
          }
        });

        const result = results && results[0] && results[0].result;
        if (result && result.ok) {
          done++;
          // 等待 target="_blank" 新开的下载 tab 加载完成，再关闭
          const newTab = await newTabPromise;
          if (newTab) {
            await waitForTabLoad(newTab.id);
            await sleep(1500);
            try { await chrome.tabs.remove(newTab.id); } catch (_) {}
          } else {
            // 未检测到新 tab（直接下载场景），等固定时间
            await sleep(3000);
          }
        } else {
          failed++;
          console.log(`[batch-dl] 失败 [${item.title}]:`, result);
        }

        // 关闭详情页 tab
        try { await chrome.tabs.remove(tab.id); } catch (_) {}

      } catch (e) {
        failed++;
        console.log(`[batch-dl] 异常 [${item.title}]:`, e.message);
      }

      // 间隔 3 秒
      if (i < total - 1) {
        await sleep(3000);
      }
    }

    const msg = failed === 0
      ? `✅ 全部 ${done} 篇下载完成！文件会自动导入。`
      : `完成 ${done} 篇，失败 ${failed} 篇。`;
    updateProgress({ running: false, current: total, total, done, failed, msg: `${range}：${msg}` });

  } catch (e) {
    updateProgress({ running: false, current: 0, total: 0, done: 0, failed: 0, error: true, msg: "❌ " + e.message });
  }
}

// ── 批量抓取对标文章正文 ──────────────────────────────────────
function updateContentProgress(obj) {
  chrome.storage.local.set({ content_progress: obj });
}

async function batchFetchContent() {
  updateContentProgress({ running: true, current: 0, total: 0, done: 0, failed: 0, msg: "获取待抓取列表..." });

  try {
    const res = await fetch(`${FLASK}/api/competitor/pending-content`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "获取列表失败");

    const articles = data.articles || [];
    if (articles.length === 0) {
      updateContentProgress({ running: false, current: 0, total: 0, done: 0, failed: 0, msg: "✅ 所有文章正文已抓取" });
      return;
    }

    let done = 0, failed = 0;
    const total = articles.length;

    for (let i = 0; i < total; i++) {
      const item = articles[i];
      updateContentProgress({
        running: true, current: i + 1, total, done, failed,
        msg: `正在抓取 ${i + 1}/${total}：${(item.title || "").slice(0, 20)}`
      });

      try {
        const tab = await chrome.tabs.create({ url: item.url, active: false });
        await waitForTabLoad(tab.id);
        await sleep(2000);

        // 注入脚本提取正文
        const results = await chrome.scripting.executeScript({
          target: { tabId: tab.id },
          func: () => {
            const el = document.getElementById("js_content");
            if (!el) return { ok: false, reason: "no js_content" };
            const text = el.innerText.trim().replace(/\s+/g, " ");
            if (text.length < 5) return { ok: false, reason: "content too short" };
            return { ok: true, text: text.slice(0, 3000) };
          }
        });

        const result = results && results[0] && results[0].result;
        if (result && result.ok) {
          // 发回 Flask 存库
          const saveRes = await fetch(`${FLASK}/api/competitor/article/${item.id}/content`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content: result.text })
          });
          if (saveRes.ok) done++;
          else failed++;
        } else {
          failed++;
          console.log(`[content] 失败 [${item.title}]:`, result);
        }

        try { await chrome.tabs.remove(tab.id); } catch (_) {}
      } catch (e) {
        failed++;
        console.log(`[content] 异常 [${item.title}]:`, e.message);
      }

      if (i < total - 1) await sleep(2000);
    }

    const msg = failed === 0
      ? `✅ 全部 ${done} 篇正文抓取完成！`
      : `完成 ${done} 篇，失败 ${failed} 篇。`;
    updateContentProgress({ running: false, current: total, total, done, failed, msg });

  } catch (e) {
    updateContentProgress({ running: false, current: 0, total: 0, done: 0, failed: 0, msg: "❌ " + e.message });
  }
}

// ── 消息监听：popup 发指令过来 ────────────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === "start-batch-download") {
    batchDownload(msg.selection);
    sendResponse({ ok: true });
  }
  if (msg.action === "start-fetch-content") {
    batchFetchContent();
    sendResponse({ ok: true });
  }
  if (msg.action === "get-progress") {
    chrome.storage.local.get("dl_progress", (data) => {
      sendResponse(data.dl_progress || { running: false, msg: "" });
    });
    return true;
  }
  if (msg.action === "get-content-progress") {
    chrome.storage.local.get("content_progress", (data) => {
      sendResponse(data.content_progress || { running: false, msg: "" });
    });
    return true;
  }
});
