import type { Metadata } from 'next'
import { Toaster } from 'sonner'

import { ThemeProvider } from '@/components/theme-provider'
import './globals.css'

export const metadata: Metadata = {
  title: 'JobPilot - X, LinkedIn & Naukri job agent',
  description:
    'An agent that finds fresh jobs on X, LinkedIn and Naukri, writes outreach, and applies on Naukri with your review.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className="h-full">
      <body className="flex min-h-full flex-col">
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem={false}
          disableTransitionOnChange
        >
          {children}
          <Toaster position="bottom-right" theme="dark" richColors />
        </ThemeProvider>
      </body>
    </html>
  )
}
