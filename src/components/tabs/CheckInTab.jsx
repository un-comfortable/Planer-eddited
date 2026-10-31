import { useState } from 'react';
import { LIMIT_PERIOD_KR, PLAN_CATEGORIES, WEEKDAY_NAMES, addDays, checkInTag, countInMonth, isDawn, progressLine } from '../../features/tonkatsu/tonkatsuCore.mjs';
import { editableKeys, planEditError, planInputError } from '../../features/tonkatsu/tonkatsuWrites.mjs';
import { addPlan, cancelCheckIn, cancelRest, checkIn, deletePlan, editPlan, setAlertHour, takeRest } from '../../features/tonkatsu/tonkatsuService';
import '../../styles/tonkatsu.css';

const TITLES = { Daily: '🌞 매일', Routine: '🔄 요일', Weekly: '📅 주간', Monthly: '🗓️ 월간', Interval: '🔁 반복', OneTime: '🎯 목표', Limit: '🚫 제한' };
const millis = (v) => v?.toMillis?.() ?? 0;

function planDetail(plan) {
  if (plan.category === 'Weekly') return `주 ${plan.count}회`;
  if (plan.category === 'Monthly') return `월 ${plan.count}회`;
  if (plan.category === 'Routine') return `${(plan.days || []).join('')}요일`;
  if (plan.category === 'Interval') return `${plan.interval}일마다`;
  if (plan.category === 'OneTime') return `${plan.deadline}까지`;
  if (plan.category === 'Limit') return `${LIMIT_PERIOD_KR[plan.period]} ${plan.limit}회 이하`;
  return '';
}

function AddPlanForm({ discordId, today, onDone, run }) {
  const [form, setForm] = useState({ kind: 'Daily', content: '', count: 3, limit: 2, limitOn: false, days: [], interval: 3, deadline: addDays(today, 7), photo: false });
  const set = (key, value) => setForm((f) => ({ ...f, [key]: value }));
  const periodKind = ['Daily', 'Weekly', 'Monthly'].includes(form.kind);
  const isLimit = periodKind && form.limitOn;
  const input = isLimit
    ? { category: 'Limit', content: form.content, period: { Daily: 'day', Weekly: 'week', Monthly: 'month' }[form.kind], limit: Number(form.limit) }
    : { category: form.kind, content: form.content, photo: form.photo, count: Number(form.count), days: form.days, interval: Number(form.interval), deadline: form.deadline };
  const error = planInputError(input);

  const submit = (e) => {
    e.preventDefault();
    if (error) return;
    run('add', () => addPlan(discordId, input, today), '계획을 등록했어요.').then((ok) => ok && onDone());
  };

  return <form className="tk-add" onSubmit={submit}>
    <div className="tk-add-row">
      <select value={form.kind} onChange={(e) => set('kind', e.target.value)} aria-label="계획 종류">
        <option value="Daily">매일</option><option value="Weekly">주간</option><option value="Monthly">월간</option>
        <option value="Routine">요일</option><option value="Interval">N일마다</option><option value="OneTime">목표 (마감일)</option>
      </select>
      <input value={form.content} maxLength={80} placeholder="내용 (예: 운동, 몬스터)" onChange={(e) => set('content', e.target.value)} aria-label="내용" />
    </div>
    <div className="tk-add-row">
      {periodKind && <label className="tk-check"><input type="checkbox" checked={form.limitOn} onChange={(e) => set('limitOn', e.target.checked)} /> 제한 (N회 넘기면 벌금)</label>}
      {isLimit && <label>최대 <input type="number" min={0} max={50} value={form.limit} onChange={(e) => set('limit', e.target.value)} />회</label>}
      {!isLimit && (form.kind === 'Weekly' || form.kind === 'Monthly') &&
        <label>목표 <input type="number" min={1} max={form.kind === 'Weekly' ? 7 : 31} value={form.count} onChange={(e) => set('count', e.target.value)} />회</label>}
      {form.kind === 'Routine' && <span className="tk-days">{WEEKDAY_NAMES.map((d) =>
        <label key={d} className="tk-check tk-day"><input type="checkbox" checked={form.days.includes(d)} onChange={(e) => set('days', e.target.checked ? [...form.days, d] : form.days.filter((x) => x !== d))} />{d}</label>)}</span>}
      {form.kind === 'Interval' && <label><input type="number" min={1} max={365} value={form.interval} onChange={(e) => set('interval', e.target.value)} />일마다</label>}
      {form.kind === 'OneTime' && <label>마감 <input type="date" value={form.deadline} onChange={(e) => set('deadline', e.target.value)} /></label>}
      {!isLimit && <label className="tk-check"><input type="checkbox" checked={form.photo} onChange={(e) => set('photo', e.target.checked)} /> 사진 필수 (디스코드에서만 인증)</label>}
    </div>
    <div className="tk-add-row">
      {form.content && error && <span className="tk-note">{error}</span>}
      <button type="submit" className="btn btn-login" disabled={!!error}>등록</button>
      <button type="button" className="btn-signout" onClick={onDone}>닫기</button>
    </div>
  </form>;
}

