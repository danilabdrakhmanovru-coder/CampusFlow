import { MouseEvent, ReactNode, useSyncExternalStore } from 'react'
import type { Role } from './api'

export const adminTabs = [
  ['imports','Импорт'], ['rooms','Аудитории'], ['users','Пользователи'],
  ['groups','Группы'], ['moves','Переносы'], ['walk','Время ходьбы'], ['audit','Журнал'],
  ['analytics','Аналитика'], ['model','О модели'], ['settings','Настройки'],
] as const

const locationKey = () => window.location.pathname + window.location.search
function subscribe(listener: () => void) {
  window.addEventListener('popstate', listener)
  return () => window.removeEventListener('popstate', listener)
}

export function useLocation() {
  return useSyncExternalStore(subscribe, locationKey)
}

export function go(href:string, replace = false) {
  if (locationKey() === href) return
  if (replace) history.replaceState(null,'',href)
  else history.pushState(null,'',href)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

export function Link({href,children,className,onNavigate,current}:{
  href:string; children:ReactNode; className?:string; onNavigate?:()=>void; current?:boolean
}) {
  function follow(event:MouseEvent<HTMLAnchorElement>) {
    if(event.defaultPrevented || event.button!==0 || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
    event.preventDefault()
    onNavigate?.()
    go(href)
  }
  return <a href={href} className={className} aria-current={current?'page':undefined} onClick={follow}>{children}</a>
}

export const landing = (role:Role) => role === 'dean' ? '/windows' : role === 'admin' ? '/admin' : role === 'teacher' ? '/booking' : '/rooms'
