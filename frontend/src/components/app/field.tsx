import * as React from "react"
import { cn } from "cn"
import { Label } from "@/components/ui/label"

// 「标签 + 控件」布局，替代原全局 label / .control-row / .check-row 样式。
function Field({
  label,
  labelClassName,
  className,
  children,
  ...props
}: React.ComponentProps<"div"> & {
  label: React.ReactNode
  labelClassName?: string
}) {
  return (
    <div className={cn("min-w-0", className)} {...props}>
      <Label className={cn("mb-1.5 block text-xs font-bold text-slate-700", labelClassName)}>
        {label}
      </Label>
      {children}
    </div>
  )
}

function FieldRow({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("grid gap-2.5", className)} {...props} />
}

function CheckRow({ className, ...props }: React.ComponentProps<"label">) {
  return (
    <label
      className={cn(
        "flex min-h-9 items-center gap-2 rounded-md border bg-card px-2.5 py-2 text-[13px] font-semibold",
        className
      )}
      {...props}
    />
  )
}

// 带「已忽略」角标的参数标签，替代 .param-ignored / .ignored-tag。
function IgnoredTag({ children }: { children: React.ReactNode }) {
  return (
    <em className="ml-1.5 rounded border border-border bg-secondary px-1 align-[1px] text-[10px] font-semibold not-italic text-muted-foreground">
      {children}
    </em>
  )
}

export { Field, FieldRow, CheckRow, IgnoredTag }