function EditPlanForm({ plan, run, onDone }) {
  const keys = editableKeys(plan.category);
  const [form, setForm] = useState(() => Object.fromEntries(keys.map((k) => [k, plan[k] ?? (k === 'days' ? [] : '')])));
  const set = (key, value) => setForm((f) => ({ ...f, [key]: value }));
  const changes = {};
  for (const k of keys) {
    const value = ['count', 'limit', 'interval'].includes(k) ? Number(form[k]) : k === 'content' ? form[k].trim() : form[k];
    const before = plan[k];
    if (JSON.stringify(k === 'days' ? WEEKDAY_NAMES.filter((d) => value.includes(d)) : value) !== JSON.stringify(before ?? (k === 'photo' ? false : before))) changes[k] = value;
  }
  const changed = Object.keys(changes).length > 0;
  const error = changed ? planEditError(plan, changes) : null;
  const conditionChanged = Object.keys(changes).some((k) => k !== 'content');

  const submit = (e) => {
    e.preventDefault();
    if (!changed || error) return;
    run(plan.id, () => editPlan(plan, changes), '계획을 수정했어요.').then((ok) => ok && onDone());
  };

  return <form className="tk-add tk-edit" onSubmit={submit}>
    <div className="tk-add-row">
      <input value={form.content} maxLength={80} onChange={(e) => set('content', e.target.value)} aria-label="내용" />
    </div>
    <div className="tk-add-row">
      {keys.includes('count') && <label>목표 <input type="number" min={1} max={plan.category === 'Weekly' ? 7 : 31} value={form.count} onChange={(e) => set('count', e.target.value)} />회</label>}
      {keys.includes('limit') && <label>{LIMIT_PERIOD_KR[plan.period]} 최대 <input type="number" min={0} max={50} value={form.limit} onChange={(e) => set('limit', e.target.value)} />회</label>}
      {keys.includes('days') && <span className="tk-days">{WEEKDAY_NAMES.map((d) =>
        <label key={d} className="tk-check tk-day"><input type="checkbox" checked={form.days.includes(d)} onChange={(e) => set('days', e.target.checked ? [...form.days, d] : form.days.filter((x) => x !== d))} />{d}</label>)}</span>}
      {keys.includes('interval') && <label><input type="number" min={1} max={365} value={form.interval} onChange={(e) => set('interval', e.target.value)} />일마다</label>}
      {keys.includes('deadline') && <label>마감 <input type="date" value={form.deadline} onChange={(e) => set('deadline', e.target.value)} /></label>}
      {keys.includes('photo') && <label className="tk-check"><input type="checkbox" checked={!!form.photo} onChange={(e) => set('photo', e.target.checked)} /> 사진 필수</label>}
    </div>
    <div className="tk-add-row">
      {error && <span className="tk-note">{error}</span>}
      {!error && conditionChanged && <span className="tk-muted">조건을 바꾸면 디스코드 알림 채널에 알려요.</span>}
      <button type="submit" className="btn btn-login" disabled={!changed || !!error}>저장</button>
      <button type="button" className="btn-signout" onClick={onDone}>취소</button>
    </div>
  </form>;
}

