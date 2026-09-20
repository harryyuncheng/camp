# Mac and iPhone demo runbook

camp coordinates estimated orders in its database. Ramp creates sandbox spending allocations;
no restaurant checkout or payment is performed. Use one backend process for this demo.

## Prepare the apps

On a Mac with compatible Xcode installed:

```sh
cp Config/Local.xcconfig.example Config/Local.xcconfig
# Edit Local.xcconfig: set your DEVELOPMENT_TEAM and unique BUNDLE_ID_PREFIX.
xcrun swift test --disable-sandbox
bash scripts/build-mac.sh
bash scripts/build-ios.sh
```

The local signing file is ignored by Git and applies to both iOS targets. Open `Lunchline.xcodeproj`,
choose Lunchline and a trusted phone with Developer Mode enabled, then Run. An unsigned simulator
build checks compilation; it does not prove signing, device preparation or Live Activity behavior.

## Connect through USB-C

A USB-C cable used for charging or Xcode installation does not itself provide camp's HTTP transport.
The intended route is **USB Personal Hotspot**:

1. Use a data-capable cable, trust the Mac on the phone, and enable Personal Hotspot on the iPhone.
   Availability depends on the carrier/plan. Follow Apple's
   [Personal Hotspot instructions](https://support.apple.com/en-us/111785).
2. Confirm that **iPhone USB** is connected in the Mac's Network settings. On the Mac,
   `networksetup -listallhardwareports` identifies its interface; `ipconfig getifaddr <interface>`
   returns the **Mac's** address on that interface. Do not use the phone's gateway address.
3. Allow camp's Local Network permission on iPhone and the backend through the Mac firewall.
4. Configure the iPhone with the Mac's USB-interface address and port 8788. The Mac app can use
   `http://127.0.0.1:8788`; both must use the same backend and token.

This USB networking path requires a physical rehearsal. If no iPhone USB interface appears, a
shared Wi-Fi network is the fallback; keep the same database and token. USB-C does not remove the
need for reconnect handling, and it does not grant iOS background execution. Keep camp foregrounded
on the phone for incoming changes; returning to the foreground refreshes the Lock Screen state.

## Start the database and backend

From the repository root:

```sh
cd backend
uv sync --frozen --extra dev
export CAMP_DB="$PWD/camp-demo.db"
export CAMP_DATABASE_URL=""  # Select the SQLite file for this run.
export CAMP_TOKEN="$(uv run python -c 'import secrets; print(secrets.token_urlsafe(32))')"
uv run camp serve --host 0.0.0.0 --port 8788
```

Keep this shell and token for the rehearsal. Enter the token in **Demo → Recommendation service**
on Mac and **More → Demo → Recommendation service** on iPhone. Do not commit it. To use PostgreSQL,
set `CAMP_DATABASE_URL` instead; it takes precedence over `CAMP_DB`. Changing that URL/file changes
the database and therefore the user's visible history.

In another shell with the same token configured:

```sh
curl --fail -H "X-Camp-Token: $CAMP_TOKEN" http://127.0.0.1:8788/v1/health
```

Without the header this returns 401. If phone requests fail, check the interface address, port,
firewall, Local Network permission and token before changing app state. Never run multiple workers:
database transactions serialize writes, but sync notifications and Ramp coordination are local to
one process.

## Rehearse the golden path

These are acceptance checks, not a claim of completed physical-device testing.

1. Save the same office on both devices and use the same demo identity. Refresh Today.
2. Open a full menu and join with a main plus a side. Check both selected names, the server-returned
   estimate and **one** delivery share. A single item may exceed the cap; additional items must fit.
3. Confirm on Mac, foreground camp on the phone, and check the same selection. Lock the phone and
   verify its Live Activity. Use a stale button after changing the order; it should not overwrite
   the newer revision.
4. Leave a standing-order occurrence and refresh Today. It should remain skipped today while
   the standing schedule remains available for future dates.
5. Stop/restart the backend without changing the database or token. Refresh both apps and verify
   membership, cart, spending history and shared session survive. Relaunch the apps too.
6. Disconnect/reconnect the cable. Try a join while offline: keep the failure visible and retry
   after reconnecting. Do not call a pending mutation successful.
7. Stop with the confirmed database order and estimate. Clearly identify any Ramp action as a
   sandbox allocation; it is not a food purchase.

The shared-session stream currently represents one implicit demo user. It is not an isolated
multi-employee account system. Calendar IDs and permission state belong to the local device.

## Automated checks

GitHub Actions runs backend correctness lint, limited model/contract type checking, tests on
SQLite and PostgreSQL, package build, Swift tests, a Mac release build and an unsigned iOS
simulator build. See each run's actual status before treating it as validation. Device signing,
visual layout, calendar/location permissions, background behavior and the USB link still need
the rehearsal above.
