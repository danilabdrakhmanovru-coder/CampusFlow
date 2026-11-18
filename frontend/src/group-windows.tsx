import { FormEvent, useEffect, useRef, useState } from 'react'
import { api, json, Session } from './api'
import { allRooms, campus, clock, Heading, message, params, Status, today, useLoad } from './common'
import { go, Link } from './routing'
import { useConfirmation } from './Sheet'
import { addDays,durationLabel,monday } from './weekly'

type Metric = {group:string;size:number|null;course:number|null;status:string;total:number|null;count:number|null;largest:number|null;days:number|null;transitions:number|null;score:number|null;quality:number|null;lesson_count:number|null;compact_days:number|null;teaching_days:number|null}
type Gap = {day:string;minutes:number;walking_minutes:number|null;before:string;after:string;start:string;end:string;building:string|null;transfer:boolean;from_id:number;to_id:number}
type Lesson = {id:number;start:string;end:string;subject:string;building:string|null;room:string|null;pinned:boolean;teachers:{building:string;number:number;label:string}[]}
type Slot = {start:string;end:string;room:string;building:string}
export type Suggestion={id:number;group:string;subject:string;lesson_id:number;original:Slot;target:Slot;gain:number;before:number;after:number;transitions_before:number;transitions_after:number;groups:number;teachers:number;acceptance:number|null;expected_value:number|null;teacher_breaks_before?:number;teacher_breaks_after?:number}
type Result = {items:Suggestion[];status:string}
const dayLabel=(day:string)=>new Intl.DateTimeFormat('ru-RU',{weekday:'short',day:'numeric',month:'short',timeZone:'UTC'}).format(new Date(day+'T12:00:00Z'))
const when=(slot:Slot)=>dayLabel(slot.start.slice(0,10))+' '+clock(slot.start)+'–'+clock(slot.end)+' — '+slot.room+', корпус '+slot.building
const terms:Record<string,string>={pedagogy:'Учебный процесс',coordination:'Нужны согласования',room:'Аудитория не подходит',other:'Другое'}

