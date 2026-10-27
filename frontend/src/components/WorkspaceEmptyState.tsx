import { cn } from '../lib/utils'

interface CommandDef {
  trigger: string
  description: string
  example?: string
}

interface WorkspaceMeta {
  label: string
  tagline: string
  purpose: string
  accentColor: 'cyan' | 'pink' | 'green' | 'yellow' | 'orange'
  commands: CommandDef[]
  examples: string[]
}

const ACCENT: Record<
  WorkspaceMeta['accentColor'],
  { text: string; textDim: string; border: string; bg: string; ctaHover: string; corner: string }
> = {
  cyan: {
    text: 'text-neon-cyan',
    textDim: 'text-neon-cyan/60',
    border: 'border-neon-cyan/20',
    bg: 'bg-neon-cyan/5',
    ctaHover: 'hover:text-neon-cyan hover:border-neon-cyan/50',
    corner: 'border-neon-cyan/40',
  },
  pink: {
    text: 'text-neon-pink',
    textDim: 'text-neon-pink/60',
    border: 'border-neon-pink/20',
    bg: 'bg-neon-pink/5',
    ctaHover: 'hover:text-neon-pink hover:border-neon-pink/50',
    corner: 'border-neon-pink/40',
  },
  green: {
    text: 'text-neon-green',
    textDim: 'text-neon-green/60',
    border: 'border-neon-green/20',
    bg: 'bg-neon-green/5',
    ctaHover: 'hover:text-neon-green hover:border-neon-green/50',
    corner: 'border-neon-green/40',
  },
  yellow: {
    text: 'text-neon-yellow',
    textDim: 'text-neon-yellow/60',
    border: 'border-neon-yellow/20',
    bg: 'bg-neon-yellow/5',
    ctaHover: 'hover:text-neon-yellow hover:border-neon-yellow/50',
    corner: 'border-neon-yellow/40',
  },
  orange: {
    text: 'text-neon-orange',
    textDim: 'text-neon-orange/60',
    border: 'border-neon-orange/20',
    bg: 'bg-neon-orange/5',
    ctaHover: 'hover:text-neon-orange hover:border-neon-orange/50',
    corner: 'border-neon-orange/40',
  },
}

const SHARED_COMMANDS: CommandDef[] = [
  { trigger: '!goal <task>', description: 'Multi-step planning + execution', example: '!goal Draft a 90-day onboarding plan for my new hire' },
  { trigger: '!plan <task>', description: 'Alias for !goal', example: '!plan Map out the Q4 OKR review process' },
  { trigger: '!research <question>', description: 'Web research + synthesized answer', example: '!research Best frameworks for giving difficult feedback' },
  { trigger: '!remember <text>', description: 'Save something to long-term memory', example: '!remember My preferred 1:1 cadence is every two weeks' },
  { trigger: '!search <query>', description: 'Query Drift\'s memory', example: '!search leadership principles' },
  { trigger: 'Attach file', description: 'PDF, image, CSV, JSON, Markdown — up to 10 MB', },
]

