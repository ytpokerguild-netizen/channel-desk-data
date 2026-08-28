/* ═══════════════════════════════════════════════════════════════════════════
   report_model.js — 週次レポートの数字を、ここで1回だけ確定させる
   ═══════════════════════════════════════════════════════════════════════════

   なぜ要るか（2026-08-28 外部レビュー6回目）:
     `report.html`（提出用・明色・A4）と `report_brief.html`（画面用・暗色）の
     2つが、**同じ計算をそれぞれのファイルに書き写して**持っていました。
     それは共通化ではなく複製です。**実際に分岐が起きました** — 正式レポートの
     アクションが3件なのに、ブリーフには `NEXT CHECK` が4件ありました
     （4件目はオーナー判断で、種類の違うものが混ざっていた）。

   ⚠⚠ **この2つのHTMLに計算を書き戻さないこと。**
     HTML側は「表示」だけを担当します。次のものは必ずここから取ります:
       前週比 ／ 最大寄与1本を除いた前週比 ／ 増加要因・減少要因 ／ 流入順位 ／
       1本を除いた流入数 ／ 新作初速の中央値 ／ アクションの件数と中身 ／
       オーナー判断の集約 ／ 万への丸め方
   ⚠ 数字の見た目（fmtMan など）もここに置いてあります。丸め方が片方だけ変わると、
     同じ週の同じ指標が2つの資料で食い違います。**HTML側で定義し直さないこと。**

   ★ MODEL_VERSION は、**出てくる数字の意味が変わったときだけ**上げます。
     表示の変更では上げません。両方のHTMLに出るので、食い違いに気づく手がかりになります。
   ═══════════════════════════════════════════════════════════════════════════ */
