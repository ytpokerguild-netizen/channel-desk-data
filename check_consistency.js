/* ═══════════════════════════════════════════════════════════════════════════
   check_consistency.js — 2つの資料が同じ数字を出しているかを見張る
   ═══════════════════════════════════════════════════════════════════════════

   なぜ要るか（2026-08-28 外部レビュー6回目 §1）:
     `report.html`（提出用）と `report_brief.html`（画面用）が、同じ計算を
     それぞれのファイルに書き写して持っていました。**実際に分岐しました** —
     正式レポートのアクションが3件なのに、ブリーフは NEXT CHECK が4件でした。
     いまは `report_model.js` に集約してありますが、**集約したことは、
     誰かが片方に計算を書き戻さない保証にはなりません。**この検査がその見張りです。

   見るもの:
     A. 両方のHTMLが report_model.js を読み込んでいるか
     B. 両方のHTMLに、モデルにあるはずの計算が**書き戻されていないか**
     C. モデル自体が、週ごとに矛盾のない値を出しているか
     D. アクションの件数が、データの suggestions と一致しているか
        （⚠ オーナー判断をアクションに混ぜると、ここで落ちます）

   使い方:
       node check_consistency.js          # 表示するだけ。違反があれば終了コード 1

   ⚠ この検査は「数字が食い違っていないか」しか見ません。
     **数字が正しいかは人が読むしかありません。**
   ═══════════════════════════════════════════════════════════════════════════ */
'use strict';
const fs = require('fs');
const vm = require('vm');

const problems = [];
const ng = m => problems.push(m);

/* ── A. 読み込みと B. 書き戻しの検査 ───────────────────────── */
// ⚠ ここに挙げた名前は「モデルが持つべき計算」です。HTML側に**実装が**あったら違反。
//   （`M.cause(...)` のような**呼び出し**や、1行の委譲は違反ではありません）
const FORBIDDEN = [
  { re: /function\s+causeSplit\s*\([^)]*\)\s*\{(?![^}]*return\s+M\.cause)/,
    why: '増減要因の計算が書き戻されています（M.cause を使ってください）' },
  { re: /function\s+trafficSplitData\s*\([^)]*\)\s*\{(?![^}]*return\s+M\.trafficSplit)/,
    why: '「1本を除いた流入」の計算が書き戻されています（M.trafficSplit を使ってください）' },
  { re: /function\s+ownerState\s*\([^)]*\)\s*\{(?![^}]*return\s+M\.ownerState)/,
    why: 'オーナー判断の集約が書き戻されています（M.ownerState を使ってください）' },
  { re: /const\s+FLAT\s*=\s*\d/,
    why: '「横ばい」の帯がHTML側にあります（report_model.js の FLAT が唯一の定義です）' },
  { re: /=>\s*\(n\s*\/\s*10000\)\.toFixed/,
    why: '万への丸めが書き戻されています（M.fmtMan を使ってください）' },
  { re: /const\s+TRAFFIC_LABEL\s*=\s*\{\s*['"]/,
    why: '流入ラベルの表がHTML側にあります（M.TRAFFIC_LABEL を使ってください）' },
];

for (const f of ['report.html', 'report_brief.html']) {
  let s;
  try { s = fs.readFileSync(f, 'utf8'); }
  catch (e) { ng(`${f} を読めません: ${e.message}`); continue; }

  if (!/<script\s+src=["']report_model\.js["']\s*>/.test(s))
    ng(`${f} が report_model.js を読み込んでいません`);

  for (const { re, why } of FORBIDDEN)
    if (re.test(s)) ng(`${f}: ${why}`);
}

/* ── C・D. モデルを実際に動かして確かめる ───────────────────── */
let data, CDModel;
try {
  data = JSON.parse(fs.readFileSync('data.json', 'utf8'));
  const sandbox = { window: {}, console };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync('report_model.js', 'utf8'), sandbox);
  CDModel = sandbox.window.CDModel;
  if (!CDModel) ng('report_model.js が window.CDModel を作りませんでした');
} catch (e) {
  ng(`モデルを読み込めません: ${e.message}`);
}

if (CDModel && data) {
  const weeks = (data.weekly_reports || []).filter(w => w.ai_analysis);
  let checked = 0;

  for (const w of weeks) {
    const m = CDModel.build(data, w.week_start);
    const tag = w.week_start;
    if (!m) { ng(`${tag}: モデルを作れませんでした`); continue; }
    checked++;

    // 識別情報がそろっているか（レビュー6回目 §1）
    for (const k of ['report_id', 'model_version', 'data_version'])
      if (!m[k] && m[k] !== 0) ng(`${tag}: ${k} が空です`);

    // ★ D. アクションの件数。⚠⚠ ここが「3件 / 4件」の食い違いを捕まえる場所です。
    //   オーナー判断を actions に混ぜると、ここで落ちます。
    const sug = (w.ai_analysis.suggestions || []).length;
    if (m.actions.length !== sug)
      ng(`${tag}: アクションが ${m.actions.length}件。データの suggestions は ${sug}件です。`
       + `**オーナー判断をアクションに混ぜていませんか。**別の配列にしてください`);
    if (m.actions.some(a => !a.title))
      ng(`${tag}: タイトルの無いアクションがあります`);

    // オーナー判断は独立していること
    if (!m.owner || !m.owner.level) ng(`${tag}: owner が空です`);
    else if (!['none', 'confirm', 'approve', 'unset'].includes(m.owner.level))
      ng(`${tag}: owner.level が範囲外（${m.owner.level}）`);

    // C. 増減要因の合計が純増と一致するか（万に丸める前の生の値で見る）
    if (m.cause) {
      const c = m.cause;
      const diff = Math.abs((c.upSum + c.dnSum) - c.tot);
      if (diff > 1)   // 1回ぶんの誤差だけ許す（整数の丸め）
        ng(`${tag}: 増加要因＋減少要因 が純増と一致しません`
         + `（${c.upSum} + ${c.dnSum} = ${c.upSum + c.dnSum} ≠ ${c.tot}）`);
      if (c.tot !== c.views - c.viewsPrev)
        ng(`${tag}: 純増が「今週 − 前週」になっていません`);
    }

    // 前週比と「1本を除いた前週比」の向きが説明できること
    if (m.verdict) {
      const V = m.verdict;
      if (!V.headline) ng(`${tag}: 結論の見出しが空です`);
      if (!['増加', '減少', '横ばい'].includes(V.dirAll))
        ng(`${tag}: 判定の語彙が範囲外（${V.dirAll}）。増加／減少／横ばい のどれかにしてください`);
    }

    // 流入は実数と順位で持っていること（⚠ 構成比を持たせないこと）
    for (const t of m.traffic.rows) {
      if (t.now == null) ng(`${tag}: 流入 ${t.nm} の実数がありません`);
      if ('share' in t || 'pct' in t)
        ng(`${tag}: 流入に構成比が入っています。**構成比は出さない方針です**`);
    }
  }

  if (checked) console.log(`  モデルを ${checked}週ぶん確かめました`);
  else ng('確かめられる週がありませんでした');
}

/* ── 結果 ───────────────────────────────────────────────── */
if (!problems.length) {
  console.log('[OK] 2つの資料は同じモデルから作られています');
  process.exit(0);
}
console.log(`[NG] ${problems.length}件の問題があります`);
for (const p of problems) console.log('  ・' + p);
console.log('\n直し方: 計算は report_model.js に置き、HTML側は表示だけにしてください。');
process.exit(1);
