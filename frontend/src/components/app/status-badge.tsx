import * as React from "react"
import { cn } from "cn"
import { Badge } from "@/components/ui/badge"

// job / model / Immich 上传状态 → 配色的统一映射（沿用原 pill 配色）。
const statusStyles = {
  running: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  queued: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  uploading: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  downloading: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  succeeded: "bg-green-100 text-green-900 dark:bg-green-950 dark:text-green-300",
  ready: "bg-green-100 text-green-900 dark:bg-green-950 dark:text-green-300",
  uploaded: "bg-green-100 text-green-900 dark:bg-green-950 dark:text-green-300",
  duplicate: "bg-green-100 text-green-900 dark:bg-green-950 dark:text-green-300",
  failed: "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-300",
  missing: "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-300",
  pending: "bg-orange-100 text-orange-900 dark:bg-orange-950 dark:text-orange-300",
} as const

type StatusKey = keyof typeof statusStyles

function StatusBadge({
  status,
  className,
  ...props
}: Omit<React.ComponentProps<typeof Badge>, "variant"> & {
  status: string
}) {
  return (
    <Badge
      variant="secondary"
      className={cn(
        "border-transparent font-semibold capitalize",
        statusStyles[status as StatusKey],
        className
      )}
      {...props}
    />
  )
}

export { StatusBadge }
