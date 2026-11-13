/* ── PanelManager：通用面板显示/隐藏 ─────────────────────────────────────────
 * 用法：
 *   PanelManager.init('dashboard', [
 *     { id: 'charts', label: '每日趋势图表', defaultVisible: true },
 *     ...
 *   ]);
 *
 * 页面元素须带 data-panel="<id>" 属性。
 * 设置面板挂载到 id="panelSettingsBox" 的容器（由本模块自动插入）。
 * ──────────────────────────────────────────────────────────────────────────── */
const PanelManager = (function() {

    function init(pageKey, panels) {
        const STORAGE_KEY = 'panels_' + pageKey;

        /* ── 读取保存的偏好，未保存则用 defaultVisible ── */
        function getPrefs() {
            const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
            const prefs = {};
            panels.forEach(p => {
                prefs[p.id] = saved && p.id in saved ? saved[p.id] : (p.defaultVisible !== false);
            });
            return prefs;
        }

        /* ── 根据 prefs 更新所有面板元素的显示状态 ── */
        function applyPrefs(prefs) {
            panels.forEach(p => {
                const el = document.querySelector('[data-panel="' + p.id + '"]:not(#panelSettingsBox [data-panel])');
                if (el) el.style.display = prefs[p.id] ? '' : 'none';
            });
        }

        /* ── 将当前勾选框状态写入 localStorage 并刷新显示 ── */
        function saveAndApply() {
            const prefs = {};
            document.querySelectorAll('#panelSettingsBox input[data-panel]').forEach(cb => {
                prefs[cb.getAttribute('data-panel')] = cb.checked;
            });
            localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
            applyPrefs(prefs);
        }

        /* ── 渲染设置框（勾选列表）── */
        function renderSettingsBox() {
            const prefs = getPrefs();
            let html = '<div class="card" id="panelSettingsBox" style="display:none;">';
            html += '<div class="card-title" style="margin-bottom:12px;">显示/隐藏面板</div>';
            html += '<div style="display:flex;flex-wrap:wrap;gap:12px;">';
            panels.forEach(p => {
                const checked = prefs[p.id] ? ' checked' : '';
                html += '<label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:14px;">' +
                        '<input type="checkbox" data-panel="' + p.id + '"' + checked + '> ' +
                        p.label +
                        '</label>';
            });
            html += '</div></div>';

            /* 插到 .main-content 的最前面（page-header 之后，但在第一个面板之前） */
            const mainContent = document.querySelector('.main-content');
            if (!mainContent) return;
            const pageHeader = mainContent.querySelector('.page-header');
            const box = document.createElement('div');
            box.innerHTML = html;
            const boxEl = box.firstElementChild;
            if (pageHeader && pageHeader.nextSibling) {
                mainContent.insertBefore(boxEl, pageHeader.nextSibling);
            } else {
                mainContent.appendChild(boxEl);
            }

            /* 绑定 change 事件 */
            document.querySelectorAll('#panelSettingsBox input[data-panel]').forEach(cb => {
                cb.addEventListener('change', saveAndApply);
            });
        }

        /* ── 切换设置框的显示/隐藏 ── */
        function toggleSettingsBox() {
            const box = document.getElementById('panelSettingsBox');
            if (box) box.style.display = box.style.display === 'none' ? '' : 'none';
        }

        /* ── 初始化流程 ── */
        renderSettingsBox();
        applyPrefs(getPrefs());

        /* 把 toggle 函数挂到全局，供页面按钮的 onclick 调用 */
        window._panelToggle = toggleSettingsBox;
    }

    return { init };
})();
