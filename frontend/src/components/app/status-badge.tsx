import * as React from "react"
import { cn } from "cn"
import { Badge } from "@/components/ui/badge"

// job / model / Immich 上传状态 → 配色的统一映射（沿用原 pill 配色）。
const statusStyles = {
  running: "bg-sky-100 text-sky-800",
  queued: "bg-sky-100 text-sky-800",
  uploading: "bg-sky-100 text-sky-800",
  downloading: "bg-sky-100 text-sky-800",
  succeeded: "bg-green-100 text-green-900",
  ready: "bg-green-100 text-green-900",
  uploaded: "bg-green-100 text-green-900",
  duplicate: "bg-green-100 text-green-900",
  failed: "bg-red-100 text-red-900",
  missing: "bg-red-100 text-red-900",
  pending: "bg-orange-100 text-orange-900",
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
