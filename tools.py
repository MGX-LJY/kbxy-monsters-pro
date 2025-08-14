# -*- coding: utf-8 -*-
# KBXY 获取渠道清洗台（UI）
# 运行： streamlit run tools_ui.py

import re
import io
import os
import json
import time
import base64
import pandas as pd
import streamlit as st

st.set_page_config(page_title="KBXY 获取渠道清洗台", layout="wide")

# --------------------- 通用正则与常量 ---------------------
LOG_RE = re.compile(
    r"^\s*(?:INFO|WARNING|ERROR)?\s*ACQ\s+"
    r"(?P<name>.*?)\s*\|\s*type=(?P<type>[^|]+?)\s+new=(?P<new>\S+)\s*\|\s*method=(?P<method>.*)\s*$"
)

OTHERS = {"其它", "其他", "None", "null", "NULL", "", None}

DEFAULT_RULES_TXT = """# 一行一条：Python正则  =>  标签（命中后立即返回，不再继续匹配）
# 可用标签：活动获取宠物 / BOSS宠物 / 兑换/商店 / 可捕捉宠物 / 超进化 / 任务获取 / 其它
# 示例（可按需修改/追加/调序）：
(参与|进行).{0,8}(活动|充值好礼|七日送好礼|嘉年华|节|合一|守|战|挑战活动|考验).*(获|可?获得) => 活动获取宠物
(BOSS|首领|地府|内殿|万妖洞|副本|组队|挑战|切磋|通关|荣耀|幻境|超能幻境|首次(击|打)败) => BOSS宠物
(寻宝罗盘|罗盘|七星宝图|北斗七星图|神宠之魂|扭蛋|转盘|兑换所|礼盒|商店).*(获|可?获得|抽(取|得)) => 兑换/商店
(可在.*捕获|捕捉|捕获|有几率?获得|在.*(海岸|山|国|区域|地点|洞|谷|林|湾)) => 可捕捉宠物
(超进化|进化|觉醒|进阶|升阶|无双印记|无双状态|战斗中出现) => 超进化
(任务|剧情|点亮|签到|每日|周常) => 任务获取
(VIP|年费|月费|充值|成为.*超级VIP|当月VIP) => 其它
"""

ACQ_LABELS = ["活动获取宠物", "BOSS宠物", "兑换/商店", "可捕捉宠物", "超进化", "任务获取", "其它"]


# --------------------- 工具函数 ---------------------
def _clean(x: str) -> str:
    if x is None:
        return ""
    return re.sub(r"\s+", " ", str(x)).strip()


def parse_log_text(text: str) -> list[dict]:
    """从 ACQ 日志行解析结构"""
    items = []
    for i, line in enumerate(text.splitlines(), 1):
        m = LOG_RE.match(line)
        if not m:
            continue
        typ = _clean(m.group("type"))
        items.append(
            {
                "name": _clean(m.group("name")),
                "type": typ.replace("其它", "其他") if typ else typ,
                "new": _clean(m.group("new")),
                "method": _clean(m.group("method")),
                "source": "log",
                "line_no": i,
            }
        )
    return items


def parse_json_text(text: str) -> list[dict]:
    """从 JSON 中抽取 name/type/new/method，允许 acq_ 前缀字段名"""
    out = []
    try:
        data = json.loads(text)
    except Exception:
        return out

    def pick_one(d):
        name = d.get("name") or d.get("title") or ""
        typ = d.get("acq_type") or d.get("type")
        new = d.get("acq_new_type") or d.get("new_type") or d.get("new")
        method = d.get("acq_method") or d.get("method")
        if name or method or typ:
            out.append(
                {
                    "name": _clean(name),
                    "type": _clean(typ) if typ is not None else None,
                    "new": _clean(new),
                    "method": _clean(method),
                    "source": "json",
                    "line_no": None,
                }
            )

    if isinstance(data, list):
        for d in data:
            if isinstance(d, dict):
                pick_one(d)
    elif isinstance(data, dict):
        pick_one(data)
    return out


def load_inputs(uploaded_files: list, pasted_text: str) -> list[dict]:
    """合并上传文件与粘贴文本"""
    items = []
    # 文件
    for f in uploaded_files or []:
        content = f.read().decode("utf-8", errors="ignore")
        # 先试 JSON，再回落日志
        js = parse_json_text(content)
        if js:
            items.extend(js)
        else:
            items.extend(parse_log_text(content))
    # 粘贴
    pasted_text = pasted_text or ""
    if pasted_text.strip():
        js = parse_json_text(pasted_text)
        if js:
            items.extend(js)
        else:
            items.extend(parse_log_text(pasted_text))
    return items


def filter_others(items: list[dict]) -> list[dict]:
    """仅保留原始 type 属于 '其它/其他/None/空' 的条目"""
    out = []
    for it in items:
        typ = it.get("type")
        if typ in OTHERS or _clean(typ) in OTHERS:
            out.append(it)
    return out


def compile_rules(rules_text: str) -> list[tuple[re.Pattern, str]]:
    rules = []
    for ln in (rules_text or "").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if "=>" not in ln:
            continue
        patt, label = ln.split("=>", 1)
        patt = patt.strip()
        label = label.strip()
        if not patt or not label:
            continue
        try:
            rules.append((re.compile(patt), label))
        except re.error as e:
            st.warning(f"正则编译失败：{patt} -> {e}")
    return rules


