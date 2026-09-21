/**
 * All landing-page text lives here so it can be swapped against the design prototype in one place.
 * Lines marked [spec] are verbatim from the brief; the rest is drafted in the same voice and is
 * pending comparison with the prototype.
 */
export const HERO = {
  headline: "It doesn't guess. It checks.", // [spec]
  subhead:
    'It researches, verifies and scores every claim before anything reaches you, and when it cannot confirm something, it says so.',
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
    'Required skills: Python, PyTorch and computer vision are present in the profile.',
    "Employer verified: the posting was confirmed from the employer's own source.",
  ],
  verifiedAt: '2 hours ago',
  verifiedAtLabel: 'Verified',
  uncertainty: "One uncertainty: the salary isn't published.", // [spec]
}

export const LADDER = {
  heading: 'Not every source counts the same.',
  intro:
    'Sources are ranked before they are read. A claim backed by an official page outweighs a dozen forum posts, and forum posts are only ever treated as anecdote.',
  tiers: [
    { name: 'Official', note: 'The organisation itself, speaking about itself.' },
    { name: 'Government', note: 'Registries, regulators and public records.' },
    { name: 'Documentation', note: 'Product, standards and technical documentation.' },
    { name: 'Reputable secondary', note: 'Established outlets that cite their own sources.' },
    { name: 'Forums, as anecdote', note: 'Useful for leads. Never used as proof.' },
  ],
} as const

export const RISK = {
  heading: 'Every action has a risk level.',
  intro: 'The agent never decides how much authority it has. The level does, and the level is fixed in code.',
  tiers: [
    {
      name: 'Green',
      summary: 'Automatic',
      detail: 'Safe, reversible work such as reading, drafting and saving notes locally. Nothing leaves your machine.',
    },
    {
      name: 'Yellow',
      summary: 'You confirm',
      detail: 'Anything sent outside, like an email, a post or an application. You read it and approve it first.',
    },
    {
      name: 'Red',
      summary: 'You confirm, then a second check',
      detail: 'High-stakes actions need your explicit confirmation and a second, independent check.',
    },
  ],
} as const

export const FOOTER = {
  line: 'Every claim traces back to evidence. Where it cannot, the answer is "I don\'t know."',
}
