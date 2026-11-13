'use client'

import { Fragment, useMemo } from 'react'

import { cn } from '@/lib/utils'

type Block =
  | { kind: 'paragraph'; text: string }
  | { kind: 'field'; label: string; value: string }
  | { kind: 'bullet'; text: string }

type Group =
  | { kind: 'paragraph'; text: string }
  | { kind: 'fields'; items: { label: string; value: string }[] }
  | { kind: 'bullets'; items: string[] }

const FIELD_RE = /^([A-Za-z][A-Za-z0-9 /&()'.-]{1,26}):\s*(.+)$/
const URL_RE = /(https?:\/\/[^\s]+)/g

function splitLinkParts(value: string): { text: string; href?: string }[] {
  const parts: { text: string; href?: string }[] = []
  let last = 0
  for (const match of value.matchAll(URL_RE)) {
    const index = match.index ?? 0
    if (index > last) parts.push({ text: value.slice(last, index) })
    parts.push({ text: match[0], href: match[0] })
    last = index + match[0].length
  }
  if (last < value.length) parts.push({ text: value.slice(last) })
  return parts.length ? parts : [{ text: value }]
}

function parsePost(text: string): Block[] {
  const lines = (text || '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)

  const blocks: Block[] = []
  for (const line of lines) {
    if (/^[-*•]\s+/.test(line)) {
      blocks.push({ kind: 'bullet', text: line.replace(/^[-*•]\s+/, '') })
      continue
    }

    const field = line.match(FIELD_RE)
    if (field && !/^https?$/i.test(field[1])) {
      blocks.push({ kind: 'field', label: field[1], value: field[2] })
      continue
    }

    blocks.push({ kind: 'paragraph', text: line })
  }

  return blocks
}

function groupBlocks(blocks: Block[]): Group[] {
  const groups: Group[] = []
  for (const block of blocks) {
    if (block.kind === 'field') {
      const last = groups[groups.length - 1]
      if (last?.kind === 'fields') {
        last.items.push({ label: block.label, value: block.value })
      } else {
        groups.push({
          kind: 'fields',
          items: [{ label: block.label, value: block.value }],
        })
      }
      continue
    }

    if (block.kind === 'bullet') {
      const last = groups[groups.length - 1]
      if (last?.kind === 'bullets') {
        last.items.push(block.text)
      } else {
        groups.push({ kind: 'bullets', items: [block.text] })
      }
      continue
    }

    groups.push({ kind: 'paragraph', text: block.text })
  }
  return groups
}

export function isLongPost(text: string): boolean {
  const blocks = parsePost(text)
  return blocks.length > 6 || (text || '').length > 420
}

function LinkText({ value }: { value: string }) {
  return (
    <>
      {splitLinkParts(value).map((part, index) =>
        part.href ? (
          <a
            key={index}
            href={part.href}
            target="_blank"
            rel="noreferrer"
            className="break-all text-sky-600 underline decoration-sky-500/40 underline-offset-2 hover:decoration-sky-500 dark:text-sky-400"
          >
            {part.text}
          </a>
        ) : (
          <Fragment key={index}>{part.text}</Fragment>
        ),
      )}
    </>
  )
}

export function PostBody({
  text,
  expanded,
  className,
}: {
  text: string
  expanded: boolean
  className?: string
}) {
  const groups = useMemo(() => groupBlocks(parsePost(text)), [text])
  if (!groups.length) return null

  const visible = expanded ? groups : groups.slice(0, 6)
  const hidden = groups.length - visible.length

  return (
    <div
      className={cn(
        'mt-3 rounded-lg border border-border/70 bg-muted/20 px-3.5 py-3',
        className,
      )}
    >
      <div className="flex flex-col gap-2">
        {visible.map((group, index) => {
          if (group.kind === 'paragraph') {
            return (
              <p
                key={index}
                className="text-sm leading-relaxed whitespace-pre-wrap break-words text-foreground/90"
              >
                <LinkText value={group.text} />
              </p>
            )
          }

          if (group.kind === 'fields') {
            return (
              <dl
                key={index}
                className="grid grid-cols-[104px_minmax(0,1fr)] gap-x-3 gap-y-1.5 sm:grid-cols-[132px_minmax(0,1fr)]"
              >
                {group.items.map((field, fieldIndex) => (
                  <div key={fieldIndex} className="contents">
                    <dt className="text-[11px] leading-5 font-medium tracking-wide text-muted-foreground uppercase">
                      {field.label}
                    </dt>
                    <dd className="text-sm leading-5 break-words text-foreground/90">
                      <LinkText value={field.value} />
                    </dd>
                  </div>
                ))}
              </dl>
            )
          }

          return (
            <ul key={index} className="flex flex-col gap-1">
              {group.items.map((item, itemIndex) => (
                <li
                  key={itemIndex}
                  className="flex gap-2 text-sm leading-relaxed text-foreground/90"
                >
                  <span className="mt-[7px] size-1 shrink-0 rounded-full bg-muted-foreground/60" />
                  <span className="break-words">
                    <LinkText value={item} />
                  </span>
                </li>
              ))}
            </ul>
          )
        })}
      </div>

      {hidden > 0 ? (
        <p className="mt-2 text-[11px] text-muted-foreground">+{hidden} more lines</p>
      ) : null}
    </div>
  )
}
