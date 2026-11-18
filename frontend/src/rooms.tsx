import { useEffect, useState } from 'react'
import QRCode from 'qrcode'
import { Icon } from './icons'
import { Profile } from './profile'
import { Sheet } from './Sheet'
import { api, Booking, json, occupancyEvents, Option } from './api'
import { allRooms, bell, campusInstant, clock, dayFmt, fmt, Heading, kinds, message, Status, today, useLoad } from './common'

export function useLive() {
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    let timer: number | undefined
    async function connect() {
      try { await occupancyEvents(controller.signal, () => setRevision(value => value + 1)) }
      catch { /* Retry after a lost connection. */ }
      if (!controller.signal.aborted) timer = window.setTimeout(connect, 5000)
    }
    void connect()
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [])
  return revision
}

const equipmentNames:Record<string,string>={accessible:'Доступная среда',pc:'Компьютеры',projector:'Проектор',board:'Доска',microphone:'Микрофон',screen:'Экран'}
type FreeRoom = { id:number; code:string; building:string; floor:number|null; capacity:number|null; kind:string|null; free_until:string; walk_minutes:number|null;equipment:Record<string,number>;accessible:boolean|null }
export function AvailableRooms({ book }: { book?: (slot: Option) => void }) {
  const query=new URLSearchParams(location.search)
  const [building, select] = useState(() => query.get('building')??localStorage.getItem('cf-building')??'')
  const [kind,setKind]=useState('')
  const [origin,setOrigin]=useState('')
  const [floor,setFloor]=useState('')
  const [capacity,setCapacity]=useState('')
  const [equipment,setEquipment]=useState<string[]>([])
  const queryStart=query.get('start')??''
  const queryEnd=query.get('end')??''
  const hasInterval=!!queryStart&&!!queryEnd&&Number.isFinite(Date.parse(queryStart))&&Date.parse(queryEnd)>Date.parse(queryStart)
  const [mode,setMode]=useState(hasInterval?'interval':'now')
  const [day,setDay]=useState(()=>hasInterval?dayFmt.format(new Date(queryStart)):today())
  const [pair,setPair]=useState('1')
  const [linked,setLinked]=useState(hasInterval)
  const catalog=useLoad(allRooms,'now-origin')
  const profile=useLoad(()=>api<Profile>('/me'),'rooms-profile')
  const buildings=[...new Set(catalog.data?.map(item=>item.building))].sort()
  const activeBuilding=building||profile.data?.preferences.building||buildings[0]||''
  const [selected, show] = useState<FreeRoom>()
  const [time, updateTime] = useState(Date.now)
  const revision = useLive()
  const [a,b]=bell[Number(pair)-1]??bell[0]
  const start=linked?queryStart:mode==='today'?new Date(Math.floor(time/60000)*60000).toISOString():campusInstant(day,a).toISOString()
  const end=linked?queryEnd:mode==='today'?campusInstant(today(),1380).toISOString():campusInstant(day,b).toISOString()
  const data = useLoad(async()=>{
    if(!activeBuilding)return {covered:false,rooms:[] as FreeRoom[]}
    const params=new URLSearchParams({building:activeBuilding,...(origin?{from_room_id:origin}:{})})
    if(mode==='now')return api<{covered:boolean;rooms:FreeRoom[]}>('/free-now?'+params)
    if(Date.parse(end)<=Math.max(Date.parse(start),time))return {covered:false,rooms:[] as FreeRoom[],ended:true}
    params.set('start',start);params.set('end',end)
    const result=await api<{covered_buildings:string[];rooms:FreeRoom[];ended?:boolean}>('/rooms/free?'+params)
    return {covered:result.covered_buildings.includes(activeBuilding),rooms:result.rooms,ended:result.ended}
  },[activeBuilding,origin,mode,mode==='now'?Math.floor(time/60000):start,end,revision].join(':'))
  useEffect(() => {
    const id = window.setInterval(() => updateTime(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])
  const shown = data.data?.rooms.filter(room => (!kind||room.kind===kind)&&(!floor||String(room.floor)===floor)&&
    (!capacity||(room.capacity??0)>=Number(capacity))&&equipment.every(key=>key==='accessible'?room.accessible:room.equipment[key]))
  const visibleRoom = data.data?.rooms.find(room => room.id === selected?.id)
  return <>
    <Heading title="Свободные аудитории"/>
    <div className="board">
      <div className="clock">{mode==='now'?fmt.format(time):clock(start)+'–'+clock(end)}</div>
      <div className="actions filter-chips" aria-label="Корпус">{buildings.map(value =>
        <button key={value} aria-pressed={activeBuilding===value} className={activeBuilding===value?'':'secondary'} onClick={()=>{
          select(value);setFloor('');show(undefined);localStorage.setItem('cf-building',value)
        }}>Корпус {value}</button>)}</div>
    </div>
    <div className="actions filter-chips">{[['now','Сейчас'],['today','До конца дня'],['interval','Дата и пара']].map(([key,label])=>
      <button key={key} className="secondary" aria-pressed={mode===key} onClick={()=>{setMode(key);setLinked(false);show(undefined)}}>{label}</button>)}</div>
    {mode==='interval'&&!linked&&<div className="toolbar"><label>Дата<input type="date" value={day} onChange={e=>{if(e.target.value)setDay(e.target.value)}}/></label>
      <label>Пара<select value={pair} onChange={e=>setPair(e.target.value)}>{bell.map((_,index)=><option key={index} value={index+1}>{index+1} пара</option>)}</select></label></div>}
    {linked&&<p className="feedback">Поиск на время окна {clock(start)}–{clock(end)}.</p>}
    <details className="secondary-options"><summary>Фильтры аудиторий</summary>
    <div className="toolbar"><label>Этаж<select value={floor} onChange={event=>setFloor(event.target.value)}><option value="">Все этажи</option>
      {[...new Set(catalog.data?.filter(room=>room.building===activeBuilding&&room.floor!==null).map(room=>room.floor))].map(level=><option key={level} value={String(level)}>{level}</option>)}</select></label>
      <label>Мест от<input type="number" min="1" value={capacity} onChange={event=>setCapacity(event.target.value)}/></label></div>
    <div className="actions filter-chips" aria-label="Оборудование">{[...new Set(['accessible',...(catalog.data??[]).filter(room=>room.building===activeBuilding).flatMap(room=>Object.keys(room.equipment))])].map(key=>
      <button type="button" key={key} className="secondary" aria-pressed={equipment.includes(key)} onClick={()=>setEquipment(value=>value.includes(key)?value.filter(item=>item!==key):[...value,key])}>
        {equipmentNames[key]??key}</button>)}</div>
    <div className="actions filter-chips now-types" aria-label="Тип аудитории">{[['','Все типы'],...Object.entries(kinds)].map(([value,label])=>
      <button key={value} className={kind===value?'':'secondary'} aria-pressed={kind===value} onClick={()=>setKind(value)}>{label}</button>)}
    </div>
    <label className="now-origin">Откуда идти<select value={origin} onChange={e=>setOrigin(e.target.value)}>
      <option value="">Без маршрута</option>{catalog.data?.map(room=><option key={room.id} value={room.id}>{room.building} — {room.code}</option>)}
    </select></label></details>
    <Status pending={!data.data&&!data.error} error={data.error} empty={data.data ? 'ended' in data.data && data.data.ended?'Выбранное время уже прошло.':!data.data.covered ?
      'Расписание этого корпуса на выбранное время ещё не подтверждено.' :
      !data.data.rooms.length ? 'Сейчас свободных аудиторий нет.' : !shown?.length ? 'По выбранным фильтрам свободных аудиторий нет.' : undefined : undefined}/>
    <ul className="records board-rows">{shown?.map(r=><li key={r.id}>
      <button className="room-link" onClick={()=>show(r)}><strong>{r.code}</strong><small>{kinds[r.kind??'']??'Тип уточняется'}</small></button>
      <span className="room-meta">{r.capacity===null?'Вместимость уточняется':'Мест: '+r.capacity}{r.walk_minutes!==null&&' — '+r.walk_minutes+' мин пешком'}</span><div className="actions">{Object.entries(r.equipment).map(([key,value])=><span className="tag" key={key}><Icon name={key==='pc'?'pc':key==='projector'?'projector':key==='board'?'board':'room'}/> {equipmentNames[key]??key} × {value}</span>)}</div><span className={Date.parse(r.free_until)-time<=1800000?'soon-label':'free-label'}>
        {Date.parse(r.free_until)-time<=1800000?'Скоро занята':'Свободна'} до {clock(r.free_until)}</span>
    </li>)}</ul>
    {selected&&<Sheet label={'Аудитория '+selected.code} onClose={()=>show(undefined)}>
      <h2>Аудитория {selected.code}</h2><p>Корпус {selected.building} — этаж {selected.floor??'уточняется'}</p>
      <p>{visibleRoom?'Свободна до '+clock(visibleRoom.free_until):'Проверяем актуальность. Обновите список или выберите другую аудиторию.'}</p>
      <div className="actions">{book&&visibleRoom&&Date.parse(visibleRoom.free_until)>=time+15*60000&&<button onClick={()=>
        book({room_id:visibleRoom.id,room:visibleRoom.code,building:activeBuilding,start:mode==='now'?new Date().toISOString():start,end:mode==='now'?new Date(Math.min(Date.parse(visibleRoom.free_until),Date.now()+60*60000)).toISOString():end})
      }>Забронировать</button>}<button className="secondary" onClick={()=>show(undefined)}>Закрыть</button></div>
    </Sheet>}
  </>
}

type Ticket = { token:string; checked_in_at:string|null; auto_release_at:string; cancelled:boolean }
export function TicketPanel({ booking, close }: { booking:Booking; close:()=>void }) {
  const [revision, refresh] = useState(0)
  const [code,setCode]=useState('')
  const [qr, setQr] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const ticket = useLoad(()=>api<Ticket>('/tickets/'+booking.id), booking.id+':'+revision)
  useEffect(()=>{
    let active = true
    setQr('')
    if(ticket.data) void QRCode.toDataURL('campusflow:'+booking.id+':'+ticket.data.token).then(value=>{if(active)setQr(value)})
      .catch(()=>{if(active)setError('Не удалось сформировать QR талона.')})
    return ()=>{active=false}
  },[booking.id,ticket.data])
  async function checkIn() {
    if(!ticket.data) return
    setBusy(true);setError('')
    try { await api('/tickets/'+booking.id+'/check-in',json({code}));refresh(value=>value+1) }
    catch(e){setError(message(e))}finally{setBusy(false)}
  }
  return <Sheet label="Талон брони" onClose={close}><h2>Талон №{booking.id}</h2>
    <p>{booking.title} — {clock(booking.start)}–{clock(booking.end)}</p>
    <Status pending={!ticket.data&&!ticket.error} error={ticket.error||error}/>
    {ticket.data&&!ticket.data.cancelled&&<>
      {qr&&<img src={qr} alt={'QR талона №'+booking.id} width="160" height="160"/>}
      <p>{ticket.data.checked_in_at?'Явка отмечена в '+clock(ticket.data.checked_in_at):'Отметьтесь до '+clock(ticket.data.auto_release_at)}</p>
      {!ticket.data.checked_in_at&&<form className="toolbar" onSubmit={event=>{event.preventDefault();void checkIn()}}>
        <p>Введите код у двери. Если не отметиться в первые 15 минут, бронь освободится.</p>
        <label>Код аудитории<input autoComplete="off" minLength={6} required value={code} onChange={event=>setCode(event.target.value)}/></label>
        <button disabled={busy}>Отметиться</button>
      </form>}
    </>}
    {ticket.data?.cancelled&&<p>Бронь отменена.</p>}
    <button className="secondary" onClick={close}>Закрыть талон</button>
  </Sheet>
}
