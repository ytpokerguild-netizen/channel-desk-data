#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""運営ログ（非公開）→ ops.json（公開）変換スクリプト

入力は Google スプレッドシート「PG運営ログ（非公開）」の内容。シートは種別ごとに分かれている。

  宿題       内容 / 担当 / 期限 / 状態 / 公開 / 備考
  決定事項   内容 / 公開 / 備考
  施策       開始日 / 内容 / 公開 / 備考
  担当マスタ 内部名 / 公開表記 / 備考
  議事録     会議名 / 備考（URL・注意点）        ← ops.json には出さない

対応フォーマット（自動判別）:
  1. Markdown のパイプ表が複数連なったもの … Drive コネクタの read_file_content が返す形式。
     週次AI分析セッションはこれをそのままファイルに保存して渡すのが一番楽。
  2. .xlsx … スプレッドシートをダウンロードした場合（openpyxl が必要）。

使い方:
    python3 build_ops_json.py <入力ファイル> [出力先=ops.json]

設計の要点:
  * 公開列が "○" の行だけを出力する。空欄・× は出力しない（既定は非公開）。
  * 担当者の実名は 担当マスタ に従って公開表記へ置き換える。担当列だけでなく本文中の実名も置換する。
  * マスタに無い「〜さん / 〜様 / 〜氏」が本文に残っていたら「担当者」に潰し、警告を出す（社外名の流出防止）。
  * 備考は出力しない（機微が混ざりやすいため）。
  * 非公開にした件数だけは出力する（「見えていない項目がある」ことを隠さないため）。

この分離があるので、AI や人が「これは公開していいか」を毎回判断する必要がない。
判断はスプレッドシートの公開列を打つ瞬間だけ、人が行う。
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

# 公開とみなす表記（全角/半角・表記ゆれを吸収する。ここに無いものは全部「非公開」）
PUBLIC_TOKENS = {"○", "◯", "〇", "◎", "o", "yes", "y", "true", "1", "公開", "可"}

SEP_RE = re.compile(r"^:?-+:?$")  # Drive の出力は `:-:`（ハイフン1本）なので -{2,} では拾えない
HONORIFIC = re.compile(r"[぀-ヿ一-鿿A-Za-zＡ-Ｚａ-ｚ]{1,8}(?:さん|様|氏)")


def norm(v):
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip()
    # Markdown 表のエスケープを戻す（line\_notify.py → line_notify.py）
    return re.sub(r"\\([_*`\[\]|])", r"\1", s)


def parse_markdown_tables(text):
    """空行で区切られた複数の Markdown 表を [[行,...], ...] にする"""
    tables, cur = [], []
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            if cur:
                tables.append(cur)
                cur = []
            continue
        cells = [norm(c) for c in s.strip("|").split("|")]
        if cells and all(SEP_RE.fullmatch(c) for c in cells if c):
            continue  # 区切り行
        if any(cells):
            cur.append(cells)
    if cur:
        tables.append(cur)
    return tables


def parse_xlsx(path):
    try:
        from openpyxl import load_workbook
    except ImportError:
        sys.exit("xlsx を読むには openpyxl が必要です: pip install openpyxl --break-system-packages")
    wb = load_workbook(path, data_only=True)
    out = []
    for ws in wb:
        rows = [[norm(c) for c in r] for r in ws.iter_rows(values_only=True)]
        rows = [r for r in rows if any(r)]
        if rows:
            out.append(rows)
    return out


