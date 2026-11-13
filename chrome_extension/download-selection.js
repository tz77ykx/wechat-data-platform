// Popup 和后台共用的发布日期选择规则，不访问微信或数据库。
const DownloadSelection = (() => {
  function chinaToday(now = new Date()) {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
    }).formatToParts(now);
    const fields = Object.fromEntries(parts.map(part => [part.type, part.value]));
    return `${fields.year}-${fields.month}-${fields.day}`;
  }

  function validDate(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const date = new Date(`${value}T00:00:00Z`);
    return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
  }

  function validate(selection) {
    if (!selection || !validDate(selection.start_date) || !validDate(selection.end_date)) {
      throw new Error("请选择有效的文章发布日期范围");
    }
    if (selection.start_date > selection.end_date) throw new Error("开始日期不能晚于结束日期");
    if (!["missing", "refresh"].includes(selection.download_mode)) throw new Error("请选择下载方式");
    return {
      start_date: selection.start_date,
      end_date: selection.end_date,
      download_mode: selection.download_mode,
    };
  }

  function resolve(preference = {}, now = new Date()) {
    const preset = ["7", "30", "90", "custom"].includes(preference.preset) ? preference.preset : "30";
    const mode = preference.download_mode === "refresh" ? "refresh" : "missing";
    if (preset === "custom") return { ...validate({ ...preference, download_mode: mode }), preset };
    const end = chinaToday(now);
    const start = new Date(`${end}T00:00:00Z`);
    start.setUTCDate(start.getUTCDate() - Number(preset) + 1);
    return { preset, start_date: start.toISOString().slice(0, 10), end_date: end, download_mode: mode };
  }

  return { chinaToday, validate, resolve };
})();
