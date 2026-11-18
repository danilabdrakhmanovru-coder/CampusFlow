import { useEffect, useState } from 'react'
import { api, Room } from './api'

export const kinds: Record<string, string> = { lecture:'Лекционная',computer:'Компьютерный класс',laboratory:'Лаборатория',seminar:'Семинарская' }
export const roles = { student:'Студент', teacher:'Преподаватель', dean:'Сотрудник деканата', admin:'Администратор' }
export let campus = 'Asia/Yekaterinburg'
export let fmt = new Intl.DateTimeFormat('ru-RU',{timeZone:campus,hour:'2-digit',minute:'2-digit'})
export let dayFmt = new Intl.DateTimeFormat('sv-SE',{timeZone:campus,year:'numeric',month:'2-digit',day:'2-digit'})
export let bell: [number,number][] = [[480,560],[575,655],[695,775],[790,870],[910,990],[1005,1085],[1100,1180],[1195,1275],[1285,1365]]
export function configureCampus(timezone:string, periods:[number,number][]){
  if(campus===timezone&&bell===periods)return
  campus=timezone;bell=periods
  fmt=new Intl.DateTimeFormat('ru-RU',{timeZone:campus,hour:'2-digit',minute:'2-digit'})
  dayFmt=new Intl.DateTimeFormat('sv-SE',{timeZone:campus,year:'numeric',month:'2-digit',day:'2-digit'})
}
export function campusInstant(day:string, minute:number) {
  const local=Date.parse(day+'T00:00:00Z')+minute*60000
  const offset=new Intl.DateTimeFormat('en-US',{timeZone:campus,timeZoneName:'longOffset'})
  let result=local
  for(let pass=0;pass<2;pass++){
    const zone=offset.formatToParts(result).find(part=>part.type==='timeZoneName')?.value
    const match=zone?.match(/GMT([+-])(\d{2}):(\d{2})/)
    result=local-(match?(match[1]==='-'?-1:1)*(Number(match[2])*60+Number(match[3]))*60000:0)
  }
  return new Date(result)
}
export const today = () => dayFmt.format(Date.now())
export const clock = (value:string) => fmt.format(new Date(value))
export const options = Object.entries(kinds).map(([value,label]) => ({value,label}))
export const message = (error:unknown) => error instanceof Error ? error.message : 'Произошла ошибка'
export const params = (data:Record<string,string>) => new URLSearchParams(data).toString()

export function useLoad<T>(load:()=>Promise<T>, key:string, keepKey?:string) {
  const [state,setState] = useState<{ key:string; keepKey?:string; data?:T; error?:string }>({key:''})
  useEffect(() => {
    let live = true
    setState(previous => ({key, keepKey, data: keepKey && keepKey===previous.keepKey ? previous.data : undefined}))
    load().then(data=> { if(live) setState({key,keepKey,data}) }).catch(error=> { if(live) setState({key,keepKey,error:message(error)}) })
    return () => { live = false }
  },[key])
  return state.key === key ? state : {key, data: keepKey && keepKey===state.keepKey ? state.data : undefined}
}
export async function allRooms() {
  const rooms: Room[] = []
  for (let offset=0; ; offset+=100) {
    const next = await api<Room[]>('/rooms?offset='+offset)
    rooms.push(...next)
    if (next.length < 100) return rooms
  }
}
export function Status({pending,error,empty}:{pending?:boolean;error?:string;empty?:string}) {
  if (error) return <p className="feedback error" role="alert">{error}</p>
  if (pending) return <div className="skeleton" role="status"><span className="visually-hidden">Загрузка…</span><i aria-hidden="true"/><i aria-hidden="true"/><i aria-hidden="true"/></div>
  if (empty) return <p className="feedback" role="status">{empty}</p>
  return null
}
export function Toast({text,dismiss}:{text:string;dismiss:()=>void}) {
  useEffect(()=>{
    if(!text)return
    const timer=window.setTimeout(dismiss,8000)
    return ()=>window.clearTimeout(timer)
  },[text,dismiss])
  return text?<aside className="feedback toast"><p role="status">{text}</p>
    <button type="button" className="secondary" aria-label="Закрыть сообщение" onClick={dismiss}>×</button>
  </aside>:null
}

export function Heading({title,description}:{title:string;description?:string}) {
  return <div className="heading"><h1>{title}</h1>{description&&<p>{description}</p>}</div>
}

