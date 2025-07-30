import requests
import os
from datetime import datetime

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

# ========== 获取今天的日期 ==========
today = datetime.now().strftime("%Y-%m-%d")  # 格式：2025-07-29
print(f" 当前日期：{today}")

# ========== 查询 Notion 数据：Start Date == 今天 ==========
query_url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
payload = {
    "filter": {
        "property": "Start Date",
        "date": {"equals": today}
    }
}

print(" 正在请求 Notion 数据...")
response = requests.post(query_url, headers=NOTION_HEADERS, json=payload)
data = response.json()

if "results" not in data:
    print(f" Notion API 错误响应: {data}")
    raise SystemExit("无法获取 Notion 数据，请检查 Token 或 Database ID")

tasks_sent = 0

# ========== 处理每条记录 ==========
for page in data.get("results", []):
    props = page["properties"]

    # 获取任务名称 Duty
    duty = props["Duty"]["title"][0]["plain_text"] if props["Duty"]["title"] else "未命名任务"

    # Slack 用户 ID（从 Notion 字段获取）
    slack1 = props.get("Slack Username 1", {}).get("rich_text", [])
    slack1 = slack1[0]["plain_text"] if slack1 else None

    slack2 = props.get("Slack Username 2", {}).get("rich_text", [])
    slack2 = slack2[0]["plain_text"] if slack2 else None

    # Notion 人员姓名
    persons = []
    if "Person" in props and props["Person"].get("people"):
        persons = [p["name"] for p in props["Person"]["people"]]

    # 检查是否已通知
    notified = props.get("Notification Status", {}).get("checkbox", False)

    if not notified:
        # 拼接 Slack mention 格式
        mentions = []
        for sid in [slack1, slack2]:
            if sid and sid.startswith("U"):  # 确保是 Slack 用户 ID
                mentions.append(f"<@{sid}>")

        # 如果 Slack ID 都不存在，使用人员姓名
        mention_text = " ".join(mentions) if mentions else " 和 ".join(persons) if persons else "值班人员"

        # 使用 emoji + 换行格式化
        message = (
            ":sunny: *Good morning!*\n"
            f"{mention_text}\n"
            f":clipboard: *Today's Duty:* {duty}\n"
            ":sparkles: Thanks for your work!"
        )

        print(f" 发送消息: {message}")

        # 发送 Slack 消息（逐个私聊）
        for slack_id in [slack1, slack2]:
            if slack_id and slack_id.startswith("U"):
                slack_url = "https://slack.com/api/chat.postMessage"
                payload = {"channel": slack_id, "text": message}
                res = requests.post(slack_url, headers=SLACK_HEADERS, json=payload)
                if res.status_code == 200:
                    print(f" 发送给 {slack_id} 成功")
                else:
                    print(f" 发送给 {slack_id} 失败: {res.text}")

        # 更新 Notion 状态（标记已通知）
        update_url = f"https://api.notion.com/v1/pages/{page['id']}"
        update_data = {"properties": {"Notification Status": {"checkbox": True}}}
        requests.patch(update_url, headers=NOTION_HEADERS, json=update_data)

        tasks_sent += 1

print(f" ✅ 脚本执行完成，共发送 {tasks_sent} 条任务通知")
