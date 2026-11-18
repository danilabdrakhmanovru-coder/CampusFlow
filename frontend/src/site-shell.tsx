import { DeviceAlerts, Notice, NoticeList } from './notifications'
import { useEffect, useState } from 'react'
import { api, Room, Session } from './api'
import { BrandMark } from './BrandMark'
import { allRooms, campus, Heading, roles, Status, useLoad } from './common'
import { Icon, IconName } from './icons'
import { Link } from './routing'
import { Sheet } from './Sheet'

export type Site = { name:string;description:string;campus:string;support_email:string|null;support_hours:string|null;timezone:string;bell:[number,number][];
  schedule_source:string;schedule_updated_at:string|null;schedule_scopes:string[] }
type TeacherChoice = {building:string;number:number;label:string}
export const navigation: {path:string;label:string;short:string;icon:IconName;roles:Session['role'][]}[] = [
  {path:'/rooms',label:'Аудитории',short:'Аудитории',icon:'plan',roles:['student','admin']},
  {path:'/booking',label:'Бронирование',short:'Брони',icon:'ticket',roles:['teacher','admin']},
  {path:'/schedule',label:'Расписание',short:'Расписание',icon:'calendar',roles:['student','teacher','dean','admin']},
  {path:'/windows',label:'Рейтинг групп',short:'Рейтинг',icon:'chart',roles:['dean','admin']},
  {path:'/admin',label:'Управление',short:'Управление',icon:'control',roles:['admin']},
]
const documents = [
  ['/legal/privacy','Политика обработки данных'],
  ['/legal/consent','Согласие на обработку данных'],
  ['/legal/cookies','Технические cookie'],
] as const