const WORKSPACE_META: Record<string, WorkspaceMeta> = {
  'chief-of-staff': {
    label: 'Architect',
    tagline: 'Identity · Values · Operating Model',
    purpose:
      'The most reflective workspace. This is where you examine how you think, what you value, and how you operate. No performance layer — Drift at its clearest and most direct.',
    accentColor: 'cyan',
    commands: SHARED_COMMANDS,
    examples: [
      'What are my core leadership principles?',
      'How do I typically make decisions under pressure?',
      '!goal Map my operating model for next year',
      '!research Second-order thinking frameworks',
    ],
  },
  admin: {
    label: 'Admin Prime',
    tagline: 'Leadership Development · Career Strategy · Difficult Conversations',
    purpose:
      'Your personal leadership lab. Work through career strategy, prep for hard conversations, research management frameworks, and develop yourself as a leader. Drift pushes back here — expect to be challenged.',
    accentColor: 'cyan',
    commands: SHARED_COMMANDS,
    examples: [
      'Help me prep for a tough conversation about underperformance',
      'What should I be prioritizing for my career this quarter?',
      '!research Executive presence for engineers moving into leadership',
      '!goal Build a 6-month development plan for myself',
    ],
  },
  institute: {
    label: 'Institute Prime',
    tagline: 'Team Coaching · People Development · 1:1 Prep',
    purpose:
      'Your team management workspace. Track direct reports, run 1:1 prep, work through coaching moments, and log what matters. Open the Roster to browse your team and start entity-linked threads.',
    accentColor: 'pink',
    commands: [
      ...SHARED_COMMANDS,
      {
        trigger: 'Transcript paste / file',
        description: 'Drop a 1:1 transcript to extract and file coaching notes automatically',
        example: '[paste transcript text or attach a .txt/.pdf file]',
      },
    ],
    examples: [
      'Help me prep for tomorrow\'s 1:1 with [name]',
      'What are the signs that someone is disengaged?',
      '!goal Build a PIP framework for an underperformer',
      'Draft feedback for [name]\'s mid-year review',
    ],
  },
  health: {
    label: 'Med-Bay',
    tagline: 'Health Tracking · Labs · Protocol',
    purpose:
      'Your health workspace. Track labs, manage supplement protocols, and get evidence-based guidance. Paste or attach a lab panel and Drift will parse and file it automatically.',
    accentColor: 'green',
    commands: [
      { trigger: 'Lab paste / file', description: 'Paste lab values or attach a PDF panel — Drift parses and files it', },
      { trigger: '!research <topic>', description: 'Health research with functional medicine context', example: '!research optimal ferritin levels for men over 35' },
      { trigger: '!remember <text>', description: 'Save a health note to memory', example: '!remember Started magnesium glycinate 400mg at night' },
      { trigger: '!search <query>', description: 'Search health memory', example: '!search testosterone protocol' },
      { trigger: 'Attach file', description: 'Lab PDF, imaging report, or any health doc', },
    ],
    examples: [
      'Review my latest labs and flag anything concerning',
      'What\'s my current supplement protocol?',
      '!research optimal testosterone levels and what affects them',
      'Am I missing anything in my current stack?',
    ],
  },
  engineering: {
    label: 'The Rig',
    tagline: 'Engineering · Architecture · Debugging · Build Planning',
    purpose:
      'The engineering workspace. Ask architecture questions, debug issues, plan new features, or search the codebase. Drift knows this project — it has access to codebase search and full tool access.',
    accentColor: 'yellow',
    commands: [
      ...SHARED_COMMANDS,
      {
        trigger: 'Codebase search (auto)',
        description: 'Drift searches the repo automatically when the question is code-related',
      },
    ],
    examples: [
      'What\'s the blast radius of changing the memory isolation logic?',
      '!plan Build a new REST endpoint for X',
      '!research Postgres vs SQLite performance tradeoffs at 10M rows',
      'Debug this: [paste error / stack trace]',
    ],
  },
  parker: {
    label: 'Parker.exe',
    tagline: 'Games · Stories · Ideas · Your Space',
    purpose:
      'This is Parker\'s workspace. Talk about games, build wild stories, explore ideas, ask anything. Drift is your robot friend here — game buddy, cool mentor, story co-pilot.',
    accentColor: 'orange',
    commands: [
      { trigger: 'Just talk', description: 'Ask anything, start a story, or kick off a game' },
      { trigger: 'Attach image', description: 'Show Drift a screenshot or drawing and talk about it' },
      { trigger: '!remember <text>', description: 'Save something you want Drift to remember', example: '!remember My favorite game is Minecraft' },
    ],
    examples: [
      'Tell me a story about zombie ninjas vs robot pirates',
      'Let\'s build a new video game world — you start',
      'What\'s the most overpowered weapon in Minecraft?',
      'Make me a riddle that\'s really hard',
    ],
  },
  general: {
    label: 'Terminal',
    tagline: 'Catch-All · Adaptive · No Rules',
    purpose:
      'The general-purpose workspace. Drift adapts to whatever you bring — reflective like Architect, technical like The Rig, or warm like Institute Prime. No fixed mode. Just start talking.',
    accentColor: 'orange',
    commands: SHARED_COMMANDS,
    examples: [
      'Explain X to me from first principles',
      '!research Best practices for Y',
      '!goal Help me think through a decision about Z',
      'Write a first draft of [anything]',
    ],
  },
}

