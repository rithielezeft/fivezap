# FiveZap: Import and Run

Bring the existing FiveZap project (FiveZap3) from GitHub repo `rithielezeft/fivezap` into this workspace and get it running exactly as it is today.
Nothing about how it works changes. The only edits made are the ones needed to get it to start.

## Who it's for
The owner of the FiveZap repo, who wants a working preview of the current code on this platform.

## Core features and experience
- The full repo is imported as it stands today: all files, branches left alone, no features removed.
- The app runs in the preview with its current features and screens.
- Fixes are limited to what stops it from starting, such as missing dependencies, environment settings, ports, or the API address. Each fix is listed afterwards.
- Bugs in features that don't stop the app from starting are written down for you but not fixed.

## User flow
1. You make the repo public on GitHub, or tell me if the code is somewhere else.
2. The code is imported and checked to see what it's built with.
3. The app is started. If something stops it from starting, I make the smallest fix that solves it.
4. You get a working preview link, a list of every change I made, and a list of any other problems I found.

## UI/UX feel
No change. The app keeps its current look and layout.

## Implementation phases
- **Phase 1 (MVP, built now):** Import the repo, set up what it needs, get the frontend and backend running in the preview, and confirm the main screens load.
- **Phase 2:** Fix the bugs found in Phase 1, if you approve.
- **Phase 3:** Add new features or changes you ask for.

## Assumptions
- The repo will be public before the build starts. If it still can't be reached, the build stops and asks you for access instead of guessing at the code.
- "FiveZap3" is the project's name or version, not a description of what it does. The code itself shows what the app is.
- If the project's stack doesn't match this workspace's setup (React + Python backend + MongoDB), it gets the smallest changes that let it run. Nothing gets rewritten.
- If the app needs outside services (payments, messaging, AI, login, and so on), they won't work until you add the real keys through the secure keys card. Any feature waiting on a key is labelled clearly, never faked.
- If the code has its own database contents or seed data, they get loaded. If not, the app starts with an empty database.