export function SuggestionCard({item,admin,applied=false,decided,onUpdate}:{item:Suggestion;admin:boolean;applied?:boolean;decided?:boolean;onUpdate:()=>void}){
  const confirm=useConfirmation()
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [note,setNote]=useState('')
  async function decide(accepted:boolean,reason:string){
    setBusy(true);setError('')
    try{
      if(accepted&&!applied)await api('/admin/proposals/'+item.id+'/apply',json({lesson_ids:[item.lesson_id]},'POST',crypto.randomUUID()))
      await api('/suggestions/'+item.id+'/decision',json({accepted,reason}))
      setNote(accepted?'Перенос применён.':'Предложение отклонено.')
      onUpdate()
    }catch(error){setError(message(error))}
    finally{setBusy(false)}
  }
  return <article className="panel suggestion-card"><h3>{item.subject}</h3><p>{item.group} — окна сократятся на {item.gain} мин.</p>
    <div className="suggestion-diff"><div><strong>Было</strong><p>{when(item.original)}</p><p>Окна: {item.before} мин. Смена корпуса: {item.transitions_before}.</p></div>
      <div><strong>Стало</strong><p>{when(item.target)}</p><p>Окна: {item.after} мин. Смена корпуса: {item.transitions_after}.</p></div></div>
    <p>Затронуто групп: {item.groups}, преподавателей: {item.teachers}.</p>
    {item.teacher_breaks_before!==undefined&&item.teacher_breaks_after!==undefined&&<p>
      Перерывы преподавателей за период: {durationLabel(item.teacher_breaks_before)} → {durationLabel(item.teacher_breaks_after)}.
    </p>}
    {item.acceptance!==null&&<p>Вероятность принятия по модели: {Math.round(item.acceptance*100)}%. Ожидаемое сокращение окон: {item.expected_value} мин.</p>}
    {!admin&&<p className="muted">Предложение отправлено в диспетчерскую.</p>}
    {admin&&!decided&&!note&&<div className="actions"><button disabled={busy} onClick={()=>confirm.ask({
      title:'Применить перенос?',description:'CampusFlow ещё раз проверит расписание и занятость.',label:'Применить перенос',apply:()=>void decide(true,'approved'),
    })}>{applied?'Записать принятие':'Принять'}</button>
      {!applied&&<form className="actions" onSubmit={event=>{
        event.preventDefault();const reason=String(new FormData(event.currentTarget).get('reason'))
        confirm.ask({title:'Отклонить перенос?',description:'Причина сохранится в истории решений.',label:'Отклонить перенос',apply:()=>void decide(false,reason)})
      }}><label>Причина отказа<select name="reason" required><option value="">Выберите причину</option>{Object.entries(terms).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
        <button className="secondary" disabled={busy}>Отклонить</button></form>}
    </div>}
    <Status error={error} pending={busy}/>{note&&<p className="feedback" role="status">{note}</p>}
    {confirm.dialog}
  </article>
}

type GapAnalysis={summary:string;observations:string[];next_steps:string[]}
function WindowAnalysis({group,start,end,minimum}:{group:string;start:string;end:string;minimum:number}){
  const [result,setResult]=useState<GapAnalysis>()
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  async function analyze() {
    setBusy(true);setError('');setResult(undefined)
    try{
      setResult(await api<GapAnalysis>('/analytics/groups/'+encodeURIComponent(group)+'/analysis',
        json({start,end,minimum})))
    }catch(error){setError(message(error))}
    finally{setBusy(false)}
  }
  return <section className="panel" aria-label="ИИ-анализ окон">
    <div className="actions">
      <button className="secondary" disabled={busy} onClick={()=>void analyze()}>
        {busy?'Qwen разбирает окна…':result?'Обновить разбор':'Разобрать окна с ИИ'}
      </button>
    </div>
    <Status error={error}/>
    {busy&&<p role="status">Первый ответ может занять до полутора минут.</p>}
    {result&&<div aria-live="polite">
      <h3>Разбор расписания</h3>
      <p className="muted">Группа {group}, {dayLabel(start)} — {dayLabel(end)}</p>
      <p>{result.summary}</p>
      <ul>{result.observations.map((item,index)=><li key={index}>{item}</li>)}</ul>
      <h3>Что проверить перед переносом</h3>
      <ul>{result.next_steps.map((item,index)=><li key={index}>{item}</li>)}</ul>
    </div>}
  </section>
}

export function GroupWindows({user}:{user:Session}){
  const query=new URLSearchParams(location.search)
  const group=query.get('group')??''
  const date=query.get('day')??''
  const first=/^\d{4}-\d{2}-\d{2}$/.test(date)&&Number.isFinite(Date.parse(date))?monday(date):monday(today())
  const [start,setStart]=useState(first)
  const [end,setEnd]=useState(addDays(first,5))
  const [building,setBuilding]=useState('')
  const [course,setCourse]=useState('')
  const [minimum,setMinimum]=useState('40')
  const [sort,setSort]=useState<'score'|'total'|'count'|'largest'|'days'|'transitions'>('score')
  const [output,setOutput]=useState<Result>()
  const resultsHeading=useRef<HTMLHeadingElement>(null)
  const scopedLesson=query.get('lesson')
  useEffect(()=>{if(output)resultsHeading.current?.focus()},[output])
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const [revision,refresh]=useState(0)
  const rooms=useLoad(()=>group?Promise.resolve([]):allRooms(),'window-rooms:'+group)
  const filter=params({start,end,minimum,building,course:course||'0'})
  const detailParams=params({start,end,minimum})
  const ranking=useLoad(()=>group?Promise.resolve(undefined):api<{items:Metric[];missing_sizes:number;formula:string}>('/analytics/groups/windows?'+filter),group+':'+filter+':'+revision)
  const detail=useLoad(()=>group?api<{summary:Metric;windows:Gap[];lessons:Lesson[]}>('/analytics/groups/'+encodeURIComponent(group)+'/windows?'+detailParams):Promise.resolve(undefined),group+':'+detailParams+':'+revision)
  const items=[...(ranking.data?.items??[])].sort((a,b)=>(b[sort]??-1)-(a[sort]??-1))
  const buildings=[...new Set(rooms.data?.map(room=>room.building))].sort()
  async function search(target:string,lesson?:number){
    setBusy(true);setError('');setOutput(undefined)
    try{
      const base=start,last=addDays(start,Math.min(6,Math.max(0,Math.floor((Date.parse(end)-Date.parse(start))/86400000))))
      const candidates=target?[target]:items.filter(item=>item.status==='ready').slice(0,5).map(item=>item.group)
      let result:Result={items:[],status:'ready'}
      for(const code of candidates){
        const value=await api<Result>('/analytics/groups/'+encodeURIComponent(code)+'/suggestions',json({start:base,end:last,lesson_id:lesson}))
        result={items:[...result.items,...value.items].slice(0,5),status:value.status}
        if(result.items.length>=5)break
      }
      setOutput(result)
    }catch(error){setError(message(error))}
    finally{setBusy(false)}
  }
  return <><Heading title={group?'Разбор расписания':'Рейтинг групп'} description={group?undefined:'Сначала показаны группы, которым больше всего нужны изменения.'}/>
    {!group&&<p className="muted">100 баллов — удобное расписание. Выберите группу, посмотрите причины оценки и сравните варианты переноса.</p>}
    <div className="toolbar panel">
      <label>С<input type="date" value={start} onChange={e=>{if(e.target.value)setStart(e.target.value)}}/></label>
      <label>По<input type="date" value={end} onChange={e=>{if(e.target.value)setEnd(e.target.value)}}/></label>
      <details className="secondary-options"><summary>Фильтры</summary><div className="actions">
        {!group&&<><label>Корпус<select value={building} onChange={e=>setBuilding(e.target.value)}><option value="">Все корпуса</option>{buildings.map(key=><option key={key}>{key}</option>)}</select></label>
        <label>Курс<select value={course} onChange={e=>setCourse(e.target.value)}><option value="">Любой</option>{[1,2,3,4,5,6].map(key=><option key={key}>{key}</option>)}</select></label></>}
        <label>Окно от, мин<input type="number" min="1" max="480" value={minimum} onChange={e=>setMinimum(e.target.value)}/></label>
      </div></details>
    </div>
    <Status error={error||ranking.error||detail.error} pending={busy||(group?!detail.data&&!detail.error:!ranking.data&&!ranking.error)}/>
    {!group&&ranking.data&&<>
      <details><summary>Как считается балл</summary><p>{ranking.data.formula}</p></details>
      {ranking.data.missing_sizes>0&&<p className="feedback">Групп без размера: {ranking.data.missing_sizes}. Для них переносы пока недоступны.</p>}
      <div className="actions"><label>Сортировка<select value={sort} onChange={e=>setSort(e.target.value as typeof sort)}>
        <option value="score">Индекс неудобства</option><option value="total">Минуты окон</option><option value="count">Число окон</option>
        <option value="largest">Самое длинное</option><option value="days">Дни с окнами</option><option value="transitions">Смены корпуса</option>
      </select></label><button disabled={busy||!items.some(item=>item.status==='ready'&&(item.count??0)>0)} onClick={()=>void search('')}>Найти исправления за неделю</button></div>
      <Status empty={!items.length?'За этот период нет групп с доступным расписанием.':undefined}/>
      <ul className="records">{items.map(item=><li key={item.group}><div><Link href={'/windows?'+params({group:item.group,day:start})}>{item.group}</Link>
        {item.status==='unknown_size'&&<p>Нет данных о размере группы.</p>}
        {item.status==='small'?<p>Сводка скрыта для групп меньше пяти человек.</p>:<p>Окон {item.count}, потеряно {durationLabel(item.total??0)}. Дней без окон {item.compact_days} из {item.teaching_days}.</p>}</div>
        {item.quality!==null&&<strong className="tag">Качество {item.quality}/100</strong>}</li>)}</ul>
    </>}
    {group&&detail.data&&<section>
      <Link href={'/windows?day='+start}>К рейтингу</Link><h2>Группа {group}</h2>
      {detail.data.summary.status==='ready'&&<section className="panel" aria-label="Оценка расписания">
        <h3>Качество {detail.data.summary.quality}/100</h3>
        <p>Занятий {detail.data.summary.lesson_count}. Окон {detail.data.summary.count}, потеряно {durationLabel(detail.data.summary.total??0)}.</p>
        <p>Дней без окон {detail.data.summary.compact_days} из {detail.data.summary.teaching_days}.</p>
        <details><summary>Как получен балл</summary><p>Из 100 вычитаем минуты окон ÷ 12, самое длинное окно ÷ 12, число окон × 2 и смены корпуса × 4. Штраф округляем и ограничиваем 100. Это стартовая формула прототипа.</p></details>
      </section>}
      {detail.data.summary.status==='unknown_size'&&<p className="feedback">Нет данных о размере группы. Диспетчер должен заполнить каталог.</p>}
      <section className="schedule-improve" aria-label="Способы сокращения окон">
        <div><h3>Как сократить окна</h3>
          <p>ИИ подсказывает, где искать улучшения. Поиск переносов проверяет занятость аудитории, преподавателя и группы.</p></div>
        <div className="actions">
          <button disabled={busy||detail.data.summary.status!=='ready'||!detail.data.windows.length}
            onClick={()=>void search(group)}>Найти исправления</button>
          {scopedLesson&&detail.data.windows.some(gap=>String(gap.from_id)===scopedLesson||String(gap.to_id)===scopedLesson)&&
            <button className="secondary" disabled={busy||detail.data.summary.status!=='ready'}
              onClick={()=>void search(group,Number(scopedLesson))}>Найти перенос для этой пары</button>}
          <Link className="action-link" href={'/schedule?'+params({scope:'group',entity_id:group,day:start})}>Открыть расписание недели</Link>
        </div>
      </section>
      {detail.data.summary.status==='ready'&&detail.data.windows.length>0&&
        <WindowAnalysis key={group+':'+detailParams+':'+revision} group={group} start={start} end={end} minimum={Number(minimum)||40}/>}
      <div className="group-week">{Array.from({length:Math.min(6,Math.max(1,Math.floor((Date.parse(end)-Date.parse(start))/86400000)+1))},(_,i)=>addDays(start,i)).map(day=><section className="panel" key={day}>
        <h3>{dayLabel(day)}</h3>
        {detail.data?.lessons.filter(lesson=>new Intl.DateTimeFormat('sv-SE',{timeZone:campus}).format(new Date(lesson.start))===day).map(lesson=><div key={lesson.id}>
          {detail.data?.windows.filter(gap=>gap.to_id===lesson.id).map(gap=><div className="weekly-gap" key={gap.start}><strong>Окно {durationLabel(gap.minutes)}</strong>
            <Link className="action-link" href={'/rooms?'+params({start:gap.start,end:gap.end,...(gap.building?{building:gap.building}:{})})}>Где посидеть</Link></div>)}
          <article className="lesson-card"><time>{clock(lesson.start)}–{clock(lesson.end)}</time><strong>{lesson.subject}</strong><p>
            {lesson.room?'Аудитория '+lesson.room+(lesson.building?' — корпус '+lesson.building:''):'Аудитория уточняется'}
          </p>
            {lesson.teachers.map(teacher=>user.role==='admin'?<Link key={teacher.number} href={'/schedule?'+params({scope:'teacher',entity_id:String(teacher.number),building:teacher.building,day})}>{teacher.label}</Link>:
              <span key={teacher.number}>{teacher.label}</span>)}
            {user.role==='admin'&&<button className="secondary" onClick={()=>void api('/admin/lessons/'+lesson.id+'/pin?pinned='+!lesson.pinned,{method:'PUT'}).then(()=>refresh(i=>i+1),error=>setError(message(error)))}>
              {lesson.pinned?'Снять закрепление':'Закрепить пару'}</button>}
          </article>
        </div>)}
      </section>)}</div>
      <section aria-label="Окна по дням" className="daily-gaps">
        <h3>Окна по дням</h3>
        <p className="muted">Окно считаем между занятиями одного дня, если в перерыв помещается целая пара.</p>
        <Status empty={!detail.data.windows.length?'В выбранном периоде таких окон нет.':undefined}/>
        {[...new Set(detail.data.windows.map(gap=>gap.day))].map(day=><section key={day} className="panel daily-gap">
          <h4>{dayLabel(day)}</h4>
          <ul>{detail.data?.windows.filter(gap=>gap.day===day).map(gap=><li key={gap.start}>
            <div><strong>{clock(gap.start)}–{clock(gap.end)}</strong> <span className="tag">{durationLabel(gap.minutes)}</span></div>
            <p>После «{gap.before}», до «{gap.after}». {gap.transfer&&(gap.walking_minutes!==null?
              'Переход между корпусами — '+gap.walking_minutes+' мин.':'Время перехода между корпусами пока неизвестно.')}</p>
          </li>)}</ul>
        </section>)}
      </section>
    </section>}
    {output&&<section><h2 ref={resultsHeading} tabIndex={-1} className="booking-anchor">Варианты переноса</h2>
      <Status empty={!output.items.length?'В выбранном диапазоне нет допустимого переноса, который сократит окна. Попробуйте другие даты или поиск по всей группе.':undefined}/>
      {output.items.map(item=><SuggestionCard key={item.id} item={item} admin={user.role==='admin'||user.role==='dean'} onUpdate={()=>refresh(value=>value+1)}/>)}
    </section>}
  </>
}
