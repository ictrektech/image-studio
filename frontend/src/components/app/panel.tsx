import * as React from "react"
import { cn } from "cn"
import { Card } from "@/components/ui/card"

// 统一面板容器：基于 Card 收敛原 .panel / .panel-heading / .panel-title 手写样式。
function Panel({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <Card
      className={cn(
        "gap-0 rounded-lg py-0 shadow-[0_6px_18px_rgba(15,23,42,0.035)]",
        className
      )}
      {...props}
    />
  )
}

function PanelHeading({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      className={cn("flex items-start justify-between gap-3", className)}
      {...props}
    />
  )
}

function PanelTitle({ className, ...props }: React.ComponentProps<"h2">) {
  return <h2 className={cn("text-[15px] font-bold", className)} {...props} />
}

export { Panel, PanelHeading, PanelTitle }
