import { FormEvent,useState } from 'react'
import { api,json } from './api'
import { campus, clock, message, Status,today,useLoad } from './common'
import { Suggestion,SuggestionCard } from './group-windows'
import { Link } from './routing'
import { useConfirmation } from './Sheet'

export const actions:Record<string,string>={
  'user.created':'Создан аккаунт','user.updated':'Изменён аккаунт','user.erased':'Удалены данные аккаунта',
  'user.teacher_link_requested':'Запрошена привязка','user.teacher_linked':'Привязан преподаватель','user.teacher_unlinked':'Снята привязка',
  'user.deletion_requested':'Запрошено удаление данных','user.password_changed':'Изменён пароль','user.password_reset':'Восстановлен пароль',
  'user.password_reset_issued':'Выдана ссылка восстановления','user.sessions_revoked':'Завершены все сеансы',
  'schedule.publish':'Опубликовано расписание','schedule.staged':'Подготовлена выгрузка','schedule.rollback':'Выполнен откат',
  'schedule.lesson_skipped':'Пара исключена','booking.created':'Создана бронь','booking.cancelled':'Отменена бронь',
  'booking.cancelled_for_import':'Отмена из-за импорта','booking.auto_released':'Бронь освобождена автоматически',
  'consent.accepted':'Приняты документы','consent.withdrawn':'Отозвано согласие','proposal.applied':'Применён перенос',
  'proposal.decided':'Записано решение по переносу','room.saved':'Изменена аудитория','hold.renewed':'Продлено удержание',
  'site.settings_changed':'Обновлены настройки','login.throttled':'Ограничены попытки входа',
}
type Overview={uncovered_buildings:string[];conflicts:number;checked_staged_imports:number;missing_group_sizes:string[];bookings_today:number;requests:number;auto_releases:{booking_id:number;at:string}[];actions:{id:number;action:string;at:string}[]}
export function OverviewPage(){
  const data=useLoad(()=>api<Overview>('/admin/overview'),'overview')
  return <section><h2>Обзор на сегодня</h2><Status pending={!data.data&&!data.error} error={data.error}/>
    {data.data&&<><div className="dispatch-grid">
      <section className="panel"><h3>Расписание корпусов</h3><p>{data.data.uncovered_buildings.length?'Нет полной выгрузки: '+data.data.uncovered_buildings.join(', '):'На сегодня выгрузки полные.'}</p>
        {data.data.conflicts>0&&<p>Конфликтов импорта: {data.data.conflicts}.</p>}<Link href="/admin/imports">К импорту расписания</Link></section>
      <section className="panel"><h3>Брони на сегодня</h3><p>{data.data.bookings_today}</p><Link href="/booking?view=mine">Посмотреть брони</Link></section>
      <section className="panel"><h3>Качество расписания</h3><p>Посмотрите группы с длинными окнами и сравните переносы существующих занятий.</p><Link className="action-link primary-action" href="/windows">Открыть рейтинг групп</Link></section>
      </div>
      <details className="secondary-options"><summary>Подробности за сегодня</summary><div className="dispatch-grid">
      <section className="panel"><h3>Группы без размера</h3><p>{data.data.missing_group_sizes.length} на ближайшую неделю.</p>
        <p>{data.data.missing_group_sizes.slice(0,6).join(', ')}</p><Link href="/admin/groups">Заполнить размеры</Link></section>
      <section className="panel"><h3>Автоосвобождение</h3><ul>{data.data.auto_releases.map(row=><li key={row.booking_id}>Бронь №{row.booking_id}, {clock(row.at)}</li>)}</ul>
        {!data.data.auto_releases.length&&<p>На ближайшие четыре часа нет броней, ожидающих отметку.</p>}</section>
      <section className="panel"><h3>Запросы пользователей</h3><p>{data.data.requests} аккаунтов с запросами на привязку или удаление.</p><Link href="/admin/users">К пользователям</Link></section></div>
      <section className="panel"><h3>Последние действия</h3><ul className="records">{data.data.actions.map(row=><li key={row.id}>
        <span>{actions[row.action]??row.action}</span><time>{new Intl.DateTimeFormat('ru-RU',{dateStyle:'short',timeStyle:'short',timeZone:campus}).format(new Date(row.at))}</time></li>)}</ul><Link href="/admin/audit">Открыть журнал</Link></section></details></>}
  </section>
}

