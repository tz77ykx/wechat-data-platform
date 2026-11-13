        let currentDate = new Date();
        let currentView = 'month';
        let events = JSON.parse(localStorage.getItem('wechatEvents') || '[]');
        let selectedDate = null;
        let editingIndex = null;
        let draggedIndex = null;
        let draggedEventData = null;

        // 回收站数据
        let trashItems = JSON.parse(localStorage.getItem('calendarTrash')) || [];

        // 批量操作相关
        let batchMode = false;
        let selectedItems = new Set();

        // 从localStorage加载标签配置，或使用默认
        let PREDEFINED_TAGS = JSON.parse(localStorage.getItem('calendarTags')) || [
            { name: '活动', color: '#FF6B6B' },
            { name: '产品', color: '#4ECDC4' },
            { name: '干货', color: '#45B7D1' },
            { name: '资讯', color: '#96CEB4' },
            { name: '其他', color: '#999999' }
        ];

        // ==================== 多日历管理 ====================
        let calendars = JSON.parse(localStorage.getItem('calendars')) || [
            { id: 'default', name: '默认日历', events: [] }
        ];
        let currentCalendarId = localStorage.getItem('currentCalendarId') || 'default';

        // 加载当前日历的事件
        function loadCurrentCalendar() {
            const calendar = calendars.find(c => c.id === currentCalendarId);
            if (calendar) {
                events = calendar.events || [];
            } else {
                events = [];
            }
        }

        // 保存当前日历
        function saveCurrentCalendar() {
            const calendar = calendars.find(c => c.id === currentCalendarId);
            if (calendar) {
                calendar.events = events;
            }
            localStorage.setItem('calendars', JSON.stringify(calendars));
            localStorage.setItem('currentCalendarId', currentCalendarId);
        }

        // 渲染日历列表
        function renderCalendarList() {
            const list = document.getElementById('calendarList');
            if (!list) return;

            let html = '';
            calendars.forEach(cal => {
                const count = cal.events ? cal.events.length : 0;
                const isActive = cal.id === currentCalendarId;
                html += `
                    <div class="calendar-item ${isActive ? 'active' : ''}" onclick="switchCalendar('${cal.id}')">
                        <span>${escapeHtml(cal.name)}</span>
                        <span class="calendar-item-count">${count}</span>
                    </div>
                `;
            });
            list.innerHTML = html;
        }

        // 切换日历
        function switchCalendar(calendarId) {
            // 先保存当前日历
            saveCurrentCalendar();
            // 切换
            currentCalendarId = calendarId;
            loadCurrentCalendar();
            renderCalendarList();
            render();
            // 关闭侧边栏（移动端）
            document.getElementById('calendarSidebar').classList.remove('open');
        }

        // 添加新日历
        function addNewCalendar() {
            const name = prompt('请输入日历名称：');
            if (!name || !name.trim()) return;

            const newCalendar = {
                id: 'cal_' + Date.now(),
                name: name.trim(),
                events: []
            };
            calendars.push(newCalendar);
            saveCurrentCalendar();
            renderCalendarList();
        }

        // 切换侧边栏
        function toggleSidebar() {
            document.getElementById('calendarSidebar').classList.toggle('open');
        }

        // ==================== 重复事件功能 ====================
        // 生成重复事件实例
        function generateRepeatInstances(event, startDate, endDate) {
            if (!event.repeat || !event.repeat.type) return [];

            const instances = [];
            const start = new Date(startDate);
            const end = endDate ? new Date(endDate) : new Date(start.getFullYear() + 1, 11, 31);
            let current = new Date(event.date);
            let count = 0;
            const maxCount = event.repeat.endType === 'count' ? parseInt(event.repeat.endValue) || 999 : 999;

            while (current <= end) {
                if (current >= start) {
                    instances.push(formatDate(current));
                    count++;
                    if (event.repeat.endType === 'count' && count >= maxCount) break;
                    if (event.repeat.endType === 'date' && current >= new Date(event.repeat.endValue)) break;
                }

                // 计算下一个日期
                switch (event.repeat.type) {
                    case 'weekly':
                        current.setDate(current.getDate() + 7);
                        break;
                    case 'biweekly':
                        current.setDate(current.getDate() + 14);
                        break;
                    case 'monthly':
                        current.setMonth(current.getMonth() + 1);
                        break;
                    case 'yearly':
                        current.setFullYear(current.getFullYear() + 1);
                        break;
                    default:
                        return instances;
                }
            }

            return instances;
        }

        // 获取所有事件（包括重复实例）
        function getAllEventsWithRepeats(viewDate) {
            const year = viewDate.getFullYear();
            const month = viewDate.getMonth();
            const firstDay = new Date(year, month, 1);
            const lastDay = new Date(year, month + 1, 0);

            // 扩展日期范围以包含跨月的事件
            const startRange = new Date(year, month - 1, 1);
            const endRange = new Date(year, month + 2, 0);

            const allEvents = [];
            const processedKeys = new Set();

            events.forEach(event => {
                if (event.repeat && event.repeat.type) {
                    // 重复事件
                    const instances = generateRepeatInstances(event, startRange, endRange);
                    instances.forEach(date => {
                        const key = `${date}_${event.title}`;
                        if (!processedKeys.has(key)) {
                            processedKeys.add(key);
                            allEvents.push({ ...event, date, isRepeat: true, originalDate: event.date });
                        }
                    });
                } else {
                    // 普通事件
                    allEvents.push(event);
                }
            });

            return allEvents;
        }

        // ==================== 统计面板功能 ====================
        function openStatsPanel() {
            const modal = document.createElement('div');
            modal.className = 'modal-overlay active';
            modal.id = 'statsModal';
            modal.innerHTML = `
                <div class="modal" style="max-width: 800px;">
                    <div class="modal-header">
                        <h3 class="modal-title">数据统计</h3>
                        <button class="modal-close" onclick="closeStatsPanel()">×</button>
                    </div>
                    <div class="modal-body">
                        ${renderStatsContent()}
                    </div>
                </div>
            `;
            modal.onclick = (e) => {
                if (e.target === modal) closeStatsPanel();
            };
            document.body.appendChild(modal);
        }

        function closeStatsPanel() {
            const modal = document.getElementById('statsModal');
            if (modal) modal.remove();
        }

        function renderStatsContent() {
            const year = currentDate.getFullYear();
            const month = currentDate.getMonth();

            // 本月统计
            const monthEvents = events.filter(e => {
                const d = new Date(e.date);
                return d.getFullYear() === year && d.getMonth() === month;
            });

            // 年度统计
            const yearEvents = events.filter(e => {
                const d = new Date(e.date);
                return d.getFullYear() === year;
            });

            // 标签统计
            const tagStats = {};
            PREDEFINED_TAGS.forEach(tag => tagStats[tag.name] = 0);
            events.forEach(e => {
                if (e.tag && tagStats.hasOwnProperty(e.tag)) {
                    tagStats[e.tag]++;
                }
            });

            // 近6个月趋势
            const monthlyTrend = [];
            for (let i = 5; i >= 0; i--) {
                const d = new Date(year, month - i, 1);
                const count = events.filter(e => {
                    const ed = new Date(e.date);
                    return ed.getFullYear() === d.getFullYear() && ed.getMonth() === d.getMonth();
                }).length;
                monthlyTrend.push({
                    label: `${d.getMonth() + 1}月`,
                    count: count
                });
            }

            const maxCount = Math.max(...monthlyTrend.map(t => t.count), 1);

            return `
                <div class="stats-panel">
                    <div class="stats-grid">
                        <div class="stat-card">
                            <div class="stat-card-number">${monthEvents.length}</div>
                            <div class="stat-card-label">本月推送</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-card-number">${yearEvents.length}</div>
                            <div class="stat-card-label">本年推送</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-card-number">${events.length}</div>
                            <div class="stat-card-label">总计划数</div>
                        </div>
                    </div>

                    <div class="stats-chart">
                        <div class="stats-chart-title">近6个月推送趋势</div>
                        <div class="bar-chart">
                            ${monthlyTrend.map(t => `
                                <div class="bar-item">
                                    <div class="bar" style="height: ${(t.count / maxCount * 120)}px;"></div>
                                    <div class="bar-label">${t.label}</div>
                                </div>
                            `).join('')}
                        </div>
                    </div>

                    <div class="stats-chart">
                        <div class="stats-chart-title">标签分布</div>
                        <div class="tag-distribution">
                            ${PREDEFINED_TAGS.map(tag => {
                                const count = tagStats[tag.name] || 0;
                                return `
                                    <div class="tag-stat-item">
                                        <span class="tag-stat-dot" style="background: ${tag.color};"></span>
                                        <span class="tag-stat-name">${tag.name}</span>
                                        <span class="tag-stat-count">${count}</span>
                                    </div>
                                `;
                            }).join('')}
                        </div>
                    </div>
                </div>
            `;
        }

        document.addEventListener('DOMContentLoaded', () => {
            // 加载当前日历数据
            loadCurrentCalendar();
            renderCalendarList();
            updateTrashCount();
            render();

            // 默认隐藏批量选择区域
            const batchSelectAll = document.querySelector('.batch-select-all');
            if (batchSelectAll) {
                batchSelectAll.style.display = 'none';
            }

            // 监听窗口大小变化，重新渲染以调整标题显示
            window.addEventListener('resize', debounce(() => {
                if (currentView === 'month') {
                    renderMonthView();
                }
            }, 200));
        });

        // 防抖函数
        function debounce(func, wait) {
            let timeout;
            return function executedFunction(...args) {
                const later = () => {
                    clearTimeout(timeout);
                    func(...args);
                };
                clearTimeout(timeout);
                timeout = setTimeout(later, wait);
            };
        }

        // 根据容器宽度计算能显示的字符数
        function getMaxTitleLength() {
            const containerWidth = document.querySelector('.calendar-day')?.offsetWidth || 150;
            // 估算：每个中文字符约 12px，留一些边距
            const maxChars = Math.floor((containerWidth - 16) / 12);
            return Math.max(4, Math.min(maxChars, 20)); // 最少4个，最多20个
        }

        function switchView(view) {
            currentView = view;
            document.querySelectorAll('.view-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.view === view);
            });
            document.getElementById('monthView').style.display = view === 'month' ? 'block' : 'none';
            document.getElementById('yearView').classList.toggle('active', view === 'year');
            document.getElementById('timelineView').classList.toggle('active', view === 'timeline');

            // 批量选择区域只在时间线视图显示
            const batchSelectAll = document.querySelector('.batch-select-all');
            if (batchSelectAll) {
                batchSelectAll.style.display = view === 'timeline' ? 'flex' : 'none';
            }

            if (view === 'timeline') {
                document.querySelectorAll('.nav-unit').forEach(el => {
                    el.textContent = '';
                });
                document.getElementById('periodLabel').textContent = '时间线视图';
            } else {
                document.querySelectorAll('.nav-unit').forEach(el => {
                    el.textContent = view === 'month' ? '月' : '年';
                });
                document.getElementById('periodLabel').textContent = view === 'month' ? '本月推送' : '本年推送';
            }

            // 退出批量模式
            if (view !== 'timeline') {
                cancelBatchMode();
            }

            render();
        }

        function navigate(delta) {
            if (currentView === 'month') {
                currentDate.setMonth(currentDate.getMonth() + delta);
            } else {
                currentDate.setFullYear(currentDate.getFullYear() + delta);
            }
            render();
        }

        function render() {
            if (currentView === 'month') {
                renderMonthView();
            } else if (currentView === 'year') {
                renderYearView();
            } else if (currentView === 'timeline') {
                renderTimelineView();
            }
            updateStats();
            updateTrashCount();
        }

        function renderMonthView() {
            const year = currentDate.getFullYear();
            const month = currentDate.getMonth();

            document.getElementById('periodTitle').textContent = `${year}年 ${month + 1}月`;

            const firstDay = new Date(year, month, 1);
            const lastDay = new Date(year, month + 1, 0);
            const daysInMonth = lastDay.getDate();

            let startDayOfWeek = firstDay.getDay();
            startDayOfWeek = startDayOfWeek === 0 ? 6 : startDayOfWeek - 1;

            const prevMonthLastDay = new Date(year, month, 0).getDate();
            const grid = document.getElementById('monthGrid');
            grid.innerHTML = '';

            // 获取包含重复事件的所有事件
            const allEvents = getAllEventsWithRepeats(currentDate);

            // 上月
            for (let i = startDayOfWeek - 1; i >= 0; i--) {
                const day = prevMonthLastDay - i;
                grid.appendChild(createMonthDay(day, true));
            }

            // 当月
            const today = new Date();
            for (let day = 1; day <= daysInMonth; day++) {
                const dateStr = formatDate(new Date(year, month, day));
                const isToday = today.getFullYear() === year && today.getMonth() === month && today.getDate() === day;
                const dayEvents = allEvents.filter(e => e.date === dateStr);

                const dayEl = createMonthDay(day, false, isToday, dayEvents);
                // 使用闭包捕获当前的 dateStr，每次点击时重新计算 dayEvents
                dayEl.onclick = () => {
                    const currentDayEvents = allEvents.filter(e => e.date === dateStr);
                    openDayModal(year, month, day, currentDayEvents);
                };
                grid.appendChild(dayEl);
            }

            // 下月
            const remainingCells = 42 - (startDayOfWeek + daysInMonth);
            for (let day = 1; day <= remainingCells; day++) {
                grid.appendChild(createMonthDay(day, true));
            }
        }

        function createMonthDay(day, isOtherMonth, isToday = false, dayEvents = []) {
            const div = document.createElement('div');
            div.className = 'calendar-day';

            // 保存这些值到 dataset 以便拖拽时使用
            div.dataset.day = day;
            div.dataset.isOtherMonth = isOtherMonth;
            div.dataset.isToday = isToday;

            if (isOtherMonth) div.classList.add('other-month');
            if (isToday) div.classList.add('today');
            if (dayEvents.length > 0) div.classList.add('has-event');

            const date = new Date(currentDate.getFullYear(), currentDate.getMonth(), day);
            const dateStr = formatDate(date);
            const dayOfWeek = date.getDay();
            if (dayOfWeek === 0 || dayOfWeek === 6) div.classList.add('weekend');

            let html = `<div class="day-number">${day}</div>`;

            if (dayEvents.length > 0) {
                html += '<div class="day-events">';

                // 先显示标签色点
                const tagsHtml = dayEvents.slice(0, 5).map(evt => {
                    if (!evt.tag) return '';
                    const tag = PREDEFINED_TAGS.find(t => t.name === evt.tag);
                    const color = tag ? tag.color : '#999999';
                    return `<span class="day-event-tag" style="background: ${color}"></span>`;
                }).join('');

                if (tagsHtml) {
                    html += `<div class="day-event-tags">${tagsHtml}</div>`;
                }

                // 动态计算能显示多少个事件（根据屏幕高度）
                const windowHeight = window.innerHeight;
                let maxEvents = 2;
                if (windowHeight > 900) maxEvents = 4;
                else if (windowHeight > 700) maxEvents = 3;

                const displayEvents = dayEvents.slice(0, maxEvents);
                const maxLength = getMaxTitleLength();

                displayEvents.forEach(evt => {
                    let displayTitle = evt.title;
                    if (displayTitle.length > maxLength) {
                        displayTitle = displayTitle.substring(0, maxLength) + '...';
                    }
                    const statusClass = evt.status ? `status-${evt.status}` : 'status-pending';
                    html += `<div class="day-event-item ${statusClass}" title="${escapeHtml(evt.title)} [${getStatusLabel(evt.status)}]">${escapeHtml(displayTitle)}</div>`;
                });

                if (dayEvents.length > maxEvents) {
                    html += `<div class="event-more">+${dayEvents.length - maxEvents}</div>`;
                }
                html += '</div>';
            }

            div.innerHTML = html;

            // 跨日拖拽支持
            div.addEventListener('dragover', (e) => {
                e.preventDefault();
                if (draggedEventData && draggedEventData.date !== dateStr) {
                    div.classList.add('drag-over');
                }
            });

            div.addEventListener('dragleave', () => {
                div.classList.remove('drag-over');
            });

            div.addEventListener('drop', (e) => {
                e.preventDefault();
                div.classList.remove('drag-over');

                if (draggedEventData && draggedEventData.date !== dateStr) {
                    // 更新事件日期
                    const eventIndex = events.findIndex(e =>
                        e.date === draggedEventData.date &&
                        e.title === draggedEventData.title
                    );

                    if (eventIndex !== -1) {
                        // 保存原日期
                        const originalDate = draggedEventData.date;

                        // 更新日期
                        events[eventIndex].date = dateStr;
                        saveEvents();

                        // 重新渲染整个月视图（最简单可靠的方法）
                        refreshMonthView();

                        // 如果弹窗打开的是原日期，更新显示
                        if (selectedDate === originalDate) {
                            const dayEvents = events.filter(e => e.date === selectedDate);
                            if (dayEvents.length === 0) {
                                closeModal();
                            } else {
                                renderModalContent(dayEvents);
                            }
                        }
                    }
                    draggedEventData = null;
                    draggedIndex = null;
                }
            });

            return div;
        }

        // 简化：直接重新渲染整个月视图
        function refreshMonthView() {
            if (currentView === 'month') {
                renderMonthView();
            }
        }

        function renderYearView() {
            const year = currentDate.getFullYear();
            document.getElementById('periodTitle').textContent = `${year}年`;

            const grid = document.getElementById('yearGrid');
            grid.innerHTML = '';

            const today = new Date();

            for (let month = 0; month < 12; month++) {
                const monthCard = document.createElement('div');
                monthCard.className = 'year-month-card';

                const isCurrentMonth = today.getFullYear() === year && today.getMonth() === month;
                if (isCurrentMonth) monthCard.classList.add('current-month');

                monthCard.innerHTML = `<div class="year-month-title">${month + 1}月</div>`;

                const miniCalendar = document.createElement('div');
                miniCalendar.className = 'year-mini-calendar';

                const weekdays = ['一', '二', '三', '四', '五', '六', '日'];
                weekdays.forEach(d => {
                    miniCalendar.innerHTML += `<div class="year-mini-weekday">${d}</div>`;
                });

                const firstDay = new Date(year, month, 1);
                const lastDay = new Date(year, month + 1, 0);
                const daysInMonth = lastDay.getDate();

                let startDayOfWeek = firstDay.getDay();
                startDayOfWeek = startDayOfWeek === 0 ? 6 : startDayOfWeek - 1;

                for (let i = 0; i < startDayOfWeek; i++) {
                    miniCalendar.innerHTML += '<div class="year-mini-day"></div>';
                }

                for (let day = 1; day <= daysInMonth; day++) {
                    const dateStr = formatDate(new Date(year, month, day));
                    const isToday = today.getFullYear() === year && today.getMonth() === month && today.getDate() === day;
                    const dayEvents = events.filter(e => e.date === dateStr);

                    const dayEl = document.createElement('div');
                    dayEl.className = 'year-mini-day';
                    dayEl.textContent = day;

                    if (isToday) dayEl.classList.add('today');
                    if (dayEvents.length > 0) {
                        dayEl.classList.add('has-event');
                        if (dayEvents.length >= 3) dayEl.classList.add('event-count-3');
                        else if (dayEvents.length === 2) dayEl.classList.add('event-count-2');
                    }

                    dayEl.onclick = (e) => {
                        e.stopPropagation();
                        openDayModal(year, month, day, dayEvents);
                    };

                    miniCalendar.appendChild(dayEl);
                }

                monthCard.appendChild(miniCalendar);
                monthCard.onclick = () => {
                    currentDate = new Date(year, month, 1);
                    switchView('month');
                };

                grid.appendChild(monthCard);
            }
        }

        function goToToday() {
            currentDate = new Date();
            render();
        }

        function openDayModal(year, month, day, dayEvents) {
            selectedDate = formatDate(new Date(year, month, day));
            editingIndex = null;
            document.getElementById('modalTitle').textContent = `${year}年${month + 1}月${day}日`;

            renderModalContent(dayEvents);
            document.getElementById('dayModal').classList.add('active');
        }

        function renderModalContent(dayEvents) {
            let content = '';

            if (dayEvents.length > 0) {
                content += '<div class="event-list" id="eventList">';
                dayEvents.forEach((evt, idx) => {
                    const globalIdx = events.indexOf(evt);
                    const isEditing = editingIndex === globalIdx;
                    const tag = evt.tag ? PREDEFINED_TAGS.find(t => t.name === evt.tag) || { name: evt.tag, color: '#999999' } : null;

                    if (isEditing) {
                        content += renderEditForm(globalIdx, evt);
                    } else {
                        content += renderEventItem(globalIdx, evt, tag, true);
                    }
                });
                content += '</div>';
            } else {
                content += '<div class="empty-state">暂无推送计划</div>';
            }

            if (editingIndex === null) {
                content += renderAddForm();
            }

            document.getElementById('modalContent').innerHTML = content;

            // 绑定拖拽事件
            bindDragEvents(dayEvents);
        }

        function renderEventItem(globalIdx, evt, tag, isDraggable) {
            const tagHtml = tag ? `
                <div class="event-tag">
                    <span class="tag-dot" style="background: ${tag.color}"></span>
                    ${tag.name}
                </div>
            ` : '';

            const statusBadgeHtml = evt.status ? `
                <span class="event-status-badge status-${evt.status}">${getStatusLabel(evt.status)}</span>
            ` : '<span class="event-status-badge status-pending">未推送</span>';

            const noteHtml = evt.note ? `
                <div class="event-note">${escapeHtml(evt.note)}</div>
            ` : '';

            const dragHandle = `<span class="drag-handle" draggable="true" data-index="${globalIdx}">⋮⋮</span>`;

            return `
                <div class="event-item draggable status-${evt.status || 'pending'}" data-index="${globalIdx}" draggable="true" data-date="${evt.date}" data-title="${escapeHtml(evt.title)}">
                    ${tagHtml}
                    <div class="event-title">${escapeHtml(evt.title)}${statusBadgeHtml}</div>
                    ${evt.time ? `<div class="event-meta">${evt.time}</div>` : ''}
                    ${evt.description ? `<div class="event-desc">${escapeHtml(evt.description)}</div>` : ''}
                    ${noteHtml}
                    <div class="event-actions">
                        ${dragHandle}
                        <button class="btn-secondary" onclick="startEdit(${globalIdx})">编辑</button>
                        <button class="btn-delete" onclick="deleteEvent(${globalIdx})">删除</button>
                    </div>
                </div>
            `;
        }

        function renderEditForm(globalIdx, evt) {
            const tagSelectorHtml = renderTagSelector(`editTag-${globalIdx}`, evt.tag);
            const repeatSelectorHtml = renderRepeatSelector(`editRepeat-${globalIdx}`, evt.repeat);
            const statusSelectorHtml = renderStatusSelector(`editStatus-${globalIdx}`, evt.status);

            return `
                <div class="event-item editing">
                    <div class="form-group">
                        <label>推送标题</label>
                        <input type="text" id="editTitle-${globalIdx}" value="${escapeHtml(evt.title)}">
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label>日期</label>
                            <input type="date" id="editDate-${globalIdx}" value="${evt.date}">
                        </div>
                        <div class="form-group">
                            <label>时间</label>
                            <input type="time" id="editTime-${globalIdx}" value="${evt.time || ''}">
                        </div>
                    </div>
                    <div class="form-group">
                        <label>标签</label>
                        ${tagSelectorHtml}
                    </div>
                    <div class="form-group">
                        <label>推送状态</label>
                        ${statusSelectorHtml}
                    </div>
                    <div class="form-group">
                        <label>重复设置</label>
                        ${repeatSelectorHtml}
                    </div>
                    <div class="form-group">
                        <label>描述</label>
                        <textarea id="editDesc-${globalIdx}">${escapeHtml(evt.description || '')}</textarea>
                    </div>
                    <div class="form-group">
                        <label>备注</label>
                        <textarea id="editNote-${globalIdx}" class="note-textarea" placeholder="添加备注信息...">${escapeHtml(evt.note || '')}</textarea>
                    </div>
                    <div class="event-actions">
                        <button class="btn-primary" onclick="saveEdit(${globalIdx})">保存</button>
                        <button class="btn-secondary" onclick="cancelEdit()">取消</button>
                    </div>
                </div>
            `;
        }

        function renderAddForm() {
            const tagSelectorHtml = renderTagSelector('newTag', null);
            const repeatSelectorHtml = renderRepeatSelector('newRepeat', null);
            const statusSelectorHtml = renderStatusSelector('newStatus', 'pending');

            return `
                <div class="form-section">
                    <h4>添加新推送</h4>
                    <div class="form-row">
                        <div class="form-group">
                            <label>推送标题</label>
                            <input type="text" id="newTitle" placeholder="输入标题">
                        </div>
                        <div class="form-group">
                            <label>时间</label>
                            <input type="time" id="newTime" value="20:00">
                        </div>
                    </div>
                    <div class="form-group">
                        <label>标签</label>
                        ${tagSelectorHtml}
                    </div>
                    <div class="form-group">
                        <label>推送状态</label>
                        ${statusSelectorHtml}
                    </div>
                    <div class="form-group">
                        <label>重复设置</label>
                        ${repeatSelectorHtml}
                    </div>
                    <div class="form-group">
                        <label>描述（可选）</label>
                        <textarea id="newDesc" placeholder="输入推送描述"></textarea>
                    </div>
                    <div class="form-group">
                        <label>备注</label>
                        <textarea id="newNote" class="note-textarea" placeholder="添加备注信息..."></textarea>
                    </div>
                    <div class="modal-footer">
                        <button class="btn-primary" onclick="addEvent()">添加推送</button>
                    </div>
                </div>
            `;
        }

        // 渲染重复选择器
        function renderRepeatSelector(id, currentRepeat) {
            const types = [
                { value: '', label: '不重复' },
                { value: 'weekly', label: '每周' },
                { value: 'biweekly', label: '每两周' },
                { value: 'monthly', label: '每月' },
                { value: 'yearly', label: '每年' }
            ];

            const currentType = currentRepeat ? currentRepeat.type : '';
            const currentEndType = currentRepeat ? currentRepeat.endType : 'never';
            const currentEndValue = currentRepeat ? currentRepeat.endValue : '';

            let html = `<div class="repeat-options" id="${id}">`;

            // 重复类型
            html += `<div class="repeat-type-selector">`;
            types.forEach(type => {
                const active = type.value === currentType ? 'active' : '';
                html += `<button type="button" class="repeat-option ${active}" data-type="${type.value}" onclick="selectRepeatType('${id}', '${type.value}')">${type.label}</button>`;
            });
            html += `</div>`;

            // 结束条件（仅当选择重复时显示）
            if (currentType) {
                html += `
                    <div class="repeat-end-options">
                        <label style="font-size: 12px; color: #6E6E6E;">结束：</label>
                        <select id="${id}_endType" onchange="onRepeatEndChange('${id}')" style="padding: 6px; border: 1px solid #E0E0E0;">
                            <option value="never" ${currentEndType === 'never' ? 'selected' : ''}>永不</option>
                            <option value="count" ${currentEndType === 'count' ? 'selected' : ''}>次数</option>
                            <option value="date" ${currentEndType === 'date' ? 'selected' : ''}>日期</option>
                        </select>
                        <span id="${id}_endValueContainer">
                            ${renderRepeatEndValueInput(id, currentEndType, currentEndValue)}
                        </span>
                    </div>
                `;
            }

            html += `</div>`;
            return html;
        }

        function renderRepeatEndValueInput(id, endType, endValue) {
            if (endType === 'count') {
                return `<input type="number" id="${id}_endValue" value="${endValue || '10'}" min="1" style="width: 60px; padding: 6px; border: 1px solid #E0E0E0;"> 次`;
            } else if (endType === 'date') {
                return `<input type="date" id="${id}_endValue" value="${endValue || ''}" style="padding: 6px; border: 1px solid #E0E0E0;">`;
            }
            return '';
        }

        function selectRepeatType(id, type) {
            const container = document.getElementById(id);
            const buttons = container.querySelectorAll('.repeat-option');
            buttons.forEach(btn => {
                btn.classList.toggle('active', btn.dataset.type === type);
            });

            // 重新渲染结束条件
            const endOptions = container.querySelector('.repeat-end-options');
            if (type) {
                if (!endOptions) {
                    // 添加结束条件选项
                    const div = document.createElement('div');
                    div.className = 'repeat-end-options';
                    div.innerHTML = `
                        <label style="font-size: 12px; color: #6E6E6E;">结束：</label>
                        <select id="${id}_endType" onchange="onRepeatEndChange('${id}')" style="padding: 6px; border: 1px solid #E0E0E0;">
                            <option value="never">永不</option>
                            <option value="count">次数</option>
                            <option value="date">日期</option>
                        </select>
                        <span id="${id}_endValueContainer"></span>
                    `;
                    container.appendChild(div);
                }
            } else {
                // 移除结束条件
                if (endOptions) endOptions.remove();
            }
        }

        function onRepeatEndChange(id) {
            const endType = document.getElementById(`${id}_endType`).value;
            const container = document.getElementById(`${id}_endValueContainer`);
            container.innerHTML = renderRepeatEndValueInput(id, endType, '');
        }

        function getRepeatConfig(id) {
            const container = document.getElementById(id);
            const activeBtn = container.querySelector('.repeat-option.active');
            const type = activeBtn ? activeBtn.dataset.type : '';

            if (!type) return null;

            const endType = document.getElementById(`${id}_endType`)?.value || 'never';
            const endValueInput = document.getElementById(`${id}_endValue`);
            const endValue = endValueInput ? endValueInput.value : '';

            return { type, endType, endValue };
        }

        // 渲染状态选择器
        function renderStatusSelector(id, selectedStatus) {
            const statuses = [
                { value: 'pending', label: '未推送', class: 'status-pending' },
                { value: 'published', label: '已推送', class: 'status-published' },
                { value: 'deleted', label: '已删除', class: 'status-deleted' }
            ];

            let html = `<div class="status-selector" id="${id}">`;
            statuses.forEach(status => {
                const isActive = status.value === (selectedStatus || 'pending') ? 'active' : '';
                html += `
                    <button type="button" class="status-option ${status.class} ${isActive}"
                            data-status="${status.value}" onclick="selectStatus('${id}', '${status.value}')">
                        ${status.label}
                    </button>
                `;
            });
            html += '</div>';
            return html;
        }

        function selectStatus(id, status) {
            const container = document.getElementById(id);
            container.querySelectorAll('.status-option').forEach(opt => {
                opt.classList.toggle('active', opt.dataset.status === status);
            });
        }

        function getSelectedStatus(id) {
            const container = document.getElementById(id);
            const active = container.querySelector('.status-option.active');
            return active ? active.dataset.status : 'pending';
        }

        function getStatusLabel(status) {
            const labels = {
                'pending': '未推送',
                'published': '已推送',
                'deleted': '已删除'
            };
            return labels[status] || '未推送';
        }

        function renderTagSelector(id, selectedTag) {
            let html = `<div class="tag-selector" id="${id}">`;
            PREDEFINED_TAGS.forEach(tag => {
                const isActive = tag.name === selectedTag ? 'active' : '';
                html += `
                    <div class="tag-option ${isActive}" data-tag="${tag.name}" onclick="selectTag('${id}', '${tag.name}')">
                        <span class="tag-dot" style="background: ${tag.color}"></span>
                        ${tag.name}
                    </div>
                `;
            });
            html += '</div>';
            return html;
        }

        function selectTag(selectorId, tagName) {
            const selector = document.getElementById(selectorId);
            selector.querySelectorAll('.tag-option').forEach(opt => {
                opt.classList.toggle('active', opt.dataset.tag === tagName);
            });
        }

        function getSelectedTag(selectorId) {
            const selector = document.getElementById(selectorId);
            const active = selector.querySelector('.tag-option.active');
            return active ? active.dataset.tag : null;
        }

        function startEdit(index) {
            editingIndex = index;
            const dayEvents = events.filter(e => e.date === selectedDate);
            renderModalContent(dayEvents);
        }

        function cancelEdit() {
            editingIndex = null;
            const dayEvents = events.filter(e => e.date === selectedDate);
            renderModalContent(dayEvents);
        }

        function saveEdit(index) {
            const title = document.getElementById(`editTitle-${index}`).value.trim();
            const date = document.getElementById(`editDate-${index}`).value;
            const time = document.getElementById(`editTime-${index}`).value;
            const description = document.getElementById(`editDesc-${index}`).value.trim();
            const tag = getSelectedTag(`editTag-${index}`);
            const repeat = getRepeatConfig(`editRepeat-${index}`);
            const status = getSelectedStatus(`editStatus-${index}`);
            const note = document.getElementById(`editNote-${index}`)?.value.trim() || '';

            if (!title) {
                alert('请输入推送标题');
                return;
            }
            if (!date) {
                alert('请选择日期');
                return;
            }

            events[index] = { date, title, time, description, tag, repeat, status, note };
            saveEvents();

            selectedDate = date;
            editingIndex = null;

            render();

            const newDate = new Date(selectedDate);
            const allEvents = getAllEventsWithRepeats(currentDate);
            const dayEvents = allEvents.filter(e => e.date === selectedDate);
            renderModalContent(dayEvents);
        }

        function closeModal(event) {
            // 如果没有事件对象，直接关闭（用于按钮调用）
            if (!event) {
                document.getElementById('dayModal').classList.remove('active');
                editingIndex = null;
                return;
            }
            // 检测点击位置是否在弹窗内容区外
            const modal = document.querySelector('#dayModal .modal');
            if (modal && !modal.contains(event.target)) {
                document.getElementById('dayModal').classList.remove('active');
                editingIndex = null;
            }
        }

        function addEvent() {
            const title = document.getElementById('newTitle').value.trim();
            const time = document.getElementById('newTime').value;
            const description = document.getElementById('newDesc').value.trim();
            const tag = getSelectedTag('newTag');
            const repeat = getRepeatConfig('newRepeat');
            const status = getSelectedStatus('newStatus');
            const note = document.getElementById('newNote')?.value.trim() || '';

            if (!title) {
                alert('请输入推送标题');
                return;
            }

            events.push({ date: selectedDate, title, time, description, tag, repeat, status, note });
            saveEvents();
            render();

            const date = new Date(selectedDate);
            const allEvents = getAllEventsWithRepeats(currentDate);
            const dayEvents = allEvents.filter(e => e.date === selectedDate);
            renderModalContent(dayEvents);
        }

        function deleteEvent(index) {
            if (confirm('确定删除这条推送？（可在回收站恢复）')) {
                moveToTrash(index);
                render();
                closeModal();
            }
        }

        // ==================== 时间线视图功能 ====================
        function renderTimelineView() {
            const container = document.getElementById('timelineList');

            // 获取所有事件（包括重复事件）
            const allEvents = getAllEventsWithRepeats(currentDate);

            // 按日期分组
            const groupedEvents = {};
            allEvents.forEach((evt, index) => {
                if (!groupedEvents[evt.date]) {
                    groupedEvents[evt.date] = [];
                }
                // 找到原始事件索引
                const originalIndex = events.findIndex(e =>
                    e.date === evt.originalDate && e.title === evt.title
                );
                groupedEvents[evt.date].push({ ...evt, originalIndex });
            });

            // 按日期排序
            const sortedDates = Object.keys(groupedEvents).sort();

            if (sortedDates.length === 0) {
                container.innerHTML = '<div class="timeline-empty">暂无推送计划</div>';
                return;
            }

            let html = '';
            sortedDates.forEach(date => {
                const dateObj = new Date(date);
                const dateStr = `${dateObj.getFullYear()}年${dateObj.getMonth() + 1}月${dateObj.getDate()}日`;
                const dayEvents = groupedEvents[date];

                html += `
                    <div class="timeline-date-group">
                        <div class="timeline-date-header">${dateStr}</div>
                `;

                dayEvents.forEach(evt => {
                    const tag = evt.tag ? PREDEFINED_TAGS.find(t => t.name === evt.tag) : null;
                    const tagHtml = tag ? `<span class="timeline-item-tag" style="background: ${tag.color}20; color: ${tag.color}; border: 1px solid ${tag.color};">${tag.name}</span>` : '';
                    const statusHtml = evt.status ? `<span class="event-status-badge status-${evt.status}">${getStatusLabel(evt.status)}</span>` : '';
                    const checkboxHtml = batchMode ? `<div class="timeline-item-checkbox"><input type="checkbox" ${selectedItems.has(evt.originalIndex) ? 'checked' : ''} onchange="toggleBatchSelect(${evt.originalIndex})"></div>` : '';

                    html += `
                        <div class="timeline-item" onclick="${batchMode ? '' : `openDayModal(${dateObj.getFullYear()}, ${dateObj.getMonth()}, ${dateObj.getDate()}, events.filter(e => e.date === '${date}'))`}">
                            ${checkboxHtml}
                            <div class="timeline-item-content">
                                <div class="timeline-item-time">${evt.time || '未设置时间'} ${tagHtml} ${statusHtml}</div>
                                <div class="timeline-item-title">${escapeHtml(evt.title)}</div>
                                ${evt.description ? `<div style="font-size: 12px; color: #6E6E6E; margin-top: 4px;">${escapeHtml(evt.description)}</div>` : ''}
                            </div>
                        </div>
                    `;
                });

                html += '</div>';
            });

            container.innerHTML = html;
        }

        // ==================== 批量操作功能 ====================
        function toggleBatchMode() {
            batchMode = !batchMode;
            selectedItems.clear();
            updateBatchToolbar();

            // 更新按钮文本
            const btn = document.getElementById('batchModeBtn');
            if (btn) {
                btn.textContent = batchMode ? '退出批量模式' : '进入批量模式';
            }

            // 全选框状态重置
            const selectAllCheckbox = document.getElementById('selectAllTimeline');
            if (selectAllCheckbox) {
                selectAllCheckbox.checked = false;
            }

            if (currentView === 'timeline') {
                renderTimelineView();
            }
        }

        function toggleBatchSelect(index) {
            if (selectedItems.has(index)) {
                selectedItems.delete(index);
            } else {
                selectedItems.add(index);
            }
            updateBatchToolbar();
        }

        function toggleSelectAll() {
            const checkbox = document.getElementById('selectAllTimeline');
            if (checkbox.checked) {
                // 全选当前视图中的所有事件
                events.forEach((_, index) => selectedItems.add(index));
            } else {
                selectedItems.clear();
            }
            updateBatchToolbar();
            renderTimelineView();
        }

        function updateBatchToolbar() {
            const toolbar = document.getElementById('batchToolbar');
            const count = selectedItems.size;

            if (batchMode && count > 0) {
                toolbar.classList.add('active');
                document.getElementById('batchSelectedCount').textContent = count;
            } else {
                toolbar.classList.remove('active');
            }
        }

        function cancelBatchMode() {
            batchMode = false;
            selectedItems.clear();
            updateBatchToolbar();

            const selectAllCheckbox = document.getElementById('selectAllTimeline');
            if (selectAllCheckbox) {
                selectAllCheckbox.checked = false;
            }

            const btn = document.getElementById('batchModeBtn');
            if (btn) {
                btn.textContent = '进入批量模式';
            }

            if (currentView === 'timeline') {
                renderTimelineView();
            }
        }

        function batchChangeTag() {
            const tagNames = PREDEFINED_TAGS.map(t => t.name).join('/');
            const newTag = prompt(`选择新标签 (${tagNames}):`);
            if (!newTag) return;

            const validTag = PREDEFINED_TAGS.find(t => t.name === newTag);
            if (!validTag) {
                alert('无效的标签名称');
                return;
            }

            selectedItems.forEach(index => {
                if (events[index]) {
                    events[index].tag = newTag;
                }
            });

            saveEvents();
            cancelBatchMode();
            render();
        }

        function batchChangeStatus() {
            const statusOptions = 'pending(未推送)/published(已推送)/deleted(已删除)';
            const newStatus = prompt(`选择新状态 (${statusOptions}):`);
            if (!newStatus) return;

            const validStatuses = ['pending', 'published', 'deleted'];
            if (!validStatuses.includes(newStatus)) {
                alert('无效的状态');
                return;
            }

            selectedItems.forEach(index => {
                if (events[index]) {
                    events[index].status = newStatus;
                }
            });

            saveEvents();
            cancelBatchMode();
            render();
        }

        function batchDelete() {
            if (!confirm(`确定删除选中的 ${selectedItems.size} 条推送？（可在回收站恢复）`)) return;

            // 将选中的事件移到回收站（从后往前删除，避免索引变化）
            const sortedIndices = Array.from(selectedItems).sort((a, b) => b - a);
            sortedIndices.forEach(index => {
                if (events[index]) {
                    trashItems.unshift({
                        ...events[index],
                        deletedAt: new Date().toISOString()
                    });
                    events.splice(index, 1);
                }
            });

            saveEvents();
            saveTrash();
            cancelBatchMode();
            render();
        }

        function bindDragEvents(dayEvents) {
            const eventList = document.getElementById('eventList');
            if (!eventList) return;

            const items = eventList.querySelectorAll('.event-item.draggable');

            items.forEach((item) => {
                item.addEventListener('dragstart', (e) => {
                    draggedIndex = parseInt(item.dataset.index);
                    // 从单独的数据属性获取，避免 JSON 解析问题
                    draggedEventData = {
                        date: item.dataset.date,
                        title: item.dataset.title
                    };
                    item.classList.add('dragging');
                    e.dataTransfer.effectAllowed = 'move';
                    e.dataTransfer.setData('text/plain', draggedIndex);
                });

                item.addEventListener('dragend', () => {
                    item.classList.remove('dragging');
                    draggedIndex = null;
                    // 不清除draggedEventData，因为可能拖到了日历格子上
                    setTimeout(() => {
                        draggedEventData = null;
                    }, 100);
                    items.forEach(i => i.classList.remove('drag-over'));
                });

                item.addEventListener('dragover', (e) => {
                    e.preventDefault();
                    const targetIdx = parseInt(item.dataset.index);
                    if (draggedIndex === null || draggedIndex === targetIdx) return;
                    item.classList.add('drag-over');
                });

                item.addEventListener('dragleave', () => {
                    item.classList.remove('drag-over');
                });

                item.addEventListener('drop', (e) => {
                    e.preventDefault();
                    item.classList.remove('drag-over');

                    const targetIndex = parseInt(item.dataset.index);
                    if (draggedIndex === null || draggedIndex === targetIndex) return;

                    reorderEvents(draggedIndex, targetIndex);
                });
            });
        }

        function reorderEvents(fromIdx, toIdx) {
            const dateEventsIndices = [];
            events.forEach((e, idx) => {
                if (e.date === selectedDate) dateEventsIndices.push(idx);
            });

            const fromLocalIdx = dateEventsIndices.indexOf(fromIdx);
            const toLocalIdx = dateEventsIndices.indexOf(toIdx);

            if (fromLocalIdx === -1 || toLocalIdx === -1) return;

            const fromGlobalIdx = dateEventsIndices[fromLocalIdx];
            const toGlobalIdx = dateEventsIndices[toLocalIdx];

            const [movedEvent] = events.splice(fromGlobalIdx, 1);
            const newToGlobalIdx = fromGlobalIdx < toGlobalIdx ? toGlobalIdx : toGlobalIdx + 1;
            events.splice(newToGlobalIdx, 0, movedEvent);

            saveEvents();
            render();

            const dayEvents = events.filter(e => e.date === selectedDate);
            renderModalContent(dayEvents);
        }

        function saveEvents() {
            localStorage.setItem('wechatEvents', JSON.stringify(events));
        }

        // 覆盖原来的 saveEvents
        const originalSaveEvents = saveEvents;
        saveEvents = function() {
            saveCurrentCalendar();
        };

        function saveTags() {
            localStorage.setItem('calendarTags', JSON.stringify(PREDEFINED_TAGS));
        }

        // ==================== 回收站功能 ====================
        function saveTrash() {
            localStorage.setItem('calendarTrash', JSON.stringify(trashItems));
            updateTrashCount();
        }

        function updateTrashCount() {
            const countEl = document.getElementById('trashCount');
            if (countEl) {
                countEl.textContent = trashItems.length;
                countEl.style.display = trashItems.length > 0 ? 'inline-block' : 'none';
            }
        }

        function moveToTrash(eventIndex) {
            const event = events[eventIndex];
            if (!event) return;

            // 添加到回收站（带删除时间）
            trashItems.unshift({
                ...event,
                deletedAt: new Date().toISOString(),
                originalIndex: eventIndex
            });

            // 从事件中移除
            events.splice(eventIndex, 1);

            saveEvents();
            saveTrash();
            render();
        }

        function restoreFromTrash(trashIndex) {
            const item = trashItems[trashIndex];
            if (!item) return;

            // 恢复事件（删除回收站相关字段）
            const { deletedAt, originalIndex, ...restoredEvent } = item;
            events.push(restoredEvent);

            // 从回收站移除
            trashItems.splice(trashIndex, 1);

            saveEvents();
            saveTrash();
            render();
            renderTrashList();
        }

        function permanentlyDelete(trashIndex) {
            if (!confirm('确定永久删除这条推送？此操作不可恢复。')) return;

            trashItems.splice(trashIndex, 1);
            saveTrash();
            renderTrashList();
        }

        function emptyTrash() {
            if (!confirm('确定清空回收站？共 ' + trashItems.length + ' 条推送将被永久删除。')) return;

            trashItems = [];
            saveTrash();
            renderTrashList();
        }

        function openTrashPanel() {
            renderTrashList();
            document.getElementById('trashModal').classList.add('active');
        }

        function closeTrashModal(event) {
            if (!event) {
                document.getElementById('trashModal').classList.remove('active');
                return;
            }
            const modal = document.querySelector('#trashModal .modal');
            if (modal && !modal.contains(event.target)) {
                document.getElementById('trashModal').classList.remove('active');
            }
        }

        function renderTrashList() {
            const container = document.getElementById('trashList');
            const emptyState = document.getElementById('trashEmptyState');

            if (trashItems.length === 0) {
                container.innerHTML = '';
                emptyState.style.display = 'block';
                return;
            }

            emptyState.style.display = 'none';

            let html = '';
            if (trashItems.length > 0) {
                html += `
                    <div style="margin-bottom: 16px; text-align: right;">
                        <button class="btn-delete" onclick="emptyTrash()">清空回收站</button>
                    </div>
                `;
            }

            trashItems.forEach((item, index) => {
                const deletedDate = new Date(item.deletedAt);
                const deletedStr = `${deletedDate.getMonth() + 1}月${deletedDate.getDate()}日 ${String(deletedDate.getHours()).padStart(2, '0')}:${String(deletedDate.getMinutes()).padStart(2, '0')}`;

                html += `
                    <div class="trash-item">
                        <div class="trash-item-deleted">删除于 ${deletedStr}</div>
                        <div class="trash-item-title">${escapeHtml(item.title)}</div>
                        ${item.date ? `<div style="font-size: 12px; color: #999; margin-top: 4px;">原定日期: ${item.date}</div>` : ''}
                        <div class="trash-item-actions">
                            <button class="btn-secondary" onclick="restoreFromTrash(${index})">恢复</button>
                            <button class="btn-delete" onclick="permanentlyDelete(${index})">彻底删除</button>
                        </div>
                    </div>
                `;
            });

            container.innerHTML = html;
        }

        // ==================== 标签管理 ====================
        function openTagManager() {
            renderTagManager();
            document.getElementById('tagModal').classList.add('active');
        }

        function closeTagModal(event) {
            if (!event) {
                document.getElementById('tagModal').classList.remove('active');
                return;
            }
            const modal = document.querySelector('#tagModal .modal');
            if (modal && !modal.contains(event.target)) {
                document.getElementById('tagModal').classList.remove('active');
            }
        }

        function renderTagManager() {
            const container = document.getElementById('tagModalContent');

            let html = '<div class="tag-manager-list">';

            PREDEFINED_TAGS.forEach((tag, index) => {
                html += `
                    <div class="tag-manager-item" data-index="${index}">
                        <input type="color" class="tag-color-picker" value="${tag.color}"
                               onchange="updateTagColor(${index}, this.value)">
                        <input type="text" class="tag-name-input" value="${escapeHtml(tag.name)}"
                               onchange="updateTagName(${index}, this.value)">
                        <button class="btn-delete" onclick="deleteTag(${index})">删除</button>
                    </div>
                `;
            });

            html += '</div>';

            html += `
                <div class="tag-add-form">
                    <input type="color" id="newTagColor" class="tag-color-picker" value="#${Math.floor(Math.random()*16777215).toString(16).padStart(6, '0')}">
                    <input type="text" id="newTagName" class="tag-name-input" placeholder="新标签名称">
                    <button class="btn-primary" onclick="addTag()">添加</button>
                </div>
            `;

            container.innerHTML = html;
        }

        function updateTagColor(index, color) {
            PREDEFINED_TAGS[index].color = color;
            saveTags();
            render();
        }

        function updateTagName(index, name) {
            const oldName = PREDEFINED_TAGS[index].name;
            PREDEFINED_TAGS[index].name = name.trim() || oldName;
            saveTags();
            render();
        }

        function deleteTag(index) {
            if (PREDEFINED_TAGS.length <= 1) {
                alert('至少需要保留一个标签');
                return;
            }
            if (confirm('确定删除这个标签？已使用该标签的推送将变为无标签。')) {
                const deletedTag = PREDEFINED_TAGS[index];
                PREDEFINED_TAGS.splice(index, 1);
                // 清除已删除标签的引用
                events.forEach(e => {
                    if (e.tag === deletedTag.name) {
                        delete e.tag;
                    }
                });
                saveTags();
                saveEvents();
                renderTagManager();
                render();
            }
        }

        function addTag() {
            const nameInput = document.getElementById('newTagName');
            const colorInput = document.getElementById('newTagColor');
            const name = nameInput.value.trim();

            if (!name) {
                alert('请输入标签名称');
                return;
            }

            if (PREDEFINED_TAGS.some(t => t.name === name)) {
                alert('标签名称已存在');
                return;
            }

            PREDEFINED_TAGS.push({ name, color: colorInput.value });
            saveTags();
            renderTagManager();
            render();

            nameInput.value = '';
        }

        function updateStats() {
            const year = currentDate.getFullYear();
            const month = currentDate.getMonth();

            let periodEvents;
            if (currentView === 'month') {
                periodEvents = events.filter(e => {
                    const d = new Date(e.date);
                    return d.getFullYear() === year && d.getMonth() === month;
                });
            } else {
                periodEvents = events.filter(e => {
                    const d = new Date(e.date);
                    return d.getFullYear() === year;
                });
            }

            document.getElementById('periodCount').textContent = periodEvents.length;
            document.getElementById('totalCount').textContent = events.length;
        }

        function handleFileImport(event) {
            const file = event.target.files[0];
            if (!file) return;

            const reader = new FileReader();
            reader.onload = (e) => {
                try {
                    const content = e.target.result;
                    let newEvents = [];

                    if (file.name.endsWith('.json')) {
                        newEvents = JSON.parse(content);
                    } else {
                        newEvents = parseCSV(content);
                    }

                    if (Array.isArray(newEvents) && newEvents.length > 0) {
                        events = [...events, ...newEvents];
                        saveEvents();
                        render();
                        alert(`成功导入 ${newEvents.length} 条推送`);
                    }
                } catch (err) {
                    alert('文件解析失败');
                }
            };
            reader.readAsText(file);
            event.target.value = '';
        }

        function parseCSV(content) {
            const lines = content.trim().split('\n');
            if (lines.length < 2) return [];

            const headers = lines[0].split(',').map(h => h.trim());
            const result = [];

            for (let i = 1; i < lines.length; i++) {
                const values = lines[i].split(',').map(v => v.trim());
                const obj = {};
                headers.forEach((h, idx) => obj[h] = values[idx] || '');
                if (obj.date && obj.title) result.push(obj);
            }
            return result;
        }

        function exportData() {
            const blob = new Blob([JSON.stringify(events, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `calendar-${formatDate(new Date())}.json`;
            a.click();
            URL.revokeObjectURL(url);
        }

        function toggleHelp() {
            document.getElementById('helpPanel').classList.toggle('active');
        }

        // ==================== 搜索功能 ====================
        let searchResults = [];
        let hideDropdownTimer = null;

        function handleSearch(keyword) {
            const clearBtn = document.getElementById('searchClear');
            const dropdown = document.getElementById('searchDropdown');

            if (!keyword.trim()) {
                clearBtn.classList.remove('visible');
                dropdown.classList.remove('active');
                return;
            }

            clearBtn.classList.add('visible');

            // 搜索逻辑：匹配标题和描述
            const lowerKeyword = keyword.toLowerCase();
            searchResults = events
                .map((evt, index) => ({ ...evt, index }))
                .filter(evt =>
                    evt.title.toLowerCase().includes(lowerKeyword) ||
                    (evt.description && evt.description.toLowerCase().includes(lowerKeyword))
                )
                .sort((a, b) => new Date(b.date) - new Date(a.date)); // 按日期倒序

            renderSearchResults(keyword);
            dropdown.classList.add('active');
        }

        function renderSearchResults(keyword) {
            const dropdown = document.getElementById('searchDropdown');

            if (searchResults.length === 0) {
                dropdown.innerHTML = '<div class="search-empty">未找到相关内容</div>';
                return;
            }

            const lowerKeyword = keyword.toLowerCase();
            let html = '';

            searchResults.slice(0, 10).forEach(evt => {
                // 高亮匹配的关键词
                const highlightTitle = highlightKeyword(evt.title, keyword);
                const dateStr = formatDateChinese(evt.date);

                html += `
                    <div class="search-result-item" onclick="goToSearchResult('${evt.date}', ${evt.index})">
                        <div class="search-result-date">${dateStr}${evt.time ? ' ' + evt.time : ''}</div>
                        <div class="search-result-title">${highlightTitle}</div>
                    </div>
                `;
            });

            if (searchResults.length > 10) {
                html += `<div class="search-empty">还有 ${searchResults.length - 10} 条结果...</div>`;
            }

            dropdown.innerHTML = html;
        }

        function highlightKeyword(text, keyword) {
            if (!keyword) return escapeHtml(text);
            const regex = new RegExp(`(${escapeRegExp(keyword)})`, 'gi');
            return escapeHtml(text).replace(regex, '<span class="search-result-highlight">$1</span>');
        }

        function escapeRegExp(string) {
            return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        }

        function formatDateChinese(dateStr) {
            const date = new Date(dateStr);
            return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`;
        }

        function applyQueryPrefill(prefill) {
            if (!prefill || typeof prefill !== 'object') {
                return;
            }

            const title = (prefill.title || '').trim();
            const draft = (prefill.draft || '').trim();
            const source = (prefill.source || '').trim();
            const dateStr = (prefill.date || '').trim();
            const time = (prefill.time || '').trim();
            const extraNote = (prefill.note || '').trim();

            if (!title && !draft && !source && !dateStr && !time && !extraNote) {
                return;
            }

            const targetDate = dateStr || formatDate(new Date());
            const [year, month, day] = targetDate.split('-').map(Number);
            if (!year || !month || !day) {
                return;
            }

            currentDate = new Date(year, month - 1, 1);
            if (currentView !== 'month') {
                switchView('month');
            } else {
                render();
            }

            const dayEvents = events.filter(e => e.date === targetDate);
            openDayModal(year, month - 1, day, dayEvents);

            const titleInput = document.getElementById('newTitle');
            const timeInput = document.getElementById('newTime');
            const descInput = document.getElementById('newDesc');
            const noteInput = document.getElementById('newNote');

            if (titleInput && title) {
                titleInput.value = title;
            }
            if (timeInput && time) {
                timeInput.value = time;
            }
            if (descInput && draft) {
                descInput.value = draft;
            }
            if (noteInput) {
                const noteParts = [];
                if (source) {
                    noteParts.push(`来源：${source}`);
                }
                if (extraNote) {
                    noteParts.push(extraNote);
                }
                noteInput.value = noteParts.join('\n');
            }
        }

        function goToSearchResult(dateStr, index) {
            const date = new Date(dateStr);
            selectedDate = dateStr;

            // 切换到月视图并跳转到对应月份
            if (currentView !== 'month') {
                switchView('month');
            }

            currentDate = new Date(date.getFullYear(), date.getMonth(), 1);
            render();

            // 打开该日期的弹窗
            const dayEvents = events.filter(e => e.date === dateStr);
            openDayModal(date.getFullYear(), date.getMonth(), date.getDate(), dayEvents);

            // 清空搜索
            clearSearch();
        }

        function clearSearch() {
            const input = document.getElementById('searchInput');
            const clearBtn = document.getElementById('searchClear');
            const dropdown = document.getElementById('searchDropdown');

            input.value = '';
            clearBtn.classList.remove('visible');
            dropdown.classList.remove('active');
            searchResults = [];
        }

        function showSearchDropdown() {
            const input = document.getElementById('searchInput');
            if (input.value.trim() && searchResults.length > 0) {
                document.getElementById('searchDropdown').classList.add('active');
            }
        }

        function hideSearchDropdownDelayed() {
            // 延迟隐藏，让点击事件能触发
            hideDropdownTimer = setTimeout(() => {
                document.getElementById('searchDropdown').classList.remove('active');
            }, 200);
        }

        // 点击下拉框时阻止隐藏
        document.getElementById('searchDropdown')?.addEventListener('mousedown', (e) => {
            e.preventDefault();
            if (hideDropdownTimer) {
                clearTimeout(hideDropdownTimer);
            }
        });

        function formatDate(date) {
            return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
