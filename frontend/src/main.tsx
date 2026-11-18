import { FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'
import '@fontsource-variable/golos-text'
import '@fontsource-variable/unbounded'
import './design-v2.css'
import './site-shell.css'
import './privacy.css'
import { api, ApiError, AuthResult, json, Option, Role, Session, setSession } from './api'
import { Admin } from './admin'
import { BookingPage } from './booking'
import { today, configureCampus, Heading, message, roles, Status, Toast, useLoad } from './common'
import { GroupWindows } from './group-windows'
import { addDays, Schedule } from './weekly'
import { AvailableRooms, useLive } from './rooms'
import { Timeline } from './timeline'
import { Footer, Header, Help, navigation, Site } from './site-shell'
import {DemoRoles} from './DemoRoles'
import {Sheet} from './Sheet'
import { ConsentGate, CookieNotice, DocumentKind, documentTitles, LegalDocument, LoginForm, operatorLabels, Policy } from './privacy'
import { Profile, ProfilePage, ResetPassword } from './profile'
import { adminTabs, go, landing, Link, useLocation } from './routing'

function Workspace({user,location,option,book}:{
  user:Session;location:string;option?:Option;book:(slot:Option)=>void
}) {
  const [path,search='']=location.split('?')
  const params=new URLSearchParams(search)
  if(path==='/schedule')return <Schedule key={location} user={user}/>
  if(path==='/rooms')return <>
    <nav className="actions room-views" aria-label="Виды аудиторий">
      <Link href="/rooms" current={params.get('view')!=='plan'} className="secondary">Свободные сейчас</Link>
      <Link href="/rooms?view=plan" current={params.get('view')==='plan'} className="secondary">План занятости</Link>
    </nav>
    {params.get('view')==='plan'?<Timeline key={location} book={user.role==='student'?undefined:book}/>:
      <AvailableRooms key={location} book={user.role==='student'?undefined:book}/>}
  </>
  if(path==='/booking'){
    const view=params.get('view')
    return <BookingPage user={user} initial={option} initialTab={view==='mine'||view==='watch'?view:'new'}/>
  }
  if(path==='/windows')return <GroupWindows key={location} user={user}/>
  if(path==='/admin'||path.startsWith('/admin/'))return <Admin user={user} tab={path.split('/')[2]??'overview'}/>
  return null
}

function SignedInHeader(props:Omit<Parameters<typeof Header>[0],'revision'> & {onRevision:(revision:number)=>void}) {
  const revision=useLive()
  useEffect(()=>{props.onRevision(revision)},[revision,props.onRevision])
  return <Header {...props} revision={revision}/>
}

function App(){
  const [user,setUser]=useState<Session>()
  const [consentVersion,setConsentVersion]=useState<string>()
  const [loading,setLoading]=useState(true)
  const [pending,setPending]=useState(false)
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const dismissNotice=useCallback(()=>setNotice(''),[])
  const [option,setOption]=useState<Option>()
  const [theme,setTheme]=useState(()=>localStorage.getItem('cf-theme')??'system')
  const [density,setDensity]=useState('comfortable')
  const [picker,showPicker]=useState(false)
  const [demoDestination,setDemoDestination]=useState<string>()
  const [attempt,setAttempt]=useState(0)
  const [online,setOnline]=useState(navigator.onLine)
  const [revision,setRevision]=useState(0)
  const location=useLocation()
  const [path]=location.split('?')
  const policy=useLoad(()=>api<Policy>('/privacy/policy'),'policy:'+attempt+':'+(consentVersion??''))
  const profile=useLoad(()=>user?api<Profile>('/me'):Promise.resolve(undefined),'account-profile:'+user?.id)
  const site=useLoad(()=>api<Site>('/site'),'site:'+revision+':'+attempt,'site')
  if(site.data)configureCampus(site.data.timezone,site.data.bell)
  const content=useRef<HTMLElement>(null)
  const kind=path.startsWith('/legal/')?path.slice(7):''
  const legalKind=Object.hasOwn(documentTitles,kind)?kind as DocumentKind:undefined
  const legalTitle=legalKind?documentTitles[legalKind]:undefined
  const isPublic=Boolean(legalTitle)||path==='/help'||path==='/reset-password'
  const section=navigation.find(item=>path===item.path||item.path==='/admin'&&adminTabs.some(([key])=>path==='/admin/'+key))
  const known=Boolean(section)||['/','/login','/profile'].includes(path)||isPublic
  const denied=!!(user&&section&&!section.roles.includes(user.role))

  function enter(result?:AuthResult){
    const session=result?.status==='authenticated'?result:undefined
    setSession(session);setUser(session);setOption(undefined)
    setConsentVersion(result?.status==='consent_required'?result.version:undefined)
  }
  useEffect(()=>{
    const requireConsent=(event:Event)=>{
      enter({status:'consent_required',version:(event as CustomEvent<string>).detail})
      setAttempt(value=>value+1)
    }
    window.addEventListener('cf-consent-required',requireConsent)
    return ()=>window.removeEventListener('cf-consent-required',requireConsent)
  },[])
  useEffect(()=>{
    let active=true
    setLoading(true);setError('')
    void api<AuthResult>('/auth/refresh',{method:'POST'})
      .then(value=>{if(active)enter(value)})
      .catch(error=>{
        if(!active)return
        if(error.status===401)enter()
        else setError(message(error))
      })
      .finally(()=>{if(active)setLoading(false)})
    return ()=>{active=false}
  },[attempt])
  useEffect(()=>{
    if(user&&demoDestination){
      go(demoDestination,true);setDemoDestination(undefined)
    }else if(user&&path==='/login')go(landing(user.role),true)
    if(path!=='/booking')setOption(undefined)
    setError('')
    document.title=(legalTitle??section?.label??(path==='/profile'?'Личный кабинет':path==='/help'?'Помощь':'CampusFlow'))+' — CampusFlow'
    if(path!=='/'){window.scrollTo(0,0);content.current?.focus({preventScroll:true})}
  },[path,user?.role,demoDestination])
  useEffect(()=>{document.documentElement.dataset.theme=theme;localStorage.setItem('cf-theme',theme)},[theme])
  useEffect(()=>{document.documentElement.dataset.density=density},[density])
  useEffect(()=>{
    if(profile.data){setTheme(profile.data.preferences.theme);setDensity(profile.data.preferences.density)}
  },[profile.data])
  useEffect(()=>{
    const update=()=>setOnline(navigator.onLine)
    window.addEventListener('online',update);window.addEventListener('offline',update)
    return ()=>{window.removeEventListener('online',update);window.removeEventListener('offline',update)}
  },[])
  useEffect(()=>{
    function shortcuts(event:KeyboardEvent){
      if(!user||matchMedia('(max-width:700px)').matches||!event.altKey||event.ctrlKey||event.metaKey||event.target instanceof HTMLElement&&event.target.closest('input,select,textarea,[contenteditable]'))return
      if(event.code==='KeyF'&&(user.role==='student'||user.role==='admin')){event.preventDefault();go('/rooms')}
      if((user.role==='teacher'||user.role==='admin')&&(event.code==='KeyT'||event.code==='KeyB')){
        event.preventDefault();go('/booking?view='+(event.code==='KeyT'?'mine':'watch'))
      }
    }
    window.addEventListener('keydown',shortcuts)
    return ()=>window.removeEventListener('keydown',shortcuts)
  },[user])
  async function login(e:FormEvent<HTMLFormElement>){
    e.preventDefault();setPending(true);setError('')
    const data=new FormData(e.currentTarget)
    try{
      enter(await api<AuthResult>('/auth/login',json({login:data.get('login'),password:data.get('password')})))
    }catch(error){
      setError(error instanceof ApiError&&error.status===401?'Проверьте логин и пароль.':message(error))
    }finally{setPending(false)}
  }
  async function demoSignIn(role:Role){
    setPending(true);setError('')
    try{
      const result=await api<AuthResult>('/auth/demo?role='+role,{method:'POST'})
      showPicker(false)
      let date=addDays(today(),1)
      if(new Date(date+'T12:00:00Z').getUTCDay()===0)date=addDays(date,1)
      setDemoDestination(role==='teacher'?'/booking?day='+date:landing(role))
      enter(result)
    }catch(error){setError(message(error))}
    finally{setPending(false)}
  }
  async function acceptConsent(version:string,data:FormData){
    setPending(true);setError('')
    try{
      enter(await api<AuthResult>('/auth/consent',json({
        version,policy_accepted:data.has('policy'),consent_accepted:data.has('consent'),
      })))
    }catch(error){
      if(error instanceof ApiError&&error.code==='consent_version_changed'){
        setAttempt(value=>value+1)
      }else if(error instanceof ApiError&&error.status===401){
        enter();setNotice('Время подтверждения истекло. Войдите снова.')
      }else setError(message(error))
    }finally{setPending(false)}
  }
  function leaveWithNotice(text:string){
    setDemoDestination(undefined);enter();go('/login',true);setNotice(text)
  }
  async function logout(){
    setPending(true);setError('');setNotice('')
    try{await api('/auth/logout',{method:'POST'});leaveWithNotice(consentVersion?'Вы вышли. Согласие не было принято.':'')}
    catch(e){setError(message(e))}finally{setPending(false)}
  }
  async function password(event:FormEvent<HTMLFormElement>){
    event.preventDefault();setPending(true);setError('')
    const values=new FormData(event.currentTarget)
    try{await api('/auth/password',json(Object.fromEntries(values)));enter();go('/login',true);setNotice('Пароль изменён. Войдите с новым паролем.')}
    catch(e){setError(message(e))}finally{setPending(false)}
  }

  return <>
    <a className="skip" href="#content">К содержанию</a>
    {user?<SignedInHeader user={user} path={location} site={site.data} onRevision={setRevision} pending={pending} logout={()=>void logout()}/>:
      <Header path={location} site={site.data} revision={0} pending={pending} logout={()=>{}}/>}
    <CookieNotice/>
    {picker&&policy.data?.demo&&<Sheet label="Доступ для демонстрации" onClose={()=>showPicker(false)}>
      <h2>Доступ для демонстрации</h2><DemoRoles pending={pending} select={role=>void demoSignIn(role)}/>
      <Status error={error}/><button className="secondary" onClick={()=>showPicker(false)}>Закрыть</button>
    </Sheet>}
    <main className="shell" id="content" tabIndex={-1} ref={content}>
      {!online&&<p className="feedback error" role="status">Нет соединения. Проверьте интернет и повторите действие.</p>}
      {policy.data?.demo&&<div className="demo-banner demo-access"><span>Учебный кампус — все имена и расписание вымышлены</span>
        <button type="button" className="secondary" onClick={()=>showPicker(true)}>{user?'Сменить роль':'Роли, логины и пароли'}</button></div>}
      <Toast text={notice} dismiss={dismissNotice}/>
      {path==='/'?<section className="campus-welcome"><div><h1>Аудитория для вашего занятия</h1><p>Выберите время и число участников. CampusFlow покажет свободные аудитории и сохранит вашу бронь.</p>
        {!user&&policy.data?.demo?<button disabled={pending||loading} onClick={()=>void demoSignIn('teacher')}>Забронировать аудиторию</button>:<Link className="action-link primary-action" href={user?landing(user.role):'/login'}>{user?.role==='student'?'Найти свободную аудиторию':user?.role==='dean'?'Открыть рейтинг групп':user?.role==='admin'?'Перейти к управлению':'Забронировать аудиторию'}</Link>}<Status error={error}/>
        {!user&&<Link className="welcome-login" href="/login">Войти в другой роли</Link>}</div>
        <ol><li>Укажите дату и требования</li><li>Выберите свободную аудиторию</li><li>Подтвердите бронь</li></ol>
      </section>:path==='/reset-password'?<ResetPassword/>:path==='/help'?<Help site={site.data} booking={user?.role==='teacher'||user?.role==='admin'}/>:legalKind?
        <LegalDocument kind={legalKind} policy={policy.data} error={policy.error} retry={()=>setAttempt(value=>value+1)}/>:!known||denied?<section className="route-error">
        {!denied&&<svg className="error-grid" viewBox="0 0 224 120" aria-hidden="true" focusable="false">
          {Array.from({length:12},(_,i)=><rect key={i} x={4+i%4*55} y={4+Math.floor(i/4)*39}
            width="48" height="32" rx="7" className={i===6?'missing-cell':undefined}/>)}
        </svg>}
        <Heading title={denied?'Раздел недоступен':'404 — Страница не найдена'} description={denied?'У вашей роли нет доступа к этой странице.':'Проверьте адрес или вернитесь на главную.'}/>
        <Link className="primary-link" href={user?landing(user.role):'/'}>На главную</Link>
      </section>:loading||!user&&!policy.data&&!policy.error?<Status pending/>:consentVersion?<Heading title="Подтверждение документов" description="Для продолжения подтвердите актуальную редакцию."/>:!user?
      <LoginForm description={site.data?.description??'Бронирование аудиторий'} support={site.data?.support_email}
        pending={pending} error={error} submit={login} demoSignIn={policy.data?.demo?role=>void demoSignIn(role):undefined} retry={online&&error.startsWith('Сервер')?()=>setAttempt(value=>value+1):undefined}/>:<>
        <Status error={error}/>
        {path.startsWith('/admin/')&&<nav className="breadcrumbs" aria-label="Путь"><Link href="/admin">Управление</Link> <span>/ {adminTabs.find(([key])=>path==='/admin/'+key)?.[1]}</span></nav>}
        {path==='/admin'&&user.role==='admin'&&!policy.data?.demo&&!!policy.data?.missing.length&&<section className="panel" aria-label="Реквизиты документов">
          <h2>Перед запуском заполните реквизиты документов</h2>
          <ul>{policy.data.missing.map(key=><li key={key}>{operatorLabels[key]}</li>)}</ul>
          <Link href="/legal/privacy">Открыть политику</Link>
        </section>}
        {path==='/profile'?<ProfilePage user={user} policy={policy.data} setTheme={setTheme} setDensity={setDensity}
          password={password} pending={pending} leave={leaveWithNotice} tab={new URLSearchParams(location.split('?')[1]).get('tab')??'identity'}/>:<Workspace user={user} location={location} option={option} book={slot=>{setOption(slot);go('/booking')}}/>}
      </>}
    </main>
    <Footer/>
    {consentVersion&&!legalKind&&path!=='/help'&&path!=='/reset-password'&&<ConsentGate key={consentVersion}
      policy={policy.data?.version===consentVersion?policy.data:undefined}
      loadError={policy.error} error={error} pending={pending||loading}
      retry={()=>setAttempt(value=>value+1)} decline={()=>void logout()} accept={(version,data)=>void acceptConsent(version,data)}/>}
  </>
}
createRoot(document.getElementById('root')!).render(<App/>)
