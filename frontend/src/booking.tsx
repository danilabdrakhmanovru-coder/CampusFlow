import { FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, Booking, json, Option, Session } from './api'
import { Group, Profile } from './profile'
import { Icon } from './icons'
import { go } from './routing'
import { useConfirmation } from './Sheet'
import { TicketPanel, useLive } from './rooms'
import { allRooms, bell, campusInstant, clock, dayFmt, Heading, message, options, params, Status, Toast, today, useLoad } from './common'

const equipmentLabels:Record<string,string>={accessible:'Доступная среда',pc:'Компьютеры',board:'Доска',projector:'Проектор',microphone:'Микрофон',screen:'Экран'}
type Hold = { id:number; expires_at:string; start?:string; end?:string }
type RoomAlternative = {
  room_id:number; room:string; building:string; capacity:number|null
  selectable:boolean; status:'free'|'busy'|'unknown'|'no_time'; available:{start:string;end:string}|null; reasons:string[]
}
type Recommendations = {options:Option[];waiting:Option[];other_rooms:RoomAlternative[]}
const alternativeStatuses = {
  free:'Есть свободное время',busy:'Занята',unknown:'Занятость неизвестна',no_time:'Подходящего времени нет',
}
type Watch = Option & { id:number; state:string; offer?:Hold }
export function BookingPage({user,initial,initialTab="new"}:{user:Session;initial?:Option;initialTab?:"new"|"mine"|"watch"}) {
  const resultsHeading=useRef<HTMLHeadingElement>(null)
  const chosenHeading=useRef<HTMLHeadingElement>(null)
  const confirmHeading=useRef<HTMLHeadingElement>(null)
  const scrollToResults=useRef(false)
  const tab = initialTab
  function setTab(view: typeof tab) {
    go(view==='new'?'/booking':'/booking?view='+view)
  }
  const confirmation=useConfirmation()
  const [opened,setOpened]=useState<Booking>()
  const live=useLive()

  const url=new URLSearchParams(location.search)
  const profile=useLoad(()=>api<Profile>('/me'),'booking-profile')
  const groups=useLoad(()=>api<Group[]>('/catalog/groups'),'booking-groups')
  const [group,setGroup]=useState('')
  const [building,setBuilding]=useState<string>()
  const [otherRooms,setOtherRooms]=useState<RoomAlternative[]>([])
  const [count,setCount]=useState(20)
  const incomingDay=url.get('day')??''
  const incomingStart=url.get('start')??''
  const incomingEnd=url.get('end')??''
  const [day,setDay]=useState(initial ? dayFmt.format(Date.parse(initial.start)) : /^\d{4}-\d{2}-\d{2}$/.test(incomingDay)&&Number.isFinite(Date.parse(incomingDay))?incomingDay:today())
  const [kind,setKind]=useState('any')
  const [equipment,setEquipment]=useState<string[]>([])
  const [pair,setPair]=useState('')
  const [duration,setDuration]=useState(()=>Math.max(15,Math.min(480,(Date.parse(incomingEnd)-Date.parse(incomingStart))/60000||90)))
  const [customTime,setCustomTime]=useState(Number.isFinite(Date.parse(incomingStart))?clock(incomingStart):'')
  const [waiting,setWaiting]=useState<Option[]>([])
  const [filter,setFilter]=useState('all')
  const [editing,edit]=useState<Booking>()
  const [chosen,setChosen]=useState<Option|undefined>(initial)
  const [hold,setHold]=useState<Hold>()
  const [time,setTime]=useState(Date.now())
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const dismissNotice=useCallback(()=>setNotice(''),[])
  const [results,setResults]=useState<Option[]>()
  const [revision,refresh]=useState(0)
  const [offset,setOffset]=useState(0)
  const [key,setKey]=useState<string>()
  const [confirmKey,setConfirmKey]=useState<string>()
  const [renewKey,setRenewKey]=useState<string>()
  const watchers=useLoad(()=>tab==='watch'?api<Watch[]>('/watches'):Promise.resolve([]),tab+':'+live+':'+revision)
  const rooms=useLoad(allRooms,'catalog')
  const list=useLoad(()=>tab==='mine'?api<Booking[]>((user.role==='admin'?'/admin/bookings':'/bookings/mine')+'?offset='+offset+(user.role==='admin'?'':filter==='upcoming'?'&upcoming=true':filter==='all'?'':'&include_cancelled=true')):Promise.resolve([]),tab+':'+revision+':'+offset+':'+filter)
  useEffect(()=>{
    if(!hold)return
    const id=window.setInterval(()=>setTime(Date.now()),1000)
    return ()=>clearInterval(id)
  },[hold])
  const remaining=hold ? Math.max(0,Math.ceil((Date.parse(hold.expires_at)-time)/1000)) : 0
  async function run(action:()=>Promise<void>) {
    setBusy(true);setError('')
    try{await action()}catch(e){setError(message(e))}
    finally{setBusy(false)}
  }
  const selected=pair?bell[Number(pair)-1]:undefined
  const [hours,minutes]=customTime.split(':').map(Number)
  const exactMinute=selected?selected[0]:customTime?hours*60+minutes:undefined
  const buildings=[...new Set(rooms.data?.map(room=>room.building))].sort()
  const selectedBuilding=building??profile.data?.preferences.building??''
  const equipmentOptions=[...new Set(['projector','pc','accessible',...(rooms.data??[]).flatMap(room=>Object.keys(room.equipment))])]
  const fitCount=rooms.data?.filter(room=>(!selectedBuilding||room.building===selectedBuilding)&&(kind==='any'||room.kind===kind)
    &&room.capacity!==null&&room.capacity>=count&&equipment.every(key=>key==='accessible'?room.accessible:room.equipment[key])).length
  const groupValid=!group||groups.data?.some(item=>item.code===group)
  const criteria:Record<string,string>={day,kind,count:String(count),equipment:equipment.join(','),duration:String(duration)}
  if(exactMinute!==undefined)criteria.start_minute=String(exactMinute)
  if(selectedBuilding)criteria.building=selectedBuilding
  if(group)criteria.group=group
  const queryString=params(criteria)
  const [submitted,setSubmitted]=useState(0)
  const [searching,setSearching]=useState(false)
  const activeQuery=tab==='new'&&groupValid&&day&&count>=1&&count<=10000&&duration>=15&&duration<=480?queryString:''
  useEffect(()=>{
    if(!submitted||!activeQuery||hold){setSearching(false);return}
    setSearching(true)
    const controller=new AbortController()
    const timer=window.setTimeout(()=>{
      void api<Recommendations>('/slots/recommendations?'+activeQuery,{signal:controller.signal})
        .then(response=>{
          if(controller.signal.aborted)return
          setResults(response.options);setWaiting(response.waiting);setOtherRooms(response.other_rooms??[])
        },error=>{if(!controller.signal.aborted)setError(message(error))})
        .finally(()=>{if(!controller.signal.aborted)setSearching(false)})
    },submitted?220:450)
    return ()=>{window.clearTimeout(timer);controller.abort()}
  },[activeQuery,hold,initial,submitted])
  function clearResults(){
    setChosen(undefined);setKey(undefined);setResults(undefined);setOtherRooms([]);setWaiting([]);setError('')
  }
  function focusSection(section:HTMLHeadingElement|null){
    section?.scrollIntoView({block:'start'})
    section?.focus({preventScroll:true})
  }
  useEffect(()=>{
    if(results&&scrollToResults.current){
      scrollToResults.current=false
      focusSection(resultsHeading.current)
    }
  },[results])
  useEffect(()=>{if(chosen&&!hold)focusSection(chosenHeading.current)},[chosen,hold])
  useEffect(()=>{if(hold)focusSection(confirmHeading.current)},[hold])
  function search(event:FormEvent<HTMLFormElement>){
    event.preventDefault()
    if(!groupValid){setError('Выберите группу из подсказок или оставьте поле пустым.');return}
    clearResults();setNotice('')
    scrollToResults.current=true
    setSubmitted(value=>value+1)
  }
  function watch(option:Option){
    void run(async()=>{
      await api('/watches',json({room_id:option.room_id,start:option.start,end:option.end},'POST',crypto.randomUUID()))
      refresh(value=>value+1);setNotice('Вы в очереди. Когда очередь дойдёт до вас, у вас будет 5 минут для подтверждения.');setTab('watch')
    })
  }
  function acquire(){
    if(!chosen)return
    const requestKey=key??crypto.randomUUID()
    setKey(requestKey)
    void run(async()=>{
      try{
        const value=await api<Hold>('/booking-holds',json({room_id:chosen.room_id,start:chosen.start,end:chosen.end},'POST',requestKey))
        setTime(Date.now());setHold(value);setRenewKey(undefined);setNotice('')
      }catch(e){
        if(e instanceof ApiError&&e.status===409){
          setChosen(undefined)
          setKey(undefined)
          setResults(e.alternatives);setOtherRooms([]);setWaiting([])
        }
        throw e
      }
    })
  }
  function release(){
    void run(async()=>{
      if(hold&&remaining)await api('/booking-holds/'+hold.id,{method:'DELETE'})
      setHold(undefined);setChosen(undefined);setKey(undefined);setConfirmKey(undefined)
    })
  }
  function confirm(event:FormEvent<HTMLFormElement>){
    event.preventDefault()
    if(!hold)return
    const fields=new FormData(event.currentTarget)
    const title=String(fields.get('title')).trim()
    const repeats=Number(fields.get('repeats')??1)
    const requestKey=confirmKey??crypto.randomUUID()
    setConfirmKey(requestKey)
    void run(async()=>{
      await api('/bookings',json({hold_id:hold.id,title,repeats},'POST',requestKey))
      setHold(undefined);setChosen(undefined);setKey(undefined);setConfirmKey(undefined);setNotice('Бронь подтверждена.')
      setSubmitted(0);setOffset(0);refresh(revision+1);setTab('mine')
    })
  }
  return <>
    {confirmation.dialog}
    <Heading title="Бронирование"/>
    <div className="actions"><button className={tab==='new'?'':'secondary'} aria-pressed={tab==='new'} onClick={()=>setTab('new')}>Новая бронь</button>
      <button className={tab==='new'?'secondary':''} aria-pressed={tab!=='new'} onClick={()=>setTab('mine')}>{user.role==='admin'?'Все брони':'Мои брони'}</button></div>
    {tab==='mine'&&<button className="secondary" onClick={()=>setTab('watch')}>Лист ожидания</button>}
    <Status pending={busy} error={error}/><Toast text={notice} dismiss={dismissNotice}/>
    {editing&&<form className="panel toolbar" onSubmit={event=>{
      event.preventDefault();const fields=new FormData(event.currentTarget)
      void run(async()=>{await api('/bookings/'+editing.id,json({title:fields.get('title')},'PATCH'));edit(undefined);refresh(value=>value+1)})
    }}><label>Новое название<input name="title" maxLength={120} required defaultValue={editing.title}/></label><button>Сохранить название</button>
      <button type="button" className="secondary" onClick={()=>edit(undefined)}>Назад</button></form>}
    {opened&&<TicketPanel booking={opened} close={()=>setOpened(undefined)}/>}
    {tab==='watch'?<>
      <h2>Ждать освобождения</h2><p>При поиске задайте точное время. Если аудиторию заняли, нажмите «Ждать освобождения». Когда подойдёт ваша очередь, здесь появится кнопка «Открыть удержание». Подтвердите бронь в течение 5 минут.</p>
      <Status pending={!watchers.data&&!watchers.error} error={watchers.error} empty={watchers.data?.length===0?'Подписок пока нет. Если нужная аудитория занята, подпишитесь на её освобождение. Мы удержим её для вас на 5 минут и пришлём уведомление.':undefined}/>
      <ul className="records">{watchers.data?.map(item=><li key={item.id}>
        <span>Аудитория {rooms.data?.find(r=>r.id===item.room_id)?.code??item.room_id} — {clock(item.start)}–{clock(item.end)} — {item.offer?'Удержание готово':item.state==='waiting'?'Ожидание':item.state==='offered'?'Предложение завершено':item.state==='expired'?'Истекла':'Отменена'}</span>
        {item.offer&&<button onClick={()=>{setChosen(item);setHold(item.offer);setTime(Date.now());setConfirmKey(undefined);setRenewKey(undefined);setTab('new')}}>Открыть удержание</button>}
        {item.state==='waiting'&&<button className="secondary" disabled={busy} onClick={()=>void run(async()=>{await api('/watches/'+item.id,{method:'DELETE'});setNotice('Подписка отменена.');refresh(value=>value+1)})}>Отменить подписку</button>}
      </li>)}</ul>
    </>:tab==='mine'?<>
      {user.role!=='admin'&&<label>Показать брони<select value={filter} onChange={event=>{setFilter(event.target.value);setOffset(0)}}>
        <option value="all">Действующие и завершённые</option><option value="upcoming">Предстоящие</option><option value="cancelled">Включая отменённые</option></select></label>}
      <Status pending={!list.data&&!list.error} error={list.error} empty={list.data?.length===0?'Броней пока нет.':undefined}/>
      <ul className="records">{list.data?.map(booking=><li key={booking.id}><div><strong>{booking.title}</strong><p>{rooms.data?.find(r=>r.id===booking.room_id)?.code??'Аудитория '+booking.room_id} — {dayFmt.format(Date.parse(booking.start))} — {clock(booking.start)}–{clock(booking.end)}</p></div>
        {!booking.cancelled_at&&<button className="secondary" onClick={()=>edit(booking)}>Изменить название</button>}
        {!booking.cancelled_at&&<button className="secondary" onClick={()=>setOpened(booking)}>Талон</button>}{booking.cancelled_at?<span className="tag">Отменена</span>:<button className="secondary" disabled={busy} onClick={()=>confirmation.ask({title:'Отменить бронь?',description:'После отмены этот интервал можно будет забронировать снова.',label:'Подтвердить отмену',apply:()=>void run(async()=>{await api('/bookings/'+booking.id+'/cancel',{method:'POST'});refresh(revision+1);setNotice('Бронь отменена.')})})}>Отменить</button>}</li>)}</ul>
      {(offset>0||list.data?.length===100)&&<div className="actions"><button className="secondary" disabled={!offset} onClick={()=>setOffset(offset-100)}>Назад</button><button className="secondary" disabled={list.data?.length!==100} onClick={()=>setOffset(offset+100)}>Далее</button></div>}
    </>:<>
      <div className={'booking-columns'+(!results&&!searching&&!waiting.length?' booking-start':'')}>
      {!hold&&!chosen&&!submitted&&<form className="panel booking-form" onSubmit={search} onChange={clearResults}>
        <h2>1. Когда и какая аудитория нужна?</h2>
        <label>Корпус<select value={selectedBuilding} onChange={event=>setBuilding(event.target.value)}>
          <option value="">Все корпуса</option>{buildings.map(key=><option key={key} value={key}>Корпус {key}</option>)}
        </select></label>
        <label>Человек<input type="number" min="1" max="10000" required value={count} onChange={event=>setCount(Number(event.target.value))}/></label>
        <fieldset><legend>Тип аудитории</legend><div className="room-kinds">{[{value:"any",label:"Любой тип"},...options].map(item=>
          <label key={item.value}><input type="radio" name="kind" value={item.value} checked={kind===item.value} onChange={()=>setKind(item.value)}/>
            <Icon name={item.value==='computer'?'pc':item.value==='laboratory'?'laboratory':'room'}/>{item.label}</label>)}</div></fieldset>
        <fieldset><legend>Оборудование и доступность</legend><div className="actions equipment-chips">{equipmentOptions.map(item=>
          <button type="button" className="secondary" key={item} aria-pressed={equipment.includes(item)} onClick={()=>{
            clearResults();setEquipment(value=>value.includes(item)?value.filter(k=>k!==item):[...value,item])
          }}><Icon name={item==='accessible'?'access':item==='pc'?'pc':item==='projector'?'projector':item==='board'?'board':'room'}/>
            {equipmentLabels[item]??item}</button>)}</div></fieldset>
        {rooms.data&&count>0&&<p className="room-fit" role="status">{fitCount?
          'По характеристикам подходит: '+fitCount+'. Свободное время проверим при подборе.':
          'В каталоге нет точного совпадения. При подборе покажем ближайшие варианты и отличия.'}</p>}
        <details className="secondary-options">
          <summary>Учесть расписание группы{group&&' — '+group}</summary>
          <label>Группа<input list="booking-groups" value={group} placeholder="Введите код группы"
            aria-describedby="booking-group-help" onChange={event=>{
              const code=event.target.value
              setGroup(code)
              const size=groups.data?.find(item=>item.code===code)?.size
              if(size)setCount(size)
            }}/></label>
          <datalist id="booking-groups">{groups.data?.map(item=><option key={item.code} value={item.code}/>)}</datalist>
          <p className="muted" id="booking-group-help">Укажите группу, чтобы учесть её пары и подставить число участников. Для обычного поиска достаточно указать количество человек.</p>
        </details>

        <label>Дата<input type="date" required value={day} onChange={event=>setDay(event.target.value)}/></label>
        <label>Время по звонкам<select value={pair} onChange={event=>{
          setPair(event.target.value);const selected=bell[Number(event.target.value)-1]
          if(selected)setDuration(selected[1]-selected[0])
        }}><option value="">Любое или своё время</option>{bell.map(([start],index)=><option key={start} value={index+1}>{index+1} пара — {clock(campusInstant(day,start).toISOString())}</option>)}</select></label>
        {!pair&&<label>Своё время<input type="time" value={customTime} onChange={event=>setCustomTime(event.target.value)}/></label>}
        <label>Длительность в минутах<input type="number" min="15" max="480" value={duration} onChange={event=>setDuration(Number(event.target.value))} required/></label>
        <button disabled={busy}>Подобрать</button>
      </form>}
      {!hold&&!chosen&&submitted>0&&<section aria-label="Результаты подбора"><h2 ref={resultsHeading} tabIndex={-1} className="booking-anchor">Подходящие аудитории</h2><p>Шаг 2 из 3. Выберите время и аудиторию.</p><button className="secondary" onClick={()=>{clearResults();setSubmitted(0)}}>Изменить параметры</button>
        <Status pending={searching&&!results} empty={results&&!results.length?(otherRooms.length?'Точных совпадений нет. Ниже — другие аудитории и причины.':'Подходящих свободных аудиторий нет.'):undefined}/>
        <ul className="records tickets">{results?.map(option=><li key={option.room_id+'-'+option.start}>
          <div><strong>{clock(option.start)}–{clock(option.end)} — {option.room??'Аудитория '+option.room_id}</strong>
            <p>{option.building&&'Корпус '+option.building+'. '}Свободна на этот интервал.</p><p>{option.explanation}</p></div>
          <button className="secondary" disabled={busy} onClick={()=>{setChosen(option);setKey(undefined);setError('')}}>Выбрать</button>
        </li>)}</ul>
        {results?.length===0&&otherRooms.length>0&&<div>
          <h3>Другие аудитории</h3>
          <ul className="records">{otherRooms.map(room=>{
            const offer=waiting.find(option=>option.room_id===room.room_id)
            return <li key={room.room_id}>
              <div>
                <strong>{room.room} — корпус {room.building}</strong>
                <p>{room.capacity===null?'Вместимость не указана':'Мест: '+room.capacity}</p>
                <p>{room.available?'Свободна '+clock(room.available.start)+'–'+clock(room.available.end):alternativeStatuses[room.status]}</p>
                <ul className="alternative-reasons">{room.reasons.map(reason=><li key={reason}>{reason}.</li>)}</ul>
              </div>
              {room.selectable&&room.available&&<button className="secondary" disabled={busy} onClick={()=>{
                setChosen({room_id:room.room_id,room:room.room,building:room.building,...room.available!,explanation:room.reasons.join('. ')})
                setKey(undefined);setError('')
              }}>Выбрать эту аудиторию</button>}
              {offer&&<button className="secondary" disabled={busy} onClick={()=>watch(offer)}>Ждать освобождения</button>}
            </li>
          })}</ul>
        </div>}
        {waiting.filter(option=>!otherRooms.some(room=>room.room_id===option.room_id)).map(option=><div className="panel" key={option.room_id}><p>{option.room}, корпус {option.building} — занята.</p>
          <button className="secondary" onClick={()=>watch(option)}>Ждать освобождения</button></div>)}
      </section>}
      </div>
      {chosen&&!hold&&<section className="panel"><button className="secondary" onClick={()=>{setChosen(undefined);setKey(undefined)}}>Назад к выбору</button><h2 ref={chosenHeading} tabIndex={-1} className="booking-anchor">Выбранный интервал</h2><p>{chosen.building&&'Корпус '+chosen.building+' — '}{chosen.room??'Аудитория '+chosen.room_id} — {clock(chosen.start)}–{clock(chosen.end)}</p>{chosen.explanation&&<p>{chosen.explanation}</p>}<button disabled={busy||(Date.parse(chosen.start)<=Date.now()&&Date.parse(chosen.end)<Date.now()+15*60000)} onClick={acquire}>Удержать на 5 минут</button>{Date.parse(chosen.start)<=Date.now()&&Date.parse(chosen.end)<Date.now()+15*60000&&<p>До конца слота осталось меньше 15 минут.</p>}</section>}
      {hold&&<form className="panel" onSubmit={confirm}><h2 ref={confirmHeading} tabIndex={-1} className="booking-anchor">Подтверждение</h2><p>Шаг 3 из 3. {chosen?.room} — {chosen&&clock(chosen.start)}–{chosen&&clock(chosen.end)}</p>
        <p>Осталось <strong role="timer">{Math.floor(remaining/60)}:{String(remaining%60).padStart(2,'0')}</strong></p>
        {!remaining&&<p role="status">Удержание истекло. Выберите интервал снова.</p>}
        <label>Название брони<input name="title" required maxLength={120} onChange={()=>setConfirmKey(undefined)}/></label>
        <details className="secondary-options"><summary>Повторение</summary><label>Повторять бронь<select name="repeats" onChange={()=>setConfirmKey(undefined)}>
          <option value={1}>Без повторения</option>{Array.from({length:11},(_,i)=><option key={i} value={i+2}>Еженедельно, всего {i+2}</option>)}
        </select></label></details>
        <div className="actions"><button disabled={busy||!remaining}>Подтвердить</button><button type="button" className="secondary" disabled={busy} onClick={release}>Отпустить</button>
          <button type="button" className="secondary" disabled={busy||!remaining} onClick={()=>{
            const requestKey=renewKey??crypto.randomUUID()
            setRenewKey(requestKey)
            void run(async()=>{setHold(await api<Hold>('/booking-holds/'+hold.id+'/renew',json({},'POST',requestKey)));setTime(Date.now());setNotice('Удержание продлено.')})
          }}>Продлить</button></div>
      </form>}
    </>}
  </>
}