export function Header({user,path,site,revision,pending,logout}:{
  user?:Session;path:string;site?:Site;revision:number;pending:boolean;logout:()=>void
}) {
  const [panel,setPanel]=useState<'search'|'notices'>()
  const [read,setRead]=useState(0)
  const notices=useLoad(()=>user&&(user.role==='teacher'||user.role==='admin')?api<Notice[]>('/notifications'):Promise.resolve([]),
    [user?.id,revision].join(':'), user ? 'notices:'+user.id : undefined)
  useEffect(()=>{setRead(user ? Number(localStorage.getItem('cf-notice:'+user.id)||0) : 0)},[user?.id])
  useEffect(()=>{setPanel(undefined)},[path,user?.id])
  useEffect(()=>{
    function shortcut(e:KeyboardEvent){
      if(user&&user.role!=='teacher'&&!matchMedia('(max-width:700px)').matches&&(e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();setPanel('search')}
    }
    window.addEventListener('keydown',shortcut)
    return ()=>window.removeEventListener('keydown',shortcut)
  },[user])
  const unread=notices.data?.filter(notice=>notice.id>read).length??0
  const close=()=>setPanel(undefined)
  const pathname=path.split('?')[0]
  return <header className="masthead site-header">
    <div className="shell top">
      <Link href='/' className="brand"><BrandMark/><span>{site?.name??'CampusFlow'}<small>{site?.description??'Бронирование аудиторий'}</small></span></Link>
      {user&&<nav className="nav site-nav" aria-label="Разделы">
        {navigation.filter(item=>item.roles.includes(user.role)).map(item=><Link key={item.path} href={item.path}
          current={pathname===item.path||pathname.startsWith(item.path+'/')}>
          <Icon name={item.icon}/><span className="nav-label">{item.label}</span><span className="nav-compact" aria-hidden="true">{item.short}</span>
        </Link>)}
      </nav>}
      {user&&<div className="account header-actions">
        {(user.role==='teacher'||user.role==='admin')&&<button className="secondary" aria-label={unread?'Уведомления: '+unread+' новых':'Уведомления'} onClick={()=>{
          setPanel('notices')
          const last=notices.data?.[0]?.id
          if(last && last>read){localStorage.setItem('cf-notice:'+user.id,String(last));setRead(last)}
        }}><Icon name="bell"/>{unread>0&&<span className="count">{unread}</span>}</button>}
        <details className="profile-menu" key={path}>
          <summary aria-label="Меню профиля"><span className="avatar">{roles[user.role][0]}</span><span className="header-role">{roles[user.role]}</span></summary>
          <div><Link href="/profile">Личный кабинет</Link><Link href="/help">Помощь</Link><button className="text-button" disabled={pending} onClick={logout}>Выйти</button></div>
        </details>
      </div>}
    </div>
    {panel==='search'&&user&&<QuickSearch user={user} close={close}/>}
    {panel==='notices'&&<Sheet label="Уведомления" onClose={close}><h2>Уведомления</h2>
      <Status pending={!notices.data&&!notices.error} error={notices.error} empty={notices.data?.length===0?'Здесь появятся напоминания о бронях и предложения из листа ожидания.':undefined}/>
      <NoticeList items={notices.data??[]} close={close}/>
      <DeviceAlerts/>
      <button className="secondary" onClick={close}>Закрыть</button>
    </Sheet>}
  </header>
}

function QuickSearch({user,close}:{user:Session;close:()=>void}) {
  const [query,setQuery]=useState('')
  const data=useLoad(()=>api<{groups:string[];teachers?:TeacherChoice[]}>('/schedule/entities'),'entities')
  const rooms=useLoad(allRooms,'search-rooms')
  const needle=query.trim().toLocaleLowerCase('ru')
  const found=(label:string)=>label.toLocaleLowerCase('ru').includes(needle)
  const candidates=[
    ...navigation.filter(item=>item.roles.includes(user.role)).map(item=>({href:item.path,label:item.label})),
    {href:'/profile',label:'Личный кабинет'},
    {href:'/help',label:'Помощь'},
    ...(needle?(data.data?.groups??[]).map(group=>({href:'/schedule?'+new URLSearchParams({scope:'group',entity_id:group}),label:'Группа '+group})):[]),
    ...(needle?(data.data?.teachers??[]).map(t=>({href:'/schedule?'+new URLSearchParams({scope:'teacher',entity_id:String(t.number),building:t.building}),label:t.label+' — '+t.building})):[]),
    ...(needle?(rooms.data??[]).map((room:Room)=>({href:'/rooms?'+new URLSearchParams({view:'plan',room:String(room.id),building:room.building}),label:'Аудитория '+room.code+' — корпус '+room.building})):[]),
  ].filter(item=>found(item.label)).slice(0,14)
  return <Sheet label="Поиск по CampusFlow" onClose={close}><h2>Поиск по CampusFlow</h2>
    <label>Группа, аудитория или раздел<input autoFocus type="search" value={query} onChange={e=>setQuery(e.target.value)}/></label>
    <Status error={data.error||rooms.error} empty={!candidates.length&&!!data.data&&!!rooms.data?'Ничего не найдено.':undefined}/>
    <ul className="records">{candidates.map(item=><li key={item.href}><Link href={item.href} onNavigate={close}>{item.label}</Link></li>)}</ul>
    <button className="secondary" onClick={close}>Закрыть поиск</button>
  </Sheet>
}

export function Footer() {
  return <footer className="site-footer"><div className="shell simple-footer">
    <Link href="/help">Помощь</Link>
    {documents.map(([path,label])=><Link key={path} href={path}>{label}</Link>)}
  </div></footer>
}

function Shortcuts({booking}:{booking:boolean}) {
  const shortcuts=[
    ['Ctrl+K','Поиск по разделам, группам и аудиториям'],
    ['Alt+F','Аудитории'],
    ...(booking?[['Alt+T','Мои брони'],['Alt+B','Ожидание свободной аудитории']]:[]),
    ['Escape','Закрыть открытое окно'],
  ]
  return <dl className="shortcut-list">{shortcuts.map(([keys,label])=>
    <div key={keys}><dt><kbd>{keys}</kbd></dt><dd>{label}</dd></div>)}</dl>
}

export function Help({site,booking}:{site?:Site;booking:boolean}) {
  return <><Heading title="Помощь" description="Как пользоваться CampusFlow"/>
    <section className="panel"><h2>Найти расписание или аудиторию</h2><p>Откройте «Расписание» и выберите группу, аудиторию или корпус. В разделе «Аудитории» доступны свободные помещения и план занятости.</p>
      <p>Преподаватель может выбрать время и зарезервировать его на пять минут, чтобы успеть подтвердить бронь.</p>
      <div className="actions"><Link href="/schedule">К расписанию</Link><Link href="/rooms">К аудиториям</Link></div></section>
    <section className="panel desktop-shortcuts"><h2>Клавиатура</h2><Shortcuts booking={booking}/></section>
    <section className="panel"><h2>Связаться с диспетчерской</h2>{site?.support_email?<a href={'mailto:'+site.support_email}>{site.support_email}</a>:<p>Контакт диспетчерской пока не опубликован.</p>}{site?.support_hours&&<p>{site.support_hours}</p>}</section>
  </>
}
