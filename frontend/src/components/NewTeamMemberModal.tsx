import { useState } from 'react'
import { X, UserPlus } from 'lucide-react'
import { cn } from '../lib/utils'
import { createEntity } from '../api/client'
import type {
  Entity,
  EntityAccentColor,
  EntityRelationshipType,
} from '../api/client'

interface NewTeamMemberModalProps {
  onClose: () => void
  onCreated: (entity: Entity) => void
}

const RELATIONSHIP_OPTIONS: {
  value: EntityRelationshipType
  label: string
}[] = [
  { value: 'direct_report', label: 'Direct Report' },
  { value: 'peer', label: 'Peer' },
  { value: 'skip_level', label: 'Skip-level' },
  { value: 'stakeholder', label: 'Stakeholder' },
  { value: 'external', label: 'External' },
]

const ACCENT_OPTIONS: {
  value: EntityAccentColor
  swatchClass: string
  ringClass: string
}[] = [
  {
    value: 'cyan',
    swatchClass: 'bg-neon-cyan',
    ringClass: 'ring-neon-cyan',
  },
  {
    value: 'pink',
    swatchClass: 'bg-neon-pink',
    ringClass: 'ring-neon-pink',
  },
  {
    value: 'green',
    swatchClass: 'bg-neon-green',
    ringClass: 'ring-neon-green',
  },
  {
    value: 'yellow',
    swatchClass: 'bg-neon-yellow',
    ringClass: 'ring-neon-yellow',
  },
]

export function NewTeamMemberModal({
  onClose,
  onCreated,
}: NewTeamMemberModalProps) {
  const [name, setName] = useState('')
  const [title, setTitle] = useState('')
  const [relationship, setRelationship] =
    useState<EntityRelationshipType>('direct_report')
  const [accent, setAccent] = useState<EntityAccentColor>('cyan')
  const [firstNote, setFirstNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const canSubmit = name.trim().length > 0 && !submitting

  const handleSubmit = async () => {
    if (!canSubmit) return
    setSubmitting(true)
    setError('')
    try {
      const entity = await createEntity({
        name: name.trim(),
        title: title.trim() || undefined,
        relationship_type: relationship,
        accent_color: accent,
        first_note: firstNote.trim() || undefined,
      })
      onCreated(entity)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create entity')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <div
        className="fixed inset-0 bg-black/60 z-40"
        onClick={onClose}
      />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div
          className="w-full max-w-[480px] pointer-events-auto industrial-panel border-2 border-neon-cyan/40 cyber-frame relative"
          style={{ filter: 'drop-shadow(0 0 12px rgba(0,240,255,0.2))' }}
        >
          {/* Corner accents */}
          <div className="absolute top-2 left-2 w-3 h-3 border-l-2 border-t-2 border-neon-cyan/60" />
          <div className="absolute top-2 right-2 w-3 h-3 border-r-2 border-t-2 border-neon-pink/60" />

          <div className="p-5 space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="p-1.5 industrial-inset border border-neon-cyan/40">
                  <UserPlus className="w-4 h-4 text-neon-cyan" />
                </div>
                <h2 className="font-mono text-xs uppercase tracking-widest text-neon-cyan glow-cyan-text font-bold">
                  // NEW TEAM MEMBER
                </h2>
              </div>
              <button
                onClick={onClose}
                title="Close"
                className="p-1.5 industrial-inset border border-[#00f0ff]/30 text-[#00f0ff] hover:text-[#ff2a6d] hover:border-[#ff2a6d]/40 transition-all cursor-pointer"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>

            <div className="industrial-divider-h" />

            {/* Name */}
            <div className="space-y-1.5">
              <label className="font-mono text-[10px] uppercase tracking-widest text-neon-pink/70">
                [ Name ]
              </label>
              <input
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Full name"
                className="w-full px-3 py-2 industrial-inset border-2 border-neon-cyan/30 font-sans text-sm bg-transparent text-foreground placeholder:text-muted-foreground/40 focus:outline-none focus:border-neon-pink/50"
              />
            </div>

            {/* Title */}
            <div className="space-y-1.5">
              <label className="font-mono text-[10px] uppercase tracking-widest text-neon-pink/70">
                [ Title / Role ]
              </label>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Senior Engineer"
                className="w-full px-3 py-2 industrial-inset border-2 border-neon-cyan/30 font-sans text-sm bg-transparent text-foreground placeholder:text-muted-foreground/40 focus:outline-none focus:border-neon-pink/50"
              />
            </div>

            {/* Relationship */}
            <div className="space-y-1.5">
              <label className="font-mono text-[10px] uppercase tracking-widest text-neon-pink/70">
                [ Relationship ]
              </label>
              <select
                value={relationship}
                onChange={(e) =>
                  setRelationship(e.target.value as EntityRelationshipType)
                }
                className="w-full px-3 py-2 industrial-inset border-2 border-neon-cyan/30 font-sans text-sm bg-[#0a0a10] text-foreground focus:outline-none focus:border-neon-pink/50"
              >
                {RELATIONSHIP_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Accent color */}
            <div className="space-y-1.5">
              <label className="font-mono text-[10px] uppercase tracking-widest text-neon-pink/70">
                [ Accent Color ]
              </label>
              <div className="flex items-center gap-3">
                {ACCENT_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setAccent(opt.value)}
                    className={cn(
                      'w-8 h-8 industrial-inset border-2 transition-all cursor-pointer flex items-center justify-center',
                      accent === opt.value
                        ? 'border-foreground/60'
                        : 'border-muted-foreground/20 hover:border-foreground/40',
                    )}
                    title={opt.value}
                  >
                    <span className={cn('w-4 h-4', opt.swatchClass)} />
                  </button>
                ))}
              </div>
            </div>

            {/* First note */}
            <div className="space-y-1.5">
              <label className="font-mono text-[10px] uppercase tracking-widest text-neon-pink/70">
                [ First Note — optional ]
              </label>
              <textarea
                value={firstNote}
                onChange={(e) => setFirstNote(e.target.value)}
                rows={3}
                placeholder="A starting note to anchor the coaching history..."
                className="w-full px-3 py-2 industrial-inset border-2 border-neon-cyan/30 font-sans text-sm bg-transparent text-foreground placeholder:text-muted-foreground/40 focus:outline-none focus:border-neon-pink/50 resize-none"
              />
            </div>

            {error && (
              <div className="px-3 py-2 industrial-inset border border-neon-pink/40">
                <p className="font-mono text-[11px] text-neon-pink">
                  {error}
                </p>
              </div>
            )}

            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                onClick={onClose}
                className="px-3 py-1.5 industrial-inset border border-muted-foreground/30 text-muted-foreground hover:text-neon-pink hover:border-neon-pink/40 transition-all cursor-pointer font-mono text-[10px] uppercase tracking-wider"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={!canSubmit}
                className={cn(
                  'px-3 py-1.5 industrial-raised border-2 transition-all cursor-pointer font-mono text-[10px] uppercase tracking-wider font-bold flex items-center gap-2',
                  canSubmit
                    ? 'border-neon-cyan/50 text-neon-cyan hover:border-neon-pink/50 hover:text-neon-pink hover:glow-pink'
                    : 'border-muted-foreground/20 text-muted-foreground/40 cursor-not-allowed',
                )}
              >
                <UserPlus className="w-3 h-3" />
                {submitting ? 'Creating...' : 'Add Member'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
