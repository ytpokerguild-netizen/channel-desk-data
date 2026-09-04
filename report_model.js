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

  /* ── 期間レポート（2026-09-04 追加。運営者の依頼「月次・3ヶ月・6ヶ月・年初来のレポートがほしい」）──
     `data.json` の `period_summary.months`（fetch.py が生成）を、期間ごとに足し上げます。
     ⚠⚠ **表示側で `video_daily.json` を読む形に変えないこと。**既存/新作の分解も初速も
       fetch.py 側で済んでいます。約2.6MB をページを開くたびに取りに行くことになります。

     足してよいもの（＝月の値をそのまま合計できるもの）:
       views / watch_min / base_views / new_views / video_count / subs_* / days
     ⚠ **`new_ratio_pct` は足せません。**割合なので、合計してから割り直します。
       分母は `base+new` です（`views` ではありません。集計元が違うので一致しません）。
     ⚠⚠ **初速の中央値は期間をまたいで合成できません。**中央値の中央値は中央値ではない
       ためです。月ごとの中央値と本数をそのまま並べて返し、画面もそう出しています。
       **ここで平均を取って「期間の初速」と名づけないこと。**

     前期の取り方: 同じ長さの直前の期間（3ヶ月なら、その前の3ヶ月）。
     ⚠ 年初来だけは比較しません。**前年の同じ月が手元に無いためです**（月は12ヶ月ぶんしか
       持っていません）。無いものを「—」と出すこと。ここを埋めるために月数を増やすのは、
       data.json が重くなるので別の判断が要ります。 */
  const SPANS = { month:{take:1,label:'今月'}, m3:{take:3,label:'直近3ヶ月'},
                  m6:{take:6,label:'直近6ヶ月'}, ytd:{take:0,label:'年初来'} };

  function aggPeriod(rs) {
    if (!rs || !rs.length) return null;
    const sum  = k => rs.reduce((a, r) => a + (r[k] || 0), 0);
    const days = sum('days'), views = sum('views');
    const base = sum('base_views'), fresh = sum('new_views');
    const vc   = sum('video_count');
    // 平均尺は本数で重み付け（月ごとの単純平均にすると、本数の少ない月が同じ重みになる）
    const durW = rs.reduce((a, r) => a + (r.avg_duration_sec || 0) * (r.video_count || 0), 0);
    return {
      from: rs[0].start, to: rs[rs.length - 1].end, monthCount: rs.length, days,
      views, viewsPerDay: days ? Math.round(views / days) : null,
      watchMin: sum('watch_min'),
      baseViews: base, basePerDay: days ? Math.round(base / days) : null,
      newViews: fresh,
      newRatioPct: (base + fresh) ? +(fresh / (base + fresh) * 100).toFixed(1) : null,
      videoCount: vc, avgDurationSec: vc ? Math.round(durW / vc) : null,
      subsGained: sum('subs_gained'), subsLost: sum('subs_lost'), subsNet: sum('subs_net'),
      speedByMonth: rs.map(r => ({ key: r.key, median: r.speed2_median, n: r.speed2_n }))
    };
  }

  /* 期間の合計を analytics_daily（チャンネル全体の日次。2022年からの4年分がある）から出す。
     ⚠ ここでしか出せないもの: **前年同期**。period_summary は12ヶ月ぶんしか無いので、
       年初来の比較相手が作れませんでした。日次はもっと遡れるので、そちらから取ります。
     ⚠ 日次にあるのは views / watch_min / subs のみ。**既存/新作の分解と初速はありません**
       （video_daily.json が要る）。分解が要る数字は period_summary から取ること。 */
  function dailySpan(data, from, to) {
    const ad = (data && data.analytics_daily) || [];
    let views = 0, watch = 0, g = 0, l = 0, days = 0;
    for (const r of ad) {
      if (r.date < from || r.date > to) continue;
      if (!(r.views > 0)) continue;               // 未確定日は数えない
      views += r.views || 0; watch += r.watch_min || 0;
      g += r.subs_gained || 0; l += r.subs_lost || 0; days++;
    }
    if (!days) return null;
    return { from, to, days, views, viewsPerDay: Math.round(views / days),
             watchMin: watch, subsGained: g, subsLost: l, subsNet: g - l };
  }
  const shiftYear = (d, n) => { const t = new Date(d + 'T00:00:00Z');
    t.setUTCFullYear(t.getUTCFullYear() + n); return t.toISOString().slice(0, 10); };

  /* その期間に公開した動画の顔ぶれ。videos と video_archive（企画タイプ／ナレーター／クーポン）から。
     ⚠ `videos[].views` は**公開以来の累計**です。期間内の再生数ではありません。画面でもそう書くこと。 */
  function periodVideos(data, from, to) {
    const vs = (data && data.videos) || [], ar = (data && data.video_archive) || {};
    const inRange = vs.filter(v => { const d = String(v.published_at || '').slice(0, 10);
      return d >= from && d <= to; });
    const tally = key => {
      const m = new Map();
      for (const v of inRange) { const k = (ar[v.video_id] || {})[key]; if (!k) continue;
        m.set(k, (m.get(k) || 0) + 1); }
      return [...m.entries()].map(([name, count]) => ({ name, count })).sort((x, y) => y.count - x.count);
    };
    return {
      count: inRange.length,
      types: tally('type'), narrators: tally('narrator'),
      couponCount: inRange.filter(v => (ar[v.video_id] || {}).coupon).length,
      top: inRange.slice().sort((a, b) => (b.views || 0) - (a.views || 0)).slice(0, 3)
             .map(v => ({ video_id: v.video_id, title: v.title, views: v.views,
                          published_at: String(v.published_at || '').slice(0, 10) }))
    };
  }

  /* 同じ長さの期間を過去にさかのぼって並べ、いまがその中でどこかを返す。
     ⚠ 「前期比だけでは読み違える」ため（週次の「26週の中での位置」と同じ考え方）。
       2026-08 の週次で、前週比 -51.9% でも26週平均の106%だった例があります。
     ⚠ 比べるのは**日あたり**。区間の日数がそろわない端は捨てます（90%未満は使わない）。
     ⚠ 日次は2022-09からありますが、**初期は動画がほとんど無く数百回/日です。**
       「過去最高」と出たときに誇らしく見えすぎないよう、画面では2位の値も併記すること。 */
  function periodRank(data, from, to) {
    const ad = (data && data.analytics_daily) || [];
    const byDate = new Map();
    for (const r of ad) if (r.views > 0) byDate.set(r.date, r);
    const dates = [...byDate.keys()].sort();
    if (!dates.length) return null;
    const day = s => new Date(s + 'T00:00:00Z');
    const iso = t => t.toISOString().slice(0, 10);
    const L = Math.round((day(to) - day(from)) / 86400000) + 1;
    if (L < 7) return null;

    const avg = (s, e) => {
      let sum = 0, n = 0;
      for (const d of dates) { if (d < s) continue; if (d > e) break; sum += byDate.get(d).views; n++; }
      return n >= L * 0.9 ? { perDay: Math.round(sum / n), start: s, n } : null;
    };
    const cur = avg(from, to);
    if (!cur) return null;

    const past = [];
    let end = new Date(day(from) - 86400000);
    for (let i = 0; i < 40; i++) {
      const st = new Date(end - (L - 1) * 86400000);
      if (iso(st) < dates[0]) break;
      const v = avg(iso(st), iso(end));
      if (v) past.push(v);
      end = new Date(st - 86400000);
    }
    if (!past.length) return null;
    const above = past.filter(x => x.perDay >= cur.perDay).length;
    const runnerUp = past.slice().sort((a, b) => b.perDay - a.perDay)[0];
    return { lengthDays: L, perDay: cur.perDay, compared: past.length,
             rank: above + 1, best: above === 0, runnerUp };
  }

  /* 期間の中で、どの月（週）が伸びを作ったか。⚠ 動画別ではありません。
     動画別の増減要因は video_daily.json が要るため fetch.py 側の仕事です。
     ⚠ ここで「◯◯の動画が効いた」と書かないこと。根拠がありません。 */
  function periodDrivers(inner) {
    if (!inner || inner.length < 2) return null;
    const withDelta = inner.map((x, i) => i === 0 ? null
      : { key: x.key, delta: x.viewsPerDay - inner[i - 1].viewsPerDay,
          from: inner[i - 1].viewsPerDay, to: x.viewsPerDay }).filter(Boolean);
    if (!withDelta.length) return null;
    const sorted = withDelta.slice().sort((a, b) => b.delta - a.delta);
    return { up: sorted[0], down: sorted[sorted.length - 1],
             first: inner[0], last: inner[inner.length - 1] };
  }

  function periodReport(data, span) {
    const ps = data && data.period_summary;
    const ms = (ps && ps.months) || [];
    if (!ms.length) return null;
    const cfg = SPANS[span]; if (!cfg) return null;

    let rows, cur, prev = null, prevLabel = null;
    if (span === 'ytd') {
      const y = String(ms[ms.length - 1].key).slice(0, 4);
      rows = ms.filter(m => String(m.key).slice(0, 4) === y);
      cur = aggPeriod(rows);
    } else {
      const t = cfg.take;
      if (ms.length < t) return null;
      rows = ms.slice(-t);
      cur  = aggPeriod(rows);
      const pr = ms.slice(-(t * 2), -t);
      if (pr.length === t) { prev = aggPeriod(pr); prevLabel = t === 1 ? '前月' : `その前の${t}ヶ月`; }
    }
    if (!cur) return null;

    // ⚠ 比較は**日あたり**で。当月は確定分だけなので日数が違い、合計だと必ず今期が小さく見えます。
    const dPct = (prev && prev.viewsPerDay) ? pctNum(cur.viewsPerDay, prev.viewsPerDay) : null;
    // ⚠ 「横ばい」の帯は週次と同じ FLAT（±5%）。画面ごとに別の帯を使わないこと。
    const dir = dPct == null ? null : (Math.abs(dPct) < FLAT ? '横ばい' : (dPct > 0 ? '増加' : '減少'));

    // 前年同期（日次から。⚠ 去年まだ動画が無い期間は null になります）
    const ly = dailySpan(data, shiftYear(cur.from, -1), shiftYear(cur.to, -1));
    const yoy = (ly && ly.viewsPerDay) ? Object.assign({}, ly,
      { deltaPct: pctNum(cur.viewsPerDay, ly.viewsPerDay) }) : null;

    // 期間の中の動き。⚠ 1ヶ月しか無いときは週に落とす（1本の棒では推移になりません）
    let inner = rows.map(r => ({ key: String(r.key).replace('-', '/'),
      viewsPerDay: r.views_per_day, subsNet: r.subs_net, days: r.days }));
    let innerUnit = '月';
    if (rows.length === 1) {
      const wk = ((ps && ps.weeks) || []).filter(w => w.end >= cur.from && w.start <= cur.to);
      if (wk.length >= 2) {
        inner = wk.map(w => ({ key: fmtDate(w.start).slice(5), viewsPerDay: w.views_per_day,
                               subsNet: w.subs_net, days: w.days }));
        innerUnit = '週';
      }
    }
    const vals = inner.map(x => x.viewsPerDay).filter(v => v != null);
    const peak = vals.length ? Math.max(...vals) : null;
    const best = vals.length ? inner.find(x => x.viewsPerDay === peak) : null;
    const worst = vals.length ? inner.find(x => x.viewsPerDay === Math.min(...vals)) : null;

    // 登録者の効率。⚠ 純増ではなく**獲得**で割ること（解除は視聴と結びつけにくい）
    const per10k  = cur.views  ? +(cur.subsGained  / cur.views  * 10000).toFixed(1) : null;
    const per10kP = (prev && prev.views) ? +(prev.subsGained / prev.views * 10000).toFixed(1) : null;

    return {
      span, label: cfg.label, confirmedThrough: ps.confirmed_through || null,
      cur, prev, prevLabel, deltaPct: dPct, dir, yoy,
      inner, innerUnit, best, worst, peak,
      rank: periodRank(data, cur.from, cur.to),
      drivers: periodDrivers(inner),
      per10k, per10kPrev: per10kP,
      videos: periodVideos(data, cur.from, cur.to)
    };
  }

  /* 比較文の文言。⚠ **2つの画面で別々に組み立てないこと。**同じ期間で違う言い回しが出ます。
     ⚠ 断定を足さないこと。ここが返すのは「観測できたこと」だけです。理由の推測は書きません
       （動画別の増減要因が無いので、根拠を示せません）。 */
  /* 比較文をHTMLにする。⚠ `md` はこのファイルでは**日付のフォーマッタ**です（月/日）。
     名前が紛らわしいので、比較文の強調はこちらを使うこと。 */
  function noteHtml(s) {
    return esc(String(s)).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
  }

  function periodNotes(r) {
    if (!r) return [];
    const out = [];
    const k = r.rank;
    if (k) {
      out.push(k.best
        ? `${k.lengthDays}日という同じ長さで過去にさかのぼって並べると、**いまが最も高い水準**です（比べた ${k.compared}区間のうち2番目は1日 ${fmtMan(k.runnerUp.perDay)}回）`
        : `${k.lengthDays}日という同じ長さで過去にさかのぼって並べると、比べた ${k.compared}区間のうち **${k.rank}番目**です（最も高い区間は1日 ${fmtMan(k.runnerUp.perDay)}回）`);
    }
    const d = r.drivers;
    if (d) {
      out.push(`${r.innerUnit}ごとに見ると、いちばん伸びたのは **${d.up.key}**（1日 ${fmtMan(d.up.from)}回 → ${fmtMan(d.up.to)}回、${d.up.delta >= 0 ? '+' : ''}${fmtMan(d.up.delta)}回）です`);
      if (d.down.delta < 0)
        out.push(`逆に落ちたのは ${d.down.key}（1日 ${fmtMan(d.down.from)}回 → ${fmtMan(d.down.to)}回、${fmtMan(d.down.delta)}回）です`);
      out.push(`期間の最初と最後を比べると、1日あたり ${fmtMan(d.first.viewsPerDay)}回 → ${fmtMan(d.last.viewsPerDay)}回 です`);
    }
    if (r.per10k != null && r.per10kPrev != null) {
      const diff = r.per10k - r.per10kPrev;
      out.push(Math.abs(diff) < 0.15
        ? `登録の効率（1万再生あたりの獲得）は ${r.per10k}人で、${r.prevLabel}の ${r.per10kPrev}人と**ほぼ同じ**です`
        : `登録の効率は 1万再生あたり ${r.per10k}人。${r.prevLabel}の ${r.per10kPrev}人より${diff > 0 ? '上がっています' : '下がっています'}`);
    }
    // ⚠ ここに「◯◯の動画が効いた」を足さないこと。動画別の増減は fetch.py 側にしかありません。
    return out;
  }

  global.CDModel = {
    VERSION: MODEL_VERSION, TRAFFIC_LABEL, FLAT, OWNER_GATE_RANK, ACTION_KINDS,
    SRC, fmtFull, fmtMan, fmtDate, fmtMin, md, esc, pct, pctNum, median, stripLevel,
    cause, trafficList, trafficRows, trafficSplit, verdict, ownerState, actions,
    firstSpeed, coupon, signal, periodReport, periodRank, periodNotes, noteHtml, build
  };
})(window);
