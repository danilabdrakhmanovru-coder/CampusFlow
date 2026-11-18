const messages = {
  watch_hold: ['Аудитория освободилась', 'Откройте лист ожидания и подтвердите бронь.', 'watch'],
  booking_reminder: ['Скоро начало брони', 'Откройте талон и отметьте приход в аудиторию.', 'mine'],
  slot_freed: ['Аудитория освобождена', 'Бронь завершена. Подробности доступны в CampusFlow.', 'mine'],
  cancelled_by_admin: ['Бронь отменена', 'Посмотрите подробности и подберите другое время.', 'mine']
}
self.addEventListener('push', event => {
  let data = {}
  try { data = event.data.json() } catch {}
  const [title, text, view] = messages[data.kind] || ['CampusFlow', 'У вас новое уведомление.', 'mine']
  let body = text
  if (data.kind === 'watch_hold' && Number.isFinite(Date.parse(data.until))) {
    const end = new Date(data.until).toLocaleTimeString('ru-RU', {hour:'2-digit',minute:'2-digit'})
    body = 'Подтвердите бронь до ' + end + ' по времени устройства.'
  }
  event.waitUntil(self.registration.showNotification(title, {
    body, lang:'ru', icon:'/icon-192.png', tag:'campusflow-' + data.id, data:{view}
  }))
})
self.addEventListener('notificationclick', event => {
  event.notification.close()
  const path = '/booking?view=' + (event.notification.data?.view === 'watch' ? 'watch' : 'mine')
  event.waitUntil(clients.openWindow(path))
})
