import requests
import os
from datetime import datetime, timedelta, timezone

# ========== 读取环境变量 ==========
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("DATABASE_ID")
SLACK_TOKEN = os.getenv("SLACK_TOKEN")

# 可选：如果同一个数据库下有多个 data source，可用名字来精确选择
DATA_SOURCE_NAME = os.getenv("DATA_SOURCE_NAME")  # 例如 "On-call Duty 表"；留空则选第一个


# ============================
#  Notion API
# ============================
NOTION_QUERY_URL = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
NOTION_PAGE_URL = "https://api.notion.com/v1/pages"
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

if not NOTION_TOKEN or not DATABASE_ID or not SLACK_TOKEN:
    raise ValueError("缺少 Notion Token、Database ID 或 Slack Token，请在 GitHub Secrets 设置")

# ========== 设置 API 请求头 ==========
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    # 🔧 升级到新版本
    "Notion-Version": "2025-09-03"
}

SLACK_HEADERS = {
    "Authorization": f"Bearer {SLACK_TOKEN}",
    "Content-Type": "application/json"
}

NOTION_API = "https://api.notion.com/v1"

# ========== 工具函数：根据 database_id 获取 data_source_id ==========
def get_data_source_id(database_id: str, preferred_name: str | None = None) -> str:
    resp = requests.get(f"{NOTION_API}/databases/{database_id}", headers=NOTION_HEADERS)
    try:
        resp.raise_for_status()
    except Exception:
        raise SystemExit(f"获取数据库信息失败：{resp.status_code} {resp.text}")

    db = resp.json()
    sources = db.get("data_sources", [])
    if not sources:
        raise SystemExit("该数据库下没有 data source（或无权限可见）。")

    if preferred_name:
        for s in sources:
            if (s.get("name") or "").strip() == preferred_name.strip():
                return s["id"]

    # 默认取第一个（如有多个，建议配置 DATA_SOURCE_NAME 精确选择）
    return sources[0]["id"]

# ========== 获取日本时间日期 ==========
JST = timezone(timedelta(hours=9))
today = datetime.now(JST).date()  # e.g. 2025-08-06
print(f" 当前日本时间日期：{today}")

# ========== 🔧 先拿 data_source_id，再用 data source 查询 ==========
DATA_SOURCE_ID = get_data_source_id(DATABASE_ID, DATA_SOURCE_NAME)

# 你原来是全量拉取；如果需要可在 body 里加 filter/sorts/page_size
query_url = f"{NOTION_API}/data_sources/{DATA_SOURCE_ID}/query"  # 🔧 新端点
response = requests.post(query_url, headers=NOTION_HEADERS, json={})
data = response.json()

if "results" not in data:
    print(f" Notion API 错误响应: {data}")
    raise SystemExit("无法获取 Notion 数据，请检查 Token、Database ID 或权限/版本设置")

tasks_sent = 0
status_updates = 0

# ========== 遍历每条记录 ==========
for page in data.get("results", []):
    props = page["properties"]
    page_id = page["id"]

    # 获取 Duty
    duty = props["Duty"]["title"][0]["plain_text"] if props["Duty"]["title"] else "未命名任务"

    # Slack 用户 ID
    slack1 = props.get("Slack Username 1", {}).get("rich_text", [])
    slack1 = slack1[0]["plain_text"] if slack1 else None
    slack2 = props.get("Slack Username 2", {}).get("rich_text", [])
    slack2 = slack2[0]["plain_text"] if slack2 else None

    # 人员姓名
    persons = []
    if "Person" in props and props["Person"].get("people"):
        persons = [p.get("name") for p in props["Person"]["people"] if p.get("name")]

    # 当前状态
    current_status = props.get("Status", {}).get("status", {}).get("name", "")

    # Start Date & End Date
    start_date = props.get("Start Date", {}).get("date", {}).get("start")
    end_date = props.get("End Date", {}).get("date", {}).get("start")

    # 转换为 date 对象（注意：ISO 8601 可能含时区；fromisoformat 能处理带偏移的字符串）
    start_date_obj = datetime.fromisoformat(start_date).date() if start_date else None
    end_date_obj = datetime.fromisoformat(end_date).date() if end_date else None

    # 检查是否已通知
    notified = props.get("Notification Status", {}).get("checkbox", False)

    # ✅ 1. 如果今天是 Start Date & 未通知 → 发 Slack + 状态改 Ongoing
    if start_date_obj == today and not notified:
        mentions = []
        for sid in [slack1, slack2]:
            if sid and sid.startswith("U"):
                mentions.append(f"<@{sid}>")
        mention_text = " ".join(mentions) if mentions else " 和 ".join(persons) if persons else "值班人员"
        db_url = "https://www.notion.so/213756632df180c78f56e15f294995e0?v=213756632df180fbbcf7000c58b9a3be&source=copy_link"
        message = (
            ":sunny: *Good morning!*\n"
            f"{mention_text}\n"
            f":clipboard: *Today's Duty:* {duty}\n"
            f":link: see all tasks: <{db_url}|Open Notion Database>\n"
            ":sparkles: Thanks for your work!"
        )

        print(f" 发送消息: {message}")

        for slack_id in [slack1, slack2]:
            if slack_id and slack_id.startswith("U"):
                slack_url = "https://slack.com/api/chat.postMessage"
                payload = {"channel": slack_id, "text": message}
                res = requests.post(slack_url, headers=SLACK_HEADERS, json=payload)
                ok = (res.status_code == 200 and res.json().get("ok") is True)
                print(f" 发送给 {slack_id} {'成功' if ok else f'失败 {res.status_code} {res.text}'}")

        # 更新 Notion (标记已通知 + 状态改 Ongoing)
        update_data = {
            "properties": {
                "Notification Status": {"checkbox": True},
                "Status": {"status": {"name": "Ongoing"}}
            }
        }
        requests.patch(f"{NOTION_API}/pages/{page_id}", headers=NOTION_HEADERS, json=update_data)

        tasks_sent += 1

    # ✅ 2. 如果今天 > End Date & 状态不是 Done → 改为 Done
    if end_date_obj and today > end_date_obj and current_status != "Done":
        update_data = {
            "properties": {
                "Status": {"status": {"name": "Done"}}
            }
        }
        requests.patch(f"{NOTION_API}/pages/{page_id}", headers=NOTION_HEADERS, json=update_data)
        print(f" ✅ 状态已更新为 Done for {duty}")
        status_updates += 1

print(f" ✅ 脚本执行完成，共发送 {tasks_sent} 条任务通知，更新 {status_updates} 条记录为 Done")
