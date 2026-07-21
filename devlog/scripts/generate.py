#!/usr/bin/env python3
"""STEM devlog generator.

Reads devlog/entries/<date>/ (screenshots + memo.txt), generates:
  - devlog/out/<date>/story.png   (1080x1920 IG story image)
  - devlog/out/<date>/threads.txt (Threads post text)
  - devlog/latest.json            (pointer for the mobile viewer)

Usage: python devlog/scripts/generate.py [YYYY-MM-DD]
Env:   ANTHROPIC_API_KEY (optional; falls back to template text)
"""
import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEVLOG = ROOT / "devlog"
JST = timezone(timedelta(hours=9))
IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def target_date() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    # Runs ~2:30 AM JST; the content belongs to the previous day.
    return (datetime.now(JST) - timedelta(hours=12)).strftime("%Y-%m-%d")


def load_entry(date: str):
    entry = DEVLOG / "entries" / date
    if not entry.is_dir():
        return None, []
    memo = ""
    memo_file = entry / "memo.txt"
    if memo_file.exists():
        memo = memo_file.read_text(encoding="utf-8").strip()
    images = sorted(p for p in entry.iterdir() if p.suffix.lower() in IMG_EXTS)
    return memo, images


def fallback_caption(memo: str) -> str:
    """Short caption for the story image when no API key is set.
    Prefers a natural clause break (。then、) over a hard character cut,
    so it never chops off mid-word."""
    if not memo:
        return "今日もちょっと進んだ"
    for sep in ("。", "、"):
        head = memo.split(sep)[0].strip()
        if head and len(head) <= 22:
            return head
    return memo[:20] + "…" if len(memo) > 20 else memo


def gen_copy(memo: str, day_n: int, cfg: dict):
    """Ask Claude (Haiku) for the story caption + Threads text. Cheap: ~1 call/day."""
    fallback = {
        "story_caption": fallback_caption(memo),
        "threads_text": f"{memo}\n\nローンチまでもう少し、こつこつやってます。\n{cfg.get('hashtags','')}",
    }
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not memo:
        return fallback
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        prompt = f"""あなたは、アプリを個人でこつこつ作っている開発者本人です。その日の作業を、飾らずにSNSに書き残します。
広告コピーではなく、開発日記・ドキュメンタリーの語り口。等身大で、少し独り言っぽく。

アプリ: {cfg['app_name']} — {cfg['context']}
今日は{day_n}日目。今日のメモ:
「{memo}」

書き方のルール:
- 口調は「〜した」「〜だった」「〜してる」みたいな、話し言葉に近い普通体。です・ます調は使わない
- 「ワクワク」「ぜひ」「実現」みたいな宣伝くさい言葉、キャッチコピー的な誇張は使わない
- 絵文字は使わないか、使っても1個まで
- 自分がその作業をやってて感じたこと(地味な発見、苦労、ちょっと嬉しかった点)を素直に

以下のJSONだけを出力(説明不要):
{{
  "story_caption": "ストーリー画像に手書きメモっぽく載せる一言。20文字以内。「〜した」口調。例:『ズレが見えるようにした』",
  "threads_text": "Threadsに書く独り言っぽい開発日記。100〜200文字。今日やったことと、そのとき感じたことを普通体で。最後の行にハッシュタグ: {cfg.get('hashtags','')}"
}}"""
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        if text.startswith("```"):
            text = text.strip("`").lstrip("json").strip()
        data = json.loads(text)
        if data.get("story_caption") and data.get("threads_text"):
            return data
    except Exception as e:  # noqa: BLE001
        print(f"[warn] copy generation failed, using fallback: {e}")
    return fallback


def data_url(path: Path) -> str:
    mime = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else f"image/{path.suffix.lower().lstrip('.')}"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def render_story(html: str, out_png: Path):
    from playwright.sync_api import sync_playwright

    tmp = out_png.parent / "_story.html"
    tmp.write_text(html, encoding="utf-8")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1920})
        page.goto(tmp.as_uri())
        page.wait_for_load_state("networkidle")
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(500)
        page.screenshot(path=str(out_png))
        browser.close()
    tmp.unlink()


def main():
    date = target_date()
    memo, images = load_entry(date)
    if memo is None and not images:
        print(f"[skip] no entry for {date}")
        return
    if not images:
        print(f"[skip] no screenshots for {date} (memo only is not enough for a story)")
        return

    cfg = json.loads((DEVLOG / "config.json").read_text(encoding="utf-8"))
    day_n = (datetime.strptime(date, "%Y-%m-%d").date() - datetime.strptime(cfg["start_date"], "%Y-%m-%d").date()).days + 1

    copy = gen_copy(memo or "", day_n, cfg)

    out_dir = DEVLOG / "out" / date
    out_dir.mkdir(parents=True, exist_ok=True)

    template = (DEVLOG / "template.html").read_text(encoding="utf-8")
    date_disp = datetime.strptime(date, "%Y-%m-%d").strftime("%Y.%m.%d")
    html = (
        template.replace("{{DAY_N}}", str(day_n))
        .replace("{{DATE}}", date_disp)
        .replace("{{HERO_SRC}}", data_url(images[0]))
        .replace("{{THUMBS_JSON}}", json.dumps([data_url(p) for p in images[1:3]]))
        .replace("{{CAPTION}}", copy["story_caption"])
        .replace("{{MEMO}}", (memo or "").replace("\n", "<br>"))
    )
    render_story(html, out_dir / "story.png")
    (out_dir / "threads.txt").write_text(copy["threads_text"], encoding="utf-8")

    latest = {
        "date": date,
        "day_n": day_n,
        "story": f"out/{date}/story.png",
        "threads_text": copy["threads_text"],
        "screenshots": [f"entries/{date}/{p.name}" for p in images],
    }
    (DEVLOG / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] generated devlog for {date} (Day {day_n})")


if __name__ == "__main__":
    main()
