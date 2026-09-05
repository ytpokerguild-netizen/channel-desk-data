/* 期間レポートの組み立て（report_period.html と report.html が共有）2026-09-05
   ⚠⚠ 計算をここに書かないこと。足し上げも判定も report_model.js の M.periodReport()。
   ⚠⚠ 片方の画面にコピーして直さないこと。同じ期間の数字が食い違います。
   CDPeriodView.html(data, span, channelTitle, {tabs:false}) */
(function (global) {
  const M = global.CDModel;
  const esc=s=>M.esc(s), man=n=>M.fmtMan(n), full=n=>M.fmtFull(n), fmtDate=s=>M.fmtDate(s);
  const sign = v => (v>=0?'+':'') + v.toFixed(1) + '%';

const SPANS = [['month','今月'],['m3','直近3ヶ月'],['m6','直近6ヶ月'],['ytd','年初来']];


function html(DATA, span, CHANNEL, opt){
  opt = opt || {};
  const r = M.periodReport(DATA, span);
  const tabs = opt.tabs === false ? '' : `<div class="ptabs">${SPANS.map(([k,l])=>
    `<a href="?span=${k}" class="${k===span?'on':''}">${l}</a>`).join('')}</div>`;
  if(!r){ return `<h1>期間レポート</h1>${tabs}<div class="note">この期間はまだ出せません。</div>`; }

  const c = r.cur;
  const dl = r.deltaPct==null ? '—' : sign(r.deltaPct);
  const yl = r.yoy ? sign(r.yoy.deltaPct) : '—';
  // ⚠ 前期が無いときに「増加」と書かないこと
  const head = r.deltaPct==null
    ? `${r.label}の視聴は1日あたり ${man(c.viewsPerDay)}回です`
    : `${r.label}の視聴は1日あたり ${man(c.viewsPerDay)}回。${r.prevLabel}より ${dl} で${r.dir}です`;
  const hrs = c.watchMin!=null ? Math.round(c.watchMin/60) : null;
  // ⚠ 1分未満を「0分57秒」と出さないこと（ショートは1分未満が普通です）
  const dur = c.avgDurationSec==null ? '—'
    : (c.avgDurationSec<60 ? `${c.avgDurationSec}秒`
      : `${Math.floor(c.avgDurationSec/60)}分${String(c.avgDurationSec%60).padStart(2,'0')}秒`);
  // ⚠⚠ 初速は月ごとの中央値をそのまま。期間でならして1つにしないこと
  const sp = c.speedByMonth.filter(x=>x.median!=null)
    .map(x=>`${String(x.key).replace('-','/')} ${man(x.median)}<span style="color:var(--muted)">(${x.n})</span>`).join('　');

  const tile=(v,l,s2)=>`<div class="tile"><div class="tv">${v}</div><div class="tl">${l}</div>${s2?`<div class="ts">${s2}</div>`:''}</div>`;
  const hrow=(k,v)=>`<div class="hrow"><span class="hk">${k}</span><span class="hv">${v}</span></div>`;

  /* ⚠⚠ **選択期間だけを並べないこと。**比較になりません。過去を含めて、期間の分だけ濃くします。 */
  const S = r.series, sRows = S.rows, sPeak = Math.max(...sRows.map(x=>x.viewsPerDay||0), 1);
  const bw = sRows.length<=6 ? 54 : (sRows.length<=13 ? 38 : (sRows.length<=18 ? 30 : 24));
  const onIdx = sRows.reduce((a,x,i)=>x.on?(a<0?i:a):a, -1);
  const bars = sRows.map((x,i)=>{
    const h = Math.max(3, Math.round(x.viewsPerDay/sPeak*88));
    const showKey = i%3===0 || i===sRows.length-1 || i===onIdx;
    return `<div class="pbar${x.on?' on':''}" style="width:${bw}px">
      <div class="pv">${x.on?man(x.viewsPerDay):'&nbsp;'}</div>
      <div class="pb" style="width:${Math.round(bw*0.6)}px;height:${h}px"></div>
      <div class="pk">${showKey?esc(x.key):'&nbsp;'}</div></div>`;
  }).join('');

  const types = r.videos.types.map(t=>`${esc(t.name)} ${t.count}`).join(' ／ ') || '—';
  const nars  = r.videos.narrators.map(t=>`${esc(t.name)} ${t.count}`).join(' ／ ') || '—';
  const tops  = r.videos.top.map((v,i)=>`<div class="vrow">
      <span class="vn">${i+1}</span>
      <span class="vt">${esc(v.title)}</span>
      <span class="vv">${man(v.views)}</span></div>`).join('');
  const eff = r.per10k==null ? '—'
    : `${r.per10k}人${r.per10kPrev!=null?`（${esc(r.prevLabel||'前期')} ${r.per10kPrev}人）`:''}`;

  const notes = M.periodNotes(r);
  let n=0; const sec=(t)=>`<h2><span class="eyebrow"><span class="secn">${String(++n).padStart(2,'0')}</span>${t}</span></h2>`;

  return `
<h1>期間レポート<span class="badge">${esc(r.label)}</span></h1>
<div class="sub">${esc(CHANNEL)}<br>${fmtDate(c.from)} 〜 ${fmtDate(c.to)}（確定 ${c.days}日ぶん・${fmtDate(r.confirmedThrough)} まで）</div>
${tabs}
<div class="verdict"><span class="lv">${esc(head)}</span></div>
<div class="tiles">
${tile(man(c.views)+'回', `${esc(r.label)}の視聴回数`, `1日 ${man(c.viewsPerDay)}回`)}
${tile(dl, r.prevLabel?`${esc(r.prevLabel)}比`:'前期比', r.prevLabel?'日あたりで比較':'比べられる前期がありません')}
${tile(yl, '前年同期比', r.yoy?`昨年は1日 ${man(r.yoy.viewsPerDay)}回`:'昨年のデータがありません')}
</div>
<div class="subline">登録者は ${(c.subsNet>=0?'+':'')+full(c.subsNet)}人（獲得 ${full(c.subsGained)} ／ 解除 ${full(c.subsLost)}）。1万再生あたりの獲得は ${eff}。</div>

${notes.length?`${sec('読み取れること')}
<div class="pnotes">${notes.map(n=>`<div class="pnote">${M.noteHtml(n)}</div>`).join('')}</div>
<div class="note">⚠ ここに書けるのは<b>観測できたことだけ</b>です。「どの動画が効いたか」は動画別の日次が必要なため出していません。</div>`:''}

${sec(`${esc(S.unit)}ごとの動き`)}
<div class="lede">直近${sRows.length}${esc(S.unit)}ぶん。濃い色が${esc(r.label)}、薄い色は比較のための過去です。棒は1日あたりの視聴回数で、⚠ 合計ではありません（${esc(S.unit)}によって日数が違うためです）。</div>
<div class="pbars">${bars}</div>
${r.best&&r.worst&&r.best.key!==r.worst.key?`<div class="note key">${esc(r.label)}の中でいちばん高い${esc(r.innerUnit)}は <b>${esc(r.best.key)}</b>（1日 ${man(r.best.viewsPerDay)}回）、低い${esc(r.innerUnit)}は ${esc(r.worst.key)}（1日 ${man(r.worst.viewsPerDay)}回）。差は ${(r.best.viewsPerDay/Math.max(1,r.worst.viewsPerDay)).toFixed(1)}倍です。</div>`:''}
<div class="note">⚠ 2024年〜2025年前半は動画がほとんど無く、1日あたり数千回の月があります。薄い棒が低いのはそのためです。</div>

${sec('中身')}
<div class="headrows">
${hrow('既存と新作', `既存の動画が1日あたり ${man(c.basePerDay)}回。この期間に公開した動画が全体の <b>${c.newRatioPct==null?'—':c.newRatioPct+'%'}</b>`)}
${hrow('公開したもの', `${c.videoCount}本（平均 ${dur}）${hrs!=null?`　総再生時間 ${full(hrs)}時間`:''}`)}
${hrow('企画タイプ', types)}
${hrow('ナレーター', nars)}
${sp?hrow('新作の初速', `${sp}　<span style="color:var(--muted);font-size:11.5px">括弧は本数</span>`):''}
${hrow('クーポン', `${r.videos.couponCount}本にクーポンを付けています`)}
</div>

${tops?`${sec('この期間に公開した動画')}
<div class="lede">再生の多い順に3本。⚠ 数字は<b>公開以来の累計</b>で、この期間だけの再生数ではありません。</div>
${tops}`:''}

<div class="note">前期比・前年同期比とも<b>1日あたり</b>で比べています。今月は確定した日数ぶんしか無いため、合計で比べると必ず今期が小さく出ます。
前年同期はチャンネル全体の日次から出しています。⚠ 既存/新作の分解と初速は日次に無いため、そちらは直近12ヶ月ぶんだけです。
初速は公開当日＋翌日の合計の中央値で、<b>2日そろっていない動画は数えていません</b>。月ごとに並べているのは、中央値は期間をまたいで合成できないためです。
⚠ 既存と新作の合計は上の視聴回数と一致しません（集計元が違います）。登録の効率は<b>獲得</b>で計算しています。</div>

<div class="foot">CHANNEL DESK 自動生成 ／ ${new Date().toLocaleString('ja-JP')} ／ ${esc(CHANNEL)}</div>`;
}

  global.CDPeriodView = { SPANS, html };
})(window);
