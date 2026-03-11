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



def fetch_events_via_playwright() -> list[dict]:
    """
    Playwrightでブラウザを起動し、TimeTreeカレンダーの月ナビゲーションを操作して
    各月のAPIレスポンスを傍受・収集する。

    TimeTree APIはセッション内の現在表示月に対するリクエストのみを受け付けるため、
    ページ上の「次月/前月」ボタンをクリックして月を切り替え、
    その際に発生するAPIレスポンスをキャプチャする方式を採用している。
    """
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
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        all_events = []
        seen_ids = set()

        def handle_response(response):
            """ページが行うAPIリクエストのレスポンスを傍受してイベントを蓄積"""
            if "/public_events" in response.url and response.status == 200:
                try:
                    data = response.json()
                    events = data.get("public_events", [])
                    new_count = 0
                    for ev in events:
                        if ev["id"] not in seen_ids:
                            seen_ids.add(ev["id"])
                            all_events.append(ev)
                            new_count += 1
                    print(f"  [キャプチャ] {len(events)}件 (新規: {new_count}件)", flush=True)
                except Exception:
                    pass

        page.on("response", handle_response)

        # TimeTreeページにアクセス（当月のイベントが自動取得される）
        print(f"TimeTreeページにアクセス中: {CALENDAR_URL}", flush=True)
        try:
            page.goto(CALENDAR_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            print(f"  ページタイトル: {page.title()}", flush=True)
        except Exception as e:
            print(f"  ページ読み込みエラー（続行します）: {e}", flush=True)

        print(f"  当月キャプチャ済み: {len(all_events)}件", flush=True)

        # 「次月」ボタン(_94ajna2)をクリックして将来月のイベントを取得
        print(f"次月ボタンで{MONTHS_AFTER}ヶ月分のイベントを取得中...", flush=True)
        for i in range(MONTHS_AFTER):
            try:
                next_btn = page.locator("button._94ajna2")
                next_btn.click(timeout=5000)
                page.wait_for_timeout(3000)
                print(f"  次月 {i + 1}/{MONTHS_AFTER} -> 合計: {len(all_events)}件", flush=True)
            except Exception as e:
                print(f"  次月クリック失敗 {i + 1}: {e}", flush=True)

        # 「前月」ボタン(_94ajna1)で元に戻り、さらに過去月を取得
        total_back = MONTHS_AFTER + MONTHS_BEFORE
        print(f"前月ボタンで{total_back}ヶ月戻り、過去{MONTHS_BEFORE}ヶ月分を取得中...", flush=True)
        for i in range(total_back):
            try:
                prev_btn = page.locator("button._94ajna1")
                prev_btn.click(timeout=5000)
                page.wait_for_timeout(3000)
                print(f"  前月 {i + 1}/{total_back} -> 合計: {len(all_events)}件", flush=True)
            except Exception as e:
                print(f"  前月クリック失敗 {i + 1}: {e}", flush=True)

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


def collect_event_images(event: dict) -> list[str]:
    """イベントから全画像URLをリストで返す（cover + overview）"""
    images = event.get("images", {})
    if not images:
        return []
    urls = []
    for img in images.get("cover", []):
        if img.get("url"):
            urls.append(img["url"])
    for img in images.get("overview", []):
        if img.get("url"):
            urls.append(img["url"])
    return urls


def generate_gallery_html(events: list[dict], base_url: str) -> str:
    """
    全イベントの画像ギャラリーを1つのHTMLに生成する。
    URLフラグメント（#event-ID）で各イベントにジャンプし、
    そのイベントの画像をスワイプ/スクロールで閲覧できる。
    """
    events_with_images = []
    for ev in sorted(events, key=lambda e: e.get("start_at", 0)):
        imgs = collect_event_images(ev)
        if imgs:
            start_dt = datetime.fromtimestamp(ev["start_at"] / 1000, tz=timezone.utc).astimezone(JST)
            events_with_images.append({
                "id": ev["id"],
                "title": ev.get("title", ""),
                "date": start_dt.strftime("%Y/%m/%d"),
                "location": ev.get("location_name", ""),
                "images": imgs,
            })

    events_json = json.dumps(events_with_images, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=3.0">
<title>ドマレコ イベント画像</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: #000; color: #fff;
  -webkit-text-size-adjust: 100%;
}}
.header {{
  position: sticky; top: 0; z-index: 10;
  background: rgba(0,0,0,0.85); backdrop-filter: blur(10px);
  padding: 12px 16px;
  border-bottom: 1px solid #333;
}}
.header h1 {{ font-size: 1.1em; font-weight: 600; }}
.event {{
  padding: 16px; border-bottom: 1px solid #222;
}}
.event-title {{
  font-size: 1em; font-weight: 600;
  margin-bottom: 4px;
}}
.event-meta {{
  font-size: 0.8em; color: #999;
  margin-bottom: 12px;
}}
.gallery {{
  display: flex; gap: 8px;
  overflow-x: auto; scroll-snap-type: x mandatory;
  -webkit-overflow-scrolling: touch;
  padding-bottom: 8px;
}}
.gallery::-webkit-scrollbar {{ display: none; }}
.gallery img {{
  scroll-snap-align: center;
  flex-shrink: 0;
  width: 85vw; max-width: 500px;
  height: auto; border-radius: 8px;
  object-fit: contain; background: #111;
}}
.gallery.single img {{
  width: 100%; max-width: 100%;
}}
.img-count {{
  font-size: 0.75em; color: #666;
  margin-top: 6px; text-align: center;
}}
.no-images {{
  text-align: center; padding: 60px 20px;
  color: #666; font-size: 0.9em;
}}
.target-highlight {{
  animation: highlight 2s ease-out;
}}
@keyframes highlight {{
  0% {{ background: rgba(46,204,135,0.3); }}
  100% {{ background: transparent; }}
}}
</style>
</head>
<body>
<div class="header">
  <h1>ドマレコ イベント画像</h1>