def reclassify(items: list[dict], rules: list[tuple[re.Pattern, str]]) -> list[dict]:
    """按规则对 method 重分类（仅对原始 '其它/空'）"""
    out = []
    for it in items:
        m = it.get("method") or ""
        label = "其它"
        for patt, lab in rules:
            if patt.search(m):
                label = lab
                break
        new_it = dict(it)
        new_it["suggest_type"] = label
        return_flag = None
        if re.search(r"(绝版|停止(获取|产出)|下架|已结束|未开放|不可获取|无法获得)", m):
            return_flag = False
        elif re.search(r"(可捕捉|野外|常驻|长期|周常|日常|兑换(长期)?开放|商店(长期)?开放|随时可|任意时段)", m):
            return_flag = True
        new_it["suggest_new"] = return_flag
        out.append(new_it)
    return out


def df_download_button(df: pd.DataFrame, label: str, file_name: str, file_type: str = "json"):
    if file_type == "json":
        data = df.to_json(orient="records", force_ascii=False, indent=2)
        mime = "application/json"
    else:
        data = df.to_csv(index=False)
        mime = "text/csv"
    st.download_button(label, data=data, file_name=file_name, mime=mime)


def gen_rules_snippet(rules: list[tuple[re.Pattern, str]]) -> str:
    """生成可贴回爬虫的 ACQ_CLASS_RULES 代码片段（顺序保留）"""
    lines = ["ACQ_CLASS_RULES = ["]
    for patt, lab in rules:
        # 转义内层的反斜杠与引号
        patt_src = patt.pattern.replace("\\", "\\\\").replace('"', '\\"')
        lab_src = lab.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'    (r"{patt_src}", "{lab_src}"),')
    lines.append("]")
    return "\n".join(lines)


# --------------------- UI ---------------------
st.title("🛠 KBXY 获取渠道清洗台（type=其它 专用）")

with st.sidebar:
    st.header("输入")
    files = st.file_uploader("上传日志或JSON（可多选）", type=["log", "txt", "json"], accept_multiple_files=True)
    pasted = st.text_area("或粘贴日志/JSON内容", height=180, placeholder="可直接把 INFO ACQ 日志或 out_acq_xxx.json 粘进来")
    st.caption("提示：JSON 会优先解析；否则按日志行解析。")

    st.header("规则")
    rules_text = st.text_area("正则 => 标签（按顺序匹配）", value=DEFAULT_RULES_TXT, height=240)
    st.caption("命中第一条规则后立即确定标签；未命中则保持“其它”。")

    st.header("快速搜索")
    q = st.text_input("在 name / method 中查找", value="")

raw_items = load_inputs(files, pasted)
others = filter_others(raw_items)
rules = compile_rules(rules_text)
recl_items = reclassify(others, rules)

col_a, col_b, col_c = st.columns([1,1,2])
with col_a:
    st.metric("总条目", len(raw_items))
with col_b:
    st.metric("待清洗（原始 type=其它/空）", len(others))

df = pd.DataFrame(recl_items)
if q.strip():
    q_re = re.compile(re.escape(q.strip()), re.I)
    mask = df.apply(lambda r: bool(q_re.search(_clean(r.get("name"))) or q_re.search(_clean(r.get("method")))), axis=1)
    df = df[mask]

st.subheader("预览")
if df.empty:
    st.info("没有可显示的数据。请上传或粘贴内容，或规则未命中。")
else:
    show_cols = ["name", "type", "new", "method", "suggest_type", "suggest_new", "source", "line_no"]
    for c in show_cols:
        if c not in df.columns:
            df[c] = None
    st.dataframe(df[show_cols], use_container_width=True, height=420)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        df_download_button(df[show_cols], "⬇️ 导出 JSON", "others_reclassified.json", "json")
    with c2:
        df_download_button(df[show_cols], "⬇️ 导出 CSV", "others_reclassified.csv", "csv")
    with c3:
        st.download_button("📋 复制 ACQ_CLASS_RULES 片段",
                           data=gen_rules_snippet(rules),
                           file_name="acq_class_rules.py",
                           mime="text/plain")
    with c4:
        st.write("")

# --------------------- 正则测试台 ---------------------
st.markdown("---")
st.subheader("🔎 正则测试台")
sample_methods = [it["method"] for it in others if it.get("method")]
sample_methods = list(dict.fromkeys(sample_methods))  # 去重保序
if not sample_methods:
    st.info("请先导入数据；这里会显示原始 type=其它 的 method 供测试。")
else:
    s1, s2 = st.columns([2, 1])
    with s1:
        test_text = st.selectbox("选一条 method 作为样本", options=sample_methods, index=0)
    with s2:
        test_patt = st.text_input("输入正则（临时测试，不影响上面的规则）", value=r"(VIP|年费|月费|充值|超级VIP|当月VIP)")
    try:
        rx = re.compile(test_patt)
        m = rx.search(test_text or "")
        if m:
            st.success("✅ 命中！")
            st.code(f"匹配片段：{m.group(0)}", language="text")
        else:
            st.warning("未命中。")
    except re.error as e:
        st.error(f"正则错误：{e}")

# --------------------- 规则命中统计 ---------------------
st.markdown("---")
st.subheader("📊 规则命中统计（按顺序）")
if rules and others:
    stats = []
    remained = list(others)
    for patt, lab in rules:
        cnt = sum(1 for it in remained if patt.search(it.get("method") or ""))
        stats.append({"label": lab, "pattern": patt.pattern, "hits": cnt})
        # 移除已命中，模拟“第一条命中即归类”
        remained = [it for it in remained if not patt.search(it.get("method") or "")]
    stats.append({"label": "其它(未命中)", "pattern": "-", "hits": len(remained)})
    st.dataframe(pd.DataFrame(stats), use_container_width=True)
else:
    st.info("暂无数据或规则为空。")