import { Suspense, type ReactNode } from 'react'

import { AppSidebar, MobileNav } from '@/components/app-sidebar'
import { WorkspaceGuard } from '@/components/workspace-guard'

export default function WorkspaceLayout({ children }: { children: ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 px-6 py-10">
          <div className="h-8 w-48 animate-pulse rounded-md bg-muted" />
          <div className="h-64 w-full animate-pulse rounded-xl bg-muted" />
        </div>
      }
    >
      <WorkspaceGuard>
        <div className="min-h-screen">
          <AppSidebar />
          <div className="md:pl-64">
            <MobileNav />
            <div className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6">{children}</div>
          </div>
        </div>
      </WorkspaceGuard>
    </Suspense>
  )
}
