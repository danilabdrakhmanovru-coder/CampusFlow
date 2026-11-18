import { expect, test, type Page } from '@playwright/test'

const password = {dean:'DeanFlow26!',admin:'AdminFlow26!',teacher:'TeachFlow26!',student:'StudyFlow26!'}
async function openManualLogin(page:Page){
  await expect(page.getByRole('heading',{name:'Вход в CampusFlow'})).toBeVisible()
  const summary=page.locator('details.manual-login:not([open]) > summary')
  if(await summary.isVisible())await summary.click()
}
async function submitCredentials(page:Page,role:keyof typeof password) {
  await openManualLogin(page)
  await page.getByLabel('Логин').fill(role)
  await page.getByLabel('Пароль',{exact:true}).fill(password[role])
  await page.getByRole('button',{name:'Войти',exact:true}).click()
}
async function acceptDocuments(page:Page) {
  const consent=page.getByRole('dialog',{name:'Документы и согласие'})
  await consent.getByRole('checkbox',{name:/ознакомился/i}).check()
  await consent.getByRole('checkbox',{name:/Даю согласие/}).check()
  await consent.getByRole('button',{name:'Принять и продолжить'}).click()
}
async function signIn(page:Page, role:keyof typeof password) {
  await page.goto('/login')
  await submitCredentials(page,role)
  const consent=page.getByRole('dialog',{name:'Документы и согласие'})
  const heading=page.getByRole('heading',{name:role==='dean'?'Рейтинг групп':role==='admin'?'Управление кампусом':role==='teacher'?'Бронирование':'Свободные аудитории',exact:true})
  await expect(consent.or(heading)).toBeVisible()
  if(await consent.isVisible())await acceptDocuments(page)
  await expect(page).toHaveURL(new RegExp(role==='dean'?'/windows$':role==='admin'?'/admin$':role==='teacher'?'/booking$':'/rooms$'))
  if(role==='student')await page.getByRole('navigation',{name:'Разделы',exact:true}).getByRole('link',{name:'Расписание',exact:true}).click()
}
function campusDay(offset:number) {
  return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Yekaterinburg'}).format(
    Date.now()+86400000*offset,
  )
}
async function choose(page:Page) {
  await page.getByRole('navigation',{name:'Разделы',exact:true}).getByRole('link',{name:'Бронирование',exact:true}).click()
  await page.getByRole('radio',{name:'Компьютерный класс'}).check()
  await page.getByText('Оборудование и доступность',{exact:true}).click()
  await page.getByRole('button',{name:/Компьютеры/}).click()
  await page.locator('input[type=date]').fill(campusDay(2))
  await page.getByRole('button',{name:'Подобрать',exact:true}).click()
  await page.getByRole('button',{name:'Выбрать',exact:true}).first().click()
}

test('Сейчас и План доступны студенту на ширине 360',async({page})=>{
  await signIn(page,'student')
  await page.getByRole('navigation',{name:'Разделы',exact:true}).getByRole('link',{name:'Аудитории',exact:true}).click()
  await page.getByRole('button',{name:'Корпус 7'}).click()
  await expect(page.getByRole('button',{name:'Корпус 7'})).toHaveAttribute('aria-pressed','true')
  await expect(page.getByRole('navigation',{name:'Разделы',exact:true}).getByRole('link',{name:'Бронирование',exact:true})).toHaveCount(0)
  const nav = page.getByRole('navigation',{name:'Разделы'})
  const visibleButtons = await nav.getByRole('link').all()
  const positions = await Promise.all(visibleButtons.map(button=>button.boundingBox()))
  expect(new Set(positions.map(position=>position?.y)).size).toBe(1)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBe(360)
  await page.getByRole('link',{name:'План занятости',exact:true}).click()
  await expect(page.getByRole('slider')).toBeVisible()
  await page.getByRole('slider').focus()
  await page.keyboard.press('End')
  await expect(page.getByRole('slider')).toHaveAttribute('aria-valuetext','22:00')
  await page.keyboard.press('Home')
  await expect(page.getByRole('slider')).toHaveAttribute('aria-valuetext','08:00')
  const room = page.locator('.timeline .room-link').first()
  await room.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog',{name:/Аудитория/})).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(room).toBeFocused()
  await page.getByRole('slider').focus()
  await expect(page.getByRole('slider')).toHaveAttribute('aria-valuetext','08:00')
})

