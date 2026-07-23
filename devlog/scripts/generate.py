#!/usr/bin/env python3
"""STEM devlog generator.

Reads devlog/entries/<date>/ (title.txt, memo.txt, one screenshot), generates:
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
    """Title and memo are entered separately (via add.html) so the story's
    headline and body never just repeat each other."""
    entry = DEVLOG / "entries" / date
    if not entry.is_dir():
        return None, None, []
    title = ""
    title_file = entry / "title.txt"
    if title_file.exists():
        title = title_file.read_text(encoding="utf-8").strip()
    memo = ""
    memo_file = entry / "memo.txt"
    if memo_file.exists():
        memo = memo_file.read_text(encoding="utf-8").strip()
    images = sorted(p for p in entry.iterdir() if p.suffix.lower() in IMG_EXTS)
    return title, memo, images


def fallback_caption(memo: str) -> str:
    """Fallback headline when no title was entered. Prefers a natural clause
    break (。then、) over a hard character cut, so it never chops off mid-word."""
    if not memo:
        return "今日もちょっと進んだ"
    for sep in ("。", "、"):
        head = memo.split(sep)[0].strip()
        if head and len(head) <= 22:
            return head
    return memo[:20] + "…" if len(memo) > 20 else memo


def gen_threads_text(title: str, memo: str, cfg: dict) -> str:
    """Ask Claude (Haiku) for the Threads post text. Cheap: ~1 call/day."""
    parts = [p for p in (title, memo) if p]
    body = "\n\n".join(parts) if parts else "今日もちょっと進んだ"
    fallback = f"{body}\n\nローンチまでもう少し、こつこつやってます。\n{cfg.get('hashtags','')}"

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not memo:
        return fallback
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        prompt = f"""あなたは、アプリを個人でこつこつ作っている開発者本人です。その日の作業を、飾らずにSNSに書き残します。
広告コピーではなく、開発日記・ドキュメンタリーの語り口。等身大で、少し独り言っぽく。

アプリ: {cfg['app_name']} — {cfg['context']}
今日のタイトル:「{title or '(なし)'}」
今日のメモ:
「{memo}」

書き方のルール:
- 口調は「〜した」「〜だった」「〜してる」みたいな、話し言葉に近い普通体。です・ます調は使わない
- 「ワクワク」「ぜひ」「実現」みたいな宣伝くさい言葉、キャッチコピー的な誇張は使わない
- 絵文字は使わないか、使っても1個まで
- 自分がその作業をやってて感じたこと(地味な発見、苦労、ちょっと嬉しかった点)を素直に
- 100〜200文字程度
- 最後の行にハッシュタグをそのまま入れる: {cfg.get('hashtags','')}

Threadsに投稿する文章だけを出力すること(説明や前置き、鍵カッコは不要)。"""
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        if text:
            return text
    except Exception as e:  # noqa: BLE001
        print(f"[warn] threads text generation failed, using fallback: {e}")
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
    title, memo, images = load_entry(date)
    if title is None and memo is None and not images:
        print(f"[skip] no entry for {date}")
        return
    if not images:
        print(f"[skip] no screenshots for {date} (memo only is not enough for a story)")
        return

    cfg = json.loads((DEVLOG / "config.json").read_text(encoding="utf-8"))

    caption = title or fallback_caption(memo or "")
    threads_text = gen_threads_text(title or "", memo or "", cfg)

    out_dir = DEVLOG / "out" / date
    out_dir.mkdir(parents=True, exist_ok=True)

    template = (DEVLOG / "template.html").read_text(encoding="utf-8")
    date_disp = datetime.strptime(date, "%Y-%m-%d").strftime("%Y.%m.%d")
    html = (
        template.replace("{{DATE}}", date_disp)
        .replace("{{HERO_SRC}}", data_url(images[0]))
        .replace("{{CAPTION}}", caption)
        .replace("{{MEMO}}", (memo or "").replace("\n", "<br>"))
    )
    render_story(html, out_dir / "story.png")
    (out_dir / "threads.txt").write_text(threads_text, encoding="utf-8")

    latest = {
        "date": date,
        "story": f"out/{date}/story.png",
        "threads_text": threads_text,
        "screenshots": [f"entries/{date}/{p.name}" for p in images[:1]],
    }
    (DEVLOG / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] generated devlog for {date}")


if __name__ == "__main__":
    main()