</div>
<div id="events"></div>
<script>
const events = {events_json};
const container = document.getElementById('events');
if (events.length === 0) {{
  container.innerHTML = '<div class="no-images">画像付きイベントはありません</div>';
}} else {{
  events.forEach(ev => {{
    const div = document.createElement('div');
    div.className = 'event';
    div.id = 'event-' + ev.id;
    const loc = ev.location ? ' / ' + ev.location : '';
    const singleClass = ev.images.length === 1 ? ' single' : '';
    div.innerHTML =
      '<div class="event-title">' + escapeHtml(ev.title) + '</div>' +
      '<div class="event-meta">' + ev.date + loc + '</div>' +
      '<div class="gallery' + singleClass + '">' +
        ev.images.map(url => '<img src="' + url + '" loading="lazy" alt="">').join('') +
      '</div>' +
      (ev.images.length > 1 ? '<div class="img-count">' + ev.images.length + '枚</div>' : '');
    container.appendChild(div);
  }});
  // URLフラグメントで該当イベントにスクロール
  if (location.hash) {{
    const target = document.getElementById(location.hash.slice(1));
    if (target) {{
      target.scrollIntoView({{ behavior: 'smooth' }});
      target.classList.add('target-highlight');
    }}
  }}
}}
function escapeHtml(s) {{
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}
</script>
</body>
</html>"""


def generate_ics(events: list[dict], gallery_base_url: str) -> str:
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

        start_dt = datetime.fromtimestamp(start_at_ms / 1000, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(until_at_ms / 1000, tz=timezone.utc) if until_at_ms else None
        updated_dt = datetime.fromtimestamp(updated_at_ms / 1000, tz=timezone.utc)
        start_jst = start_dt.astimezone(JST)

        # 説明文を構築
        description_parts = []
        if note:
            description_parts.append(note)

        # 画像ギャラリーリンク
        event_images = collect_event_images(event)
        if event_images:
            gallery_url = f"{gallery_base_url}#event-{event_id}"
            img_label = f"画像 ({len(event_images)}枚)" if len(event_images) > 1 else "画像"
            description_parts.append(f"\n{img_label}: {gallery_url}")

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
    # GitHub PagesのベースURL（環境変数で上書き可能）
    pages_base_url = os.environ.get(
        "PAGES_BASE_URL",
        "https://hide18.github.io/dmrc-calendar",
    )
    gallery_url = f"{pages_base_url}/gallery.html"

    # イベントデータ取得
    events = fetch_events_via_playwright()

    if not events:
        print("エラー: イベントが取得できませんでした")
        sys.exit(1)

    # 出力ディレクトリ作成
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ICSファイル生成
    ics_content = generate_ics(events, gallery_url)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(ics_content)
    print(f"\nICSファイルを生成しました: {OUTPUT_FILE}", flush=True)

    # 画像ギャラリーHTML生成
    gallery_html = generate_gallery_html(events, pages_base_url)
    gallery_path = os.path.join(OUTPUT_DIR, "gallery.html")
    with open(gallery_path, "w", encoding="utf-8") as f:
        f.write(gallery_html)

    img_count = sum(1 for ev in events if collect_event_images(ev))
    print(f"画像ギャラリーを生成しました: {gallery_path} ({img_count}件のイベントに画像あり)", flush=True)

    # イベント一覧を表示
    print("\n--- イベント一覧 ---", flush=True)
    for event in sorted(events, key=lambda e: e.get("start_at", 0)):
        start_dt = datetime.fromtimestamp(event["start_at"] / 1000, tz=timezone.utc)
        start_jst = start_dt.astimezone(JST)
        title = event.get("title", "無題")
        location = event.get("location_name", "")
        imgs = collect_event_images(event)
        loc_str = f" @ {location}" if location else ""
        img_str = f" [{len(imgs)}img]" if imgs else ""
        print(f"  {start_jst.strftime('%Y/%m/%d')} {title}{loc_str}{img_str}")

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
        .links {{ margin-top: 20px; }}
        .links a {{ color: #2ECC87; text-decoration: none; }}
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
    <div class="url" id="ics-url"></div>
    <div class="links">
        <p><a href="gallery.html">イベント画像ギャラリー ({img_count}件)</a></p>
    </div>
    <p class="updated">最終更新: {datetime.now(JST).strftime('%Y年%m月%d日 %H:%M JST')}</p>
    <script>
        const url = window.location.href.replace('index.html', '').replace(/\\/$/, '') + '/dmrc_schedule.ics';
        document.getElementById('ics-url').textContent = url;
    </script>
</body>
</html>"""

    with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)

    print(f"\nindex.htmlを生成しました: {os.path.join(OUTPUT_DIR, 'index.html')}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print(f"\n致命的エラー: {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)