test('Конфликт двух аккаунтов, удержание, талон и отмена',async({page,browser})=>{
  const otherContext=await browser.newContext({viewport:{width:360,height:800}})
  try {
    const other=await otherContext.newPage()
    await signIn(page,'teacher')
    await signIn(other,'admin')
    await choose(page)
    await choose(other)
    await page.getByRole('button',{name:'Удержать на 5 минут'}).click()
    await expect(page.getByRole('timer')).toBeVisible()
    await other.getByRole('button',{name:'Удержать на 5 минут'}).click()
    await expect(other.getByRole('alert')).toContainText('Интервал уже занят')
    await page.getByLabel('Название брони').fill('Синтетическая бронь E2E')
    await page.getByRole('button',{name:'Подтвердить',exact:true}).click()
    await expect(page.getByText('Бронь подтверждена.')).toBeVisible()
    const row=page.getByRole('listitem').filter({hasText:'Синтетическая бронь E2E'})
    await row.getByRole('button',{name:'Талон'}).click()
    await expect(page.getByRole('img',{name:/QR талона/})).toBeVisible()
    await page.getByRole('button',{name:'Закрыть талон'}).click()
    await row.getByRole('button',{name:'Отменить'}).click()
    await page.getByRole('button',{name:'Подтвердить отмену'}).click()
    await expect(row).toHaveCount(0)
  } finally {await otherContext.close()}
})

test('Диспетчер видит предпросмотр импорта',async({page})=>{
  await signIn(page,'admin')
  await page.getByRole('main').getByRole('link',{name:'К импорту расписания'}).click()
  const day=campusDay(2)
  await page.getByLabel('С',{exact:true}).fill(day)
  await page.getByLabel('По',{exact:true}).fill(day)
  await page.getByLabel(/Файл CSV/).setInputFiles({
    name:'e2e.csv',mimeType:'text/csv',buffer:Buffer.from(
      'start,end,building,room,subject\n'+day+'T22:00:00+05:00,'+day+'T22:30:00+05:00,6,DEMO-01,Синтетическая пара\n',
    ),
  })
  await page.getByRole('button',{name:'Предпросмотр'}).click()
  await expect(page.getByText(/Синтетическая пара/)).toBeVisible()
})

test('Маршруты, справка и права студента',async({page})=>{
  await page.goto('/help')
  await expect(page.getByRole('heading',{name:'Помощь',exact:true})).toBeVisible()
  await expect(page.getByRole('contentinfo').getByRole('link',{name:'Политика обработки данных'})).toBeVisible()
  await page.goto('/missing-cf')
  await expect(page.getByRole('heading',{name:/404/})).toBeVisible()
  await signIn(page,'student')
  await expect(page.getByRole('navigation',{name:'Разделы'}).getByRole('link')).toHaveCount(2)
  await expect(page.getByRole('button',{name:'Уведомления',exact:true})).toHaveCount(0)
  await page.getByLabel('Меню профиля').click()
  await page.getByRole('banner').getByRole('link',{name:'Помощь',exact:true}).click()
  await expect(page.getByRole('heading',{name:'Помощь',exact:true})).toBeVisible()
  await expect(page.getByRole('heading',{name:'Клавиатура'})).toHaveCount(0)
  await page.goBack()
  await page.setViewportSize({width:1280,height:900})
  await page.keyboard.press('Control+k')
  await page.getByRole('searchbox').fill('DEMO-01')
  await page.getByRole('dialog').getByRole('link',{name:'Аудитория DEMO-01 — корпус 6'}).click()
  await expect(page).toHaveURL(/rooms\?view=plan/)
  await expect(page.getByRole('dialog',{name:/Аудитория DEMO-01/})).toBeVisible()
  await page.keyboard.press('Escape')
  await page.goBack()
  await expect(page).toHaveURL(/schedule$/)
  await page.reload()
  await expect(page.getByRole('heading',{name:'Расписание',exact:true})).toBeVisible()
  await page.goto('/admin/users')
  await expect(page.getByRole('heading',{name:/доступ/i})).toBeVisible()
})


