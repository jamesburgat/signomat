# Archive UI Handoff

Use this when you are ready to design the public archive/map experience and want
the implementation to stay fast and predictable.

## 1. Screens

List each screen you want built:

- home / map
- trip detail
- detection detail
- gallery
- stats
- admin review

For each screen, answer:

- primary goal
- required data
- required actions
- mobile behavior
- desktop behavior

## 2. Layout Sketch

Provide one of:

- a photo of a paper sketch
- a Figma link
- a screenshot mockup
- a bullet layout description

Keep it simple:

- header
- left rail / filters
- main map or gallery region
- detail drawer / modal

## 3. Visual Direction

Decide these upfront:

- light or dark default
- map style reference
- typography mood
- color palette
- card style
- density: compact, balanced, or spacious

If you have references, collect 2-4 links or screenshots and note exactly what
you like about each one.

## 4. Data Contract

For each screen, list:

- endpoint needed
- fields required
- sorting
- filters
- pagination or infinite scroll

This keeps design and API work aligned.

## 5. Interaction Rules

Write down decisions like:

- clicking a map pin opens a right-side drawer
- trip polylines are visible by default
- thumbnails open the clean image first, annotated image second
- admin mode uses inline review actions, not separate edit pages

## 6. Component Inventory

Name reusable pieces:

- detection card
- trip summary card
- map legend
- filter bar
- confidence badge
- review state badge
- media carousel

Reusable components make the implementation much faster.

## 7. Build Order

When you hand the design to Codex, include the implementation order:

1. route structure
2. shared page shell
3. map view
4. filters
5. detail page
6. admin review tools

## 8. Best Workflow With Codex

The fastest way to collaborate is:

1. You design one screen at a time.
2. You give Codex:
   - the screen name
   - a mockup or sketch
   - required data
   - required interactions
   - any style references
3. Codex implements that screen without redesigning the rest of the app.
4. We iterate visually after the first coded pass.

This works better than asking for the whole archive UI in one shot.