(function (global) {
  'use strict';

  const MODEL_VERSION = 4;

  // YouTube Studio の表記に準拠（APIの値 → Studio の日本語ラベル）
  // ⚠ これを両方のHTMLに複製しないこと。ラベルがずれると別経路に見えます。
  const TRAFFIC_LABEL = {
    'SUBSCRIBER':'ブラウジング機能','YT_SEARCH':'YouTube検索','SHORTS':'ショートフィード',
    'EXT_URL':'外部','NOTIFICATION':'通知','RELATED_VIDEO':'関連動画',
    'BROWSE':'ブラウジング機能','CHANNEL':'チャンネルページ','YT_CHANNEL':'チャンネルページ',
    'DIRECT':'直接入力','ADVERTISING':'広告','PLAYLIST':'再生リスト',
    'END_SCREEN':'終了画面','NO_LINK_EMBEDDED':'埋め込み','OTHER':'その他',
    'ANNOTATION':'アノテーション','CAMPAIGN_CARD':'プロモーション',
    'SHORTS_CONTENT_LINKS':'ショート内リンク','YT_OTHER_PAGE':'その他のYouTube機能',
    'NO_LINK_OTHER':'直接入力または不明','SOUND_PAGE':'音源ページ','HASHTAGS':'ハッシュタグ',
    '3':'ブラウジング','9':'YouTube検索','10':'関連動画','4':'チャンネルページ',
    '5':'外部サイト','7':'Google検索','19':'通知','18':'エンドスクリーン',
    '11':'再生リスト','0':'直接/不明','1':'広告','17':'プロモーション','8':'その他'
  };
  const SRC = st => TRAFFIC_LABEL[String(st)] || String(st);

  // ⚠ 「横ばい」の帯は ±5%。±3% にすると +3.0% が「増加」に化け、この見出しの目的
  //   （土台が動いたかどうか）が逆に伝わります（2026-08-28 に実際に起きた）。
  //   ⚠ 変えるときは過去26週ぶんで判定が変わらないことを確かめてから。
  const FLAT = 5;

  const OWNER_GATE_RANK = { none: 0, confirm: 1, approve: 2 };
  const ACTION_KINDS    = ['実行', '検証', '分析', '計測整備'];

  /* ── 見た目の共通ルール ────────────────────────────────
     ⚠ 丸め方はここだけ。両方のHTMLがこれを使います。 */
  const fmtFull = n => (n == null ? 0 : n).toLocaleString('ja-JP');
  // 日本語では 587,400回 より 58.7万回 のほうが一瞬で入ります。
  // ⚠ ツールチップと表の小さい数字には生の値を残すこと。万に丸めると精密な比較ができません。
  const fmtMan  = n => (n == null) ? '—' : (Math.abs(n) >= 10000
                      ? (n / 10000).toFixed(1).replace(/\.0$/, '') + '万'
                      : n.toLocaleString('ja-JP'));
  const fmtDate = s => s ? String(s).replace(/-/g, '/') : '';
  const md      = s => s ? String(s).slice(5).replace('-', '/').replace(/^0/, '') : '';
  const fmtMin  = m => m >= 60 ? Math.round(m / 60).toLocaleString() + '時間'
                               : (m || 0).toLocaleString() + '分';
  const esc     = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const pctNum  = (a, b) => (b == null || !b) ? null : (a - b) / b * 100;
  const pct     = (a, b) => { const v = pctNum(a, b);
                              return v == null ? '—' : (v >= 0 ? '+' : '') + v.toFixed(1) + '%'; };
  const median  = a => { if (!a || !a.length) return null;
                         const s = [...a].sort((x, y) => x - y), m = s.length >> 1;
                         return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };

  /* ── 増減要因 ────────────────────────────────────────
     合計は必ず一致させること: 増加要因 + 減少要因 === 今週 − 前週。
     top_videos は上位8本ぶんしかないので、それ以外は「その他」に入れ、符号の側へ寄せます。
     ⚠ 「増加分の87%を1本が占める」という割合は出さないこと。分母が純増なので、
       純増が小さい週は200%や500%になり、純減の週は意味が成立しません。 */
  function cause(rep, views, viewsPrev) {
    const all = (rep.top_videos || []).map(v => ({
      t: v.title, short: v.short_title || '', pub: v.published_at || '',
      d: (v.views_week || 0) - (v.views_prev_week || 0)
    }));
    if (!all.length || viewsPrev == null) return null;
    const tot     = views - viewsPrev;
    const restRaw = tot - all.reduce((s, x) => s + x.d, 0);   // 上位8本の外にあるぶん（正味）
    const ups = all.filter(x => x.d > 0).sort((a, b) => b.d - a.d);
    const dns = all.filter(x => x.d < 0).sort((a, b) => a.d - b.d);
    const upOther = ups.slice(3).reduce((s, x) => s + x.d, 0) + Math.max(0, restRaw);
    const dnOther = dns.slice(3).reduce((s, x) => s + x.d, 0) + Math.min(0, restRaw);
    // ⚠ ここで {t,d} だけに絞らないこと。short_title / published_at が落ちて、
    //   見出しが「最大の1本」に化けます（2026-08-28 に実際に起きた）。
    const upRows = ups.slice(0, 3).map(x => ({ ...x }));
    const dnRows = dns.slice(0, 3).map(x => ({ ...x }));
    // ⚠ 両側に同じ名前の「その他」を出さないこと。同じ項目が両側にあるように見えます。
    if (upOther > 0) upRows.push({ t: 'その他の増加要因', d: upOther, other: true });
    if (dnOther < 0) dnRows.push({ t: 'その他の減少要因', d: dnOther, other: true });
    const upSum = upRows.reduce((s, x) => s + x.d, 0);
    const dnSum = dnRows.reduce((s, x) => s + x.d, 0);
    return { tot, upRows, dnRows, upSum, dnSum, views, viewsPrev, top: ups[0] || null };
  }

  /* ── 流入 ────────────────────────────────────────── */
  function trafficList(rep) {
    const list = (rep.traffic_sources || []).slice().sort((a, b) => b.views - a.views);
    const prev = new Map((rep.traffic_sources_prev || []).map(t => [String(t.source_type), t.views]));
    const prevRank = new Map([...prev.entries()].sort((a, b) => b[1] - a[1])
                                                .map(([k], i) => [String(k), i + 1]));
    return { list, prev, prevRank };
  }
  // 順位つきの読みやすい形（ブリーフ用。report.html は list/prev をそのまま使います）
  function trafficRows(rep, n) {
    const { list, prev, prevRank } = trafficList(rep);
    return list.slice(0, n || 5).map((t, i) => {
      const st = String(t.source_type), pr = prevRank.get(st) ?? null, rank = i + 1;
      return { st, nm: SRC(st), now: t.views, prev: prev.get(st) ?? null, rank, prank: pr,
               moved: !!(pr && pr !== rank && (rank <= 3 || pr <= 3)) };
    });
  }
  /* 首位経路から「いちばん多い1本」を引いた残りが前週を超えるか。
     ⚠ video_traffic は上位5本ぶんしかありません。「それ以外」には6本目以降と
       過去動画がまとめて入ります。1本を引く以上のことはできません。 */
  function trafficSplit(rep) {
    const vt = rep.video_traffic;
    const { list, prev } = trafficList(rep);
    if (!vt || !list.length) return null;
    const t0 = list[0], st = String(t0.source_type);
    const p0 = prev.get(st);
    if (p0 == null || !t0.views) return null;

    const titles = {};
    (rep.top_videos || []).forEach(v => { titles[v.video_id] = v.title; });
    (rep.new_videos || []).forEach(v => { if (v.video_id) titles[v.video_id] = v.title; });

    const rows = Object.keys(vt).map(vid => {
      const m = (vt[vid] || []).find(r => String(r.source_type) === st);
      return { vid, v: m ? m.views : 0 };
    }).filter(r => r.v > 0).sort((a, b) => b.v - a.v);
    if (!rows.length) return null;

    const top = rows[0], rest = t0.views - top.v;
    return { nm: SRC(st), now: t0.views, p0, top, rest,
             title: titles[top.vid] || top.vid, restBeatsPrev: rest > p0 };
  }

  /* ── 結論の判定 ──────────────────────────────────── */
  function verdict(rep, views, viewsPrev) {
    if (viewsPrev == null || !viewsPrev) return null;
    const S    = cause(rep, views, viewsPrev);
    const tot  = views - viewsPrev;
    const dp   = tot / viewsPrev * 100;
    // 最大の増加要因（1本）を除いた前週比。「土台が動いたか」を見るための数字
    const topD = S && S.upRows.length ? S.upRows[0].d : 0;
    const base = (tot - topD) / viewsPrev * 100;
    // ⚠ 語彙は「増加／減少／横ばい」。「伸長」「土台」は抽象的で、
    //   数字が専門でない読み手にそのままは伝わりません。
    const dir  = v => v >= FLAT ? '増加' : v <= -FLAT ? '減少' : '横ばい';
    const head = dir(dp) === dir(base)
        ? `視聴は${dir(dp)}。1本を除いても${dir(base)}`
        : `視聴は${dir(dp)}。ただし1本を除くと${dir(base) === '横ばい' ? 'ほぼ横ばい' : dir(base)}`;
    return { tot, deltaPct: dp, baselinePct: base,
             dirAll: dir(dp), dirBase: dir(base), headline: head, top: S && S.top };
  }

  /* ── オーナー判断 ────────────────────────────────────
     ⚠⚠ 値が無いときに「判断不要」を既定にしないこと。入力漏れが
       「オーナーのやることは無い」としてそのまま提出される事故になります。 */
  function ownerState(rep) {
    const ai  = rep.ai_analysis || {};
    const raw = (ai.owner_decision || '').trim();
    if (raw) return { level: /要承認/.test(raw) ? 'approve' : /要確認/.test(raw) ? 'confirm' : 'none',
                      text: raw, derived: false };
    const gates = (ai.suggestions || []).map(s => (s && s.owner_gate) || '')
                                        .filter(g => g in OWNER_GATE_RANK);
    if (gates.length) {
      const lv = gates.reduce((a, b) => OWNER_GATE_RANK[b] > OWNER_GATE_RANK[a] ? b : a, 'none');
      return { level: lv, derived: true,
               text: lv === 'approve' ? 'アクションから集約しました。何を承認してほしいか・推奨案・費用または影響・期限を書いてください'
                   : lv === 'confirm' ? 'アクションから集約しました。確認事項を1つに絞って書いてください'
                   : '判断不要' };
    }
    return { level: 'unset', text: '未設定', derived: false };
  }
  const stripLevel = t => String(t).replace(/^(判断不要|要確認|要承認)[｜|：:\s]*/, '');

  /* ── アクション ──────────────────────────────────────
     ★ ここが「件数がずれた」原因の場所です（レビュー6回目）。
     ⚠⚠ **オーナー判断をこの配列に混ぜないこと。**
       04「次週のアクション」＝ 運営が何をするか、
       オーナー判断        ＝ オーナーに何をしてほしいか、で種類が違います。
       ブリーフの `NEXT CHECK` に4件目としてオーナー判断を足したせいで、
       正式レポート3件・ブリーフ4件という食い違いが出ました。**別の配列・別の表示にすること。** */
  function actions(rep) {
    const sug = (rep.ai_analysis || {}).suggestions || [];
    return sug.map((s, i) => ({
      n: i + 1,
      kind: s.kind || '',
      title: s.title || '',
      lead: (s.actions || [])[0] || '',            // 何が分かるか（1行）
      details: (s.actions || []).slice(1)          // 詳しい確認方法
    }));
  }

  /* ── 新作の初速 ────────────────────────────────────
     ⚠ 平均は使わないこと。1本だけ突出する週があり、実態より高く出ます。 */
  function firstSpeed(rep, prevRep) {
    const cur  = (rep.new_videos || []).filter(v => v.first2d > 0)
                                       .slice().sort((a, b) => b.first2d - a.first2d);
    const prev = prevRep ? (prevRep.new_videos || []).filter(v => v.first2d > 0) : [];
    const m  = median(cur.map(v => v.first2d));
    const mp = median(prev.map(v => v.first2d));
    return { list: cur, count: cur.length, prevCount: prev.length,
             median: m, medianPrev: mp, medianPct: (m != null && mp) ? pctNum(m, mp) : null,
             max: cur.length ? cur[0].first2d : null };
  }

  /* ── クーポン ────────────────────────────────────── */
  function coupon(data, rep) {
    const C = data.coupon;
    if (!C || C.error) return null;
    const wk = (C.weekly || []).find(w => w.week_start === rep.week_start);
    if (!wk) return null;
    const st = new Date(rep.week_start + 'T00:00:00Z');
    const en = new Date(rep.week_start + 'T00:00:00Z'); en.setUTCDate(en.getUTCDate() + 6);
    const daily = (C.daily || []).filter(r => {
      const t = new Date(r.date + 'T00:00:00Z'); return t >= st && t <= en && r.entries > 0;
    });
    const peak = daily.slice().sort((a, b) => b.entries - a.entries)[0] || null;
    return { entries: wk.entries, used: wk.used, people: wk.people, codes: wk.codes || [],
             daily, days: daily.length, peak, snapshot: C.snapshot_date || '' };
  }

  /* ── SIGNAL & LIMITS ───────────────────────────────
     ★ レビュー6回目 §4。「事実 / 示唆 / このデータからは言えないこと / 次の対応」の4つに分けます。
     ⚠⚠ クーポン専用の固定画面にしないこと。クーポンは運用詳細の話題で、
       毎週1画面を与えると「オーナーの主要テーマ」に見えます。
       **その週いちばん意思決定に関わる未確定事項を1つだけ**出し、無い週は画面ごと省きます。
     ⚠ 「報告上の扱い」という言い方はやめました。オーナーには内部的すぎます。→「次の対応」。 */
  function signal(data, rep) {
    const cp = coupon(data, rep);
    if (cp && cp.peak && cp.entries > 0) {
      const top1 = (rep.top_videos || [])[0];
      return {
        key: 'coupon',
        eyebrow: 'Signal & limits',
        headMain: `${md(cp.peak.date)}に、`,
        headBut : 'クーポン入力が集中。',
        fact: `${md(cp.peak.date)}のコード入力が ${cp.peak.entries}件で、この週のいちばん多い日でした。`
            + `今週の入力は合計 ${cp.entries}件、うち使用済み ${cp.used}件、実人数 ${cp.people}人です。`,
        implication: '公開日と入力の増えた日が近い、という時期の重なりまでは見えています。',
        cannotSay: 'コード・動画・掲出日が結び付いていません。動画アーカイブの掲出日列が空のままなので、'
                 + 'これは日付が近いという相関であって、どの動画が入力を連れてきたかは判定できません。',
        nextStep: '掲出日を入力し、動画別に判定できる状態にします。',
        detail: cp
      };
    }
    return null;   // ⚠ 無い週は画面ごと出さない。空の枠を出さないこと
  }

  /* ── ここで1回だけ確定させる ──────────────────────── */
  function build(data, weekStart) {
    const weeks = (data.weekly_reports || []).slice()
                    .sort((a, b) => a.week_start < b.week_start ? 1 : -1);
    const rep = weekStart ? weeks.find(w => w.week_start === weekStart)
                          : (weeks.find(w => w.final && w.ai_analysis) || weeks[0]);
    if (!rep) return null;
    const prevRep = weeks[weeks.indexOf(rep) + 1] || null;

    const c = rep.channel || {}, pp = rep.post_plan || {}, ai = rep.ai_analysis || {};
    const views = c.views, viewsPrev = c.views_prev;
    const hrs   = c.watch_min      != null ? Math.round(c.watch_min / 60)      : null;
    const hrsP  = c.watch_min_prev != null ? Math.round(c.watch_min_prev / 60) : null;
    const V = verdict(rep, views, viewsPrev);
    const F = firstSpeed(rep, prevRep);

    return Object.freeze({
      // ★ この5つは両方の資料に必ず出します（レビュー6回目 §1）。
      //   食い違いが起きたとき、どのデータのどのモデルで作ったかを突き合わせられます。
      report_id: `lightthree_${rep.week_start}_${rep.week_end}`,
      model_version: MODEL_VERSION,
      data_version: (data.meta || {}).fetched_at || '',
      generated_at: ai.generated_at || '',
      period: { start: rep.week_start, end: rep.week_end,
                prevStart: prevRep ? prevRep.week_start : null,
                prevEnd:   prevRep ? prevRep.week_end   : null },

      rep, prevRep, weeks,
      final: !!rep.final,
      confirmedDays: rep.confirmed_days ?? 7,

      metrics: {
        views, viewsPrev,
        deltaPct:    V ? V.deltaPct    : null,
        baselinePct: V ? V.baselinePct : null,
        watchHours: hrs, watchHoursPrev: hrsP,
        watchPct: (hrs != null && hrsP) ? pctNum(hrs, hrsP) : null,
        subsNet: c.subs_net, subsNetPrev: c.subs_net_prev,
        subsGained: c.subs_gained, subsLost: c.subs_lost, subscribersEnd: c.subscribers_end,
        newCount: (rep.new_videos || []).length,
        planned: pp.planned, posted: pp.posted,
        firstMedian: F.median, firstMedianPrev: F.medianPrev, firstMedianPct: F.medianPct
      },
      verdict: V,
      cause: cause(rep, views, viewsPrev),
      traffic: { rows: trafficRows(rep, 6), split: trafficSplit(rep) },
      first: F,
      coupon: coupon(data, rep),
      signal: signal(data, rep),
      actions: actions(rep),          // ⚠ オーナー判断はここに入れないこと
      owner: ownerState(rep)          // ⚠ アクションとは別物
    });
  }

  global.CDModel = {
    VERSION: MODEL_VERSION, TRAFFIC_LABEL, FLAT, OWNER_GATE_RANK, ACTION_KINDS,
    SRC, fmtFull, fmtMan, fmtDate, fmtMin, md, esc, pct, pctNum, median, stripLevel,
    cause, trafficList, trafficRows, trafficSplit, verdict, ownerState, actions,
    firstSpeed, coupon, signal, build
  };
})(window);
