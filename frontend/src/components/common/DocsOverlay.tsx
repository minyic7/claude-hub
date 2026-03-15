import { useState, useEffect, useCallback } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { X, Copy, Check, BookOpen } from 'lucide-react'
import { docSections } from '../../docs'
import type { DocSection } from '../../docs'

interface DocsOverlayProps {
  open: boolean
  onClose: () => void
}

export function DocsOverlay({ open, onClose }: DocsOverlayProps) {
  const [activeSectionId, setActiveSectionId] = useState(docSections[0].id)
  const [activePageIndex, setActivePageIndex] = useState(0)
  const [copied, setCopied] = useState(false)

  const activeSection = docSections.find((s) => s.id === activeSectionId) ?? docSections[0]
  const activePage = activeSection.pages[activePageIndex] ?? activeSection.pages[0]

  // Escape key handler
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, onClose])

  // Reset state when closing
  useEffect(() => {
    if (!open) {
      setActiveSectionId(docSections[0].id)
      setActivePageIndex(0)
      setCopied(false)
    }
  }, [open])

  const handleSectionChange = useCallback((section: DocSection) => {
    setActiveSectionId(section.id)
    setActivePageIndex(0)
    setCopied(false)
  }, [])

  const handleCopyRaw = useCallback(async () => {
    await navigator.clipboard.writeText(activePage.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [activePage.content])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex bg-[var(--color-bg-primary)]">
      {/* Sidebar */}
      <nav className="flex w-52 shrink-0 flex-col border-r border-[var(--color-border)] bg-[var(--color-bg-panel)]">
        <div className="flex h-12 items-center gap-2 border-b border-[var(--color-border)] px-4">
          <BookOpen size={16} className="text-[var(--color-accent-blue)]" />
          <span className="text-sm font-bold text-[var(--color-text-primary)]">Docs</span>
        </div>
        <div className="flex-1 overflow-y-auto py-2">
          {docSections.map((section) => (
            <button
              key={section.id}
              onClick={() => handleSectionChange(section)}
              className={`w-full px-4 py-2 text-left text-xs font-medium transition-colors ${
                section.id === activeSectionId
                  ? 'bg-[var(--color-accent-blue)]/10 text-[var(--color-accent-blue)]'
                  : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)]'
              }`}
            >
              {section.title}
            </button>
          ))}
        </div>
      </nav>

      {/* Main content */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Header bar */}
        <div className="flex h-12 shrink-0 items-center justify-between border-b border-[var(--color-border)] bg-[var(--color-bg-panel)] px-4">
          <div className="flex items-center gap-1">
            {/* Page tabs */}
            {activeSection.pages.map((page, i) => (
              <button
                key={page.id}
                onClick={() => { setActivePageIndex(i); setCopied(false) }}
                className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                  i === activePageIndex
                    ? 'bg-[var(--color-accent-blue)]/10 text-[var(--color-accent-blue)]'
                    : 'text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]'
                }`}
              >
                {page.title}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleCopyRaw}
              className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)] transition-colors"
              title="Copy raw markdown"
            >
              {copied ? <Check size={14} className="text-[var(--color-accent-green)]" /> : <Copy size={14} />}
              {copied ? 'Copied!' : 'Copy Raw'}
            </button>
            <button
              onClick={onClose}
              className="rounded-md p-1.5 text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)] transition-colors"
              title="Close (Esc)"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Markdown content */}
        <div className="flex-1 overflow-y-auto">
          <div className="docs-markdown mx-auto max-w-3xl px-8 py-8">
            <Markdown remarkPlugins={[remarkGfm]}>{activePage.content}</Markdown>
          </div>
        </div>
      </div>
    </div>
  )
}
