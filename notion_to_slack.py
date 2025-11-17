import requests
import os
from datetime import datetime, timedelta, timezone

# ========== 读取环境变量 ==========
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("DATABASE_ID")
SLACK_TOKEN = os.getenv("SLACK_TOKEN")

if not NOTION_TOKEN or not DATABASE_ID or not SLACK_TOKEN:
    raise ValueError("缺少 Notion Token、Database ID 或 Slack Token，请在 GitHub Secrets 设置")

# ============================
#  Notion & Slack API
# ============================
NOTION_API = "https://api.notion.com/v1"
NOTION_QUERY_URL = f"{NOTION_API}/databases/{DATABASE_ID}/query"
NOTION_PAGE_URL = f"{NOTION_API}/pages"

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",  # ✅ 继续使用旧版本
    "Content-Type": "application/json",
}

SLACK_HEADERS = {
    "Authorization": f"Bearer {SLACK_TOKEN}",
    "Content-Type": "application/json",
}

# ========== Person 名称 -> Slack 用户 ID 映射 ==========
# ⚠️ key 必须和 Notion Person 列中显示的名字完全一致
PERSON_TO_SLACK = {
    "LIU PENG": "U05UK795E3Y",
    "温述安": "U05URS5A7RQ",
    "HE JIAQI": "U051URPC4V7",
    "matsuda": "U01107CAKS5",
    "Shun Masuda": "U06S1PK7Z7U",
    "asuka suzuki": "U03AJPLCP5M",
    "Arman Syah Goli": "U05URS51M4J",
}

# ========== 获取日本时间日期 ==========
JST = timezone(timedelta(hours=9))
today = datetime.now(JST).date()
print(f" 当前日本时间日期：{today}")

# ========== 查询 Notion 数据库（旧版端点） ==========
response = requests.post(NOTION_QUERY_URL, headers=NOTION_HEADERS, json={})
try:
    response.raise_for_status()
except Exception:
    print(" Notion API 错误响应:", response.status_code, response.text)
    raise SystemExit("无法获取 Notion 数据，请检查 Token、Database ID 或权限/版本设置")

data = response.json()
if "results" not in data:
    print(" Notion API 异常返回:", data)
    raise SystemExit("无法获取 Notion 数据，请检查响应结构")

tasks_sent = 0
status_updates = 0

# ========== 遍历每条记录 ==========
for page in data.get("results", []):
    props = page.get("properties", {})
    page_id = page["id"]

    # 获取 Duty
    duty_prop = props.get("Duty", {})
    duty_title = duty_prop.get("title", [])
    duty = duty_title[0]["plain_text"] if duty_title else "未命名任务"

    # Person 列：值班人
    persons = []
    if "Person" in props and props["Person"].get("people"):
        persons = [p.get("name") for p in props["Person"]["people"] if p.get("name")]

    # 根据 Person 名字查 Slack ID
    slack_ids = []
    for person_name in persons:
        sid = PERSON_TO_SLACK.get(person_name)
        if sid:
            slack_ids.append(sid)

    # 当前状态
    current_status = props.get("Status", {}).get("status", {}).get("name", "")

    # Start Date & End Date
    start_date = props.get("Start Date", {}).get("date", {}).get("start")
    end_date = props.get("End Date", {}).get("date", {}).get("start")

    start_date_obj = datetime.fromisoformat(start_date).date() if start_date else None
    end_date_obj = datetime.fromisoformat(end_date).date() if end_date else None

    # 检查是否已通知
    notified = props.get("Notification Status", {}).get("checkbox", False)

    # ✅ 1. 如果今天是 Start Date & 未通知 → 发 Slack + 状态改 Ongoing
    if start_date_obj == today and not notified:
        mentions = []
        for sid in set(slack_ids):
            if sid and sid.startswith("U"):
                mentions.append(f"<@{sid}>")

        if mentions:
            mention_text = " ".join(mentions)
        elif persons:
            mention_text = " 和 ".join(persons)
        else:
            mention_text = "值班人员"

        db_url = "https://www.notion.so/213756632df180c78f56e15f294995e0?v=213756632df180fbbcf7000c58b9a3be&source=copy_link"
        message = (
            ":sunny: *Good morning!*\n"
            f"{mention_text}\n"
            f":clipboard: *Today's Duty:* {duty}\n"
            f":link: see all tasks: <{db_url}|Open Notion Database>\n"
            ":sparkles: Thanks for your work!"
        )

        print(f" 发送消息: {message}")

        # 给所有匹配到 Slack ID 的人发 DM
        for slack_id in set(slack_ids):
            if slack_id and slack_id.startswith("U"):
                slack_url = "https://slack.com/api/chat.postMessage"
                payload = {"channel": slack_id, "text": message}
                res = requests.post(slack_url, headers=SLACK_HEADERS, json=payload)
                ok = (res.status_code == 200 and res.json().get("ok") is True)
                print(f"  发送给 {slack_id} {'成功' if ok else f'失败 {res.status_code} {res.text}'}")

        # 更新 Notion (标记已通知 + 状态改 Ongoing)
        update_data = {
            "properties": {
                "Notification Status": {"checkbox": True},
                "Status": {"status": {"name": "Ongoing"}},
            }
        }
        requests.patch(f"{NOTION_API}/pages/{page_id}", headers=NOTION_HEADERS, json=update_data)

        tasks_sent += 1

    # ✅ 2. 如果今天 > End Date & 状态不是 Done → 改为 Done
    if end_date_obj and today > end_date_obj and current_status != "Done":
        update_data = {
            "properties": {
                "Status": {"status": {"name": "Done"}},
            }
        }
        requests.patch(f"{NOTION_API}/pages/{page_id}", headers=NOTION_HEADERS, json=update_data)
        print(f" ✅ 状态已更新为 Done for {duty}")
        status_updates += 1

print(f" ✅ 脚本执行完成，共发送 {tasks_sent} 条任务通知，更新 {status_updates} 条记录为 Done")