export default function CheckInTab({ tonkatsu: t, discordId }) {
  const [dateValue, setDateValue] = useState('today');
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState(null);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState(null);
  const { me, today } = t;
  const date = dateValue === 'yesterday' ? addDays(today, -1) : today;

  // 실행 중 표시와 결과 안내. 오프라인이면 연결될 때 전송되므로 안내만 바꿈
  const run = async (key, action, okText) => {
    setBusy(key); setMessage(null);
    const offline = typeof navigator !== 'undefined' && navigator.onLine === false;
    if (offline) setMessage({ ok: true, text: '오프라인이에요. 인터넷에 연결되면 자동으로 보내요.' });
    try { await action(); if (!offline) setMessage({ ok: true, text: okText }); return true; }
    catch { setMessage({ ok: false, text: '저장하지 못했어요. 이미 처리됐거나 허용되지 않는 요청일 수 있어요. 잠시 후 다시 시도해 주세요.' }); return false; }
    finally { setBusy(''); }
  };

  const myRecords = (planId) => t.checkIns.filter((c) => c.planId === planId && c.date === date && c.ownerId === discordId)
    .sort((a, b) => millis(a.createdAt) - millis(b.createdAt));
  const restToday = t.offDays.find((o) => o.ownerId === discordId && o.type === 'rest' && o.date === today);
  const restUsed = countInMonth(me.rest_history || [], today) > 0;
  const finesSorted = [...t.myFines].sort((a, b) => (b.date || '').localeCompare(a.date || '') || millis(b.createdAt) - millis(a.createdAt));
  const doneGoals = (me.completed_goals || []).filter((g) => g.completed_at === date);

  const row = (category, plan) => {
    const [mark, text] = progressLine(me, category, plan, date);
    const tag = checkInTag(me, category, plan, date);
    const records = myRecords(plan.id);
    const beforeStart = date < (plan.created_at || '2000-01-01');
    const canCheck = tag !== null && !plan.photo && !beforeStart;
    return <li key={plan.id} className="tk-plan">
      <span className="tk-mark">{mark}</span>
      <span className="tk-plan-main"><strong>{plan.content}</strong> <span className="tk-muted">{planDetail(plan)} {text}</span></span>
      <span className="tk-actions">
        {canCheck && <button type="button" className="btn btn-login" disabled={!!busy}
          onClick={() => run(plan.id, () => checkIn(plan, discordId, date), category === 'OneTime' ? '🎉 목표 달성!' : '인증했어요.')}>
          {category === 'Limit' ? '+1 기록' : '인증'}</button>}
        {tag !== null && plan.photo && <span className="tk-note">📸 디스코드에서 사진과 함께 인증</span>}
        {records.length > 0 && <button type="button" className="btn-signout" disabled={!!busy}
          onClick={() => run(plan.id, () => cancelCheckIn(plan, records.at(-1).id), '인증을 한 번 취소했어요.')}>취소</button>}
        <button type="button" className="tk-icon" title="계획 수정" disabled={!!busy}
          onClick={() => setEditing(editing === plan.id ? null : plan.id)}>✏️</button>
        <button type="button" className="tk-icon" title="계획 삭제" disabled={!!busy}
          onClick={() => window.confirm(`'${plan.content}' 계획을 삭제할까요? 지금까지의 기록은 남아요.`) && run(plan.id, () => deletePlan(plan.id), '계획을 삭제했어요.')}>🗑</button>
      </span>
      {editing === plan.id && <EditPlanForm plan={plan} run={run} onDone={() => setEditing(null)} />}
    </li>;
  };

  if (t.error) return <p role="alert">돈까스봇 데이터를 불러오지 못했어요. 인터넷 연결을 확인해 주세요.</p>;
  if (!t.ready) return <p role="status">돈까스봇 데이터를 불러오는 중…</p>;

  const sections = PLAN_CATEGORIES.map((c) => [c, me[c] || []]).filter(([, plans]) => plans.length);
  return <div className="tk">
    <div className="tk-toolbar">
      <div className="tk-date">
        <button type="button" className={dateValue === 'today' ? 'tab-btn tab-active' : 'tab-btn'} onClick={() => setDateValue('today')}>오늘 {today.slice(5)}</button>
        <button type="button" className={dateValue === 'yesterday' ? 'tab-btn tab-active' : 'tab-btn'} onClick={() => setDateValue('yesterday')}>어제 (깜빡한 인증)</button>
        {isDawn() && dateValue === 'today' && <span className="tk-note">🌙 새벽 5시 전이라 어제 날짜로 인증돼요</span>}
      </div>
      <button type="button" className="btn btn-login" onClick={() => setAdding((v) => !v)}>+ 계획 등록</button>
    </div>
    {message && <p role={message.ok ? 'status' : 'alert'} className={message.ok ? 'tk-ok' : 'tk-error'}>{message.text}</p>}
    {adding && <AddPlanForm discordId={discordId} today={today} run={run} onDone={() => setAdding(false)} />}

    {!sections.length && <p>등록된 계획이 없어요. <strong>+ 계획 등록</strong>이나 디스코드 <code>/계획 등록</code>으로 추가해 보세요.</p>}
    {sections.map(([category, plans]) => <section key={category} className="tk-section">
      <h3>{TITLES[category]}</h3>
      <ul className="tk-list">{plans.map((p) => row(category, p))}</ul>
    </section>)}
    {doneGoals.length > 0 && <section className="tk-section"><h3>🏆 이날 달성한 목표</h3><ul className="tk-list">
      {doneGoals.map((g) => <li key={g.id} className="tk-plan"><span className="tk-mark">🏆</span>
        <span className="tk-plan-main"><strong>{g.content}</strong></span>
        <span className="tk-actions"><button type="button" className="btn-signout" disabled={!!busy}
          onClick={() => run(g.id, () => cancelCheckIn(g, `${g.id}_${date}`), '목표를 다시 진행 중으로 되돌렸어요.')}>되돌리기</button></span></li>)}
    </ul></section>}

    <div className="tk-side">
      <section className="tk-card">
        <h3>🛌 휴식권 (월 1회)</h3>
        {restToday
          ? <><p>오늘({today}) 휴식 중이에요.</p><button type="button" className="btn-signout" disabled={!!busy} onClick={() => run('rest', () => cancelRest(restToday.id), '휴식을 취소했어요.')}>휴식 취소</button></>
          : restUsed ? <p>이번 달 휴식권을 이미 썼어요.</p>
            : <button type="button" className="btn btn-login" disabled={!!busy}
              onClick={() => window.confirm(`오늘(${today})을 휴식일로 쓸까요? 한 달에 한 번만 쓸 수 있어요.`) && run('rest', () => takeRest(discordId, today), '휴식권을 썼어요. 푹 쉬세요!')}>오늘 휴식하기</button>}
        <p className="tk-muted">면책 요청은 디스코드 <code>/면책</code>으로 해요.</p>
      </section>
      <section className="tk-card">
        <h3>⏰ 알림 시간</h3>
        <select value={me.alert_time ?? 2} disabled={!!busy} aria-label="알림 시간"
          onChange={(e) => run('alert', () => setAlertHour(discordId, Number(e.target.value)), '알림 시간을 바꿨어요.')}>
          {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{h}시</option>)}
        </select>
        <p className="tk-muted">이 시각에 아직 안 한 계획을 디스코드에서 알려줘요.</p>
      </section>
      <section className="tk-card">
        <h3>💸 내 벌금 {me.fines.toLocaleString()}원</h3>
        {finesSorted.length ? <ul className="tk-fines">{finesSorted.slice(0, 30).map((f) =>
          <li key={f.id}><span>{f.date}</span><span className={f.amount > 0 ? 'tk-plus' : 'tk-minus'}>{f.amount > 0 ? '+' : ''}{f.amount.toLocaleString()}원</span>
            <span className="tk-muted">{f.reason}</span></li>)}</ul> : <p className="tk-muted">벌금 내역이 없어요.</p>}
      </section>
    </div>
    <p className="tk-muted">날짜는 한국 시간 새벽 5시 기준이에요. 디스코드에서 한 인증도 여기에 바로 보여요.</p>
  </div>;
}
