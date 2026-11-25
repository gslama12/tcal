<script setup lang="ts">
// The feature carousel on the home page.
//
// One feature at a time, each with the screenshot that shows it and a way into
// the part of the guide that explains it.
//
// Only the slide on show is mounted. The screenshots are a couple of hundred
// kilobytes of SVG each, so a track holding all of them at once would pull
// down several megabytes before the reader had asked for any of it.

import { computed, ref } from 'vue'
import { withBase } from 'vitepress'

interface Feature {
  title: string
  /** Rendered as HTML, so a key can be drawn as a key */
  details: string
  /** Where in the guide this feature is written up */
  link: string
  /** A file in docs/public/screenshots */
  shot: string
  alt: string
}

const features: Feature[] = [
  {
    title: 'A real week',
    details:
      'Overlapping events stack, all-day events are bars, and a red line is now. <kbd>j</kbd> <kbd>k</kbd> <kbd>h</kbd> <kbd>l</kbd> step from event to event; <kbd>+</kbd> <kbd>-</kbd> zoom.',
    link: '/guide/views#week',
    shot: 'week.svg',
    alt: 'The week view',
  },
  {
    title: 'Month, year, schedule',
    details:
      '<kbd>w</kbd> <kbd>m</kbd> <kbd>Y</kbd> <kbd>s</kbd> switch between the views; <kbd>H</kbd> and <kbd>L</kbd> page through any of them.',
    link: '/guide/views',
    shot: 'month.svg',
    alt: 'The month view',
  },
  {
    title: 'Events typed as a line',
    details:
      '<kbd>a</kbd>, then <code>Lunch with Anna fri 12:30-13:30 @Cafe #personal</code>. A card fills in below as you type, so you see what will be saved.',
    link: '/guide/typing-events',
    shot: 'prompt.svg',
    alt: 'The event prompt with its live preview',
  },
  {
    title: 'Repeats in words',
    details:
      '<code>every mon, wed until dec</code>, <code>daily 10 times</code>, <code>every 2 weeks</code>. <kbd>tab</kbd> completes the calendar after a <code>#</code>.',
    link: '/guide/typing-events#repeats',
    shot: 'prompt-repeat.svg',
    alt: 'A repeating event in the prompt',
  },
  {
    title: 'A form for editing',
    details:
      '<kbd>e</kbd> opens an event field by field. What the form does not show &mdash; time zone, guests, alarms &mdash; is kept.',
    link: '/guide/editing-events',
    shot: 'form.svg',
    alt: 'The event form',
  },
  {
    title: 'One event or all of them',
    details:
      'Editing, moving, resizing or deleting a repeating event asks once: this event, or all events.',
    link: '/guide/editing-events#repeating-events',
    shot: 'scope.svg',
    alt: 'The question asked for a repeating event',
  },
  {
    title: 'Flash jumps',
    details:
      '<kbd>f</kbd> puts a label on every event and every slot on screen; type one and you are there.',
    link: '/guide/flash-search#flash',
    shot: 'flash.svg',
    alt: 'Flash labels over the week',
  },
  {
    title: 'Grid mode',
    details:
      '<kbd>v</kbd> swaps stepping through events for a slot cursor: pick any time of the week and press <kbd>a</kbd> or <kbd>p</kbd>.',
    link: '/guide/modes#grid-mode',
    shot: 'grid.svg',
    alt: 'The slot cursor of grid mode',
  },
  {
    title: 'Resize mode',
    details:
      '<kbd>o</kbd> takes hold of an event&rsquo;s end, <kbd>j</kbd> and <kbd>k</kbd> drag it by quarter hours, <kbd>o</kbd> again switches to its start.',
    link: '/guide/modes#resize-mode',
    shot: 'resize.svg',
    alt: 'An event being resized',
  },
  {
    title: 'Batch copy',
    details:
      'Mark events with <kbd>tab</kbd>, <kbd>y</kbd> copies them all and <kbd>p</kbd> on another day pastes the lot, spacing kept.',
    link: '/guide/move-copy#several-events',
    shot: 'marks.svg',
    alt: 'Four marked events',
  },
  {
    title: 'Undo and redo',
    details:
      '<kbd>u</kbd> takes back the last 20 changes, <kbd>ctrl+r</kbd> makes them again &mdash; on iCloud too.',
    link: '/guide/undo',
    shot: 'undo.svg',
    alt: 'A move taken back',
  },
  {
    title: 'Offline first',
    details:
      'Everything is drawn from a local cache. Edits made without a network are queued and pushed later; what went wrong is in the sync log, <kbd>R</kbd>.',
    link: '/guide/sync',
    shot: 'sync-log.svg',
    alt: 'The sync log',
  },
  {
    title: 'Everyone’s calendars',
    details:
      'iCloud calendars in their own colours, plus read-only subscriptions: holidays, fixtures, a shared team calendar.',
    link: '/guide/subscriptions',
    shot: 'calendars.svg',
    alt: 'The calendar list, one calendar hidden',
  },
  {
    title: 'Every key, one press away',
    details:
      '<kbd>?</kbd> lists every binding, and each one can be changed in the config.',
    link: '/guide/keybindings',
    shot: 'help.svg',
    alt: 'The help screen',
  },
]

