# Archive Site Spec

Use this file to define the smallest useful version of the archive site before
we build it. Keep it minimal. The goal is a clean public archive first, with a
small separate admin/review mode.

## Build Philosophy

- prefer fewer screens
- prefer one strong primary map/archive screen over many thin pages
- keep public browsing separate from admin/review actions
- load thumbnails first, never huge raw assets by default
- mobile should be usable, but desktop can be the primary design target

## Recommended Minimal Screen Set

Start with only these:

1. Public Archive Map
2. Detection Detail
3. Trip Detail
4. Admin Review

Optional later:

- gallery-only view
- stats dashboard
- about/project page

## Global Decisions

Fill these in first.

- Theme:
- Default color mode:
- Map style reference:
- Typography direction:
- Card style:
- Density:
- Public tone:
- Admin tone:

## Navigation

Keep this simple.

- Primary nav items:
- Public routes:
- Admin routes:
- Should the public site have a header bar?
- Should filters live in a side rail, top bar, or drawer?

## Screen 1: Public Archive Map

- Route:
- Purpose:
- Audience:
- Must-have data:
- Optional data:
- Main layout:
- Mobile layout:
- Filters:
- Default sort:
- What happens when a map pin is clicked:
- What happens when a trip is clicked:
- Should breadcrumb trails show by default:
- Empty state:
- Loading state:
- Error state:

### Public Archive Map Components

- Filter bar:
- Map panel:
- Results list:
- Detail drawer or modal:
- Thumbnail behavior:

## Screen 2: Detection Detail

- Route:
- Purpose:
- Audience:
- Must-have data:
- Optional data:
- Main layout:
- Mobile layout:
- Media order:
- Should annotated or clean image show first:
- Should sign crop be shown:
- Should linked trip be clickable:
- Should nearby detections be shown:
- Empty state:
- Loading state:
- Error state:

### Detection Detail Components

- Media viewer:
- Metadata table:
- Map snippet:
- Linked trip section:

## Screen 3: Trip Detail

- Route:
- Purpose:
- Audience:
- Must-have data:
- Optional data:
- Main layout:
- Mobile layout:
- Should trip timeline be included:
- Should trip video segments be shown:
- Should detections be listed under the map:
- Should breadcrumb trail always be visible:
- Empty state:
- Loading state:
- Error state:

### Trip Detail Components

- Trip header:
- Trip map:
- Detection timeline/list:
- Video segment list:

## Screen 4: Admin Review

- Route:
- Purpose:
- Audience:
- Auth expectation:
- Must-have actions:
- Optional actions:
- Main layout:
- Mobile layout:
- Should review happen inline or in a side panel:
- Empty state:
- Loading state:
- Error state:

### Admin Review Actions

- relabel detection:
- mark false positive:
- add note:
- merge duplicate:
- suppress duplicate:

## Shared Data Contracts

For each screen, define the minimum API shape needed.

### Public Archive Map API

- Endpoint:
- Required fields:
- Filter params:
- Pagination style:

### Detection Detail API

- Endpoint:
- Required fields:

### Trip Detail API

- Endpoint:
- Required fields:

### Admin Review API

- Endpoint(s):
- Required fields:
- Write actions:

## Media Rules

Fill these in so we keep the site fast.

- Thumbnail max size:
- When full image loads:
- Should public pages ever show raw full-size video automatically:
- Should map markers cluster:
- Should lazy loading be used:
- Should image prefetching be used:

## Design References

Add 2-4 references max.

For each reference:

- Link or image:
- What you like:
- What you do not want copied:

## Implementation Order

Recommended minimal order:

1. shared layout shell
2. public archive map
3. detection detail
4. trip detail
5. admin review

## Notes To Codex

Use this section when handing the design off for implementation.

- keep these parts exact:
- simplify these parts if needed:
- do not spend time on:
- prioritize these interactions:
