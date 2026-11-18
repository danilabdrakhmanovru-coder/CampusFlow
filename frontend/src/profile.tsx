import { FormEvent, useEffect, useState } from 'react'
import { api, json, Session, Teacher } from './api'
import { allRooms, campus, Heading, message, roles, Status, useLoad } from './common'
import { Link, go } from './routing'
import { Policy, PrivacyHistory } from './privacy'
import { useConfirmation } from './Sheet'

const tabs = [['identity','Профиль'],['security','Безопасность'],['notifications','Уведомления'],['privacy','Данные и конфиденциальность'],['interface','Интерфейс']] as const
const noticeLabels = {watch_hold:'Освободилась аудитория из ожидания',cancelled_by_admin:'Диспетчер отменил бронь',booking_reminder:'Скоро начнётся бронь',slot_freed:'Бронь освобождена'}
export type Preferences = {group:string|null;building:string|null;theme:string;density:string;notifications:Record<string,boolean>;teaching_days_off:number[]}
export type Profile = {login:string;institute:string;role:Session['role'];preferences:Preferences;teacher:Teacher|null;teacher_link_requested_at:string|null;deletion_requested_at:string|null}
export type Group = {code:string;size:number|null}
const format=(value:string)=>new Intl.DateTimeFormat('ru-RU',{dateStyle:'medium',timeStyle:'short',timeZone:campus}).format(new Date(value))

export function PasswordFields({current=false}:{current?:boolean}){
  const [value,setValue]=useState('')
  const score=Number(value.length>=12)+Number(value.length>=16)+Number(/[\p{L}]/u.test(value))+Number(/\d/.test(value))+Number(/[^\p{L}\d]/u.test(value))
  return <>{current&&<label>Текущий пароль<input name="current_password" type="password" autoComplete="current-password" required/></label>}
    <label>Новый пароль<input name="new_password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required
      value={value} onChange={event=>setValue(event.target.value)} aria-describedby="password-rules"/></label>
    <div id="password-rules"><meter min={0} max={5} value={score} aria-label="Сложность пароля"/> Не менее 12 знаков, с буквами и цифрами.</div></>
}

export function ResetPassword(){
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const [done,setDone]=useState(false)
  async function reset(event:FormEvent<HTMLFormElement>){
    event.preventDefault();setBusy(true);setError('')
    try{
      await api('/password-reset',json({token:location.hash.slice(1),password:new FormData(event.currentTarget).get('new_password')}))
      history.replaceState(null,'',location.pathname)
      setDone(true)
    }catch(error){setError(message(error))}
    finally{setBusy(false)}
  }
  return <section className="login"><Heading title="Восстановление доступа" description="Одноразовая ссылка от диспетчера"/>
    {done?<><p role="status">Пароль изменён. Войдите с новым паролем.</p><a href="/login">Ко входу</a></>:
      location.hash?<form className="panel profile-password" onSubmit={reset}><PasswordFields/><button disabled={busy}>Установить пароль</button><Status error={error}/></form>:
      <p>Запросите ссылку для восстановления у диспетчера. <Link href="/help">Контакты и помощь</Link></p>}
  </section>
}