test('Навигация диспетчера и локальные шрифты в обеих темах',async({page})=>{
  await page.setViewportSize({width:1280,height:900})
  await signIn(page,'admin')
  const nav=page.getByRole('navigation',{name:'Разделы',exact:true})
  const links=await nav.getByRole('link').all()
  expect(links).toHaveLength(5)
  const boxes=await Promise.all(links.map(link=>link.boundingBox()))
  expect(new Set(boxes.map(box=>box?.y)).size).toBe(1)
  const headerBox=await page.getByRole('banner').boundingBox()
  expect(headerBox?.height).toBeLessThan(84)

  const fontRequests=await page.evaluate(async()=>{
    await document.fonts.ready
    return performance.getEntriesByType('resource')
      .filter(resource=>resource.name.endsWith('.woff2'))
      .map(resource=>new URL(resource.name))
      .map(url=>({local:url.origin===location.origin,path:url.pathname}))
  })
  expect(fontRequests.some(font=>font.local&&font.path.includes('golos-text-cyrillic'))).toBeTruthy()
  expect(fontRequests.some(font=>font.local&&font.path.includes('unbounded-cyrillic'))).toBeTruthy()
  expect(fontRequests.every(font=>font.local)).toBeTruthy()

  await page.goto('/profile?tab=interface')
  await page.getByLabel('Цветовая тема').selectOption('dark')
  await expect(page.locator('body')).toHaveCSS('background-color','rgb(15, 14, 20)')
  await page.getByLabel('Цветовая тема').selectOption('light')
  await expect(page.locator('body')).toHaveCSS('background-color','rgb(255, 255, 255)')
  await page.setViewportSize({width:360,height:800})
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBe(360)
})


test('Согласие после входа, отказ, история и отзыв',async({page})=>{
  await signIn(page,'student')
  await page.goto('/profile?tab=privacy')
  await expect(page.getByRole('heading',{name:'История согласий'})).toBeVisible()
  await expect(page.getByText('Действует',{exact:true})).toBeVisible()
  await page.getByRole('button',{name:'Отозвать согласие',exact:true}).click()
  await page.getByRole('button',{name:'Отозвать и выйти',exact:true}).click()
  await expect(page).toHaveURL(/login$/)
  await expect(page.getByRole('checkbox')).toHaveCount(0)
  await openManualLogin(page)
  await page.getByRole('button',{name:'Показать пароль'}).click()
  await expect(page.getByLabel('Пароль',{exact:true})).toHaveAttribute('type','text')
  await page.getByRole('button',{name:'Не помню пароль'}).click()
  await expect(page.getByRole('link',{name:'Контакты и помощь'})).toBeVisible()
  await submitCredentials(page,'student')
  const gate=page.getByRole('dialog',{name:'Документы и согласие'})
  await expect(gate).toBeVisible()
  await expect(gate.getByRole('checkbox').first()).not.toBeChecked()
  const second=gate.getByRole('checkbox',{name:/Даю согласие/})
  await expect(second).not.toBeChecked()
  expect((await page.request.get('/api/v1/rooms')).status()).toBe(401)
  await page.reload()
  await gate.getByRole('button',{name:'Отказаться и выйти'}).click()
  await expect(gate).toHaveCount(0)
  await submitCredentials(page,'student')
  await acceptDocuments(page)
  await expect(page).toHaveURL(/rooms$/)
  await page.goto('/profile?tab=privacy')
  await expect(page.getByText('Отозвано',{exact:true}).first()).toBeVisible()
  await page.getByLabel('Меню профиля').click()
  await page.getByRole('button',{name:'Выйти',exact:true}).click()
  await submitCredentials(page,'student')
  await expect(page).toHaveURL(/rooms$/)
  await expect(gate).toHaveCount(0)
})