const count = features.length
const index = ref(0)
const back = ref(false)
const current = computed(() => features[index.value])
const transition = computed(() => (back.value ? 'fc-back' : 'fc-forward'))

function go(to: number, backwards = to < index.value) {
  back.value = backwards
  // Wraps both ways, so neither arrow is ever a dead end
  index.value = (to + count) % count
}

const next = () => go(index.value + 1, false)
const prev = () => go(index.value - 1, true)

function onKey(event: KeyboardEvent) {
  // Only while the carousel itself has focus, so the arrow keys still belong
  // to the page everywhere else
  if (event.key === 'ArrowRight') {
    next()
  } else if (event.key === 'ArrowLeft') {
    prev()
  } else {
    return
  }

  event.preventDefault()
}

// A swipe, for the phone layout where there is no room for the arrows to be
// obvious
let touchX = 0

function onTouchStart(event: TouchEvent) {
  touchX = event.changedTouches[0].screenX
}

function onTouchEnd(event: TouchEvent) {
  const travelled = event.changedTouches[0].screenX - touchX

  if (Math.abs(travelled) > 40) {
    if (travelled < 0) {
      next()
    } else {
      prev()
    }
  }
}
</script>

<template>
  <section
    class="fc"
    aria-roledescription="carousel"
    aria-label="What tcal does"
  >
    <header class="fc-head">
      <h2 class="fc-heading">What it does</h2>
      <p class="fc-sub">{{ count }} things, one at a time.</p>
    </header>

    <div class="fc-frame">
      <button
        class="fc-arrow"
        type="button"
        aria-label="Previous feature"
        @click="prev"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" width="22" height="22">
          <path
            d="M15 5l-7 7 7 7"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </button>

      <div
        class="fc-viewport"
        tabindex="0"
        role="group"
        :aria-label="`${index + 1} of ${count}: ${current.title}`"
        @keydown="onKey"
        @touchstart.passive="onTouchStart"
        @touchend.passive="onTouchEnd"
      >
        <Transition :name="transition" mode="out-in">
          <article :key="index" class="fc-slide">
            <a
              class="fc-shot"
              :href="withBase(current.link)"
              tabindex="-1"
              aria-hidden="true"
            >
              <img
                :src="withBase(`/screenshots/${current.shot}`)"
                :alt="current.alt"
                loading="lazy"
                decoding="async"
              />
            </a>

            <div class="fc-body">
              <p class="fc-count">{{ index + 1 }} / {{ count }}</p>
              <h3 class="fc-title">{{ current.title }}</h3>
              <!-- Written just above, in this file -- nothing a reader can
                   type ever reaches it -->
              <p class="fc-details" v-html="current.details" />
              <a class="fc-link" :href="withBase(current.link)">
                Read the guide →
              </a>
            </div>
          </article>
        </Transition>
      </div>

      <button
        class="fc-arrow"
        type="button"
        aria-label="Next feature"
        @click="next"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" width="22" height="22">
          <path
            d="M9 5l7 7-7 7"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </button>
    </div>

    <div class="fc-dots">
      <button
        v-for="(feature, i) in features"
        :key="feature.title"
        class="fc-dot"
        type="button"
        :class="{ 'is-on': i === index }"
        :aria-label="feature.title"
        :aria-current="i === index"
        @click="go(i)"
      />
    </div>
  </section>
</template>

<style scoped>
/* No width or padding of its own: it sits inside VitePress's own content
   container on the home page, so taking that container's full width is what
   lines the carousel up with the screenshot above it */
.fc {
  margin: 48px 0 0;
}

.fc-head {
  margin-bottom: 20px;
}

.fc-heading {
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.3;
  margin: 0;
  padding: 0;
  border: 0;
}

