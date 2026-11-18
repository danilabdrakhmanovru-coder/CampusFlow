import { FormEvent, useState } from 'react'
import { api, json, type Role } from './api'
import { BrandMark } from './BrandMark'
import { campus, Heading, message, Status, useLoad } from './common'
import { Link } from './routing'
import { Sheet, useConfirmation } from './Sheet'

export const documentTitles = {
  privacy:'Политика обработки персональных данных',
  consent:'Согласие на обработку персональных данных',
  cookies:'Технические cookie',
}
export type DocumentKind = keyof typeof documentTitles
type Section = {title:string;text:string}
export const operatorLabels = {
  effective_date:'Дата вступления в силу',
  operator:'Оператор',
  responsible:'Ответственный за обработку данных',
  contact:'Контакт',
}
type OperatorField = keyof typeof operatorLabels
export type Policy = {
  version:string; status:string; demo:boolean; retention:string
  operator:Record<OperatorField,string|null>; missing:OperatorField[]
  documents:Record<DocumentKind,{title:string;sections:Section[]}>
}
type Acceptance = {id:number;version:string;accepted_at:string;withdrawn_at:string|null}

function DocumentSections({sections, anchors=false}:{sections:Section[];anchors?:boolean}){
  return <ol className="legal-sections">{sections.map(({title,text},index)=>
    <li key={title} id={anchors?'section-'+(index+1):undefined}><h2>{title}</h2><p>{text}</p></li>)}</ol>
}

export function LegalDocument({kind,policy,error,retry}:{kind:DocumentKind;policy?:Policy;error?:string;retry:()=>void}){
  const document=policy?.documents[kind]
  return <article className="legal-document">
    <Heading title={document?.title??documentTitles[kind]} description={policy?'Редакция '+policy.version:'Документы CampusFlow'}/>
    <Status pending={!policy&&!error} error={error}/>
    {error&&<button type="button" className="secondary" onClick={retry}>Повторить загрузку</button>}
    {policy&&document&&<>
      <p className="feedback legal-draft">Шаблон для пилота. Требуется согласование университетом.</p>
      <dl className="panel legal-metadata">{Object.entries(operatorLabels).map(([key,label])=>
        <div key={key}><dt>{label}</dt><dd>{policy.operator[key as OperatorField]??'Не указано'}</dd></div>)}</dl>
      <div className="actions legal-actions">
        <a className="primary-link" href={'/api/v1/privacy/documents/'+kind+'.pdf'} download>Скачать PDF</a>
        <button type="button" className="secondary" onClick={()=>window.print()}>Печать</button>
      </div>
      <nav className="panel legal-toc" aria-label="Оглавление"><h2>Оглавление</h2><ol>{document.sections.map(({title},index)=>
        <li key={title}><a href={'#section-'+(index+1)}>{title}</a></li>)}</ol></nav>
      <DocumentSections sections={document.sections} anchors/>
    </>}
  </article>
}

export function LoginForm({description,support,pending,error,retry,submit,demoSignIn}:{
  description:string; support?:string|null; pending:boolean; error:string; retry?:()=>void; demoSignIn?:(role:Role)=>void; submit:(event:FormEvent<HTMLFormElement>)=>void
}){
  const [show,setShow]=useState(false)
  const [help,setHelp]=useState(false)
  return <section className={"login"+(demoSignIn?" demo-login":"")}>
    <div className="login-mark"><BrandMark/></div>
    <Heading title="Вход в CampusFlow" description={description}/>
    {demoSignIn&&<section aria-label="Демонстрационный вход">
      <h2>Попробовать CampusFlow</h2>
      <div className="demo-role-grid">
        {([
          ['student','Найти свободную аудиторию','Студент'],
          ['teacher','Забронировать аудиторию','Преподаватель'],
          ['dean','Улучшить расписание','Сотрудник деканата'],
          ['admin','Управлять кампусом','Администратор'],
        ] as const).map(([role,action,label])=><button className="secondary demo-role" key={role} disabled={pending}
          type="button" onClick={()=>demoSignIn(role)}><small>{label}</small><strong>{action}</strong></button>)}
      </div>
    </section>}
    <details className={demoSignIn?'manual-login':'ordinary-login'} open={demoSignIn?undefined:true}>
      <summary>Войти с логином и паролем</summary>
    <form className="panel" onSubmit={submit}>
      <label>Логин<input name="login" autoComplete="username" required maxLength={100} aria-describedby="login-hint"/></label>
      <p className="field-hint" id="login-hint">Введите логин, который выдал диспетчер.</p>
      <div className="login-password">
        <label>Пароль<input name="password" type={show?'text':'password'} autoComplete="current-password" required maxLength={128}/></label>
        <button type="button" className="secondary" onClick={()=>setShow(value=>!value)}>
          {show?'Скрыть пароль':'Показать пароль'}
        </button>
      </div>
      <button className="text-button forgot-password" type="button" aria-expanded={help} onClick={()=>setHelp(value=>!value)}>Не помню пароль</button>
      {help&&<p className="feedback">За восстановлением доступа обратитесь в диспетчерскую.{' '}
        {support?<a href={'mailto:'+support}>{support}</a>:<Link href="/help">Контакты и помощь</Link>}</p>}
      <button disabled={pending}>{pending?'Проверяем данные…':'Войти'}</button>
      {retry&&<button type="button" className="secondary" onClick={retry}>Повторить подключение</button>}
    </form>
    </details>
    <Status error={error}/>
    {!demoSignIn&&<p className="muted">Здесь можно посмотреть расписание, найти свободную аудиторию и управлять бронями.</p>}
    <div className="actions"><Link href="/legal/privacy">Политика обработки данных</Link><Link href="/legal/consent">Согласие</Link></div>
  </section>
}

