/**
 * 全局日期范围选择器
 */
const DateRange = {
    _start: null,
    _end: null,
    _callbacks: [],

    init() {
        const saved = localStorage.getItem('dateRange');
        if (saved) {
            try {
                const { start, end } = JSON.parse(saved);
                this._start = start;
                this._end = end;
            } catch (e) {}
        }
        this._bindUI();
    },

    _bindUI() {
        const startEl = document.getElementById('dateStart');
        const endEl = document.getElementById('dateEnd');
        if (startEl && endEl) {
            if (this._start) startEl.value = this._start;
            if (this._end) endEl.value = this._end;
            startEl.addEventListener('change', () => this.set(startEl.value, endEl.value));
            endEl.addEventListener('change', () => this.set(startEl.value, endEl.value));
        }
    },

    set(start, end) {
        this._start = start || null;
        this._end = end || null;
        localStorage.setItem('dateRange', JSON.stringify({ start: this._start, end: this._end }));
        this._callbacks.forEach(fn => fn(this._start, this._end));
    },

    get() { return { start: this._start, end: this._end }; },

    /** Build URL query params */
    params(extra = {}) {
        const p = new URLSearchParams(extra);
        if (this._start) p.set('start', this._start);
        if (this._end) p.set('end', this._end);
        return p.toString();
    },

    onChange(fn) { this._callbacks.push(fn); },

    reset() {
        this._start = null;
        this._end = null;
        localStorage.removeItem('dateRange');
        const startEl = document.getElementById('dateStart');
        const endEl = document.getElementById('dateEnd');
        if (startEl) startEl.value = '';
        if (endEl) endEl.value = '';
        this._callbacks.forEach(fn => fn(null, null));
    },
};

document.addEventListener('DOMContentLoaded', () => DateRange.init());
