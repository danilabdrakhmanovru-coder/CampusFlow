import { FormEvent, useEffect, useRef, useState } from 'react'
import { api, Lesson, Session, Teacher } from './api'
import { allRooms, bell, campus, campusInstant, clock, dayFmt, Heading, message, params, Status, today, useLoad } from './common'
import { Group, Profile } from './profile'
import { Icon } from './icons'
import { go, Link } from './routing'

const dateLabel = (day:string)=>new Intl.DateTimeFormat('ru-RU',{weekday:'short',day:'numeric',month:'short',timeZone:'UTC'}).format(new Date(day+'T12:00:00Z'))
export function durationLabel(minutes:number){
  const hours=Math.floor(minutes/60),rest=minutes%60
  return hours?[hours+' ч',rest?rest+' мин':''].filter(Boolean).join(' '):rest+' мин'
}
export const addDays=(day:string,n:number)=>new Date(Date.parse(day+'T12:00:00Z')+n*86400000).toISOString().slice(0,10)
export const monday=(day:string)=>addDays(day,-((new Date(day+'T12:00:00Z').getUTCDay()+6)%7))
const labelTime=(minute:number)=>String(Math.floor(minute/60)).padStart(2,'0')+':'+String(minute%60).padStart(2,'0')
function typeOf(subject:string) {
  if(/лаборатор|\(лаб/i.test(subject))return ['lab','Лабораторная']
  if(/практич|семинар|\(пр/i.test(subject))return ['practice','Практическая']
  if(/лекци|\(лек/i.test(subject))return ['lecture','Лекция']
  return ['other','']
}
type Gap = {key:string;prev:Lesson;next:Lesson;minutes:number}

function GroupAnalysisAction({groups,day,lesson,primary=false,label}:{
  groups:string[];day:string;lesson?:number;primary?:boolean;label:string
}) {
  const href=(group:string)=>'/windows?'+params({group,day,...(lesson===undefined?{}:{lesson:String(lesson)})})
  if(!groups.length)return null
  if(groups.length===1)return <Link className={'action-link'+(primary?' primary-action':'')} href={href(groups[0])}>
    <Icon name={lesson===undefined?'chart':'calendar'}/>{label}</Link>
  return <form className="actions group-analysis-choice" onSubmit={event=>{
    event.preventDefault()
    const group=String(new FormData(event.currentTarget).get('group')??'')
    if(groups.includes(group))go(href(group))
  }}>
    <label>Группа для разбора<select name="group" defaultValue="" required>
      <option value="" disabled>Выберите группу</option>
      {groups.map(group=><option key={group}>{group}</option>)}
    </select></label>
    <button className={primary?undefined:'secondary'}>{label}</button>
  </form>
}

export function Schedule({user}:{user:Session}){
  const query=new URLSearchParams(location.search)
  const profile=useLoad(()=>api<Profile>('/me'),'weekly-profile')
  const raw=query.get('scope')
  const scope=raw&&['group','room','building',...(user.role==='admin'?['teacher']:['mine'])].includes(raw)?raw:user.role==='teacher'?'mine':'group'
  const entity=query.get('entity_id')||(scope==='group'?profile.data?.preferences.group??'':'')
  const building=query.get('building')??''
  const givenDay=query.get('day')??''
  const initialDay=/^\d{4}-\d{2}-\d{2}$/.test(givenDay)&&Number.isFinite(Date.parse(givenDay))?givenDay:today()
  const first=monday(initialDay)
  const days=Array.from({length:6},(_,i)=>addDays(first,i))
  const [shown,show]=useState(initialDay>days[5]?days[5]:initialDay)
  const [mode,setMode]=useState<'day'|'week'>(()=>matchMedia('(max-width:700px)').matches?'day':'week')
  const [offset,more]=useState(0)
  const [now,setNow]=useState(Date.now)
  const [format,setFormat]=useState<'pdf'|'docx'>()
  const [notice,setNotice]=useState('')
  const [error,setError]=useState('')
  const search=useRef<HTMLInputElement>(null)
  const touch=useRef<number|null>(null)
  const groups=useLoad(()=>api<Group[]>('/catalog/groups'),'schedule-groups')
  const rooms=useLoad(allRooms,'schedule-rooms')
  const names=useLoad(()=>user.role==='admin'?api<{teachers:Teacher[]}>('/schedule/entities'):Promise.resolve({teachers:[]}), 'schedule-names')
  const available=scope==='mine'||!!entity
  const period = params({scope,entity_id:entity,building,from:first,to:days[5]})
  const result=useLoad(()=>available?api<{items:Lesson[];next_offset:number|null}>('/schedule?'+period+'&offset='+offset):Promise.resolve({items:[],next_offset:null}),period+':'+offset)
  const source=useLoad(()=>api<{schedule_updated_at:string|null}>('/site'),'schedule-source')
  const labels:Record<string,string>={group:'Группа',room:'Аудитория',building:'Корпус',...(user.role==='teacher'?{mine:'Моё расписание'}:{}),...(user.role==='admin'?{teacher:'Преподаватель'}:{})}
  const choices=scope==='group'?groups.data?.map(group=>[group.code,group.code]):
    scope==='room'?rooms.data?.map(room=>['Корпус '+room.building+' — '+room.code,String(room.id)]):
    scope==='building'?[...new Set(rooms.data?.map(room=>room.building))].map(value=>[value,value]):
    scope==='teacher'?names.data?.teachers?.map(t=>['Корпус '+t.building+' — '+t.label,t.building+'|'+t.number]):[]
  const selected=choices?.find(choice=>choice[1]===(scope==='teacher'?building+'|'+entity:entity))?.[0]??(scope==='group'?entity:'')
  const [recent,setRecent]=useState<string[]>(()=>JSON.parse(localStorage.getItem('cf-search:'+user.id)??'[]'))
  function navigate(day:string,newScope=scope,id=entity,b=building) {
    go('/schedule?'+params({scope:newScope,entity_id:id,building:b,day}))
  }
  function searchFor(event:FormEvent) {
    event.preventDefault()
    const value=search.current?.value.trim()??''
    const exact=choices?.find(entry=>entry[0].toLocaleLowerCase('ru')===value.toLocaleLowerCase('ru'))
    if(!exact&&scope!=='mine'){setError('Выберите значение из подсказок.');return}
    const [b,id]=scope==='teacher'?(exact?.[1]??'').split('|'):['',exact?.[1]??'']
    const entry='/schedule?'+params({scope,entity_id:id,building:b,day:first})
    const next=[entry,...recent.filter(item=>item!==entry)].slice(0,5)
    if(scope!=='mine'){setRecent(next);localStorage.setItem('cf-search:'+user.id,JSON.stringify(next))}
    go(entry)
  }
  useEffect(()=>{
    if(search.current)search.current.value=selected
  },[selected])
  useEffect(()=>{const id=window.setInterval(()=>setNow(Date.now()),30000);return ()=>clearInterval(id)},[])
  const lessons=result.data?.items??[]
  const current=lessons.find(lesson=>Date.parse(lesson.start)<=now&&now<Date.parse(lesson.end))
  const next=lessons.find(lesson=>Date.parse(lesson.start)>now)
  const groupsFlag=scope==='group'||scope==='mine'||scope==='teacher'
  const canSeeGaps=groupsFlag&&(user.role!=='student'||profile.data?.preferences.group===entity)
  const gapMap=new Map<number,Gap>()
  if(canSeeGaps){
    let previous:Lesson|undefined
    for(const lesson of lessons){
      if(previous&&dayFmt.format(new Date(previous.end))===dayFmt.format(new Date(lesson.start))){
        const min=(Date.parse(lesson.start)-Date.parse(previous.end))/60000
        const day=dayFmt.format(new Date(lesson.start))
        const wholePair=bell.some(([start,end])=>Date.parse(previous!.end)<=campusInstant(day,start).getTime()&&
          campusInstant(day,end).getTime()<=Date.parse(lesson.start))
        if(min>=40&&wholePair)gapMap.set(lesson.id,{key:String(lesson.id),prev:previous,next:lesson,minutes:Math.floor(min)})
      }
      if(!previous||Date.parse(lesson.end)>Date.parse(previous.end))previous=lesson
    }
  }
  const canSuggest=user.role==='admin'||user.role==='dean'
  const analysisGroups=(codes:string[])=>scope==='group'?[entity]:[...new Set(codes)].sort((a,b)=>a.localeCompare(b,'ru'))
  const groupsForWeek=analysisGroups(lessons.flatMap(lesson=>lesson.groups))
  async function download(kind:'pdf'|'docx'){
    setFormat(kind);setError('')
    try{
      const data=await api<Blob>('/schedule/export/'+kind+'?'+period)
      if(!(data instanceof Blob))throw new Error('Не удалось сформировать файл расписания.')
      const url=URL.createObjectURL(data)
      const link=document.createElement('a')
      link.href=url;link.download='campusflow-schedule.'+kind;link.click()
      setTimeout(()=>URL.revokeObjectURL(url),10000)
    }catch(error){setError(message(error))}
    finally{setFormat(undefined)}
  }
  const lessonCard=(lesson:Lesson,day:string)=>{
    const [style,type]=typeOf(lesson.subject)
    return <article className={'lesson-card '+style+(current?.id===lesson.id?' is-current':'')} key={lesson.id}>
      <time dateTime={lesson.start}>{clock(lesson.start)}–{clock(lesson.end)}</time>{type&&<span className="tag">{type}</span>}
      <strong>{lesson.subject.replace(/\s+\((?:лекция|практическая|лабораторная)\)$/iu,'')}</strong>
      <p>{lesson.room?lesson.room+(lesson.building?' — корпус '+lesson.building:''):'Аудитория уточняется'}</p>
      <p>{lesson.groups.join(', ')}{lesson.teachers.length>0&&' — '+lesson.teachers.map(t=>t.label).join(', ')}</p>
      {(canSuggest||user.role==='teacher')&&<div className="lesson-actions">
        {user.role==='teacher'&&<Link className="action-link primary-action" href={'/booking?'+params({day,start:lesson.start,end:lesson.end,source:'lesson'})}>
          <Icon name="room"/>Забронировать другую аудиторию</Link>}
        {canSuggest&&<GroupAnalysisAction groups={analysisGroups(lesson.groups)} day={day} lesson={lesson.id} label="Предложить перенос"/>}
      </div>}
    </article>
  }
  const gapCard=(gap:Gap)=><div className="weekly-gap" key={gap.key}><strong>Окно {durationLabel(gap.minutes)}</strong>
    <div className="lesson-actions">{user.role!=='dean'&&<Link className="action-link" href={(user.role==='teacher'?'/booking?':'/rooms?')+params({day:dayFmt.format(new Date(gap.prev.end)),start:gap.prev.end,end:gap.next.start,...(gap.next.building?{building:gap.next.building}:{})})}>
      <Icon name="room"/>{user.role==='teacher'?'Подобрать аудиторию в окно':'Где посидеть'}</Link>}
      {canSuggest&&<GroupAnalysisAction groups={analysisGroups(gap.next.groups.filter(group=>gap.prev.groups.includes(group)))}
        day={dayFmt.format(new Date(gap.next.start))} primary label="Сократить окно"/>}</div></div>
  function nextDay(change:number){
    const next=addDays(shown,change)
    if(next<first||next>days[5])navigate(addDays(shown,change<0?-2:2))
    else show(next)
  }
  const basicViews=Object.entries(labels).filter(([key])=>key==='group'||key==='mine')
  const otherViews=Object.entries(labels).filter(([key])=>key!=='group'&&key!=='mine')
  const viewLinks=(views:[string,string][])=>views.map(([key,label])=>
    <Link className="secondary" key={key} href={'/schedule?'+params({scope:key,day:first})} current={key===scope}>{label}</Link>)
  return <div className="weekly-schedule"><Heading title="Расписание"/>
    {user.role==='teacher'&&scope==='mine'&&<Link className="action-link" href="/profile">Настроить дни без занятий</Link>}
    <nav className="actions room-views" aria-label="Поиск расписания">
      {(basicViews.length>1||scope!=='group')&&viewLinks(basicViews)}
      <details className="secondary-options" open={otherViews.some(([key])=>key===scope)||undefined}>
        <summary>Другие расписания</summary>
        <div className="actions">{viewLinks(otherViews)}</div>
      </details>
    </nav>
    {scope!=='mine'&&<form className="toolbar" onSubmit={searchFor}><label>{labels[scope]}
      <input ref={search} defaultValue={selected} list="weekly-entities" placeholder={'Поиск: '+labels[scope].toLowerCase()} required/></label>
      <datalist id="weekly-entities">{choices?.map(([label,id])=><option key={id} value={label}/>)}</datalist><button>Найти</button></form>}
    {!!recent.length&&<details className="recent-searches"><summary>Недавние запросы</summary><ul>{recent.map(url=>{
      const data=new URL(url,location.origin).searchParams
      const id=data.get('entity_id')??''
      const kind=data.get('scope')??'group'
      return <li key={url}><Link href={url}>{labels[kind]??'Расписание'} — {kind==='room'?rooms.data?.find(room=>String(room.id)===id)?.code??id:id}</Link></li>
    })}</ul></details>}
    {user.role==='student'&&!entity&&<p className="feedback">Выберите группу здесь или <Link href="/profile">задайте свою группу в профиле</Link>.</p>}
    {user.role==='teacher'&&scope==='mine'&&profile.data&&!profile.data.teacher&&<p className="feedback">Для просмотра ваших занятий <Link href="/profile">запросите привязку к расписанию</Link>.</p>}
    <div className="weekly-tools actions">
      <div className="week-picker">
        <button className="secondary" onClick={()=>navigate(addDays(first,-7))} aria-label="Прошлая неделя">‹</button>
        <strong>Неделя {dateLabel(first)} — {dateLabel(days[5])}</strong>
        <button className="secondary" onClick={()=>navigate(addDays(first,7))} aria-label="Следующая неделя">›</button>
      </div>
      <button className="secondary" onClick={()=>{show(today());navigate(today())}}>Сегодня</button>
      <button className="secondary" aria-pressed={mode==='day'} onClick={()=>setMode('day')}>День</button>
      <button className="secondary" aria-pressed={mode==='week'} onClick={()=>setMode('week')}>Неделя</button>
    </div>
    <Status pending={available&&!result.data&&!result.error} error={error||result.error} empty={available&&result.data?.items.length===0?'Занятий за эту неделю нет.':undefined}/>
    {result.data&&available&&<>
      {canSuggest&&available&&groupsForWeek.length>0&&<section className="schedule-improve" aria-label="Как сократить окна">
        <div><h2>Как сократить окна</h2>
          {groupsForWeek.length===1&&<p>Группа для разбора <strong>{groupsForWeek[0]}</strong></p>}
          <p>Найдите пары, которые можно перенести.</p></div>
        <GroupAnalysisAction groups={groupsForWeek} day={first} primary label="Разобрать окна и найти переносы"/>
      </section>}
      {current?<p className="muted">Сейчас: {current.subject}</p>:next&&<p className="muted">
        Следующая пара {dateLabel(dayFmt.format(new Date(next.start)))}, {clock(next.start)}: {next.subject}
      </p>}
      {mode==='day'&&<section className="mobile-day" onTouchStart={e=>{touch.current=e.changedTouches[0].clientX}} onTouchEnd={e=>{
        const dx=touch.current===null?0:e.changedTouches[0].clientX-touch.current
        touch.current=null
        if(Math.abs(dx)>60)nextDay(dx>0?-1:1)
      }}><div className="actions"><button className="secondary" onClick={()=>nextDay(-1)} aria-label="Предыдущий день">‹</button>
        <strong>{dateLabel(shown)}</strong><button className="secondary" onClick={()=>nextDay(1)} aria-label="Следующий день">›</button></div>
        {lessons.filter(lesson=>dayFmt.format(new Date(lesson.start))===shown).map(lesson=><div key={lesson.id}>{gapMap.has(lesson.id)&&gapCard(gapMap.get(lesson.id)!)}{lessonCard(lesson,shown)}</div>)}
      </section>}
      <div className={'weekly-table '+(mode==='day'?'print-only':'')}><table><caption>Расписание на неделю</caption>
        <thead><tr><th scope="col">Пара</th>{days.map(day=><th scope="col" key={day}>{dateLabel(day)}</th>)}</tr></thead>
        <tbody>{[...bell,[-1,-1]].map(([a,b],i)=><tr key={a}>
          <th scope="row">{a<0?'Вне сетки':<>{i+1} пара<small>{labelTime(a)}–{labelTime(b)}</small></>}</th>
          {days.map(day=><td key={day}>{lessons.filter(lesson=>dayFmt.format(new Date(lesson.start))===day&&(
            a<0?!bell.some(([start,end])=>Date.parse(lesson.start)>=campusInstant(day,start).getTime()&&Date.parse(lesson.start)<campusInstant(day,end).getTime()):
            Date.parse(lesson.start)>=campusInstant(day,a).getTime()&&Date.parse(lesson.start)<campusInstant(day,b).getTime()
          )).map(lesson=><div key={lesson.id}>{gapMap.has(lesson.id)&&gapCard(gapMap.get(lesson.id)!)}{lessonCard(lesson,day)}</div>)}</td>)}
        </tr>)}</tbody></table></div>
      {(offset>0||result.data.next_offset!==null)&&<div className="actions"><button disabled={!offset} onClick={()=>more(offset-500)}>Предыдущие занятия</button>
        <button disabled={result.data.next_offset===null} onClick={()=>more(offset+500)}>Следующие занятия</button></div>}
      <details className="secondary-options schedule-export"><summary>Скачать, распечатать или поделиться</summary><div className="actions">
        <button className="secondary" disabled={!!format} onClick={()=>void download('pdf')}>{format==='pdf'?'Готовим PDF…':'Скачать PDF'}</button>
        <button className="secondary" disabled={!!format} onClick={()=>void download('docx')}>{format==='docx'?'Готовим Word…':'Скачать Word'}</button>
        <button className="secondary" onClick={()=>window.print()}>Печать недели</button>
        <button className="secondary" onClick={()=>void navigator.clipboard.writeText(location.origin+'/schedule?'+params({scope,entity_id:entity,building,day:first})).then(()=>setNotice('Ссылка скопирована.'),()=>setNotice('Скопируйте адрес из строки браузера.'))}>Поделиться ссылкой</button>
      </div>{notice&&<p className="feedback" role="status">{notice}</p>}
      {source.data?.schedule_updated_at&&<p className="muted">Данные обновлены {new Intl.DateTimeFormat('ru-RU',{dateStyle:'medium',timeStyle:'short',timeZone:campus}).format(new Date(source.data.schedule_updated_at))}</p>}</details>
    </>}
  </div>
}