type Model={status:string;demo:boolean;version:number|null;trained_at:string|null;decisions:number;min_decisions:number;features:string[];sample_count:number|null;metrics:Record<string,number>|null;limitations:string}
export function ModelPage(){
  const [revision,reload]=useState(0)
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const model=useLoad(()=>api<Model>('/analytics/model'),'ranking:'+revision)
  const metrics:Record<string,string>={brier:'Ошибка вероятности (Brier)',baseline_brier:'Базовая ошибка вероятности',mae_minutes:'Средняя ошибка минут (MAE)',baseline_mae_minutes:'Базовая ошибка минут',train_rows:'Решений в обучении',holdout_rows:'Решений в отложенной выборке'}
  const features:Record<string,string>={window_minutes:'длительность окна',weekday:'день недели',bell_slot:'номер пары',building_change:'смена корпуса',room_type:'тип аудитории',group_size:'размер группы',groups:'число групп',teachers:'число преподавателей'}
  return <section className="panel"><h2>О модели переноса</h2><Status pending={busy||(!model.data&&!model.error)} error={error||model.error}/>
    {model.data&&<>
      <p>{model.data.version?'Версия '+model.data.version+', обучена '+new Date(model.data.trained_at!).toLocaleDateString('ru-RU'):'Недостаточно данных для обучения.'}</p>
      <p>Решений диспетчеров: {model.data.decisions}. Минимум {model.data.min_decisions}, причём в обучающей и отложенной выборках нужны и принятия, и отказы.</p>
      {model.data.demo&&<p className="feedback">Демонстрационная среда. Решения здесь синтетические, точность на данных вуза не подтверждена.</p>}
      <p>LightGBM использует {model.data.features.map(key=>features[key]??key).join(', ')}.</p>
      <p>{model.data.limitations}</p>
      {model.data.metrics&&<><p>Решений в сохранённой версии: {model.data.sample_count}.</p><ul className="records">{Object.entries(model.data.metrics).map(([key,value])=><li key={key}>{metrics[key]??key} <strong>{Number(value.toFixed(3))}</strong></li>)}</ul></>}
      <button className="secondary" disabled={busy||model.data.decisions<model.data.min_decisions} onClick={()=>{
        setBusy(true);setError('')
        void api('/analytics/model/train',{method:'POST'}).then(()=>reload(i=>i+1),error=>setError(message(error))).finally(()=>setBusy(false))
      }}>Переобучить</button></>}
  </section>
}

export function Moves(){
  const [revision,reload]=useState(0)
  const [filter,setFilter]=useState('pending')
  const records=useLoad(()=>api<{id:number;applied:number[]|null;decision:boolean|null;suggestion?:Suggestion}[]>('/admin/proposals'),'moves:'+revision)
  const suggestions=records.data?.filter(row=>row.suggestion&&(filter==='all'||(filter==='pending'?row.decision===null:row.decision!==null)))
  return <section><h2>Очередь переносов</h2><label>Показывать<select value={filter} onChange={event=>setFilter(event.target.value)}>
    <option value="pending">К рассмотрению</option><option value="done">Рассмотренные</option><option value="all">Все предложения</option></select></label>
    <Status error={records.error} pending={!records.data&&!records.error} empty={suggestions?.length===0?'В этой очереди пока нет переносов.':undefined}/>
    <Link href="/windows">Найти исправления для групп</Link>
    {suggestions?.map(row=><div key={row.id}>{row.decision!==null&&<p className="tag">{row.decision?'Принято':'Отклонено'}</p>}
      <SuggestionCard item={row.suggestion!} admin applied={row.applied!==null} decided={row.decision!==null} onUpdate={()=>reload(i=>i+1)}/></div>)}
  </section>
}

type Settings=Record<string,string|number|null>
const labels:Record<string,string>={operator:'Оператор',responsible:'Ответственный за обработку данных',contact:'Контакт по персональным данным',effective_date:'Дата вступления в силу',
  version:'Редакция',support_email:'Почта диспетчерской',support_hours:'График поддержки',booking_days:'Хранение броней, дней',audit_days:'Хранение журнала, дней',session_days:'Хранение истёкших сеансов, дней'}
export function SettingsPage(){
  const data=useLoad(()=>api<Settings>('/admin/settings'),'dispatch-settings')
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const confirm=useConfirmation()
  function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault();if(!data.data)return
    const values=Object.fromEntries([...new FormData(event.currentTarget)].map(([key,value])=>[key,key.endsWith('_days')?Number(value):String(value).trim()||null]))
    confirm.ask({title:'Сохранить настройки?',description:'После смены редакции пользователи подтверждают документы заново.',label:'Сохранить настройки',apply:()=>{
      setBusy(true);setError('')
      void api('/admin/settings',json(values,'PUT')).then(()=>window.location.reload(),error=>setError(message(error))).finally(()=>setBusy(false))
    }})
  }
  return <section><h2>Настройки сервиса</h2><p>При изменении реквизитов или сроков укажите новую редакцию документов. Даты и контакты публикуются на страницах документов.</p>
    <Status error={error||data.error} pending={busy||(!data.data&&!data.error)}/>
    {data.data&&<form className="panel settings-grid" onSubmit={submit}>{Object.entries(labels).map(([key,label])=><label key={key}>{label}
      <input name={key} type={key.endsWith('_days')?'number':key==='effective_date'?'date':key==='support_email'?'email':'text'} defaultValue={data.data?.[key]??''}
        min={key.endsWith('_days')?1:undefined} max={key.endsWith('_days')?3650:undefined} required={key==='version'||key.endsWith('_days')}/></label>)}
      <button disabled={busy}>Сохранить</button></form>}
    {confirm.dialog}</section>
}
