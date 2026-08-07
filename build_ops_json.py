#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""運営ログ（非公開）→ ops.json（公開）変換スクリプト

入力は Google スプレッドシート「PG運営ログ（非公開）」の内容。次の3形式を自動判別する。

  1. Markdown のパイプ表（`|` 始まり）… Google Drive コネクタの read_file_content が返す形式。
     週次AI分析セッションはこれをそのままファイルに保存して渡すのが一番楽。
  2. CSV / TSV … スプレッドシートを「ファイル > ダウンロード > CSV」した場合。
  3. .xlsx … Dropbox に置いたバックアップを使う場合（openpyxl が必要）。

使い方:
    python3 build_ops_json.py <入力ファイル> [出力先=ops.json]

設計の要点:
  * 公開列が "○" の行だけを出力する。空欄・× は出力しない（既定は非公開）。
  * 担当者の実名は 種別=担当マスタ の行に従って公開表記へ置き換える。担当列だけでなく本文中の実名も置換する。
  * マスタに無い「〜さん / 〜様 / 〜氏」が本文に残っていたら「担当者」に潰し、警告を出す（社外名の流出防止）。
  * 備考は出力しない（機微が混ざりやすいため）。
  * 非公開にした件数だけは出力する（「見えていない項目がある」ことを隠さないため）。

この分離があるので、AI や人が「これは公開していいか」を毎回判断する必要がない。
判断はスプレッドシートの公開列を打つ瞬間だけ、人が行う。
"""
import csv
import io
import json
import re
import sys
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

# 公開とみなす表記（全角/半角・表記ゆれを吸収する。ここに無いものは全部「非公開」）
PUBLIC_TOKENS = {"○", "◯", "〇", "◎", "o", "O", "ｏ", "Ｏ", "yes", "y", "true", "1", "公開", "可"}

HEADERS = ["種別", "日付", "内容", "担当", "期限", "状態", "分類・対象", "狙う指標", "公開", "備考"]
KIND_OWNER, KIND_MINUTES, KIND_DECISION, KIND_HW, KIND_MEASURE = (
    "担当マスタ", "議事録", "決定事項", "宿題", "施策")


def norm(v):
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip()
    # Markdown 表のエスケープを戻す（line\_notify.py → line_notify.py）
    return re.sub(r"\\([_*`\[\]|])", r"\1", s)


def parse_markdown_table(text):
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [norm(c) for c in line.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c or "-") and set(c) <= set(":- ") for c in cells if c):
            continue  # 区切り行
        if not any(cells):
            continue  # 空行（Drive が先頭に付ける空ヘッダ）
        rows.append(cells)
    return rows


def parse_delimited(text):
    delim = "\t" if text.count("\t") > text.count(",") else ","
    return [[norm(c) for c in r] for r in csv.reader(io.StringIO(text), delimiter=delim) if any(r)]


def parse_xlsx(path):
    try:
        from openpyxl import load_workbook
    except ImportError:
        sys.exit("xlsx を読むには openpyxl が必要です: pip install openpyxl --break-system-packages")
    wb = load_workbook(path, data_only=True)
    ws = wb[wb.sheetnames[0]]
    out = []
    for r in ws.iter_rows(values_only=True):
        cells = [norm(c) for c in r]
        if any(cells):
            out.append(cells)
    return out


def load_rows(path):
    if path.lower().endswith((".xlsx", ".xlsm")):
        return parse_xlsx(path)
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    return parse_markdown_table(text) if "|" in text.split("\n")[0] else parse_delimited(text)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else "ops.json"

    raw = load_rows(src)

    # ── ヘッダ行を探す（先頭に空行や注記が入っても動くように）──
    hidx = None
    for i, row in enumerate(raw[:8]):
        if "種別" in row and "公開" in row and "内容" in row:
            hidx = i
            break
    if hidx is None:
        sys.exit("ヘッダ行が見つかりません。1行目に " + " / ".join(HEADERS) + " が必要です")
    head = raw[hidx]
    col = {name: i for i, name in enumerate(head) if name}
    missing = [h for h in HEADERS if h not in col]
    if missing:
        sys.exit("列が足りません: " + " / ".join(missing))

    def cell(row, name):
        i = col[name]
        return row[i] if i < len(row) else ""

    body = [r for r in raw[hidx + 1:] if any(r)]

    # ── 担当マスタ ──
    owner_map = {}
    for r in body:
        if cell(r, "種別") == KIND_OWNER and cell(r, "内容"):
            owner_map[cell(r, "内容")] = cell(r, "担当") or cell(r, "内容")

    warnings = []
    HONORIFIC = re.compile(r"[぀-ヿ一-鿿A-Za-zＡ-Ｚａ-ｚ]{1,8}(?:さん|様|氏)")

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
        return cell(row, "公開").strip().lower() in {t.lower() for t in PUBLIC_TOKENS}

    action_items, decisions, measures = [], [], []
    hidden = {"action_items": 0, "decisions": 0, "measures": 0}

    for r in body:
        kind, text = cell(r, "種別"), cell(r, "内容")
        if not text or kind in (KIND_OWNER, KIND_MINUTES):
            continue
        if kind == KIND_HW:
            if not is_public(r):
                hidden["action_items"] += 1
                continue
            action_items.append({
                "text": mask(text),
                "owner": pub_owner(cell(r, "担当")),
                "due": cell(r, "期限"),
                "status": cell(r, "状態") or "未着手",
                "meeting_date": cell(r, "日付"),
            })
        elif kind == KIND_DECISION:
            if not is_public(r):
                hidden["decisions"] += 1
                continue
            decisions.append({
                "date": cell(r, "日付"),
                "text": mask(text),
                "category": cell(r, "分類・対象"),
            })
        elif kind == KIND_MEASURE:
            if not is_public(r):
                hidden["measures"] += 1
                continue
            measures.append({
                "start": cell(r, "日付"),
                "end": "",
                "text": mask(text),
                "target": cell(r, "分類・対象"),
                "metric": cell(r, "狙う指標"),
            })
        else:
            warnings.append(f"未知の種別 '{kind}' の行を無視しました: {text[:24]}")

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
    if warnings:
        print("\n⚠ 確認してください（止まって報告すること）:")
        for w in dict.fromkeys(warnings):
            print("  - " + w)


if __name__ == "__main__":
    main()
