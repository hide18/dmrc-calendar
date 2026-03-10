"""
TimeTree公開カレンダー「ドラマチックレコード（ドマレコ）スケジュール」のイベントデータを
Playwright経由でAPIから取得し、iCalendar (.ics) ファイルとして出力するスクリプト。

GitHub Actionsで定期実行し、GitHub Pagesでホスティングすることで
iPhoneカレンダーの「照会」機能で自動同期できる。
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

JST = timezone(timedelta(hours=9))

CALENDAR_SLUG = "dmrc"
CALENDAR_URL = f"https://timetreeapp.com/public_calendars/{CALENDAR_SLUG}?locale=ja"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "dist")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "dmrc_schedule.ics")

# 取得する月数の範囲（現在月を基準に前後何ヶ月分取得するか）
MONTHS_BEFORE = 1
MONTHS_AFTER = 4


def calculate_time_ranges() -> list[dict]:
    """
    現在日時を基準にAPIリクエスト用のタイムスタンプ範囲を計算する。

    TimeTree APIは、カレンダーグリッド（月曜始まり）の正確な境界値を要求する。
    各月について:
      - from = その月の1日を含む週の月曜日 00:00 JST（ミリ秒UTC）
      - to   = その月の末日を含む週の翌月曜日 00:00 JST（ミリ秒UTC）
    """
    now = datetime.now(JST)
    ranges = []

    for offset in range(-MONTHS_BEFORE, MONTHS_AFTER + 1):
        year = now.year
        month = now.month + offset
        while month <= 0:
            month += 12
            year -= 1
        while month > 12:
            month -= 12
            year += 1

        # 月初日
        first_day = datetime(year, month, 1, tzinfo=JST)
        # 月初日の曜日（Monday=0, Sunday=6）
        first_weekday = first_day.weekday()
        # グリッド開始 = その月の1日を含む週の月曜日
        grid_start = first_day - timedelta(days=first_weekday)

        # 月末日
        if month == 12:
            last_day = datetime(year + 1, 1, 1, tzinfo=JST) - timedelta(days=1)
        else:
            last_day = datetime(year, month + 1, 1, tzinfo=JST) - timedelta(days=1)
        # 月末日の曜日
        last_weekday = last_day.weekday()
        # グリッド終了 = 月末日を含む週の翌月曜日 (Sunday+1)
        grid_end = last_day + timedelta(days=(7 - last_weekday))

        from_ts = int(grid_start.timestamp() * 1000)
        to_ts = int(grid_end.timestamp() * 1000)

        ranges.append({
            "from": from_ts,
            "to": to_ts,
        })

    return ranges


def fetch_events_via_playwright() -> list[dict]:
    """Playwrightでブラウザを起動し、TimeTree APIからイベントデータを取得する"""
    print("Playwrightでブラウザを起動中...", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )

        # ページ読み込み中のAPIレスポンスをキャプチャ
        captured_events = []
        captured_ids = set()

        def handle_response(response):
            """ページが自動で行うAPIリクエストのレスポンスを傍受"""
            if "/public_events" in response.url and response.status == 200:
                try:
                    data = response.json()
                    events = data.get("public_events", [])
                    for ev in events:
                        if ev["id"] not in captured_ids:
                            captured_ids.add(ev["id"])
                            captured_events.append(ev)
                    print(f"  [自動キャプチャ] {response.url[:80]}... -> {len(events)}件", flush=True)
                except Exception as e:
                    print(f"  [自動キャプチャ] レスポンス解析エラー: {e}", flush=True)

        page.on("response", handle_response)

        # TimeTreeページにアクセス（APIを同一オリジンから呼ぶために必要）
        print(f"TimeTreeページにアクセス中: {CALENDAR_URL}", flush=True)
        try:
            page.goto(CALENDAR_URL, wait_until="domcontentloaded", timeout=60000)
            print(f"  ページURL: {page.url}", flush=True)
            print(f"  ページタイトル: {page.title()}", flush=True)
            page.wait_for_timeout(5000)
        except Exception as e:
            print(f"ページ読み込みエラー（続行します）: {e}", flush=True)

        # ページが自動ロードしたcookieを確認
        cookies = page.context.cookies()
        print(f"  Cookie数: {len(cookies)}", flush=True)
        for c in cookies[:5]:
            print(f"    {c['name']}: {c['value'][:30]}...", flush=True)

        print("ページ読み込み完了", flush=True)
        print(f"  自動キャプチャで取得済みイベント: {len(captured_events)}件", flush=True)

        # 追加の月分をAPIで取得
        ranges = calculate_time_ranges()
        all_events = list(captured_events)
        seen_ids = set(captured_ids)

        for i, time_range in enumerate(ranges):
            api_url = (
                f"https://timetreeapp.com/api/v2/public_calendars/{CALENDAR_SLUG}/public_events"
                f"?from={time_range['from']}&to={time_range['to']}&utc_offset=32400"
            )
            print(f"  APIリクエスト {i + 1}/{len(ranges)}: ...from={time_range['from']}&to={time_range['to']}", flush=True)

            try:
                # page.evaluate内でfullURLを使用
                response_text = page.evaluate("""
                    async (apiUrl) => {
                        try {
                            const response = await fetch(apiUrl);
                            const status = response.status;
                            const text = await response.text();
                            return JSON.stringify({status: status, body: text});
                        } catch (e) {
                            return JSON.stringify({status: -1, body: '{"public_events":[]}', error: e.message});
                        }
                    }
                """, api_url)

                wrapper = json.loads(response_text)
                print(f"    HTTP status: {wrapper['status']}", flush=True)
                if wrapper.get('error'):
                    print(f"    Fetch error: {wrapper['error']}", flush=True)

                result = json.loads(wrapper['body'])
                events = result.get("public_events", [])
                new_count = 0
                for event in events:
                    if event["id"] not in seen_ids:
                        seen_ids.add(event["id"])
                        all_events.append(event)
                        new_count += 1
                print(f"    -> {len(events)}件取得 (新規: {new_count}件)", flush=True)

            except Exception as e:
                import traceback
                print(f"    -> エラー: {e}", flush=True)
                traceback.print_exc()

        browser.close()

    print(f"合計: {len(all_events)}件のイベント取得完了", flush=True)
    return all_events


def escape_ics_text(text: str) -> str:
    """ICS形式用にテキストをエスケープする"""
    if not text:
        return ""
    text = text.replace("\\", "\\\\")
    text = text.replace(";", "\\;")
    text = text.replace(",", "\\,")
    text = text.replace("\n", "\\n")
    return text


def generate_ics(events: list[dict]) -> str:
    """イベントリストからICSファイルの文字列を生成する"""
    now_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//DMRC Schedule//TimeTree Sync//JP",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:ドマレコ スケジュール",
        "X-WR-TIMEZONE:Asia/Tokyo",
        f"X-GENERATED-AT:{now_utc}",
        # タイムゾーン定義
        "BEGIN:VTIMEZONE",
        "TZID:Asia/Tokyo",
        "BEGIN:STANDARD",
        "DTSTART:19700101T000000",
        "TZOFFSETFROM:+0900",
        "TZOFFSETTO:+0900",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]

    for event in sorted(events, key=lambda e: e.get("start_at", 0)):
        event_id = event.get("id", "")
        title = event.get("title", "無題")
        note = event.get("note", "")
        location_name = event.get("location_name", "")
        link_url = event.get("link_url", "")
        all_day = event.get("all_day", True)
        start_at_ms = event.get("start_at", 0)
        until_at_ms = event.get("until_at", 0)
        url = event.get("url", "")
        updated_at_ms = event.get("updated_at", 0)

        # タイムスタンプをdatetimeに変換
        start_dt = datetime.fromtimestamp(start_at_ms / 1000, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(until_at_ms / 1000, tz=timezone.utc) if until_at_ms else None
        updated_dt = datetime.fromtimestamp(updated_at_ms / 1000, tz=timezone.utc)

        start_jst = start_dt.astimezone(JST)

        # 説明文を構築
        description_parts = []
        if note:
            description_parts.append(note)
        if link_url:
            description_parts.append(f"\nチケット/詳細: {link_url}")
        if url:
            description_parts.append(f"\nTimeTree: {url}")
        description = "\n".join(description_parts)

        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{event_id}@timetreeapp.com")
        lines.append(f"DTSTAMP:{updated_dt.strftime('%Y%m%dT%H%M%SZ')}")

        if all_day:
            lines.append(f"DTSTART;VALUE=DATE:{start_jst.strftime('%Y%m%d')}")
            end_date = start_jst + timedelta(days=1)
            lines.append(f"DTEND;VALUE=DATE:{end_date.strftime('%Y%m%d')}")
        else:
            lines.append(f"DTSTART;TZID=Asia/Tokyo:{start_jst.strftime('%Y%m%dT%H%M%S')}")
            if end_dt:
                end_jst = end_dt.astimezone(JST)
                lines.append(f"DTEND;TZID=Asia/Tokyo:{end_jst.strftime('%Y%m%dT%H%M%S')}")

        lines.append(f"SUMMARY:{escape_ics_text(title)}")

        if description:
            lines.append(f"DESCRIPTION:{escape_ics_text(description)}")

        if location_name:
            lines.append(f"LOCATION:{escape_ics_text(location_name)}")

        if link_url:
            lines.append(f"URL:{link_url}")

        label = event.get("public_calendar_label", {})
        label_name = label.get("name", "")
        if label_name:
            lines.append(f"CATEGORIES:{escape_ics_text(label_name)}")

        lines.append("STATUS:CONFIRMED")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")

    return "\r\n".join(lines)


def main():
    # イベントデータ取得
    events = fetch_events_via_playwright()

    if not events:
        print("エラー: イベントが取得できませんでした")
        sys.exit(1)

    # ICSファイル生成
    ics_content = generate_ics(events)

    # 出力ディレクトリ作成
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ICSファイル書き出し
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(ics_content)

    print(f"\nICSファイルを生成しました: {OUTPUT_FILE}")

    # イベント一覧を表示
    print("\n--- イベント一覧 ---")
    for event in sorted(events, key=lambda e: e.get("start_at", 0)):
        start_dt = datetime.fromtimestamp(event["start_at"] / 1000, tz=timezone.utc)
        start_jst = start_dt.astimezone(JST)
        title = event.get("title", "無題")
        location = event.get("location_name", "")
        loc_str = f" @ {location}" if location else ""
        print(f"  {start_jst.strftime('%Y/%m/%d')} {title}{loc_str}")

    # index.htmlも生成（GitHub Pagesアクセス確認用）
    index_html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ドマレコ スケジュール</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 600px; margin: 40px auto; padding: 0 20px; }}
        h1 {{ font-size: 1.4em; }}
        .url {{ background: #f0f0f0; padding: 12px; border-radius: 8px; word-break: break-all; font-family: monospace; font-size: 0.9em; }}
        .steps {{ line-height: 1.8; }}
        .updated {{ color: #888; font-size: 0.85em; margin-top: 30px; }}
    </style>
</head>
<body>
    <h1>ドマレコ スケジュール カレンダー</h1>
    <p>{len(events)}件のイベントが含まれています。</p>
    <h2>iPhoneカレンダーに追加する方法</h2>
    <div class="steps">
        <p>1. 設定アプリを開く</p>
        <p>2.「カレンダー」→「アカウント」→「アカウントを追加」</p>
        <p>3.「照会するカレンダーを追加」を選択</p>
        <p>4. 以下のURLを入力:</p>
    </div>
    <div class="url" id="ics-url">（GitHub PagesのURLに置き換えてください）</div>
    <p class="updated">最終更新: {datetime.now(JST).strftime('%Y年%m月%d日 %H:%M JST')}</p>
    <script>
        const url = window.location.href.replace('index.html', '') + 'dmrc_schedule.ics';
        document.getElementById('ics-url').textContent = url;
    </script>
</body>
</html>"""

    with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)

    print(f"\nindex.htmlを生成しました: {os.path.join(OUTPUT_DIR, 'index.html')}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print(f"\n致命的エラー: {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)
