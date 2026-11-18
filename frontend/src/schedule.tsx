import { FormEvent, useState } from 'react'
import { api, json, Lesson, Session } from './api'
import { allRooms, clock, dayFmt, Heading, message, options, params, Status, today, useLoad } from './common'

type Window = {entity:string;day:string;minutes:number;start:string;end:string;free_slots:number}
type Heat = {day:string;building:string;slot:number;occupied:number;total:number}
type Forecast = {demand:{status:string;metrics?:{mae:number;historical_baseline_mae:number};rooms?:{building:string;count:number}[]};load:{status:string;metrics?:{mae:number;historical_baseline_mae:number};cells?:{slot:number;building:string;ratio:number}[]}}
type Plan = {id?:number;applied?:number[]|null;status:string;assignments:{lesson_id:number;room_id:number;slot:number;building:string;date:string}[];original?:{lesson_id:number;room_id:number;slot:number;date:string}[];before?:Record<string,number>;after?:Record<string,number>}

export function Analytics({user}:{user:Session}) {
  const [query,setQuery]=useState('')
  const [forecast,setForecast]=useState('')
  const [plan,setPlan]=useState<Plan>()
  const [selectedMoves,setMoves]=useState<number[]>([])
  const [saved,setSaved]=useState(0)
  const proposals=useLoad(()=>user.role==='admin'?api<Plan[]>('/admin/proposals'):Promise.resolve([]),user.role+':'+saved)
  const [planNotice,setPlanNotice]=useState('')
  const [error,setError]=useState('')
  const [working,setWorking]=useState(false)
  const windows=useLoad(()=>query?api<{total:number;windows:Window[]}>('/analytics/windows?'+query):Promise.resolve(undefined),query)
  const heat=useLoad(()=>query?api<{cells:Heat[]}>('/analytics/occupancy?'+query):Promise.resolve(undefined),query)
  const predicted=useLoad(()=>forecast?api<Forecast>('/analytics/forecasts?'+forecast):Promise.resolve(undefined),forecast)
  const [day,setDay]=useState(today)
  const [endDay,setEndDay]=useState(today)
  const catalog=useLoad(allRooms,'analysis-buildings')
  const buildings=[...new Set(catalog.data?.map(room=>room.building))].sort()
  const [selectedBuilding,setBuilding]=useState('')
  const building=selectedBuilding||buildings[0]||''
  const [chosen,setChosen]=useState<Lesson[]>([])
  const scoped=useLoad(()=>user.role==='admin'?api<{items:Lesson[];next_offset:number|null}>('/schedule?'+params({scope:'building',entity_id:building,from:day,to:endDay})):Promise.resolve(undefined),user.role+day+endDay+building)
  const groups=new Map<string,Heat[]>()
  for(const cell of heat.data?.cells??[]){
    const key=cell.day+' — корпус '+cell.building
    groups.set(key,[...(groups.get(key)??[]),cell])
  }
  function compare(e:FormEvent<HTMLFormElement>){
    e.preventDefault()
    const values=new FormData(e.currentTarget)
    const dates={start:String(values.get('start')),end:String(values.get('end'))}
    setQuery(params(dates))
    setForecast(values.get('target')?params({...dates,target:String(values.get('target'))}):'')
  }
  async function optimize(e:FormEvent<HTMLFormElement>){
    e.preventDefault();setPlan(undefined);setMoves([]);setPlanNotice('');setError('');setWorking(true)
    const values=new FormData(e.currentTarget)
    try {setPlan(await api<Plan>('/admin/optimization-runs',json({day,end_day:endDay,requirements:Object.fromEntries(chosen.map(r=>[r.id,{
      kind:values.get('kind-'+r.id)||null, people:values.get('count-'+r.id)?Number(values.get('count-'+r.id)):null, equipment:String(values.get('equipment-'+r.id)||'').split(',').map(v=>v.trim()).filter(Boolean),
      accessible:values.has('access-'+r.id),
    }]))})));setSaved(saved+1)}catch(e){setError(message(e))}finally{setWorking(false)}
  }
  async function applyMoves(){
    if(!plan?.id||!selectedMoves.length)return
    setWorking(true);setError('');setPlanNotice('')
    try{
      const result=await api<{applied:number[]}>('/admin/proposals/'+plan.id+'/apply',
        json({lesson_ids:selectedMoves},'POST',crypto.randomUUID()))
      setPlan({...plan,applied:result.applied});setSaved(saved+1);setPlanNotice('Переносы опубликованы.')
    }catch(e){setError(message(e))}finally{setWorking(false)}
  }
  return <>
    <Heading title="Аналитика" description="Загрузка корпусов, окна между парами и варианты переноса."/>
    <form onSubmit={compare} className="toolbar"><label>С<input name="start" type="date" required defaultValue={today()}/></label><label>По<input name="end" type="date" required defaultValue={today()}/></label><label>Дата прогноза<input type="date" name="target"/></label><button>Рассчитать</button></form>
    <h2>Загрузка аудиторий</h2>
    <Status pending={!!query&&!heat.data&&!heat.error} error={heat.error} empty={heat.data?.cells.length===0?'За этот период нет полного покрытия корпусов.':undefined}/>
    {groups.size>0&&<div className="heat-scroll"><table><caption>Занятые аудитории / всего. Чем темнее ячейка, тем выше загрузка.</caption><thead><tr><th>Дата и корпус</th>{Array.from({length:9},(_,i)=><th key={i}>{i+1}-я</th>)}</tr></thead><tbody>{[...groups].map(([key,cells])=><tr key={key}><th>{key}</th>{cells.map(c=><td className={'heat h'+Math.round(4*c.occupied/c.total)} key={c.slot}>{c.occupied}/{c.total}</td>)}</tr>)}</tbody></table></div>}
    <h2>Самые длинные окна</h2>
    <Status pending={!!query&&!windows.data&&!windows.error} error={windows.error} empty={windows.data?.total===0?'В опубликованных данных окна не найдены.':undefined}/>
    <ul className="records">{windows.data?.windows.slice(0,20).map((w,i)=><li key={i}><span>{w.entity.startsWith('g:')?w.entity.slice(2):w.entity} — {w.day} — {clock(w.start)}–{clock(w.end)}</span><strong>{w.minutes} мин</strong></li>)}</ul>
    {forecast&&<section className="panel"><h2>Прогноз</h2><Status pending={!predicted.data&&!predicted.error} error={predicted.error}/>
      {predicted.data&&<><p>{predicted.data.load.metrics?'MAE модели '+predicted.data.load.metrics.mae.toFixed(3)+' — историческое среднее '+predicted.data.load.metrics.historical_baseline_mae.toFixed(3):'Для обучения нужно не менее 14 дней полного покрытия.'}</p>
      <ul>{predicted.data.load.cells?.map(c=><li key={c.building+':'+c.slot}>Корпус {c.building} — пара {c.slot} — {Math.round(c.ratio*100)}%</li>)}</ul>
      <p>Источник прогноза загрузки — опубликованные выгрузки корпусов.</p><h3>Спрос на брони</h3><p>Источник — история броней этого сервера.</p>
      {predicted.data.demand.metrics?<><p>MAE модели {predicted.data.demand.metrics.mae.toFixed(2)} — базовый прогноз {predicted.data.demand.metrics.historical_baseline_mae.toFixed(2)}</p>
      <ul>{predicted.data.demand.rooms?.map(r=><li key={r.building}>Корпус {r.building} — {r.count.toFixed(1)} брони</li>)}</ul></>:<p>Недостаточно данных: нужны история минимум за 28 дней и 30 броней.</p>}</>}
    </section>}
    {user.role==='admin'&&<section className="panel"><h2>Подобрать перенос</h2>
      {!!proposals.data?.length&&<label>Очередь предложений<select value={plan?.id??''} onChange={e=>{
        setPlan(proposals.data?.find(p=>p.id===Number(e.target.value)));setMoves([]);setPlanNotice('')
      }}><option value="">Выберите предложение</option>{proposals.data.map(p=><option key={p.id} value={p.id}>№{p.id} — {p.applied?'Применено':'К рассмотрению'}</option>)}</select></label>}
      {planNotice&&<p role="status">{planNotice}</p>}
      <div className="toolbar"><label>День<input type="date" value={day} onChange={e=>{if(e.target.value){setDay(e.target.value);if(endDay<e.target.value)setEndDay(e.target.value);setChosen([]);setPlan(undefined)}}}/></label><label>По<input type="date" min={day} value={endDay} onChange={e=>{if(e.target.value){setEndDay(e.target.value);setChosen([]);setPlan(undefined)}}}/></label><label>Корпус исходной пары<select value={building} onChange={e=>{setBuilding(e.target.value);setChosen([]);setPlan(undefined)}}>{buildings.map(key=><option key={key}>{key}</option>)}</select></label></div>
      <label>Добавить занятие<select value="" disabled={working} onChange={e=>{const row=scoped.data?.items.find(r=>r.id===Number(e.target.value));if(row)setChosen([...chosen,row])}}><option value="">Выберите занятие</option>{scoped.data?.items.filter(r=>!chosen.some(c=>c.id===r.id)).map(r=><option key={r.id} value={r.id}>{clock(r.start)} — {r.room} — {r.subject}</option>)}</select></label>
      <Status pending={!scoped.data&&!scoped.error} error={scoped.error||error} empty={scoped.data?.items.length===0?'Нет занятий для выбора.':undefined}/>
      <form onSubmit={optimize}>{chosen.map(r=><fieldset key={r.id}><legend>{r.subject} — {clock(r.start)}</legend><div className="toolbar">
        <label>Тип<select name={'kind-'+r.id}><option value="">Как у исходной аудитории</option>{options.map(o=><option key={o.value} value={o.value}>{o.label}</option>)}</select></label>
        <label>Человек<input type="number" name={'count-'+r.id} placeholder="Из размера группы" min="1"/></label><label>Оборудование<input name={'equipment-'+r.id}/></label>
        <label className="check"><input type="checkbox" name={'access-'+r.id}/>Доступная среда</label>
        <button type="button" className="secondary" onClick={()=>setChosen(chosen.filter(c=>c.id!==r.id))}>Убрать</button></div></fieldset>)}
        {chosen.length>0&&<button disabled={working}>Найти переносы</button>}</form>
      <Status pending={working}/>
      {plan&&<div role="status"><p>{({optimal:'Найден оптимальный вариант',feasible:'Найден допустимый вариант',infeasible:'Подходящего варианта нет',insufficient_coverage:'Нет полного покрытия корпусов',unknown:'Решение не найдено за отведённое время'} as Record<string,string>)[plan.status]??plan.status}.</p>
        <ul>{plan.assignments.map(a=><li key={a.lesson_id}>
          {plan.id&&!plan.applied&&plan.original?.some(o=>o.lesson_id===a.lesson_id&&(o.date!==a.date||o.room_id!==a.room_id||o.slot!==a.slot))&&
            <label className="check"><input type="checkbox" checked={selectedMoves.includes(a.lesson_id)} onChange={e=>setMoves(e.target.checked?[...selectedMoves,a.lesson_id]:selectedMoves.filter(id=>id!==a.lesson_id))}/>Применить занятие №{a.lesson_id}</label>}{chosen.find(r=>r.id===a.lesson_id)?.subject??a.lesson_id} — было {plan.original?.find(o=>o.lesson_id===a.lesson_id)?.date}, пара {plan.original?.find(o=>o.lesson_id===a.lesson_id)?.slot}, аудитория №{plan.original?.find(o=>o.lesson_id===a.lesson_id)?.room_id} → {a.date}, пара {a.slot}, корпус {a.building}, аудитория №{a.room_id}</li>)}</ul>
        {plan.before&&plan.after&&<p>Пустых пар у групп: {plan.before.group_empty_periods} → {plan.after.group_empty_periods}. У преподавателей: {plan.before.teacher_empty_periods} → {plan.after.teacher_empty_periods}. Переходы: {plan.before.building_switches} → {plan.after.building_switches}.</p>}
        {plan.id&&!plan.applied&&selectedMoves.length>0&&<button disabled={working} onClick={()=>void applyMoves()}>Опубликовать выбранные переносы</button>}</div>}
    </section>}
  </>
}