test('Публичный документ, оглавление, PDF и уведомление о cookie',async({page})=>{
  await page.goto('/legal/privacy')
  await expect(page.getByRole('heading',{name:'Политика обработки персональных данных'})).toBeVisible()
  const toc=page.getByRole('navigation',{name:'Оглавление'})
  await toc.getByRole('link',{name:'Сроки хранения'}).click()
  await expect(page).toHaveURL(/#section-4$/)
  const download=page.waitForEvent('download')
  await page.getByRole('link',{name:'Скачать PDF'}).click()
  expect((await download).suggestedFilename()).toBe('campusflow-privacy.pdf')
  await page.evaluate(()=>{window.print=()=>document.body.setAttribute('data-print-called','true')})
  await page.getByRole('button',{name:'Печать'}).click()
  await expect(page.locator('body')).toHaveAttribute('data-print-called','true')
  await page.getByRole('button',{name:'Понятно',exact:true}).click()
  await page.reload()
  await expect(page.getByRole('button',{name:'Понятно',exact:true})).toHaveCount(0)
})

test('Студент сохраняет группу, смотрит неделю и ищет аудиторию в окно',async({page})=>{
  await signIn(page,'student')
  await page.goto('/profile')
  await page.getByLabel('Моя группа').selectOption('ДЕМО-61')
  await page.getByRole('button',{name:'Сохранить',exact:true}).click()
  await expect(page.getByText('Настройки сохранены.')).toBeVisible()
  await page.goto('/schedule')
  await page.getByRole('button',{name:'Следующая неделя'}).click()
  await page.getByRole('button',{name:'Неделя',exact:true}).click()
  await expect(page.getByRole('table',{name:'Расписание на неделю'})).toBeVisible()
  await expect(page.getByText('Дискретная математика',{exact:true}).first()).toBeVisible()
  await expect(page.getByRole('button',{name:'Скачать PDF',exact:true})).toBeHidden()
  await page.getByText('Скачать, распечатать или поделиться',{exact:true}).click()
  for(const [label,extension] of [['Скачать PDF','pdf'],['Скачать Word','docx']]){
    const download=page.waitForEvent('download')
    await page.getByRole('button',{name:label,exact:true}).click()
    expect((await download).suggestedFilename()).toBe('campusflow-schedule.'+extension)
  }
  await page.getByRole('link',{name:'Где посидеть'}).first().click()
  await expect(page.getByText(/Поиск на время окна/)).toBeVisible()
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBe(360)
})

test('Смена пароля в кабинете завершает сеанс',async({page})=>{
  await signIn(page,'admin')
  const auth=await page.request.post('/api/v1/auth/refresh')
  const admin=await auth.json()
  const login='test-profile-'+Date.now()
  const headers={Authorization:'Bearer '+admin.access_token}
  expect((await page.request.post('/api/v1/admin/users',{headers,data:{login,password:'InitialLocal42!',role:'student'}})).status()).toBe(201)
  await page.getByLabel('Меню профиля').click()
  await page.getByRole('button',{name:'Выйти',exact:true}).click()
  await openManualLogin(page)
  await page.getByLabel('Логин').fill(login)
  await page.getByLabel('Пароль',{exact:true}).fill('InitialLocal42!')
  await page.getByRole('button',{name:'Войти',exact:true}).click()
  await acceptDocuments(page)
  await expect(page).toHaveURL(/rooms$/)
  await page.goto('/profile?tab=security')
  await expect(page.getByText('Текущий сеанс',{exact:true})).toBeVisible()
  await page.getByLabel('Текущий пароль').fill('InitialLocal42!')
  await page.getByLabel('Новый пароль').fill('ChangedLocal426!')
  await page.getByRole('button',{name:'Сменить пароль',exact:true}).click()
  await expect(page).toHaveURL(/login$/)
  await openManualLogin(page)
  await page.getByLabel('Логин').fill(login)
  await page.getByLabel('Пароль',{exact:true}).fill('ChangedLocal426!')
  await page.getByRole('button',{name:'Войти',exact:true}).click()
  await expect(page).toHaveURL(/rooms$/)
  await expect(page.getByRole('dialog',{name:'Документы и согласие'})).toHaveCount(0)
})

test('Диспетчер находит и применяет перенос для группы',async({page})=>{
  await signIn(page,'admin')
  const auth=await page.request.post('/api/v1/auth/refresh')
  const admin=await auth.json()
  const headers={Authorization:'Bearer '+admin.access_token}
  const building='T'+String(Date.now()).slice(-8)
  const group='ТЕСТ-'+building
  const day=campusDay(4)
  expect((await page.request.post('/api/v1/admin/rooms',{headers,data:{building,code:'QA101',kind:'seminar',capacity:24,equipment:{}}})).status()).toBe(201)
  expect((await page.request.put('/api/v1/admin/group-sizes',{headers,data:{sizes:{[group]:18}}})).status()).toBe(200)
  const csv='start,end,building,room,subject,groups,teachers\n'+[
    ['08:00','09:20','Первая пара'],['15:10','16:30','Вторая пара'],['16:45','18:05','Третья пара'],
  ].map(([a,b,title])=>day+'T'+a+':00+05:00,'+day+'T'+b+':00+05:00,'+building+',QA101,'+title+','+group+',synthetic-'+building).join('\n')
  const imported=await page.request.post('/api/v1/admin/imports',{headers,multipart:{
    scope:building,date_from:day,date_to:day,complete:'true',file:{name:'test-move.csv',mimeType:'text/csv',buffer:Buffer.from(csv)},
  }})
  expect(imported.status(),await imported.text()).toBe(201)
  const batch=await imported.json()
  expect((await page.request.post('/api/v1/admin/imports/'+batch.id+'/publish',{headers})).status()).toBe(200)
  await page.context().clearCookies()
  await signIn(page,'dean')
  const session=await (await page.request.post('/api/v1/auth/refresh')).json()
  expect((await page.request.get('/api/v1/admin/users',{headers:{Authorization:'Bearer '+session.access_token}})).status()).toBe(403)
  await page.goto('/windows?group='+encodeURIComponent(group)+'&day='+day)
  await page.getByLabel('С',{exact:true}).fill(day)
  await page.getByLabel('По',{exact:true}).fill(day)
  await page.getByRole('button',{name:'Найти исправления',exact:true}).click()
  await page.getByRole('button',{name:'Принять',exact:true}).first().click({timeout:40000})
  await page.getByRole('button',{name:'Применить перенос',exact:true}).click()
  await expect(page.getByText('Перенос применён.',{exact:true})).toBeVisible()
})

test('Основные экраны вмещаются на 360 px и на десктопе',async({page})=>{
  const errors:string[]=[]
  page.on('pageerror',error=>errors.push(error.message))
  await signIn(page,'admin')
  const paths=['/schedule?scope=group&entity_id='+encodeURIComponent('ДЕМО-61'),'/rooms','/rooms?view=plan','/booking',
    '/windows','/profile','/profile?tab=security','/profile?tab=privacy','/admin','/admin/imports','/admin/rooms','/admin/groups',
    '/admin/users','/admin/moves','/admin/walk','/admin/audit','/admin/settings','/admin/model','/admin/analytics',
    '/help','/legal/privacy','/legal/consent','/legal/cookies']
  for(const width of [360,1280]){
    await page.setViewportSize({width,height:850})
    for(const path of paths){
      await page.goto(path)
      await expect(page.getByRole('main').getByRole('heading',{level:1}).first()).toBeVisible()
      await expect(page.getByRole('main').getByText('Загрузка…',{exact:true})).toHaveCount(0)
      expect(await page.evaluate(()=>document.documentElement.scrollWidth),path).toBe(width)
    }
  }
  expect(errors).toEqual([])
})

test('Подбор без группы показывает другие аудитории и объясняет, чего не хватает',async({page})=>{
  await signIn(page,'teacher')
  await page.getByRole('navigation',{name:'Разделы',exact:true}).getByRole('link',{name:'Бронирование',exact:true}).click()
  const groupSettings=page.getByText('Учесть расписание группы',{exact:true})
  await expect(page.getByRole('combobox',{name:'Группа',exact:true})).toBeHidden()
  await page.getByRole('combobox',{name:'Корпус',exact:true}).selectOption('6')
  await page.getByRole('radio',{name:'Лекционная'}).check()
  await expect(page.getByRole('button',{name:/Компьютеры/})).toBeHidden()
  await page.getByText('Оборудование и доступность',{exact:true}).click()
  await page.getByRole('button',{name:/Компьютеры/}).click()
  await page.locator('input[type=date]').fill(campusDay(2))
  const searched=page.waitForResponse(response=>response.url().includes('/slots/recommendations?')&&
    new URL(response.url()).searchParams.get('kind')==='lecture'&&new URL(response.url()).searchParams.get('equipment')==='pc')
  await page.getByRole('button',{name:'Подобрать',exact:true}).click()
  const request=await searched
  expect(new URL(request.url()).searchParams.has('group')).toBe(false)
  const results=page.getByRole('region',{name:'Результаты подбора'})
  await expect(results.getByRole('heading',{name:'Другие аудитории'})).toBeVisible()
  await expect(results.getByText('Нет компьютеров.',{exact:true}).first()).toBeVisible()
  await expect(results.getByRole('button',{name:'Выбрать',exact:true})).toHaveCount(0)
  await results.getByRole('button',{name:'Выбрать эту аудиторию'}).first().click()
  await expect(page.getByRole('heading',{name:'Выбранный интервал'})).toBeVisible()
  await page.getByRole('button',{name:'Удержать на 5 минут'}).click()
  await expect(page.getByRole('timer')).toBeVisible()
  await page.getByRole('button',{name:'Отпустить',exact:true}).click()
  await page.getByRole('button',{name:'Изменить параметры'}).click()
  await groupSettings.click()
  await expect(page.getByRole('combobox',{name:'Группа',exact:true})).toHaveValue('')
})

test('Демо-вход ведёт преподавателя сразу к подбору аудитории',async({page})=>{
  await page.goto('/')
  await page.getByRole('button',{name:/Забронировать аудиторию/}).click()
  const gate=page.getByRole('dialog',{name:'Документы и согласие'})
  await expect(gate.or(page.getByRole('heading',{name:'Бронирование',exact:true}))).toBeVisible()
  if(await gate.isVisible())await acceptDocuments(page)
  await expect(page).toHaveURL(/booking\?day=/)
  await page.getByRole('button',{name:'Подобрать',exact:true}).click()
  await expect(page.getByRole('heading',{name:'Подходящие аудитории'})).toBeFocused()
  await page.getByRole('button',{name:'Выбрать',exact:true}).first().click()
  await expect(page.getByRole('heading',{name:'Выбранный интервал'})).toBeFocused()
  await page.getByRole('button',{name:'Удержать на 5 минут'}).click()
  await expect(page.getByRole('heading',{name:'Подтверждение',exact:true})).toBeFocused()
  await page.getByRole('button',{name:'Отпустить',exact:true}).click()
  await expect(page.getByRole('timer')).toHaveCount(0)
})

test('Разбор окон выводится на странице группы',async({page})=>{
  await signIn(page,'admin')
  const day=campusDay(2)
  await page.goto('/windows?group='+encodeURIComponent('ДЕМО-61')+'&day='+day)
  await page.route('**/api/v1/analytics/groups/*/analysis',route=>{
    expect(route.request().postDataJSON()).toEqual(expect.objectContaining({minimum:40}))
    return route.fulfill({json:{summary:'Самые длинные окна в середине недели.',
      observations:['Окна повторяются.'],next_steps:['Проверьте пары до и после окна.']}})
  })
  await page.getByRole('button',{name:'Разобрать окна с ИИ'}).click()
  await expect(page.getByText('Самые длинные окна в середине недели.')).toBeVisible()
  await expect(page.getByRole('heading',{name:'Что проверить перед переносом'})).toBeVisible()
  await expect(page.getByRole('contentinfo').getByText(/Версия/)).toHaveCount(0)
})

test('Преподаватель видит свои занятия и бронирует аудиторию',async({page})=>{
  await signIn(page,'teacher')
  await expect(page.getByRole('navigation',{name:'Разделы',exact:true}).getByRole('link')).toHaveCount(2)
  await page.goto('/schedule')
  await expect(page.getByRole('link',{name:'Настроить дни без занятий'})).toBeVisible()
  for(const route of ['/windows','/admin']){
    await page.goto(route)
    await expect(page.getByRole('heading',{name:'Раздел недоступен'})).toBeVisible()
  }
})

test('Разбор корпуса сохраняет выбранную группу от расписания до ответа ИИ',async({page})=>{
  await signIn(page,'admin')
  await page.goto('/schedule?scope=building&entity_id=6&day='+campusDay(7))
  const section=page.getByRole('region',{name:'Как сократить окна'})
  const group=section.getByLabel('Группа для разбора')
  await expect(group).toHaveValue('')
  await section.getByRole('button',{name:'Разобрать окна и найти переносы'}).click()
  await expect(page).toHaveURL(/\/schedule\?scope=building/)
  await group.selectOption('ДЕМО-63')
  await section.getByRole('button',{name:'Разобрать окна и найти переносы'}).click()
  await expect(page.getByRole('heading',{name:'Группа ДЕМО-63',exact:true})).toBeVisible()
  const analysisPath='/analytics/groups/'+encodeURIComponent('ДЕМО-63')+'/analysis'
  await page.route('**/api/v1'+analysisPath,route=>route.fulfill({json:{summary:'Разбор выбранной группы.',observations:[],next_steps:[]}}))
  const request=page.waitForRequest(value=>new URL(value.url()).pathname.endsWith(analysisPath))
  await page.getByRole('button',{name:'Разобрать окна с ИИ'}).click()
  await request
  const analysis=page.getByRole('region',{name:'ИИ-анализ окон'})
  await expect(analysis.getByText(/Группа ДЕМО-63/)).toBeVisible()
  await expect(analysis.getByText('Разбор выбранной группы.')).toBeVisible()
})

test('Деканат открывает рейтинг из своего кабинета',async({page})=>{
  await signIn(page,'dean')
  await expect(page.getByRole('navigation',{name:'Разделы',exact:true}).getByRole('link')).toHaveCount(2)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBe(360)
  await expect(page.getByRole('heading',{name:'Рейтинг групп',exact:true})).toBeVisible()
  await expect(page.getByText(/Качество \d+\/100/).first()).toBeVisible()
})
test('Два участника передают освободившийся интервал через лист ожидания',async({page,browser})=>{
  test.setTimeout(150000)
  const context=await browser.newContext({viewport:{width:360,height:800}})
  const other=await context.newPage()
  const title='Показ ожидания '+Date.now()
  async function search(screen:Page){
    await screen.goto('/booking')
    await screen.getByRole('combobox',{name:'Корпус',exact:true}).selectOption('6')
    await screen.getByLabel('Человек',{exact:true}).fill('18')
    await screen.getByLabel('Дата',{exact:true}).fill(campusDay(3))
    await screen.getByLabel('Своё время',{exact:true}).fill('19:00')
    await screen.getByLabel('Длительность в минутах').fill('30')
    await screen.getByRole('button',{name:'Подобрать',exact:true}).click()
  }
  try{
    await signIn(page,'admin')
    await signIn(other,'teacher')
    await search(page)
    await page.getByRole('button',{name:'Выбрать',exact:true}).first().click()
    await page.getByRole('button',{name:'Удержать на 5 минут'}).click()
    await page.getByLabel('Название брони').fill(title)
    await page.getByRole('button',{name:'Подтвердить',exact:true}).click()
    await search(other)
    await other.getByRole('button',{name:'Ждать освобождения',exact:true}).first().click()
    await expect(other.getByRole('heading',{name:'Ждать освобождения'})).toBeVisible()
    await page.getByRole('listitem').filter({hasText:title}).getByRole('button',{name:'Отменить',exact:true}).click()
    await page.getByRole('button',{name:'Подтвердить отмену'}).click()
    await other.getByRole('button',{name:'Открыть удержание'}).first().click({timeout:95000})
    await expect(other.getByRole('timer')).toBeVisible()
    expect(await other.evaluate(()=>document.documentElement.scrollWidth)).toBe(360)
    await other.getByRole('button',{name:'Отпустить',exact:true}).click()
  }finally{await context.close()}
})