export function ConsentGate({policy,loadError,error,pending,retry,decline,accept}:{
  policy?:Policy;loadError?:string;error:string;pending:boolean;retry:()=>void;decline:()=>void;accept:(version:string,form:FormData)=>void
}){
  return <Sheet label="Документы и согласие" className="consent-sheet" onClose={()=>{}}>
    <h2>Документы и согласие</h2>
    <Status pending={!policy&&!loadError} error={loadError||error}/>
    {(loadError||error)&&<button className="secondary" disabled={pending} onClick={retry}>Повторить загрузку</button>}
    {policy&&<>
      <p>Прочитайте документы редакции <strong>{policy.version}</strong>, чтобы продолжить.</p>
      <dl className="consent-summary">
        <div><dt>Какие данные</dt><dd>Логин, роль, брони и действия с ними, сведения о сеансах и согласиях.</dd></div>
        <div><dt>Для чего</dt><dd>Для входа, просмотра расписания и управления бронированием.</dd></div>
        <div><dt>Срок хранения</dt><dd>{policy.retention}</dd></div>
        <div><dt>Оператор</dt><dd>{policy.operator.operator??'Университет уточняет реквизиты оператора.'}</dd></div>
        <div><dt>Ваши права</dt><dd>Запросить сведения, уточнение или удаление данных у оператора. Согласие можно отозвать в личном кабинете.</dd></div>
      </dl>
      {(['privacy','consent'] as const).map(kind=><details className="consent-document" key={kind}>
        <summary>{policy.documents[kind].title}</summary>
        <p className="muted">Шаблон для пилота. Требуется согласование университетом.</p>
        <DocumentSections sections={policy.documents[kind].sections}/>
        <a href={'/legal/'+kind} target="_blank" rel="noopener">Открыть отдельную страницу</a>
      </details>)}
      <form className="consent-form" onSubmit={event=>{event.preventDefault();accept(policy.version,new FormData(event.currentTarget))}} key={policy.version}>
        <label className="check"><input type="checkbox" name="policy" required/>Ознакомился(-ась) с политикой обработки персональных данных</label>
        <label className="check"><input type="checkbox" name="consent" required/>Даю согласие на обработку персональных данных</label>
        <div className="actions"><button disabled={pending}>Принять и продолжить</button>
          <button className="secondary" type="button" disabled={pending} onClick={decline}>Отказаться и выйти</button></div>
      </form>
    </>}
    {!policy&&<button className="secondary" disabled={pending} onClick={decline}>Отказаться и выйти</button>}
  </Sheet>
}

export function PrivacyHistory({version,onWithdrawn,onExpired}:{version?:string;onWithdrawn:()=>void;onExpired:()=>void}){
  const history=useLoad(()=>api<Acceptance[]>('/auth/consents'),'consents:'+version)
  const confirmation=useConfirmation()
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const format=new Intl.DateTimeFormat('ru-RU',{dateStyle:'medium',timeStyle:'short',timeZone:campus})
  async function withdraw(){
    setBusy(true);setError('')
    try {await api('/auth/consent/withdraw',json({}));onWithdrawn()}
    catch(error){
      if((error as {status?:number}).status===401)onExpired()
      else setError(message(error))
    }finally{setBusy(false)}
  }
  return <section className="panel">
    <h2>Данные и конфиденциальность</h2>
    <h3>История согласий</h3>
    <Status pending={!history.data&&!history.error} error={error||history.error} empty={history.data?.length===0?'История согласий пуста.':undefined}/>
    <ul className="records consent-history">{history.data?.map(row=><li key={row.id}>
      <div><strong>Редакция {row.version}</strong><p>Принято <time dateTime={row.accepted_at}>{format.format(new Date(row.accepted_at))}</time></p>
        {row.withdrawn_at&&<p>Отозвано <time dateTime={row.withdrawn_at}>{format.format(new Date(row.withdrawn_at))}</time></p>}</div>
      <span className="tag">{row.withdrawn_at?'Отозвано':row.version===version?'Действует':'Предыдущая редакция'}</span>
    </li>)}</ul>
    <button type="button" className="secondary" disabled={busy} onClick={()=>confirmation.ask({
      title:'Отозвать согласие?',
      description:'CampusFlow завершит все ваши сеансы. История согласий сохранится в аккаунте.',
      label:'Отозвать и выйти',apply:()=>void withdraw(),
    })}>Отозвать согласие</button>
    {confirmation.dialog}
  </section>
}

export function CookieNotice(){
  const [seen,setSeen]=useState(()=>localStorage.getItem('cf-cookie-notice')==='seen')
  if(seen)return null
  return <aside className="cookie-note" aria-label="Технические cookie">
    <p>CampusFlow использует технические cookie для входа. <Link href="/legal/cookies">Подробнее</Link></p>
    <button className="secondary" type="button" onClick={()=>{localStorage.setItem('cf-cookie-notice','seen');setSeen(true)}}>Понятно</button>
  </aside>
}
