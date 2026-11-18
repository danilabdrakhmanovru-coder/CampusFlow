import { FormEvent, useState } from 'react'
import { useConfirmation } from './Sheet'
import { adminTabs, Link } from './routing'
import { api, Batch, json, Room, Role, Session, Teacher } from './api'
import { actions as actionNames, ModelPage, Moves, OverviewPage, SettingsPage } from './dispatch'
import { Analytics } from './schedule'
import { Group } from './profile'
import { allRooms, campus, clock, Heading, message, params, options, roles, Status, today, useLoad } from './common'

export function Admin({user,tab}:{user:Session;tab:string}) {
  const primaryTabs=['imports','rooms','moves']
  const tabs=(primary:boolean)=>adminTabs.filter(([key])=>primaryTabs.includes(key)===primary).map(([key,label])=>
    <Link key={key} href={'/admin/'+key} current={key===tab}>{label}</Link>)
  return <>
    <Heading title="Управление кампусом"/>
    {tab==='overview'&&<section className="panel"><h2>Регулирование расписания</h2><p>Выберите группу в рейтинге, посмотрите её окна и сравните варианты переноса существующей пары.</p><Link className="action-link primary-action" href="/windows">Открыть рейтинг групп</Link></section>}
    <div className="dispatch-layout">
      <nav className="dispatch-nav" aria-label="Подразделы диспетчерской">
        <Link href="/admin" current={tab==='overview'}>Обзор</Link>
        {tabs(true)}
        <Link href="/windows">Окна групп</Link>
        <details className="secondary-options" open={tab!=='overview'&&!primaryTabs.includes(tab)||undefined}>
          <summary>Управление</summary>
          <div className="dispatch-more">{tabs(false)}</div>
        </details>
      </nav>
      <div className="dispatch-content">{tab==='overview'?<OverviewPage/>:tab==='imports'?<Imports/>:tab==='rooms'?<Rooms/>:
        tab==='groups'?<GroupSizes/>:tab==='walk'?<Walking/>:tab==='audit'?<AuditLog/>:tab==='moves'?<Moves/>:
        tab==='model'?<ModelPage/>:tab==='settings'?<SettingsPage/>:tab==='analytics'?<Analytics user={user}/>:<Users ownId={user.id}/>}</div>
    </div>
  </>
}

