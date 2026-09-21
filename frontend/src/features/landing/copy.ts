/**
 * All landing-page text lives here so it can be changed in one place. The hero subhead, evidence
 * card, tier descriptions and risk descriptions are verbatim from the supplied copy. Section
 * headings and intro paragraphs were not supplied and are still drafted in the same voice.
 */
export const HERO = {
  headline: "It doesn't guess. It checks.", // [spec]
  subhead:
    "Personal AI Agent researches your job leads, verifies employers, and scores every match against real evidence — before any of it reaches you. When it can't confirm something, it says so.",
  signedOut: { label: 'Sign in', to: '/login' },
  signedIn: { label: 'Open the app', to: '/dashboard' },
}

export const EVIDENCE = {
  heading: 'Every number comes with its reasons.',
  intro:
    'A score is only useful if you can see what it stands on. Each source draws a line to the claim, and the claim only locks in once they agree.',
  exampleLabel: 'Example, not a real posting',
  title: 'AI/ML Engineer — Berlin, Germany', // [spec]
  score: 87, // [spec]
  scoreLabel: 'of what could be measured', // [spec]
  checks: [
    'Required skills present — Python, PyTorch, computer vision',
    'Employer verified — official source, checked 2 hours ago',
  ],
  uncertainty: 'One uncertainty — salary range not published',
  source: 'source: careers.employer.com · fetched 2h ago · tier: official',
}

export const LADDER = {
  heading: 'Not every source counts the same.',
  intro:
    'Sources are ranked before they are read. A claim backed by an official page outweighs a dozen forum posts, and forum posts are only ever treated as anecdote.',
  tiers: [
    { name: 'Official', note: "The employer's own domain, primary documents, and direct postings." },
    { name: 'Government', note: 'Regulatory filings, court records, and official registries.' },
    { name: 'Documentation', note: 'Authoritative vendor and technical references.' },
    { name: 'Reputable secondary', note: 'Outlets with real editorial standards, used to corroborate — not originate — a claim.' },
    { name: 'Forums, as anecdote', note: 'Anecdotal color only. Never the sole basis for a fact.' },
  ],
} as const

export const RISK = {
  heading: 'Every action has a risk level.',
  intro: 'The agent never decides how much authority it has. The level does, and the level is fixed in code.',
  tiers: [
    { name: 'Green', detail: 'Reads and analyzes. Runs on its own — nothing leaves your data.' },
    { name: 'Yellow', detail: 'Drafts something real, like a reply or a post. Waits for you to approve it.' },
    { name: 'Red', detail: 'Sends, applies, or commits to something. Needs your approval and a second check.' },
  ],
} as const

export const FOOTER = {
  line: 'Every claim traces back to evidence. Where it cannot, the answer is "I don\'t know."',
}
