import { defineConfig } from 'vitepress'

// The site is served from https://gslama12.github.io/tcal/, so every
// generated asset and link has to carry the repo name in front of it.
const base = '/tcal/'

export default defineConfig({
  base,
  lang: 'en-US',
  title: 'tcal',
  description: 'A keyboard-driven terminal calendar that syncs with iCloud.',
  lastUpdated: true,
  cleanUrls: true,
  head: [['link', { rel: 'icon', href: `${base}favicon.svg` }]],

  themeConfig: {
    search: {
      provider: 'local',
    },

    nav: [
      { text: 'Guide', link: '/guide/installation' },
      { text: 'Keybindings', link: '/guide/keybindings' },
      { text: 'Reference', link: '/reference/cli' },
      { text: 'GitHub', link: 'https://github.com/gslama12/tcal' },
    ],

    sidebar: [
      {
        text: 'Guide',
        items: [
          { text: 'Installation', link: '/guide/installation' },
          { text: 'Getting started', link: '/guide/getting-started' },
          { text: 'iCloud setup', link: '/guide/icloud' },
          { text: 'Subscriptions', link: '/guide/subscriptions' },
          { text: 'Views & navigation', link: '/guide/views' },
          { text: 'Typing events', link: '/guide/typing-events' },
          { text: 'Editing events', link: '/guide/editing-events' },
          { text: 'Moving & copying', link: '/guide/move-copy' },
          { text: 'Flash, search & go to', link: '/guide/flash-search' },
          { text: 'Grid & resize mode', link: '/guide/modes' },
          { text: 'Undo', link: '/guide/undo' },
          { text: 'Sync & offline', link: '/guide/sync' },
          { text: 'Keybindings', link: '/guide/keybindings' },
        ],
      },
      {
        text: 'Reference',
        items: [
          { text: 'CLI', link: '/reference/cli' },
          { text: 'Configuration', link: '/reference/configuration' },
          { text: 'Themes', link: '/reference/themes' },
          { text: 'Data & files', link: '/reference/data' },
          { text: 'Troubleshooting', link: '/reference/troubleshooting' },
          { text: 'Development', link: '/reference/development' },
        ],
      },
    ],

    socialLinks: [{ icon: 'github', link: 'https://github.com/gslama12/tcal' }],

    editLink: {
      pattern: 'https://github.com/gslama12/tcal/edit/main/site/docs/:path',
      text: 'Edit this page on GitHub',
    },

    outline: [2, 3],

    footer: {
      message: 'MIT licensed. Built with Textual.',
      copyright: 'Copyright © Georg Slamanig',
    },
  },
})
