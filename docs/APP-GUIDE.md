# App guide

camp helps coworkers choose workplace meals and coordinate delivery. It uses a shared backend for groups and orders, with a Mac menu-bar workspace and notch panel plus an iPhone app with Live Activities.

## Ordering together

camp has two order categories: **Coffee & tea** and **Meal**. A person can have one active order in each category per day, so a coffee run and lunch can happen separately.

On **Today**, browse office groups, start a group at a catalog restaurant, or join an existing one. **View menu** shows the full menu, public rating, and recommender picks. Choose multiple items, such as a main and drink, then join. The group shares one delivery fee per person rather than charging a separate delivery share for each item. Your selected items count toward the per-order budget; the first item is always allowed, and additional items must fit.

Use **Craving something else?** to describe a dish or cuisine in your own words. camp searches its catalog for matching restaurants and menu items. With an OpenAI key, an LLM interprets the request; without one, a keyword matcher keeps the flow working. Results come from the catalog, so the model does not invent restaurants or prices.

The Today page also shows your confirmed orders, group size, and estimated delivery-fee savings. When no groups exist, the backend can seed synthetic demo groups so the office view has examples to explore.

## Screens and settings

The Mac workspace has **Today**, **You**, **Office**, **Spending**, **Connections**, and **Demo** sections. The iPhone uses **Today**, **You**, and **Spending** tabs, with the other sections under **More**.

- **You** stores food preferences, meal timing, and standing orders. A standing order can specify its category, time, weekdays, and usual place or item. A due occurrence is created when Today refreshes; there is no background schedule runner.
- **Office** holds demo-admin controls, office geofence, budgets, and group-order rules. Some policy settings are for the prototype UI and are not server authorization.
- **Spending** shows the backend order ledger in a card-style view; it is not a live payment card. **Demo** contains the onboarding launcher, recommendation setup and debug views, plus the Ramp sandbox bridge for inspecting employees and creating a bounded test fund.
- **Connections** configures Mac location and calendars. Permissions and selections stay on the device. See [location setup](LOCATION.md) and [calendar setup](CALENDAR.md).
- **Save** syncs supported profile preferences to the backend. Device permissions, geofence confirmation, calendar choices, and connection settings remain local.

### Onboarding

The once-per-person setup — name and diet, meal window, calendars, office policy, and the backend address this device uses — is a separate flow shared by the Mac and the iPhone. It never appears on its own: a first launch lands on Today, and **Demo → Launch onboarding** is the only way in, so a demo shows it deliberately. Finishing writes the answers to the laptop's database (`PUT /v1/onboarding`, which also applies the recommender-relevant parts to the user row the way `PUT /v1/profile` does) as well as to this device's settings file. Opening the flow reads that row back (`GET /v1/onboarding`), so whichever device goes second starts from the answers the first one gave; each device keeps its own backend address, since the phone reaches the laptop over the cable's network rather than loopback. Everything stays editable afterwards in You / Office / Connections. **Mark unfinished** clears the completed flag but keeps the answers, so the flow can be shown again.

The Mac **iPhone layout preview** is a compact workspace preview, not an iOS simulator. Run the iPhone app to try actual ActivityKit behavior; see [iPhone development](IOS.md).

## Mac panel and iPhone Live Activity

The Mac notch panel presents a lunch invitation or group choice without opening a full window. The menu-bar icon can reopen a collapsed choice. On iPhone, a successful group join starts a Live Activity with controls that return to the Today page. The apps share active order state through the backend while camp is running and the phone app is in the foreground.

For an end-to-end device rehearsal, follow the [Mac and iPhone demo runbook](DEMO.md). The Mac panel is an app window rather than a system notification. iPhone background updates require APNs integration, which is not part of this prototype.

## Current limits

- Restaurant and menu prices are catalog estimates, not live delivery quotes.
- camp does not submit restaurant orders or charge a payment method.
- Ramp is connected to its sandbox only; a sandbox fund is spending permission, not a food purchase.
- Office policy controls and demo-admin mode are prototype controls, not an employee authorization system.
- The app currently uses a single implicit demo identity for shared sessions.
