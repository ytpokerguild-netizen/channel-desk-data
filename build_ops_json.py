#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""運営ログ（非公開）→ ops.json（公開）変換スクリプト

使い方:
    python3 build_ops_json.py <運営ログ_非公開.xlsx のパス> [出力先=ops.json]

設計の要点:
  * 公開列が "○" の行だけを出力する。空欄・× は出力しない（既定は非公開）。
  * 担当者の実名は「担当マスタ」の公開表記に置き換える。担当列だけでなく本文中の実名も置換する。
  * 担当マスタに無い「〜さん」が本文に残っていたら「担当者」に潰し、警告を出す（社外名の流出防止）。
  * 備考は出力しない（機微が混ざりやすいため）。
  * 非公開にした件数だけは出力する（「見えていない項目がある」ことを隠さないため）。

この分離があるので、AI や人が「これは公開していいか」を毎回判断する必要がない。
判断はスプレッドシートの公開列を打つ瞬間だけ、人が行う。
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone

try:
    from openpyxl import load_workbook
except ImportError:
    sys.exit("openpyxl が必要です: pip install openpyxl --break-system-packages")

JST = timezone(timedelta(hours=9))
PUBLIC_MARK = "○"


def norm(v):
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()


def find_header_row(ws, required):
    """ヘッダ行を探す（1行目に注意書きが入る場合があるため位置を決め打ちしない）"""
    for r in range(1, min(ws.max_row, 6) + 1):
        vals = [norm(c.value) for c in ws[r]]
        if all(k in vals for k in required):
            return r, {name: i for i, name in enumerate(vals) if name}
    raise SystemExit(f"[{ws.title}] ヘッダ行が見つかりません。必要な列: {required}")


def rows_of(ws, required):
    hrow, idx = find_header_row(ws, required)
    for r in range(hrow + 1, ws.max_row + 1):
        vals = [norm(c.value) for c in ws[r]]
        if not any(vals):
            continue
        yield {name: (vals[i] if i < len(vals) else "") for name, i in idx.items()}


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else "ops.json"

    wb = load_workbook(src, data_only=True)

    # ── 担当マスタ（実名 → 公開表記）──
    owner_map = {}
    if "担当マスタ" in wb.sheetnames:
        for row in rows_of(wb["担当マスタ"], ["内部名", "公開表記"]):
            if row["内部名"]:
                owner_map[row["内部名"]] = row["公開表記"] or row["内部名"]

    def pub_owner(name):
        if not name:
            return "未定"
        if name in owner_map:
            return owner_map[name]
        # マスタに無い名前は実名を出さない（事故防止）
        print(f"  [WARN] 担当マスタに '{name}' がありません → '担当者' として出力します")
        return "担当者"

    HONORIFIC = re.compile(r"[぀-ヿ一-鿿A-Za-zＡ-Ｚａ-ｚ]{1,8}(?:さん|様|氏)")

    def mask(text):
        """本文中の実名を公開表記に置換し、未知の人名は潰す"""
        if not text:
            return text
        for internal, public in owner_map.items():
            if internal and internal in text:
                text = text.replace(internal, public)

        def _sub(m):
            print(f"  [WARN] 担当マスタに無い人名 '{m.group(0)}' を本文で検出 → '担当者' に置換しました")
            return "担当者"

        return HONORIFIC.sub(_sub, text)

    hidden = {}

    # ── 宿題 ──
    action_items, hid = [], 0
    for row in rows_of(wb["宿題"], ["内容", "担当", "期限", "状態", "公開"]):
        if not row["内容"]:
            continue
        if row["公開"] != PUBLIC_MARK:
            hid += 1
            continue
        action_items.append({
            "text":   mask(row["内容"]),
            "owner":  pub_owner(row["担当"]),
            "due":    row["期限"],
            "status": row["状態"] or "未着手",
            "meeting_date": row.get("会議日", ""),
        })
    hidden["action_items"] = hid

    # ── 決定事項 ──
    decisions, hid = [], 0
    for row in rows_of(wb["決定事項"], ["決定内容", "分類", "公開"]):
        if not row["決定内容"]:
            continue
        if row["公開"] != PUBLIC_MARK:
            hid += 1
            continue
        decisions.append({
            "date":     row.get("会議日", ""),
            "text":     mask(row["決定内容"]),
            "category": row["分類"],
        })
    hidden["decisions"] = hid

    # ── 施策ログ ──
    measures, hid = [], 0
    for row in rows_of(wb["施策ログ"], ["施策内容", "対象", "狙う指標", "公開"]):
        if not row["施策内容"]:
            continue
        if row["公開"] != PUBLIC_MARK:
            hid += 1
            continue
        measures.append({
            "start":  row.get("開始日", ""),
            "end":    row.get("終了日", ""),
            "text":   mask(row["施策内容"]),
            "target": row["対象"],
            "metric": row["狙う指標"],
        })
    hidden["measures"] = hid

    # 状態順 → 期限順 に並べる
    order = {"進行中": 0, "未着手": 1, "保留": 2, "完了": 3, "見送り": 4}
    action_items.sort(key=lambda a: (order.get(a["status"], 9), a["due"]))

    out = {
        "updated_at": datetime.now(JST).strftime("%Y-%m-%d"),
        "source": "運営ログ（非公開・Dropbox「PGコンソール」）",
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


if __name__ == "__main__":
    main()
