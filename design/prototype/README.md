# Payables Desk prototype

A clickable prototype of the Bonded Payables Agent web app: every screen, with sample data, so a frontend developer
can see exactly what to build. Everything runs in the browser; nothing talks to a server or a blockchain.

**Open it:** double-click `index.html` (any modern browser), or view it online:
https://claude.ai/artifact/66yyDr5y9PSM1xsDcmRyyu (the owner must share the link first).

## Screens

| Route | Screen | What to try |
| --- | --- | --- |
| `#landing` | Marketing page | Hero with the waving clerk and cycling speech bubble, proof numbers, the clerk's first month, how it works, safety split screen, the dial, call to action |
| `#login` | Wallet login | Pick Owner, Finance manager or Look around (viewer), then a wallet. Tick "simulate the wallet rejecting" to see the error |
| `#desk` | The desk | Request bar with suggestions; queue (Needs you), inbox, monthly tally, detail panel |
| `#risk` | Risk and reserve | Four settings; owner can make one active (fake wallet); reserve chart |
| `#security` | Security | "Send the invoice to both" runs the drain-vs-refusal demo; pause, resume, frozen payees, red-team results |
| `#activity` | Activity | Journal that fills as you act (filter by who, security only); tasks and contracts tab |
| `#settings` | Settings (owner) | Payees with cool-down and frozen states, reserve mode, reset the demo |
| anything else | Page not found | |

## Flows worth clicking through

1. **Order → plan → run:** on the desk, tap "Pay everything from Acme…", then Run. Three bills pay one by one; the
   fourth goes to Needs you. Try "Cancel the rest" mid-run.
2. **One question:** "Pay the copper supplier" asks which of three suppliers.
3. **Refusals:** "Add a new bank account for Acme" (can't do that); as the manager, "Be more careful this month"
   (owner only).
4. **Sign a held bill (as Finance manager):** open Acme Metals in Needs you, review the fair-price card, Sign and
   pay, approve in the fake wallet. Reject in the wallet to see the cancelled state.
5. **Supplier query:** on the same bill, "Ask the supplier", Send, "Paste the sample reply", Record reply.
6. **Inbox:** take in Kai Tak (paid on its own), both Sun Kee copies (paid early, then the duplicate is stopped),
   Harbour Lubricants (scheduled), the Lion Rock email (agent freezes the payee and opens a case), the look-alike
   email (refused), the Shatin statement (opens a missed-credit case).
7. **Missed credit:** open the Shatin case, Confirm and sign (two wallet signatures), then Pay out the claim (dispute
   window still open) and Skip the window.
8. **Edge cases:** the "Prototype states" button (bottom left, inside the app) switches role and turns on: agent
   paused, server unreachable, wallet on the wrong network, ledger mismatch. The header role chip also switches role.

## Design system

- **Colours:** page `#F6F5FF`, surface `#FFFFFF`, sunk `#EEECFF`, line `#DAD6FB`, ink `#1E1B4B`, body `#4A4775`,
  muted `#6B6799`, primary `#4B3BD6` (hover `#3C2EB8`), done `#1F4CB8` on `#DCE8FF`, attention `#3C2EB8` on
  `#E4E0FF`, stop `#7A2E9E` on `#F1E4FB`, focus ring `#9CC3FF`. Status always pairs colour with words.
- **Type:** Fredoka (display), Nunito Sans (body), IBM Plex Mono (hashes, labels). Google Fonts.
- **Radius:** 10 controls, 16 cards, 999 pills. Buttons are 44 px tall minimum.
- **Rules:** money always comes from the API (two decimals on bills); nothing moves without a click; errors sit
  under the action that failed; supplier text is shown escaped and labelled "supplier says"; say "reserve" or
  "bond", never "insurance".

All tokens are the `:root` block at the top of `index.html`.

## Characters and motion

`assets/` holds every character as a standalone, self-animating SVG (CSS keyframes inside the file):

- The clerk: `clerk-idle`, `clerk-wave`, `clerk-stop`, `clerk-think`, `clerk-magnify`, `clerk-sheepish`, `clerk-cheer`
- The con artist: `con-artist-smirk`, `-grin`, `-unsure`, `-defeated`
- People and props: `owner`, `finance-manager`, `supervisor`, `vault`, `checklist`, `bank`, `logo-mark`, `favicon`

Loops: body bob, eye blink, waving arm, antenna and con-artist sway. All motion stops under
`prefers-reduced-motion`. These are SVG + CSS, not Lottie JSON. To get Lottie files, import the SVGs into
LottieFiles or After Effects (Bodymovin) and rebuild the loops; the parts are separate shapes, so they animate
cleanly.

Effects modelled on React Bits components, written here in plain JavaScript and CSS so the prototype has no
dependencies. In the React app, use the real components:

| Here | React Bits component |
| --- | --- |
| Hero headline words resolving from blur | BlurText |
| Cursor-following glow on feature cards | SpotlightCard |
| Proof numbers and risk stats counting up | CountUp |
| Sparks on button clicks | ClickSpark |
| "Topic F" shimmer | ShinyText |
| Soft moving colour behind the hero | Aurora |

## Mapping to the real app

The real frontend is in `web/` (React, TypeScript, Vite, Tailwind, wagmi/viem, TanStack Query). The API calls behind
each screen are listed on the design canvas: https://claude.ai/artifact/8rknqW24q6hSnzTb1oHJck. A few states here are
proposals the API doesn't support yet: the global banners (server down, ledger mismatch, wrong network), the Settings
page, and actions on credit or charge cases with no bill.

All companies, suppliers, amounts and hashes are sample data from a fictional demo company on a test network.