def as_dicts(table):
    """先頭の非空行をヘッダとみなして dict の列にする"""
    head = None
    body = []
    for row in table:
        if head is None:
            if any(row):
                head = row
            continue
        body.append({h: (row[i] if i < len(row) else "") for i, h in enumerate(head) if h})
    return head or [], body


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src, dst = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "ops.json")

    if src.lower().endswith((".xlsx", ".xlsm")):
        tables = parse_xlsx(src)
    else:
        with open(src, "r", encoding="utf-8") as f:
            tables = parse_markdown_tables(f.read())

    # ── どの表がどのシートかをヘッダで判定する（シート順に依存しない）──
    sheets = {}
    for t in tables:
        head, body = as_dicts(t)
        hs = set(head)
        if "内部名" in hs:
            key = "担当マスタ"
        elif "会議名" in hs:
            key = "議事録"
        elif "開始日" in hs:
            key = "施策"
        elif "状態" in hs and "担当" in hs:
            key = "宿題"
        elif "内容" in hs and "公開" in hs:
            key = "決定事項"
        else:
            continue
        sheets.setdefault(key, []).extend(body)

    missing = [k for k in ("宿題", "決定事項", "施策", "担当マスタ") if k not in sheets]
    if missing:
        sys.exit("次のシートが見つかりません: " + " / ".join(missing)
                 + "\n（Drive の read_file_content の結果をそのまま保存したファイルを渡してください）")

    warnings = []

    owner_map = {}
    for r in sheets["担当マスタ"]:
        if r.get("内部名"):
            owner_map[r["内部名"]] = r.get("公開表記") or r["内部名"]

    def mask(text):
        """本文中の実名を公開表記に置換し、未知の人名は潰す"""
        if not text:
            return text
        for internal, public in owner_map.items():
            if internal and internal in text:
                text = text.replace(internal, public)

        def _sub(m):
            warnings.append(f"担当マスタに無い人名 '{m.group(0)}' を本文で検出 → '担当者' に置換しました")
            return "担当者"

        return HONORIFIC.sub(_sub, text)

    def pub_owner(name):
        if not name:
            return "未定"
        if name in owner_map:
            return owner_map[name]
        warnings.append(f"担当マスタに '{name}' がありません → '担当者' として出力しました")
        return "担当者"

    def is_public(row):
        return row.get("公開", "").strip().lower() in {t.lower() for t in PUBLIC_TOKENS}

    hidden = {"action_items": 0, "decisions": 0, "measures": 0}

    action_items = []
    for r in sheets["宿題"]:
        if not r.get("内容"):
            continue
        if not is_public(r):
            hidden["action_items"] += 1
            continue
        action_items.append({
            "text":   mask(r["内容"]),
            "owner":  pub_owner(r.get("担当", "")),
            "due":    r.get("期限", ""),
            "status": r.get("状態") or "未着手",
        })

    decisions = []
    for r in sheets["決定事項"]:
        if not r.get("内容"):
            continue
        if not is_public(r):
            hidden["decisions"] += 1
            continue
        decisions.append({"text": mask(r["内容"])})

    measures = []
    for r in sheets["施策"]:
        if not r.get("内容"):
            continue
        if not is_public(r):
            hidden["measures"] += 1
            continue
        measures.append({"start": r.get("開始日", ""), "text": mask(r["内容"])})

    order = {"進行中": 0, "未着手": 1, "保留": 2, "完了": 3, "見送り": 4}
    action_items.sort(key=lambda a: (order.get(a["status"], 9), a["due"]))

    out = {
        "updated_at": datetime.now(JST).strftime("%Y-%m-%d"),
        "source": "PG運営ログ（非公開・Google スプレッドシート）",
        "note": "公開列が○の項目のみ。担当は役割表記に置き換え済み。",
        "hidden_counts": hidden,
        "action_items": action_items,
        "decisions": decisions,
        "measures": measures,
    }
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)

    print(f"{dst} を書き出しました: 宿題{len(action_items)}件 / 決定事項{len(decisions)}件 / 施策{len(measures)}件")
    print(f"  非公開のため除外: 宿題{hidden['action_items']} / 決定事項{hidden['decisions']} / 施策{hidden['measures']}")
    no_start = sum(1 for m in measures if not m["start"])
    if no_start:
        print(f"  ※ 開始日が空の施策が {no_start} 件あります（数字の前後比較ができません）")
    if warnings:
        print("\n⚠ 確認してください（止まって報告すること）:")
        for w in dict.fromkeys(warnings):
            print("  - " + w)


if __name__ == "__main__":
    main()