export function ProfilePage({user,policy,setTheme,setDensity,password,pending,leave,tab}:{
  user:Session;policy?:Policy;setTheme:(theme:string)=>void;setDensity:(density:string)=>void;password:(event:FormEvent<HTMLFormElement>)=>void;
  pending:boolean;leave:(text:string)=>void;tab:string
}){
  const [revision,refresh]=useState(0)
  const [error,setError]=useState('')
  const [note,setNote]=useState('')
  const [busy,setBusy]=useState(false)
  const profile=useLoad(()=>api<Profile>('/me'),'profile:'+revision,'profile')
  const groups=useLoad(()=>api<Group[]>('/catalog/groups'),'groups')
  const rooms=useLoad(allRooms,'buildings')
  const devices=useLoad(()=>tab==='security'?api<{id:string;current:boolean;created_at:string;expires_at:string}[]>('/me/sessions'):Promise.resolve([]),'sessions:'+tab+':'+revision)
  const confirm=useConfirmation()
  const record=profile.data
  const prefs=record?.preferences
  const buildings=[...new Set(rooms.data?.map(room=>room.building))].sort()
  async function run(action:()=>Promise<unknown>, label:string){
    setBusy(true);setError('');setNote('')
    try {await action();setNote(label);refresh(value=>value+1)}
    catch(error){setError(message(error))}
    finally{setBusy(false)}
  }
  function save(event:FormEvent<HTMLFormElement>){
    event.preventDefault()
    if(!prefs)return
    const fields=new FormData(event.currentTarget)
    const next={...prefs}
    if(tab==='identity'){
      next.group=String(fields.get('group')??prefs.group??'')||null;next.building=String(fields.get('building')??'')||null
      if(user.role==='teacher')next.teaching_days_off=fields.getAll('day_off').map(Number)
    }
    if(tab==='interface'){next.theme=String(fields.get('theme'));next.density=String(fields.get('density'))}
    if(tab==='notifications')next.notifications=Object.fromEntries(Object.keys(noticeLabels).map(key=>[key,fields.has(key)]))
    void run(async()=>{await api('/me/preferences',json(next,'PUT'));setTheme(next.theme);setDensity(next.density)},'Настройки сохранены.')
  }
  return <><Heading title="Личный кабинет" description={roles[user.role]}/>
    <nav className="actions room-views" aria-label="Настройки аккаунта">{tabs.filter(([key])=>key!=='notifications'||user.role!=='student').map(([key,label])=>
      <Link className="secondary" key={key} href={'/profile?tab='+key} current={tab===key}>{label}</Link>)}</nav>
    <Status error={error||profile.error} pending={!record&&!profile.error}/>{note&&<p className="feedback" role="status">{note}</p>}
    {record&&prefs&&tab==='identity'&&<section className="panel"><div className="profile-identity"><span className="avatar" aria-hidden="true">{(record.login??roles[user.role]).slice(0,2).toUpperCase()}</span><div><strong>{record.login??'Аккаунт'}</strong><p>{roles[record.role]} — {record.institute}</p></div></div>
      {user.role==='teacher'&&(record.teacher?<p>{record.teacher.label} привязан к расписанию.</p>:record.teacher_link_requested_at?<p>Запрос ожидает подтверждения диспетчера.</p>:
        <button className="secondary" disabled={busy} onClick={()=>void run(()=>api('/me/teacher-link-request',{method:'POST'}),'Запрос передан диспетчеру.')}>Запросить привязку</button>)}
      <form className="toolbar" key={revision} onSubmit={save}>
        {user.role==='student'&&<label>Моя группа<select name="group" defaultValue={prefs.group??''}><option value="">Выберите группу</option>{groups.data?.map(group=><option key={group.code}>{group.code}</option>)}</select></label>}
        <label>Корпус по умолчанию<select name="building" defaultValue={prefs.building??''}><option value="">Все корпуса</option>{buildings.map(building=><option key={building}>{building}</option>)}</select></label>
        {user.role==='teacher'&&<fieldset><legend>Дни без занятий</legend>
          <p>В эти дни CampusFlow запрещает новые переносы ваших пар. Уже опубликованные занятия можно исправить через диспетчера.</p>
          <div className="actions">{['Пн','Вт','Ср','Чт','Пт','Сб','Вс'].map((label,day)=><label className="check" key={day}>
            <input type="checkbox" name="day_off" value={day} defaultChecked={prefs.teaching_days_off?.includes(day)}/>{label}
          </label>)}</div>
          {!record.teacher&&<p>Для учёта дней в расписании нужна привязка преподавателя к аккаунту.</p>}
        </fieldset>}
        <button disabled={busy||!rooms.data||(user.role==='student'&&!groups.data)}>Сохранить</button>
      </form>
    </section>}
    {tab==='security'&&<>
      <form className="panel profile-password" onSubmit={password}><h2>Сменить пароль</h2><PasswordFields current/><button disabled={pending}>Сменить пароль</button></form>
      <section className="panel"><h2>Активные сеансы</h2><Status pending={!devices.data&&!devices.error} error={devices.error}/>
        <ul className="records">{devices.data?.map(row=><li key={row.id}><div><strong>{row.current?'Текущий сеанс':'Другой сеанс'}</strong><p>Начат {format(row.created_at)}</p></div>
          {!row.current&&<button className="secondary" onClick={()=>void run(()=>api('/me/sessions/'+row.id,{method:'DELETE'}),'Сеанс завершён.')}>Завершить сеанс</button>}</li>)}</ul>
        <button className="secondary" onClick={()=>confirm.ask({title:'Завершить все сеансы?',description:'Потребуется снова войти на каждом устройстве.',label:'Выйти на всех устройствах',
          apply:()=>void run(async()=>{await api('/me/sessions',{method:'DELETE'});leave('Все сеансы завершены.')},'')})}>Выйти на всех устройствах</button>
      </section></>}
    {prefs&&tab==='notifications'&&user.role!=='student'&&<form className="panel profile-password" key={revision} onSubmit={save}>
      <h2>Уведомления в CampusFlow</h2>{Object.entries(noticeLabels).map(([key,label])=><label key={key} className="check"><input name={key} type="checkbox" defaultChecked={prefs.notifications[key]??true}/>{label}</label>)}
      <button disabled={busy}>Сохранить</button>
    </form>}
    {record&&tab==='privacy'&&<><PrivacyHistory version={policy?.version} onWithdrawn={()=>leave('Согласие отозвано. Все сеансы завершены.')} onExpired={()=>leave('Сеанс завершился. Войдите снова.')}/>
      <section className="panel"><h2>Мои данные</h2><div className="actions"><button className="secondary" disabled={busy} onClick={()=>void run(async()=>{
        const data=await api('/me/export');const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}))
        const download=document.createElement('a');download.href=url;download.download='campusflow-my-data.json';download.click();setTimeout(()=>URL.revokeObjectURL(url),10000)
      },'Файл подготовлен.')}>Скачать мои данные</button>
      {record.deletion_requested_at?<p>Запрос на удаление ожидает рассмотрения.</p>:<button className="secondary" onClick={()=>confirm.ask({
        title:'Запросить удаление данных?',description:'Запрос увидит диспетчер.',label:'Отправить запрос',
        apply:()=>void run(()=>api('/me/deletion-request',{method:'POST'}),'Запрос отправлен.'),
      })}>Запросить удаление данных</button>}</div></section></>}
    {prefs&&tab==='interface'&&<form className="panel profile-password" key={revision} onSubmit={save}>
      <label>Тема<select name="theme" aria-label="Цветовая тема" defaultValue={prefs.theme} onChange={e=>setTheme(e.target.value)}><option value="system">Системная</option><option value="light">Светлая</option><option value="dark">Тёмная</option></select></label>
      <label>Плотность<select name="density" defaultValue={prefs.density}><option value="comfortable">Обычная</option><option value="compact">Компактная</option></select></label>
      <button disabled={busy}>Сохранить</button></form>}
    {confirm.dialog}
  </>
}
