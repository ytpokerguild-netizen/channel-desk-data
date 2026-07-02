#!/bin/bash
# ダッシュボードのパスワードを設定するスクリプト
# 使い方: bash set_password.sh → パスワードを入力（画面に表示されない）→ git push
cd "$(dirname "$0")"
python3 - <<'EOF'
import hashlib, getpass, re
pw = getpass.getpass("設定するパスワード: ")
pw2 = getpass.getpass("もう一度入力: ")
if pw != pw2:
    print("一致しません。やり直してください。"); raise SystemExit(1)
if not pw:
    print("空のパスワードは設定できません。"); raise SystemExit(1)
h = hashlib.sha256(pw.encode()).hexdigest()
s = open("index.html").read()
s2 = re.sub(r"const PW_HASH = '[^']*'", f"const PW_HASH = '{h}'", s)
if s == s2 and h not in s2:
    print("PW_HASH が見つかりませんでした。"); raise SystemExit(1)
open("index.html","w").write(s2)
print("設定完了。git add index.html && git commit && git push で反映されます。")
EOF