interface WorkspaceEmptyStateProps {
  workspaceSlug: string
  onCreateThread: () => void
}

export function WorkspaceEmptyState({
  workspaceSlug,
  onCreateThread,
}: WorkspaceEmptyStateProps) {
  const meta = WORKSPACE_META[workspaceSlug]

  // Fallback for unknown slugs
  if (!meta) {
    return (
      <div className="flex-1 flex items-center justify-center bg-[#080c12] scanlines">
        <div className="text-center">
          <div className="font-mono text-[10px] text-[#9090a8]/40 uppercase tracking-widest">
            [ SELECT OR CREATE A THREAD ]
          </div>
        </div>
      </div>
    )
  }

  const accent = ACCENT[meta.accentColor]

  return (
    <div className="flex-1 flex items-center justify-center bg-[#080c12] scanlines overflow-y-auto py-8 px-4">
      <div className="w-full max-w-[560px] space-y-5">

        {/* Header */}
        <div className={cn('border industrial-panel p-5', accent.border, accent.bg)}>
          {/* Corner accents */}
          <div className="relative">
            <div className={cn('absolute top-0 left-0 w-3 h-3 border-l-2 border-t-2', accent.corner)} />
            <div className={cn('absolute top-0 right-0 w-3 h-3 border-r-2 border-t-2', accent.corner)} />
            <div className={cn('absolute bottom-0 left-0 w-3 h-3 border-l-2 border-b-2', accent.corner)} />
            <div className={cn('absolute bottom-0 right-0 w-3 h-3 border-r-2 border-b-2', accent.corner)} />

            <div className="px-2 py-1 space-y-2">
              <div className="flex items-baseline gap-3">
                <span className={cn('font-mono text-xs uppercase tracking-widest font-bold', accent.text)}>
                  [ {meta.label} ]
                </span>
                <span className="font-mono text-[9px] text-[#9090a8]/50 uppercase tracking-widest">
                  {meta.tagline}
                </span>
              </div>
              <p className="font-sans text-xs text-[#9090a8]/80 leading-relaxed">
                {meta.purpose}
              </p>
            </div>
          </div>
        </div>

        {/* Commands */}
        <div className="space-y-2">
          <div className="font-mono text-[9px] text-[#9090a8]/40 uppercase tracking-widest px-1">
            [ Commands ]
          </div>
          <div className="border border-[#1a2332] industrial-panel">
            {meta.commands.map((cmd, i) => (
              <div
                key={i}
                className={cn(
                  'flex items-start gap-3 px-4 py-2.5',
                  i < meta.commands.length - 1 && 'border-b border-[#1a2332]',
                )}
              >
                <span className={cn(
                  'font-mono text-[10px] shrink-0 mt-0.5 font-bold tracking-wide',
                  accent.text,
                )}>
                  {cmd.trigger}
                </span>
                <div className="flex-1 min-w-0 space-y-0.5">
                  <span className="font-sans text-[11px] text-[#9090a8]/70">
                    {cmd.description}
                  </span>
                  {cmd.example && (
                    <div className="font-mono text-[9px] text-[#9090a8]/40 truncate">
                      e.g. {cmd.example}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Examples */}
        <div className="space-y-2">
          <div className="font-mono text-[9px] text-[#9090a8]/40 uppercase tracking-widest px-1">
            [ Example Prompts ]
          </div>
          <div className="space-y-1.5">
            {meta.examples.map((ex, i) => (
              <div
                key={i}
                className={cn(
                  'px-3 py-2 border industrial-inset',
                  'font-mono text-[10px] text-[#9090a8]/60',
                  accent.border,
                )}
              >
                <span className={cn('mr-2 opacity-40', accent.text)}>›</span>
                {ex}
              </div>
            ))}
          </div>
        </div>

        {/* CTA */}
        <div className="flex justify-center pt-2">
          <button
            onClick={onCreateThread}
            className={cn(
              'font-mono text-[10px] uppercase tracking-widest px-6 py-2.5',
              'border transition-all industrial-raised cursor-pointer',
              accent.border,
              accent.textDim,
              accent.ctaHover,
            )}
          >
            [ New Thread ]
          </button>
        </div>

      </div>
    </div>
  )
}
