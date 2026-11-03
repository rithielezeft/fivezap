# FiveZap: Import and Run As-Is

Bring the existing FiveZap project from GitHub (rithielezeft/fivezap) into this workspace and get it running here.
Features, look and behaviour stay the same as the original code. The only changes are the ones it needs to run here.

## Who it's for
- The FiveZap owner, who wants a working, previewable copy of the existing project on this platform.
- FiveZap's current users. Nothing they see or use should change.

## Core features and experience
- Every page, screen and feature that's already in the repository, unchanged.
- Changes are limited to what it takes to start the app here: connecting it to this platform's database and web address, installing missing pieces, and fixing anything that stops it from starting or loading.
- If the project uses outside services (payments, messaging such as WhatsApp, AI, email), they're reconnected to work the same way. Any keys they need are requested through a secure card, never in chat.
- No new features, no redesign and no cleanup beyond what's needed to run.

## User flow
1. The owner makes the GitHub repository public. It currently shows "page not found", so it's either private or the name is different.
2. The project is imported exactly as it is.
3. The app is started and opened in the preview link.
4. The owner checks that it looks and works as expected.
5. Afterwards the repository can go back to private.

## UI/UX feel
- Same as the original: same layout, colours, fonts and text. Nothing is restyled.

## Implementation phases
- **Phase 1 (MVP, built now):** Import the code, make the minimum changes needed to run here, reconnect any outside services, and confirm the main screens and flows work in the preview.
- **Phase 2:** Fix any bugs the owner finds after trying the running copy.
- **Phase 3:** Add new features or improvements the owner asks for.

## Assumptions
- The repository will be public under the name "rithielezeft/fivezap". If the name is different, the correct link is needed.
- "As it is" means no visual or feature changes. A change is made only when the app can't run without it.
- If parts of the project are written for a setup this platform doesn't support, they're converted to the closest working equivalent, and screens and behaviour stay the same.
- Outside services keep their original providers. If a key is missing, that feature is clearly marked as not connected until the key is provided.
- Existing data in the original live system isn't copied over. The copy here starts with an empty database unless the repository includes its own sample data.
