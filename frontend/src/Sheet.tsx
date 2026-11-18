import { ReactNode, useEffect, useRef, useState } from 'react'

export function Sheet({ label, onClose, children, className = '' }: {
  label: string; onClose: () => void; children: ReactNode; className?: string
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    const opener = document.activeElement
    dialog.showModal()
    return () => {
      dialog.close()
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus()
    }
  }, [])
  return <dialog ref={ref} className={'sheet ' + className} aria-label={label} onCancel={event => {
    event.preventDefault()
    onClose()
  }}>{children}</dialog>
}
type Decision = {title:string;description:string;label:string;apply:()=>void}

export function useConfirmation() {
  const [decision,ask] = useState<Decision>()
  const close = () => ask(undefined)
  const dialog = decision && <Sheet label={decision.title} onClose={close}>
    <h2>{decision.title}</h2>
    <p>{decision.description}</p>
    <div className="actions">
      <button autoFocus className="secondary" onClick={close}>Назад</button>
      <button onClick={()=>{close();decision.apply()}}>{decision.label}</button>
    </div>
  </Sheet>
  return {ask,dialog}
}
