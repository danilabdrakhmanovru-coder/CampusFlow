import {useEffect,useState} from 'react'
import {api,json} from './api'
import {campus, message, useLoad} from './common'
import {Icon, IconName} from './icons'
import {Link} from './routing'

export type Notice = {id:number;kind:string;payload:{booking_id?:number;reason?:string;room?:string;building?:string};created_at:string}
const copy:Record<string,[string,string,IconName]>={
  watch_hold:['Аудитория освободилась','Открыть лист ожидания','clock'],
  booking_reminder:['Скоро начало брони','Открыть мои брони','ticket'],
  cancelled_by_admin:['Администратор отменил бронь','Посмотреть брони','calendar'],
  slot_freed:['Аудитория освобождена','Посмотреть брони','plan']
}
function time(value:Date){
  return value.toLocaleTimeString('ru-RU',{timeZone:campus,hour:'2-digit',minute:'2-digit'})
}
export function NoticeList({items,close}:{items:Notice[];close:()=>void}){
  return <ol className="notice-list">{items.map(n=>{
    const [title,action,icon]=copy[n.kind]??['Обновление брони','Посмотреть брони','bell']
    const start=new Date(n.created_at), end=new Date(start.getTime()+300000)
    const watch=n.kind==='watch_hold', expired=watch&&end.getTime()<=Date.now()
    const detail=watch?(expired?'Срок резервирования закончился.':'Подтвердите бронь до '+time(end)+'.'):
      n.payload.reason|| (n.kind==='booking_reminder'?'Откройте талон для отметки о приходе.':'Изменился статус вашей брони.')
    return <li key={n.id}><span className={'notice-icon'+(watch&&!expired?' priority':'')}><Icon name={icon}/></span><div>
      <time dateTime={n.created_at}>{start.toLocaleDateString('ru-RU',{timeZone:campus,day:'numeric',month:'short'})}, {time(start)}</time>
      <h3>{title}</h3>{n.payload.room&&<strong>Аудитория {n.payload.room}, корпус {n.payload.building}</strong>}
      <p>{detail}</p><Link href={'/booking?view='+(watch?'watch':'mine')} onNavigate={close}>{action}</Link>
    </div></li>
  })}</ol>
}

export function DeviceAlerts(){
  const [revision,refresh]=useState(0)
  const settings=useLoad(()=>api<{key:string|null;enabled:boolean}>('/push'),'device-alerts:'+revision)
  const [registration,setRegistration]=useState<ServiceWorkerRegistration>()
  const [busy,setBusy]=useState(false), [error,setError]=useState('')
  const ios=/iPhone|iPad|iPod/.test(navigator.userAgent)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1)
  const install=ios&&!matchMedia('(display-mode: standalone)').matches
  const supported=isSecureContext&&'serviceWorker' in navigator&&'PushManager' in window&&'Notification' in window
  useEffect(()=>{
    if(!supported||install)return
    navigator.serviceWorker.register('/sw.js').then(()=>navigator.serviceWorker.ready).then(setRegistration).catch(()=>setError('Не удалось подготовить уведомления. Откройте сайт ещё раз.'))
  },[supported,install])
  async function toggle(){
    if(!registration||!settings.data?.key)return
    setBusy(true);setError('')
    try{
      if(settings.data.enabled){
        await api('/push',{method:'DELETE'})
        await (await registration.pushManager.getSubscription())?.unsubscribe()
      }else{
        if(await Notification.requestPermission()!=='granted')throw new Error('Разрешите уведомления CampusFlow в настройках устройства.')
        const key=Uint8Array.from(atob(settings.data.key.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0))
        let subscription=await registration.pushManager.getSubscription()
        const previous=subscription?.options.applicationServerKey
        if(subscription&&previous&&!key.every((byte,index)=>byte===new Uint8Array(previous)[index])){
          await subscription.unsubscribe()
          subscription=null
        }
        subscription??=await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:key})
        await api('/push',json(subscription.toJSON(),'PUT'))
      }
      refresh(n=>n+1)
    }catch(e){setError(e instanceof Error?e.message:message(e))}finally{setBusy(false)}
  }
  return <section className="device-alerts"><h3>На этом устройстве</h3>
    <p>{install?'В Safari нажмите «Поделиться» → «На экран Домой». Откройте CampusFlow с новой иконки и включите уведомления (iOS 16.4 и новее).':
      !supported?'Для уведомлений откройте сайт по HTTPS в браузере с поддержкой Web Push.':
      settings.error||(!settings.data?'Проверяем подключение…':!settings.data.key?'Системная доставка пока не настроена на сервере.':
      settings.data.enabled?'Включены уведомления о ваших бронях.':'Получайте напоминания и предложения из листа ожидания, даже когда сайт закрыт. Доставку выполняет служба уведомлений браузера.')}</p>
    {!install&&supported&&settings.data?.key&&<button className="secondary" disabled={busy||!registration} onClick={()=>void toggle()}>{busy?'Сохраняем…':settings.data.enabled?'Отключить на устройстве':'Включить уведомления'}</button>}
    {error&&<p role="alert">{error}</p>}
  </section>
}
