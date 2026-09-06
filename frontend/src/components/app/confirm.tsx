import { useState } from "react"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { messages } from "@/i18n"

type T = typeof messages["zh-CN"]

interface ConfirmRequest {
  title: string
  description?: string
  resolve: (ok: boolean) => void
}

// window.confirm 的 Promise 化替代：返回 confirm 函数和需要渲染在页面根部的 confirmElement。
export function useConfirm(t: T) {
  const [request, setRequest] = useState<ConfirmRequest | null>(null)

  const confirm = (title: string, description?: string) =>
    new Promise<boolean>(resolve => setRequest({ title, description, resolve }))

  const settle = (ok: boolean) => {
    request?.resolve(ok)
    setRequest(null)
  }

  const confirmElement = request ? (
    <AlertDialog open onOpenChange={open => !open && settle(false)}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{request.title}</AlertDialogTitle>
          {request.description && (
            <AlertDialogDescription>{request.description}</AlertDialogDescription>
          )}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={() => settle(false)}>{t.dialogCancel}</AlertDialogCancel>
          <AlertDialogAction onClick={() => settle(true)}>{t.dialogConfirm}</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  ) : null

  return { confirm, confirmElement }
}
