import { useState } from 'react'
import { api, Interval, json, Option, Room } from './api'
import { Icon, type IconName } from './icons'
import { Sheet } from './Sheet'
import { useLive } from './rooms'
import { allRooms, campusInstant, clock, dayFmt, fmt, Heading, kinds, message, options, params, Status, today, useLoad } from './common'

type DayRow = { room: Room; coverage: string; busy: (Interval & {kind?:string})[]; failed?: boolean }
const equipmentIcons:Record<string,IconName> = {pc:'pc',projector:'projector',board:'board',lift:'lift'}
const hours = Array.from({length:15},(_,i)=>i+8)
const minutes = (iso:string) => { const [h,m]=clock(iso).split(':').map(Number); return h*60+m }

export function Timeline({book}:{book?: (slot:Option)=>void}) {
  const url=new URLSearchParams(window.location.search)
  const [at,setAt] = useState(660)
  const [floor,setFloor] = useState('')
  const [notice,setNotice] = useState('')
  const [watching,setWatching] = useState(false)
  const revision = useLive()
  const [day,setDay] = useState(today)
  const [chosenBuilding,setBuilding]=useState(()=>url.get('building')??localStorage.getItem('cf-building')??'')
  const [kind,setKind] = useState('')
  const [capacity,setCapacity] = useState('')
  const [instant,setInstant] = useState<Date>()
  const [page,setPage] = useState(0)
  const [selected,setSelected] = useState<number|undefined>(()=>Number(url.get('room'))||undefined)
  const rooms = useLoad(allRooms,'catalog')
  const buildings=[...new Set(rooms.data?.map(room=>room.building))].sort()
  const building=chosenBuilding||buildings[0]||''
  const [scheme,setScheme]=useState(false)
  const filtered = rooms.data?.filter(r=>(!building||r.building===building)&&(!floor||String(r.floor)===floor)&&(!kind||r.kind===kind)&&(!capacity||(r.capacity??0)>=Number(capacity))) ?? []
  const start = campusInstant(day,480).toISOString()
  const end = campusInstant(day,23*60).toISOString()
  const fromSearch = Number(url.get('room'))
  const ordered = [...filtered].sort((a,b)=>Number(b.id===fromSearch)-Number(a.id===fromSearch))
  const visible = ordered.slice(page*16,page*16+16)
  const rows = useLoad(async() => Promise.all(visible.map(async room => {
    try { return {room,...await api<Omit<DayRow,'room'>>('/rooms/'+room.id+'/timeline?'+params({start,end}))} }
    catch { return {room,coverage:'unknown',busy:[],failed:true} }
  })), [day,revision,visible.map(r=>r.id).join(',')].join('|'), [day,visible.map(r=>r.id).join(',')].join('|'))
  function free(row:DayRow) {
    if(!instant||row.failed||row.coverage==='unknown') return false
    const startMs=instant.getTime(), endMs=startMs+30*60000
    return startMs>=Date.parse(start)&&endMs<=Date.parse(end)&&!row.busy.some(p=>Date.parse(p.start)<endMs&&Date.parse(p.end)>startMs)
  }
  const nowRows=useLoad(async()=>{
    if (!instant) return []
    const outcomes:DayRow[]=[]
    for(let offset=0;offset<filtered.length;offset+=12){
      const batch=await Promise.all(filtered.slice(offset,offset+12).map(async room=>{
        const interval={start:instant!.toISOString(),end:new Date(instant!.getTime()+30*60000).toISOString()}
        return {room,...await api<Omit<DayRow,'room'>>('/rooms/'+room.id+'/timeline?'+params(interval))}
      }))
      outcomes.push(...batch)
    }
    return outcomes
  }, instant ? [instant.toISOString(), filtered.map(r=>r.id).join(',')].join('|') : 'off')
  const current = instant ? nowRows.data?.filter(free) : rows.data
  const detail=current?.find(row=>row.room.id===selected)
  const layers:Record<string,string> = {lesson:'Пара',booking:'Бронь',hold:'Удержание',block:'Блок'}
  const value = String(Math.floor(at/60)).padStart(2,'0')+':'+String(at%60).padStart(2,'0')
  const marker = campusInstant(day,at).getTime()
  const measured = Boolean(building && floor && current?.every(({room}) => room.plan_x != null && room.plan_y != null))
  function status(row:DayRow) {
    const busy = row.busy.find(item=>Date.parse(item.start)<=marker&&marker<Date.parse(item.end))
    if (busy) return { style:'hatch', text:'Занята: '+(layers[busy.kind??'']??'занятость')+' до '+clock(busy.end) }
    if(row.failed) return { style:'unknown', text:'Ошибка загрузки' }
    if(row.coverage==='unknown') return { style:'unknown', text:'Нет данных' }
    const next = row.busy.find(item=>Date.parse(item.start)>marker)
    if(next && Date.parse(next.start)-marker<=1800000) return { style:'soon', text:'Скоро занята, свободна до '+clock(next.start) }
    return { style:'free', text:'Свободна' }
  }
  async function watch(room:Room, period:Interval) {
    setWatching(true);setNotice('')
    try {
      await api('/watches',json({room_id:room.id,start:period.start,end:period.end},'POST',crypto.randomUUID()))
      setNotice('Подписка создана. Если аудитория освободится, удержим её на пять минут и пришлём уведомление.')
    } catch(e) {setNotice(message(e))}
    finally {setWatching(false)}
  }
  function reset(){setInstant(undefined);setSelected(undefined);setPage(0)}
  return <>
    <Heading title="План кампуса" description="Выберите этаж и время. При наличии координат аудитории размещаются на схеме этажа."/>
    <div className="toolbar">
      <label>Дата<input type="date" value={day} onChange={e=>{if(e.target.value){setDay(e.target.value);reset()}}}/></label>
      <label>Корпус<select value={building} onChange={e=>{setBuilding(e.target.value);setFloor('');reset()}}>{buildings.map(key=><option key={key}>{key}</option>)}</select></label>
      <label>Этаж<select value={floor} onChange={e=>{setFloor(e.target.value);reset()}}><option value="">Все этажи</option>{[...new Set(rooms.data?.filter(r=>(!building||r.building===building)&&r.floor!==null).map(r=>r.floor)??[])].sort((a,b)=>Number(a)-Number(b)).map(n=><option key={n} value={String(n)}>{n}</option>)}</select></label>
      <label>Тип<select value={kind} onChange={e=>{setKind(e.target.value);reset()}}><option value="">Все типы</option>{options.map(o=><option key={o.value} value={o.value}>{o.label}</option>)}</select></label>
      <label>Мест от<input type="number" min="1" placeholder="Любое" value={capacity} onChange={e=>{setCapacity(e.target.value);reset()}}/></label>
      <button onClick={()=>{const value=new Date();setDay(dayFmt.format(value));setInstant(value);setSelected(undefined)}}>Свободно сейчас</button>
      {instant&&<button className="secondary" onClick={reset}>Весь день</button>}
    </div>
    {!instant&&<div className="plan-time">
      <label className="scrubber" htmlFor="plan-time">Время на плане <output htmlFor="plan-time">{value}</output></label>
      <input id="plan-time" aria-valuetext={value} type="range" min="480" max="1320" step="15" value={at} onChange={e=>setAt(Number(e.target.value))}/>
    </div>}
    {notice&&<p role="status" className="feedback">{notice}</p>}
    {measured&&!!current?.length&&<button className="secondary" aria-expanded={scheme} onClick={()=>setScheme(!scheme)}>Схема этажа</button>}
    {scheme&&measured&&!instant&&current&&current.length>0&&<div className='floor-plan measured'  aria-label="Схема этажа">{current.map(row=>{
      const roomState = status(row)
      return <button key={row.room.id} style={measured?{left:row.room.plan_x+'%',top:row.room.plan_y+'%'}:undefined}
        className={'plan-room '+roomState.style} onClick={()=>setSelected(row.room.id)}>
        <strong>{row.room.code}</strong><small>{roomState.text}</small>
      </button>
    })}</div>}
    <div className="legend"><span><i className="hatch"/>Занято</span><span><i className="free"/>Свободна</span><span><i className="soon"/>Скоро занята</span><span><i className="unknown"/>Недостаточно данных</span></div>
    {instant&&<p role="status">Доступность на {fmt.format(instant)}–{fmt.format(new Date(instant.getTime()+30*60000))}. Проверено аудиторий: {nowRows.data?.length??0}.</p>}
    <Status pending={!rooms.data&&!rooms.error || (!!filtered.length&&!current&&!(instant?nowRows.error:rows.error))}
      error={rooms.error || (instant?nowRows.error:rows.error)}
      empty={rooms.data&&!filtered.length?'По этим фильтрам аудиторий нет.':current?.length===0&&instant?'Нет подтверждённо свободных аудиторий. Проверьте полноту импорта корпуса.':undefined}/>
    {current&&current.length>0&&<div className="timeline">
      {!instant&&<div className="timeline-head"><span>Аудитория</span><div>{hours.map(h=><span key={h}>{h}:00</span>)}</div></div>}
      {current.map(row=><div className="timeline-row" key={row.room.id}>
        <button className="room-link" aria-expanded={selected===row.room.id} onClick={()=>setSelected(selected===row.room.id?undefined:row.room.id)}>
          <strong>{row.room.code}</strong><small>Корпус {row.room.building} — {row.room.capacity??'—'} мест</small>
        </button>
        {instant?<span className="tag">Свободна</span>:<>
          <div className={'track '+(row.coverage==='unknown'?'unknown':'free')} aria-hidden="true">
            {row.busy.map((p,i)=>{
              const left=Math.max(480,minutes(p.start)),right=Math.min(1380,minutes(p.end))
              return right>left&&<i key={i} className="hatch segment" style={{left:((left-480)/9)+'%',width:((right-left)/9)+'%'}} title={clock(p.start)+'–'+clock(p.end)}/>
            })}
          </div>
          <p className="row-summary"><strong>{status(row).text}. </strong>{row.failed?'Ошибка загрузки':(row.busy.length?row.busy.map(p=>(layers[p.kind??'']??'Занято')+' '+clock(p.start)+'–'+clock(p.end)).join(', '):'Занятые интервалы не указаны')+(row.coverage==='unknown'?' — расписание корпуса на выбранный день ещё не подтверждено':' — остальное свободно')}</p>
        </>}
        {detail?.room.id===row.room.id&&<Sheet label={'Аудитория '+row.room.code} className="room-detail" onClose={()=>setSelected(undefined)}><button className="secondary" onClick={()=>setSelected(undefined)}>Закрыть</button><strong>{kinds[row.room.kind??'']??'Тип не указан'}</strong>
          <span>Этаж: {row.room.floor??'—'} — Доступность: {row.room.accessible===null?'неизвестно':row.room.accessible?'да':'нет'}</span>
          <div className="actions">{Object.entries(row.room.equipment).map(([key,n])=><span className="equipment" key={key}><Icon name={equipmentIcons[key]??'control'}/>{key} × {n}</span>)}{!Object.keys(row.room.equipment).length&&'Оборудование не указано'}</div>
          {!instant&&row.busy.length>0&&<ul className="records">{row.busy.map(p=><li key={p.start+p.end}>
            <span>{layers[p.kind??'']??'Занято'} — {clock(p.start)}–{clock(p.end)}</span>
            {book&&p.kind!=='lesson'&&p.kind!=='block'&&Date.parse(p.end)>Date.now()+15*60000&&<button className="secondary" disabled={watching} onClick={()=>void watch(row.room,p)}>Сообщить, если освободится</button>}
          </li>)}</ul>}
          {instant&&book&&Date.now()<instant.getTime()+5*60000&&<button onClick={()=>book({room_id:row.room.id,room:row.room.code,building:row.room.building,start:new Date(Date.now()+5*60000).toISOString(),end:new Date(instant.getTime()+30*60000).toISOString()})}>Перейти к бронированию</button>}
        </Sheet>}
      </div>)}
    </div>}
    {!instant&&filtered.length>16&&<div className="actions"><button className="secondary" disabled={page===0} onClick={()=>setPage(page-1)}>Назад</button><span>Страница {page+1} из {Math.ceil(filtered.length/16)}</span><button className="secondary" disabled={(page+1)*16>=filtered.length} onClick={()=>setPage(page+1)}>Далее</button></div>}
  </>
}