.fc-sub {
  font-size: 14px;
  color: var(--vp-c-text-3);
  margin: 4px 0 0;
}

.fc-frame {
  display: flex;
  align-items: center;
  gap: 8px;
}

.fc-viewport {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--vp-c-divider);
  border-radius: 12px;
  background: var(--vp-c-bg-soft);
  padding: 20px;
  overflow: hidden;
}

.fc-viewport:focus-visible {
  outline: 2px solid var(--vp-c-brand-1);
  outline-offset: 2px;
}

.fc-slide {
  display: grid;
  /* The screenshot is the point of the slide, so it takes the larger half */
  grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr);
  gap: 28px;
  align-items: center;
  /* Holds the frame still while one feature is replaced by a longer one */
  min-height: 260px;
}

.fc-shot {
  display: block;
  border-radius: 8px;
  overflow: hidden;
  line-height: 0;
  background: var(--vp-c-bg);
}

.fc-shot img {
  width: 100%;
  height: auto;
  display: block;
}

.fc-count {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--vp-c-text-3);
  margin: 0 0 6px;
}

.fc-title {
  font-size: 22px;
  font-weight: 700;
  line-height: 1.3;
  letter-spacing: -0.01em;
  margin: 0 0 10px;
  padding: 0;
  border: 0;
}

.fc-details {
  font-size: 15px;
  line-height: 1.65;
  color: var(--vp-c-text-2);
  margin: 0 0 16px;
}

.fc-details :deep(kbd) {
  display: inline-block;
  padding: 1px 6px;
  border: 1px solid var(--vp-c-divider);
  border-bottom-width: 2px;
  border-radius: 5px;
  background: var(--vp-c-bg);
  font-family: var(--vp-font-family-mono);
  font-size: 12px;
  line-height: 1.6;
  color: var(--vp-c-text-1);
  white-space: nowrap;
}

.fc-details :deep(code) {
  font-size: 13px;
}

.fc-link {
  font-size: 14px;
  font-weight: 600;
  color: var(--vp-c-brand-1);
}

.fc-link:hover {
  color: var(--vp-c-brand-2);
}

.fc-arrow {
  flex: none;
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border: 1px solid var(--vp-c-divider);
  border-radius: 50%;
  background: var(--vp-c-bg);
  color: var(--vp-c-text-2);
  transition: border-color 0.2s, color 0.2s, background-color 0.2s;
}

.fc-arrow:hover {
  border-color: var(--vp-c-brand-1);
  color: var(--vp-c-brand-1);
  background: var(--vp-c-bg-soft);
}

.fc-arrow:focus-visible {
  outline: 2px solid var(--vp-c-brand-1);
  outline-offset: 2px;
}

.fc-dots {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  margin-top: 16px;
}

.fc-dot {
  width: 8px;
  height: 8px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: var(--vp-c-divider);
  transition: background-color 0.2s, transform 0.2s;
}

.fc-dot:hover {
  background: var(--vp-c-text-3);
}

.fc-dot.is-on {
  background: var(--vp-c-brand-1);
  transform: scale(1.35);
}

.fc-dot:focus-visible {
  outline: 2px solid var(--vp-c-brand-1);
  outline-offset: 3px;
}

/* One slide out and the next in, from the side the reader asked for */
.fc-forward-enter-active,
.fc-forward-leave-active,
.fc-back-enter-active,
.fc-back-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.fc-forward-enter-from {
  opacity: 0;
  transform: translateX(28px);
}

.fc-forward-leave-to {
  opacity: 0;
  transform: translateX(-28px);
}

.fc-back-enter-from {
  opacity: 0;
  transform: translateX(-28px);
}

.fc-back-leave-to {
  opacity: 0;
  transform: translateX(28px);
}

@media (max-width: 820px) {
  .fc {
    margin-top: 32px;
  }

  .fc-viewport {
    padding: 16px;
  }

  .fc-slide {
    grid-template-columns: minmax(0, 1fr);
    gap: 16px;
    min-height: 0;
  }

  .fc-arrow {
    width: 34px;
    height: 34px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .fc-forward-enter-active,
  .fc-forward-leave-active,
  .fc-back-enter-active,
  .fc-back-leave-active {
    transition: opacity 0.12s ease;
  }

  .fc-forward-enter-from,
  .fc-forward-leave-to,
  .fc-back-enter-from,
  .fc-back-leave-to {
    transform: none;
  }

  .fc-dot {
    transition: none;
  }
}
</style>
