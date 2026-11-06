"""把打印机状态报文格式化成中文文本。"""

STATE_TEXT = {
    "RUNNING": "🟢 打印中",
    "PAUSE": "🟡 已暂停",
    "FINISH": "✅ 已完成",
    "FAILED": "🔴 失败",
    "IDLE": "⚪ 空闲",
    "PREPARE": "🟠 准备中",
    "SLICING": "🟠 切片中",
    "OFFLINE": "⚫ 离线",
    "INIT": "⚪ 初始化中",
}

COLOR_NAMES = {
    "DE4343": "红色",
    "7F7E83": "灰色",
    "000000": "黑色",
    "FFFFFF": "白色",
    "00AE42": "绿色",
    "00B0E0": "蓝色",
    "F4EE2A": "黄色",
    "FF6A00": "橙色",
    "B0A7D6": "紫色",
    "C1A9E1": "紫色",
    "00376B": "深蓝",
    "E8E8E8": "白色",
    "8F8F8F": "深灰",
    "00B2E3": "湖蓝",
    "EB4C4C": "红色",
    "F1A63B": "黄色",
    "70AF9C": "青绿",
    "A8D8B9": "浅绿",
    "4C9BD6": "蓝色",
    "616161": "深灰",
    "1C1C1C": "黑色",
    "CFCFCF": "浅灰",
}


def _color_name(code):
    if not code:
        return "未知"
    key = str(code)[:6].upper()
    return COLOR_NAMES.get(key, f"#{key}")


def _duration(seconds):
    try:
        s = int(seconds or 0)
    except Exception:
        return "未知"
    if s <= 0:
        return "0 分钟"
    h, m = divmod(s // 60, 60)
    if h:
        return f"{h} 小时 {m} 分"
    return f"{m} 分钟"


def _report_print(report):
    return (report or {}).get("print", {}) or {}


def format_status_line(report):
    """一行摘要，适合实时监控。"""
    p = _report_print(report)
    state = p.get("gcode_state") or "UNKNOWN"
    percent = p.get("mc_percent")
    task = p.get("subtask_name") or p.get("task_name") or "无任务"
    return (f"{STATE_TEXT.get(state, state)} "
            f"{percent if percent is not None else '?'}% | {task}")


def format_status(report, serial=None):
    """多行中文状态摘要。"""
    p = _report_print(report)
    lines = []

    state = p.get("gcode_state") or "UNKNOWN"
    lines.append("🖨️ 拓竹打印机状态")
    if serial:
        lines.append(f"序列号：{serial}")
    lines.append(f"状态：{STATE_TEXT.get(state, state)}")

    percent = p.get("mc_percent")
    if percent is not None:
        lines.append(f"进度：{percent}%")
    layer_now = p.get("layer_num")
    layer_total = p.get("total_layer_num")
    if layer_total:
        lines.append(f"层数：{layer_now}/{layer_total}")
    remain = p.get("mc_remaining_time")
    if remain is not None:
        lines.append(f"剩余时间：{_duration(remain)}")

    task = p.get("subtask_name") or p.get("task_name")
    if task:
        lines.append(f"任务：{task}")

    nozzle = p.get("nozzle_temper")
    nozzle_target = p.get("nozzle_target_temper")
    if nozzle is not None:
        extra = f"（目标 {nozzle_target}°C）" if nozzle_target else ""
        lines.append(f"喷嘴温度：{nozzle}°C{extra}")
    bed = p.get("bed_temper")
    bed_target = p.get("bed_target_temper")
    if bed is not None:
        extra = f"（目标 {bed_target}°C）" if bed_target else ""
        lines.append(f"热床温度：{bed}°C{extra}")

    # AMS
    ams = (p.get("ams") or {}).get("ams") or []
    for unit in ams:
        uid = unit.get("id")
        hum = unit.get("humidity")
        temp = unit.get("temp")
        head = f"AMS{uid}（湿度 {hum}%" if hum is not None else "AMS"
        if temp is not None:
            head += f"，温度 {temp}°C"
        head += "）"
        lines.append(head)
        for tray in (unit.get("tray") or []):
            tid = tray.get("id")
            color = _color_name(tray.get("tray_color"))
            remain_pct = tray.get("remain")
            if isinstance(remain_pct, (int, float)) and remain_pct >= 0:
                lines.append(f"  └ 槽位 {tid}：{color}，剩余 {remain_pct}%")
            else:
                lines.append(f"  └ 槽位 {tid}：{color}")

    err = p.get("err")
    if err in (None, 0, "0", ""):
        err = p.get("mc_err")
    if err not in (None, 0, "0", "", {}, []):
        lines.append(f"⚠️ 错误码：{err}")

    return "\n".join(lines)
