import Link from 'next/link'
import { RadarIcon } from 'lucide-react'

export function Logo({ href = '/dashboard' }: { href?: string }) {
  return (
    <Link href={href} className="flex items-center gap-2 text-sm font-semibold">
      <span className="grid size-7 place-items-center rounded-lg bg-foreground text-background">
        <RadarIcon className="size-4" />
      </span>
      <span>JobPilot</span>
    </Link>
  )
}