type Conflict = {row_key:string;room_id:number;booking_id:number|null;start:string;end:string;subject:string;kind:string}
type Mapping = { state:'mapping_required';columns:string[];missing:string[] }
const fields = Object.entries({start:'Начало',end:'Конец',building:'Корпус',room:'Аудитория',subject:'Дисциплина',lesson_type:'Вид занятия',groups:'Группы',teachers:'Преподаватели'})
function Imports(){
  const confirmation=useConfirmation()
  const [batch,setBatch]=useState<Batch>()
  const [mapping,setMapping]=useState<Mapping>()
  const [revision,refresh]=useState(0)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [note,setNote]=useState('')
  const roomCatalog=useLoad(allRooms,'import-buildings')
  const list=useLoad(()=>api<Batch[]>('/admin/imports'),String(revision))
  async function run(action:()=>Promise<void>){
    setBusy(true);setError('');setNote('')
    try{await action()}catch(e){setError(message(e))}finally{setBusy(false)}
  }
  const conflicts = useLoad(()=>batch?.state==='staged'?
    api<{items:Conflict[]}>('/admin/imports/'+batch.id+'/conflicts'):Promise.resolve({items:[]}),
    [batch?.id,batch?.state,revision].join(':'))
  const [decision,setDecision]=useState<{item:Conflict;action:'cancel_booking'|'skip_lesson'}>()
  function resolve(event:FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if(!batch||!decision)return
    const reason=String(new FormData(event.currentTarget).get('reason')).trim()
    void run(async()=>{
      await api('/admin/imports/'+batch.id+'/conflicts',json({
        action:decision.action, reason, row_key:decision.item.row_key, booking_id:decision.item.booking_id,
      },'POST',crypto.randomUUID()))
      setBatch(await api('/admin/imports/'+batch.id));setDecision(undefined);refresh(revision+1)
      setNote('Конфликт обработан.')
    })
  }
  function stage(e:FormEvent<HTMLFormElement>){
    e.preventDefault()
    const data=new FormData(e.currentTarget)
    const columns:Record<string,string>={}
    for(const [key] of fields){const value=data.get('column-'+key);if(value)columns[key]=String(value);data.delete('column-'+key)}
    data.set('mapping_json',JSON.stringify(columns))
    void run(async()=>{
      const result=await api<Batch|Mapping>('/admin/imports',{method:'POST',body:data})
      if('columns' in result){setMapping(result);setBatch(undefined)}
      else{setBatch(result);setMapping(undefined);refresh(revision+1)}
    })
  }
  return <section>
    {confirmation.dialog}
    <h2>Загрузить расписание</h2>
    <form className="panel" onSubmit={stage}>
      <div className="toolbar"><label>Источник<select name="scope"><option value="iimrt">Группы ИИМРТ</option>{[...new Set(roomCatalog.data?.map(room=>room.building))].sort().map(key=><option key={key} value={key}>Корпус {key}</option>)}</select></label>
        <label>С<input name="date_from" type="date" required defaultValue={today()}/></label><label>По<input name="date_to" type="date" required defaultValue={today()}/></label></div>
      <label>Файл CSV, XLSX, ICS или JSON ИИМРТ<input type="file" name="file" accept=".csv,.xlsx,.ics,.json" required onChange={()=>{setMapping(undefined);setBatch(undefined)}}/></label>
      <label className="check"><input name="complete" type="checkbox" value="true"/>В файле полное расписание корпуса за этот период</label>
      {mapping&&<fieldset><legend>Сопоставление колонок</legend><div className="toolbar">{fields.map(([key,label])=><label key={key}>{label}<select name={'column-'+key} required={mapping.missing.includes(key)}><option value="">Автоматически</option>{mapping.columns.map(c=><option key={c}>{c}</option>)}</select></label>)}</div></fieldset>}
      <button disabled={busy}>Предпросмотр</button>
    </form>
    <Status pending={busy} error={error}/>{note&&<p role="status" className="feedback">{note}</p>}
    {batch&&<section className="panel"><h2>Импорт #{batch.id}</h2><p>Строк: {batch.report.input_rows} — Занятий: {batch.report.lessons} — Ошибок: {batch.report.errors} — Пересечений строк: {batch.report.overlapping_room_rows} — Без известной аудитории: {batch.report.unknown_room_lessons} — Конфликтов с бронями или блокировками: {batch.report.booking_conflicts.length}</p>
      <ul>{batch.report.issues.map(issue=><li key={issue.row}>Строка {issue.row}. {issue.message}</li>)}</ul>
      {batch.report.booking_conflicts.length>0&&<ul>{batch.report.booking_conflicts.map(c=><li key={c.room_id+c.start}>Аудитория #{c.room_id} — {new Date(c.start).toLocaleDateString('ru-RU',{timeZone:campus})} — {clock(c.start)}–{clock(c.end)}</li>)}</ul>}
      <ul className="records">{batch.preview?.map((row,i)=><li key={i}>{row.start.slice(0,10)} — {clock(row.start)}–{clock(row.end)} — {row.subject} — {row.building??'—'}/{row.room??'—'}</li>)}</ul>
      {batch.state==='staged'&&<section>
        <h3>Конфликты</h3>
        <Status pending={!conflicts.data&&!conflicts.error} error={conflicts.error}
          empty={conflicts.data?.items.length===0?'Активных конфликтов нет.':undefined}/>
        <ul className="records">{conflicts.data?.items.map(c=><li key={c.row_key+':'+c.booking_id+':'+c.kind}>
          <span>{c.subject} — аудитория №{c.room_id} — {clock(c.start)}–{clock(c.end)}</span>
          <div className="actions">{c.booking_id&&<button className="secondary" onClick={()=>setDecision({item:c,action:'cancel_booking'})}>Отменить бронь с уведомлением</button>}
            <button className="secondary" onClick={()=>setDecision({item:c,action:'skip_lesson'})}>Пропустить пару</button></div>
        </li>)}</ul>
        {decision&&<form className="panel" onSubmit={resolve}>
          <p>{decision.action==='cancel_booking'?'Отменить бронь':'Исключить пару из импорта'} — {decision.item.subject}</p>
          {decision.action==='skip_lesson'&&<p>Выгрузка станет неполной. Новые брони на основе этой версии будут недоступны.</p>}
          <label>Причина<input name="reason" minLength={3} maxLength={300} required/></label>
          <div className="actions"><button disabled={busy}>Подтвердить</button><button type="button" className="secondary" onClick={()=>setDecision(undefined)}>Назад</button></div>
        </form>}
      </section>}
      <div className="actions">{batch.state==='staged'&&<button disabled={busy||!!batch.report.errors||!!conflicts.data?.items.length} onClick={()=>confirmation.ask({title:'Опубликовать расписание?',description:'Текущее расписание этой области будет заменено.',label:'Подтвердить публикацию',apply:()=>void run(async()=>{setBatch(await api('/admin/imports/'+batch.id+'/publish',{method:'POST'}));refresh(revision+1);setNote('Расписание опубликовано.')})})}>Опубликовать</button>}
        {batch.state==='active'&&<button className="secondary" disabled={busy} onClick={()=>confirmation.ask({title:'Откатить публикацию?',description:'Расписание вернётся к предыдущей публикации, если она есть.',label:'Подтвердить откат',apply:()=>void run(async()=>{await api('/admin/imports/'+batch.id+'/rollback',{method:'POST'});setBatch(undefined);refresh(revision+1);setNote('Публикация отменена.')})})}>Откатить</button>}</div>
    </section>}
    <h2>История импорта</h2>
    <Status error={list.error} pending={!list.data&&!list.error} empty={list.data?.length===0?'Импортов пока нет.':undefined}/>
    <ul className="records">{list.data?.map(row=><li key={row.id}><span>#{row.id} — {row.scope==='iimrt'?'ИИМРТ':'Корпус '+row.scope} — {({active:'Опубликован',staged:'Черновик',archived:'Архив'} as Record<string,string>)[row.state]??row.state}</span><button className="secondary" disabled={busy} onClick={()=>void run(async()=>setBatch(await api('/admin/imports/'+row.id)))}>Открыть</button></li>)}</ul>
  </section>
}

function Rooms(){
  const [filter,setFilter]=useState('')
  const [door,setDoor]=useState('')
  const [page,setPage]=useState(0)
  const [floorPlan,setFloorPlan]=useState(false)
  const confirmation=useConfirmation()
  const equipmentLabels:Record<string,string>={pc:'Компьютеры',projector:'Проектор',board:'Доска',screen:'Экран',microphone:'Микрофон'}
  const [revision,refresh]=useState(0)
  const [selected,setSelected]=useState<Room>()
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const rooms=useLoad(allRooms,String(revision))
  async function save(e:FormEvent<HTMLFormElement>){
    e.preventDefault();setBusy(true);setError('')
    const form=e.currentTarget, data=new FormData(form)
    try{
      const equipment:Record<string,number>={}
      for(const [key,value] of data)if(key.startsWith('eq-')&&Number(value)>0)equipment[key.slice(3)]=Number(value)
      const accessible=data.get('accessible')
      await api('/admin/rooms'+(selected?'/'+selected.id:''),json({
        building:data.get('building'),code:data.get('code'),kind:data.get('kind'),capacity:Number(data.get('capacity')),
        floor:data.get('floor')?Number(data.get('floor')):null,
        plan_x:data.get('plan_x')?Number(data.get('plan_x')):null,plan_y:data.get('plan_y')?Number(data.get('plan_y')):null,accessible:accessible==='unknown'?null:accessible==='yes',equipment,
      },selected?'PUT':'POST'))
      form.reset();setSelected(undefined);refresh(revision+1)
    }catch(e){setError(message(e))}finally{setBusy(false)}
  }
  return <section><h2>{selected?'Изменить аудиторию':'Новая аудитория'}</h2><form className="panel toolbar" key={selected?.id??'new'} onSubmit={save}>
    <label>Корпус<input name="building" list="admin-buildings" readOnly={!!selected} defaultValue={selected?.building} required/></label>
    <datalist id="admin-buildings">{[...new Set(rooms.data?.map(room=>room.building))].map(key=><option key={key} value={key}/>)}</datalist>
    <label>Номер<input name="code" defaultValue={selected?.code} required maxLength={100}/></label>
    <label>Этаж<input name="floor" type="number" min="-5" max="50" defaultValue={selected?.floor??undefined}/></label>
    <label>Координата X, %<input name="plan_x" type="number" min="0" max="100" step="any" defaultValue={selected?.plan_x??undefined}/></label>
    <label>Координата Y, %<input name="plan_y" type="number" min="0" max="100" step="any" defaultValue={selected?.plan_y??undefined}/></label>
    <label>Тип<select name="kind" defaultValue={selected?.kind??undefined}>{options.map(o=><option value={o.value} key={o.value}>{o.label}</option>)}</select></label>
    <label>Мест<input name="capacity" type="number" min="1" required defaultValue={selected?.capacity??undefined}/></label>
    <label>Доступность<select name="accessible" defaultValue={selected?.accessible==null?'unknown':selected.accessible?'yes':'no'}><option value="unknown">Неизвестно</option><option value="yes">Доступна</option><option value="no">Недоступна</option></select></label>
    <fieldset><legend>Оборудование</legend><div className="actions" aria-label="Оборудование аудитории">{[...new Set([...Object.keys(equipmentLabels),...Object.keys(selected?.equipment??{})])].map(key=><label className="tag" key={key}>{equipmentLabels[key]??key}
      <input type="number" min="0" max="10000" name={'eq-'+key} defaultValue={selected?.equipment[key]??0}/></label>)}</div></fieldset>
    <button disabled={busy}>Сохранить</button>{selected&&<button type="button" className="secondary" onClick={()=>setSelected(undefined)}>Новая запись</button>}
  </form>
  <Status pending={busy||!rooms.data&&!rooms.error} error={error||rooms.error} empty={rooms.data?.length===0?'Каталог пуст.':undefined}/>
  {selected&&<section className="panel"><h3>Код у двери</h3><p>Распечатайте код и разместите его в аудитории для отметки о явке.</p>
    <button className="secondary" onClick={()=>confirmation.ask({title:'Выдать новый код аудитории?',description:'Предыдущий код перестанет действовать.',label:'Выдать код',apply:()=>void api<{code:string}>('/admin/rooms/'+selected.id+'/check-in-code',{method:'POST'}).then(result=>setDoor(result.code),error=>setError(message(error)))})}>Выдать код аудитории</button>
    {door&&<p role="status"><strong>{door}</strong> — сохраните код перед закрытием.</p>}
    <button className="secondary" onClick={()=>setFloorPlan(!floorPlan)} aria-expanded={floorPlan}>Координаты на схеме</button>
    {floorPlan&&<div className="floor-plan measured admin-plan">
      {rooms.data?.filter(room=>room.building===selected.building&&room.floor===selected.floor&&room.plan_x!==null&&room.plan_y!==null).map(room=>
        <button className="plan-room secondary" key={room.id} style={{left:room.plan_x+'%',top:room.plan_y+'%'}} onClick={()=>setSelected(room)}>{room.code}</button>)}
    </div>}
  </section>}
  <label>Поиск по номеру или корпусу<input type="search" value={filter} onChange={event=>{setFilter(event.target.value);setPage(0)}}/></label>
  <ul className="records">{rooms.data?.filter(room=>(room.building+' '+room.code+' '+(room.kind??'')).toLowerCase().includes(filter.toLowerCase())).slice(page*30,page*30+30).map(room=>
    <li key={room.id}><span>Корпус {room.building} — {room.code} — {room.capacity??'—'} мест</span><button className="secondary" onClick={()=>{setSelected(room);setDoor('')}}>Изменить</button></li>)}</ul>
  <div className="actions"><button className="secondary" disabled={!page} onClick={()=>setPage(page-1)}>Назад</button>
    <button className="secondary" disabled={(rooms.data?.filter(room=>(room.building+' '+room.code+' '+(room.kind??'')).toLowerCase().includes(filter.toLowerCase())).length??0)<=(page+1)*30} onClick={()=>setPage(page+1)}>Далее</button></div>
  {confirmation.dialog}</section>
}

type User = {id:number;login:string;display_name?:string|null;role:Role;active:boolean;teacher_link_requested_at:string|null;deletion_requested_at:string|null;teaching_days_off:number[]}
function Users({ownId}:{ownId:number}){
  const confirmation=useConfirmation()
  const [revision,refresh]=useState(0)
  const [offset,setOffset]=useState(0)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const [search,setSearch]=useState('')
  const [reset,setReset]=useState('')
  const list=useLoad(()=>api<User[]>('/admin/users?'+params({offset:String(offset),q:search})),offset+':'+revision+':'+search)
  const directory=useLoad(()=>api<{teachers:Teacher[]}>('/schedule/entities'),'teacher-directory')
  async function userAction(action:()=>Promise<unknown>, label:string){
    setBusy(true);setError('');setNotice('')
    try{await action();setNotice(label);refresh(revision+1)}
    catch(e){setError(message(e))}finally{setBusy(false)}
  }
  async function submit(e:FormEvent<HTMLFormElement>,user?:User){
    e.preventDefault();setBusy(true);setError('');setNotice('')
    const form=e.currentTarget,data=new FormData(form)
    try{
      if(user)await api('/admin/users/'+user.id,json({role:data.get('role'),active:data.has('active')},'PATCH'))
      else {await api('/admin/users',json(Object.fromEntries(data)));form.reset()}
      setNotice('Изменения сохранены.');refresh(revision+1)
    }catch(e){setError(message(e))}finally{setBusy(false)}
  }
  const roleField=(role:Role)=><label>Роль<select name="role" defaultValue={role}>{Object.entries(roles).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>
  return <section>{confirmation.dialog}<h2>Создать пользователя</h2><form className="panel toolbar" onSubmit={e=>void submit(e)}>
    <label>Логин<input name="login" pattern="[a-z0-9._\-]+" autoComplete="off" required maxLength={100}/></label>
    <label>Начальный пароль<input name="password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required/></label>
    {roleField('student')}<button disabled={busy}>Создать</button></form>
    <Status pending={busy||!list.data&&!list.error} error={error||list.error||directory.error}/>{notice&&<p role="status">{notice}</p>}
    <label>Поиск пользователей<input type="search" value={search} onChange={event=>{setSearch(event.target.value);setOffset(0)}}/></label>
    {reset&&<div className="panel"><label>Одноразовая ссылка на 30 минут<input readOnly value={reset} onFocus={event=>event.currentTarget.select()}/></label>
      <button className="secondary" onClick={()=>setReset('')}>Скрыть ссылку</button></div>}
    <ul className="records">{list.data?.map(user=><li key={user.id}>
      <strong>{user.display_name??user.login}</strong>{user.display_name&&<span>Логин: {user.login}</span>}{user.teacher_link_requested_at&&<span className="tag">Запрошена привязка</span>}
      {user.role==='teacher'&&<p>Дни без занятий: {user.teaching_days_off?.length?user.teaching_days_off.map(day=>['Пн','Вт','Ср','Чт','Пт','Сб','Вс'][day]).join(', '):'не указаны'}</p>}
      {user.deletion_requested_at&&<span className="tag">Запрошено удаление данных</span>}
      {user.active&&<button className="secondary" onClick={()=>confirmation.ask({title:'Создать ссылку для сброса?',description:'Передайте одноразовую ссылку владельцу аккаунта.',label:'Создать ссылку',apply:()=>void userAction(async()=>{
        const result=await api<{path:string}>('/admin/users/'+user.id+'/password-reset',{method:'POST'});setReset(location.origin+result.path)
      },'Ссылка подготовлена.')})}>Сбросить пароль</button>}{user.id===ownId?<span>Ваш аккаунт — {roles[user.role]}</span>:<form className="toolbar compact" onSubmit={e=>void submit(e,user)}>
        {roleField(user.role)}<label className="check"><input name="active" type="checkbox" defaultChecked={user.active}/>Активен</label><button className="secondary" disabled={busy}>Сохранить</button>
      </form>}
      {user.active&&user.role==='teacher'&&<form className="toolbar" onSubmit={e=>{
        e.preventDefault()
        const [building,number]=JSON.parse(String(new FormData(e.currentTarget).get('teacher')))
        void userAction(()=>api('/admin/users/'+user.id+'/teacher-link',json({building,number},'PUT')),'Преподаватель привязан.')
      }}>
        <label>Преподаватель в расписании<select name="teacher" required><option value="">Выберите преподавателя</option>{directory.data?.teachers.map(t=><option key={t.building+':'+t.number} value={JSON.stringify([t.building,t.number])}>{t.building==='unknown'?'Без корпуса':t.building} — {t.label}</option>)}</select></label>
        <button disabled={busy} className="secondary">Привязать</button>
        <button disabled={busy} type="button" className="secondary" onClick={()=>void userAction(()=>api('/admin/users/'+user.id+'/teacher-link',{method:'DELETE'}),'Привязка снята.')}>Снять привязку</button>
      </form>}
      {user.id!==ownId&&<button disabled={busy} className="secondary" onClick={()=>confirmation.ask({title:'Удалить данные аккаунта?',description:'Данные аккаунта «'+user.login+'» будут удалены, его брони освободятся.',label:'Подтвердить удаление',apply:()=>void userAction(()=>api('/admin/users/'+user.id+'/data',{method:'DELETE'}),'Данные аккаунта удалены.')})}>Удалить данные</button>}</li>)}</ul>
    <div className="actions"><button className="secondary" disabled={!offset} onClick={()=>setOffset(offset-100)}>Назад</button><button className="secondary" disabled={list.data?.length!==100} onClick={()=>setOffset(offset+100)}>Далее</button></div>
  </section>
}


function GroupSizes(){
  const [version,reload]=useState(0)
  const list=useLoad(()=>api<Group[]>('/catalog/groups'),String(version))
  const [page,setPage]=useState(0)
  const [search,setSearch]=useState('')
  const shown=(list.data??[]).filter(group=>group.code.toLowerCase().includes(search.toLowerCase()))
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  async function save(e:FormEvent<HTMLFormElement>){
    e.preventDefault();setError('');setBusy(true)
    try{
      const data=new FormData(e.currentTarget)
      const file=data.get('csv') as File|null
      const input=file?.size?await file.text():String(data.get('sizes')??'')
      const sizes:Record<string,number>={}
      for(const line of input.replace(/^\uFEFF/,'').split(/\r?\n/).filter(s=>s.trim()&&!/^(group|группа|group_code)[;,]/i.test(s.trim()))){
        const match=line.match(/^(?:"([^"]+)"|([^;,]+))[;,]\s*"?(\d+)"?\s*$/)
        if(!match)throw Error('Формат каждой строки: ГРУППА; 25')
        sizes[(match[1]||match[2]).trim()]=Number(match[3])
      }
      await api('/admin/group-sizes',json({sizes},'PUT'));reload(version+1)
    }catch(e){setError(message(e))}finally{setBusy(false)}
  }
  return <section><h2>Размеры групп</h2><form className="panel" onSubmit={save}>
    <label>Вставьте строки из таблицы в формате «ГРУППА; 25»
      <textarea name="sizes" rows={4}/></label><label>Файл CSV<input name="csv" type="file" accept=".csv,text/csv"/></label><button disabled={busy}>Импортировать размеры</button></form>
    <Status pending={busy||(!list.data&&!list.error)} error={error||list.error}/>
    <p>Размер нужен для подбора вместимости и предложений переноса. Заполнено {list.data?.filter(group=>group.size!==null).length??0} из {list.data?.length??0}.</p>
    <label>Поиск группы<input type="search" value={search} onChange={event=>{setSearch(event.target.value);setPage(0)}}/></label>
    <div className="table-scroll"><table><thead><tr><th>Группа</th><th>Участники</th><th>Действие</th></tr></thead><tbody>
      {shown.slice(page*25,page*25+25).map(group=><tr key={group.code}><th scope="row">{group.code}</th><td colSpan={2}>
        <form className="actions" key={version} onSubmit={event=>{
          event.preventDefault();const size=Number(new FormData(event.currentTarget).get('size'));setError('')
          void api('/admin/group-sizes',json({sizes:{[group.code]:size}},'PUT')).then(()=>reload(value=>value+1),error=>setError(message(error)))
        }}><input aria-label={'Число участников '+group.code} name="size" type="number" min="1" max="10000" required defaultValue={group.size??''}/>
          <button className="secondary">Сохранить</button></form></td></tr>)}</tbody></table></div>
    <div className="actions"><button className="secondary" disabled={!page} onClick={()=>setPage(page-1)}>Назад</button>
      <button className="secondary" disabled={(page+1)*25>=shown.length} onClick={()=>setPage(page+1)}>Далее</button></div></section>
}

function Walking(){
  const list=useLoad(allRooms,'walking-rooms')
  const [revision,reload]=useState(0)
  const matrix=useLoad(()=>api<{from:string;to:string;minutes:number}[]>('/admin/walking-times'),'walk:'+revision)
  const [status,setStatus]=useState('')
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  async function save(e:FormEvent<HTMLFormElement>){
    e.preventDefault();setBusy(true);setError('');setStatus('')
    const data=new FormData(e.currentTarget)
    try{await api('/admin/walking-times',json(Object.fromEntries([...data].map(([k,v])=>[k,Number(v)])),'PUT'));setStatus('Время перехода сохранено.');reload(value=>value+1)}
    catch(e){setError(message(e))}finally{setBusy(false)}
  }
  return <section><h2>Измеренное время перехода</h2><p>Переходы направленные. Для обратного маршрута добавьте отдельную запись.</p>
    <form className="toolbar" onSubmit={save}>
      {['from_room_id','to_room_id'].map((name,i)=><label key={name}>{i?'Куда':'Откуда'}<select name={name} required>
        <option value="">Выберите аудиторию</option>{list.data?.map(room=><option key={room.id} value={room.id}>{room.building} — {room.code}</option>)}</select></label>)}
      <label>Минут<input name="minutes" type="number" min="1" max="90" required/></label><button disabled={busy}>Сохранить</button>
    </form><Status pending={busy||(!list.data&&!list.error)} error={error||list.error||matrix.error}/>{status&&<p role="status">{status}</p>}
    <p>Замеры используются при подборе соседних аудиторий и расчёте окон. Маршруты без замера показываются как неизвестные.</p>
    <div className="table-scroll"><table><caption>Матрица измеренных переходов</caption><thead><tr><th>Откуда</th><th>Куда</th><th>Минуты</th></tr></thead>
      <tbody>{matrix.data?.map(row=><tr key={row.from+row.to}><td>{row.from}</td><td>{row.to}</td><td>{row.minutes}</td></tr>)}</tbody></table></div></section>
}


function AuditLog(){
  const [offset,setOffset]=useState(0)
  const [action,change]=useState('')
  const [start,setStart]=useState('')
  const [end,setEnd]=useState('')
  const query=params({offset:String(offset),action,...(start?{start}:{}),...(end?{end}:{})})
  const log=useLoad(()=>api<{id:number;action:string;actor_id:number;object_id:number;at:string}[]>('/admin/audit?'+query),query)
  return <section><h2>Журнал действий</h2><div className="toolbar">
    <label>Событие<select value={action} onChange={event=>{change(event.target.value);setOffset(0)}}><option value="">Все события</option>
      {Object.entries(actionNames).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
    <label>С<input type="date" value={start} onChange={event=>{setStart(event.target.value);setOffset(0)}}/></label>
    <label>По<input type="date" value={end} onChange={event=>{setEnd(event.target.value);setOffset(0)}}/></label></div>
    <Status pending={!log.data&&!log.error} error={log.error} empty={log.data?.length===0?'Действий пока нет.':undefined}/>
    <ul className="records">{log.data?.map(item=><li key={item.id}><span>{actionNames[item.action]??item.action} — пользователь №{item.actor_id} — запись №{item.object_id}</span><time dateTime={item.at}>{new Date(item.at).toLocaleString('ru-RU',{timeZone:campus})}</time></li>)}</ul>
    <div className="actions"><button className="secondary" disabled={!offset} onClick={()=>setOffset(offset-100)}>Назад</button><button className="secondary" disabled={log.data?.length!==100} onClick={()=>setOffset(offset+100)}>Далее</button></div>
  </section>
}
