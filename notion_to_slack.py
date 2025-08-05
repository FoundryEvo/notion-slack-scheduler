import requests
import os
from datetime import datetime, timedelta, timezone

# ========== 读取环境变量 ==========
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("DATABASE_ID")
SLACK_TOKEN = os.getenv("SLACK_TOKEN")

if not NOTION_TOKEN or not DATABASE_ID or not SLACK_TOKEN:
    raise ValueError("缺少 Notion Token、Database ID 或 Slack Token，请在 GitHub Secrets 设置")

# ========== 设置 API 请求头 ==========
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

SLACK_HEADERS = {
    "Authorization": f"Bearer {SLACK_TOKEN}",
    "Content-Type": "application/json"
}

# ========== 获取日本时间日期 ==========
JST = timezone(timedelta(hours=9))
today = datetime.now(JST).date()  # e.g. 2025-08-06
print(f" 当前日本时间日期：{today}")

# ========== 查询 Notion 全部数据（用 filter 可加限制避免拉全量）==========
query_url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
response = requests.post(query_url, headers=NOTION_HEADERS)
data = response.json()

if "results" not in data:
    print(f" Notion API 错误响应: {data}")
    raise SystemExit("无法获取 Notion 数据，请检查 Token 或 Database ID")

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
        persons = [p["name"] for p in props["Person"]["people"]]

    # 当前状态
    current_status = props.get("Status", {}).get("status", {}).get("name", "")

    # Start Date & End Date
    start_date = props.get("Start Date", {}).get("date", {}).get("start")
    end_date = props.get("End Date", {}).get("date", {}).get("start")

    # 转换为 date 对象
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
        db_url = "https://www.notion.so/213756632df1801a8af4d3a2fedf094f?v=213756632df18082a98b000c091a028a&source=copy_link"
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
                print(f" 发送给 {slack_id} {'成功' if res.status_code == 200 else '失败'}")

        # 更新 Notion (标记已通知 + 状态改 Ongoing)
        update_data = {
            "properties": {
                "Notification Status": {"checkbox": True},
                "Status": {"status": {"name": "Ongoing"}}
            }
        }
        requests.patch(f"https://api.notion.com/v1/pages/{page_id}", headers=NOTION_HEADERS, json=update_data)

        tasks_sent += 1

    # ✅ 2. 如果今天 > End Date & 状态不是 Done → 改为 Done
    if end_date_obj and today > end_date_obj and current_status != "Done":
        update_data = {
            "properties": {
                "Status": {"status": {"name": "Done"}}
            }
        }
        requests.patch(f"https://api.notion.com/v1/pages/{page_id}", headers=NOTION_HEADERS, json=update_data)
        print(f" ✅ 状态已更新为 Done for {duty}")
        status_updates += 1

print(f" ✅ 脚本执行完成，共发送 {tasks_sent} 条任务通知，更新 {status_updates} 条记录为 Done")
