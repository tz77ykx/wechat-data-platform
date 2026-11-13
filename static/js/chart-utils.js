/**
 * DUT至简 Chart.js 配色工厂
 */
const ZJ = {
    colors: ['#07C160', '#1989FA', '#FF976A', '#EE0A24', '#7C4DFF', '#00BCD4', '#FF6D00', '#795548'],
    bg:     ['rgba(7,193,96,0.12)', 'rgba(25,137,250,0.12)', 'rgba(255,151,106,0.12)',
             'rgba(238,10,36,0.12)', 'rgba(124,77,255,0.12)', 'rgba(0,188,212,0.12)',
             'rgba(255,109,0,0.12)', 'rgba(121,85,72,0.12)'],

    /** 获取第 i 个颜色 */
    color(i) { return this.colors[i % this.colors.length]; },
    bgColor(i) { return this.bg[i % this.bg.length]; },

    /** 全局 Chart.js 默认值 */
    applyDefaults() {
        if (!window.Chart) return;
        Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'PingFang SC', sans-serif";
        Chart.defaults.font.size = 12;
        Chart.defaults.color = '#6E6E6E';
        Chart.defaults.plugins.legend.labels.usePointStyle = true;
        Chart.defaults.plugins.legend.labels.pointStyleWidth = 8;
        Chart.defaults.elements.line.borderWidth = 2;
        Chart.defaults.elements.point.radius = 3;
        Chart.defaults.elements.point.hoverRadius = 5;
        Chart.defaults.scale.grid.color = '#F0F0F0';
        Chart.defaults.scale.border.display = false;
    },

    /** 创建折线图 */
    lineChart(ctx, labels, datasets, opts = {}) {
        return new Chart(ctx, {
            type: 'line',
            data: { labels, datasets: datasets.map((ds, i) => ({
                borderColor: this.color(i),
                backgroundColor: this.bgColor(i),
                tension: 0.3,
                fill: datasets.length === 1,
                ...ds,
            })) },
            options: { responsive: true, maintainAspectRatio: false, ...opts },
        });
    },

    /** 创建柱状图 */
    barChart(ctx, labels, datasets, opts = {}) {
        return new Chart(ctx, {
            type: 'bar',
            data: { labels, datasets: datasets.map((ds, i) => ({
                backgroundColor: this.color(i),
                ...ds,
            })) },
            options: { responsive: true, maintainAspectRatio: false, ...opts },
        });
    },

    /** 创建饼图 */
    pieChart(ctx, labels, data, opts = {}) {
        return new Chart(ctx, {
            type: 'pie',
            data: {
                labels,
                datasets: [{ data, backgroundColor: this.colors.slice(0, data.length) }],
            },
            options: { responsive: true, maintainAspectRatio: false, ...opts },
        });
    },

    /** 销毁已有图表实例 */
    destroy(chart) {
        if (chart && typeof chart.destroy === 'function') chart.destroy();
        return null;
    },
};

document.addEventListener('DOMContentLoaded', () => ZJ.applyDefaults());
