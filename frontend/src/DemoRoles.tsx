import {api,Role} from './api'
import {roles,Status,useLoad} from './common'

type Account={role:Role;name:string;login:string;password:string}
const action:Record<Role,string>={student:'Найти свободную аудиторию',teacher:'Забронировать аудиторию',dean:'Оценить расписание групп',admin:'Управлять кампусом'}
export function DemoRoles({pending,select}:{pending:boolean;select:(role:Role)=>void}){
  const data=useLoad(()=>api<Account[]>('/auth/demo/accounts'),'demo-accounts')
  return <section aria-label="Демонстрационные аккаунты">
    <p>Выберите роль для входа одним нажатием. Эти же логины и пароли подходят для ручного входа.</p>
    <Status pending={!data.data&&!data.error} error={data.error}/>
    <div className="demo-role-grid">{data.data?.map(account=><article className="demo-person" key={account.role}>
      <h3>{roles[account.role]}</h3><p>{account.name}</p>
      <dl><dt>Логин</dt><dd><code>{account.login}</code></dd><dt>Пароль</dt><dd><code>{account.password}</code></dd></dl>
      <button type="button" className="secondary" disabled={pending} onClick={()=>select(account.role)}>{action[account.role]}</button>
    </article>)}</div>
  </section>
}
