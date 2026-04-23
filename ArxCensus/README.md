# ArxCensus

A simple Android app for Zebra handhelds that lists every installed app along
with how much space it's taking (APK, data, cache, and the total). Intended to
be deployed via Workspace ONE.

## What it does

- Enumerates installed packages via `PackageManager.getInstalledApplications`.
- For each package, queries `StorageStatsManager.queryStatsForPackage` to get
  `appBytes`, `dataBytes`, and `cacheBytes`.
- Sorts by total size (largest first) and shows a per-app row plus a summary
  header (`N apps · X.XX GB total`).
- Pull-to-refresh rescans on demand; the list also rescans on `onResume`.

## Requirements

- Android 8.0 / API 26+ (required by `StorageStatsManager`).
- Permissions declared in the manifest:
  - `QUERY_ALL_PACKAGES` — so the app can see every package on Android 11+.
  - `PACKAGE_USAGE_STATS` — an **appop** (special access) permission. The
    system will not grant it at install time; it must either be granted by
    the user from *Settings → Apps → Special access → Usage access*, or
    pre-granted by the MDM (recommended for fleet devices — see below).

## Building

```
cd ArxCensus
./gradlew assembleRelease
```

The APK lands at `app/build/outputs/apk/release/app-release-unsigned.apk`.
Sign it with your enterprise signing key before pushing through Workspace ONE:

```
apksigner sign --ks your-keystore.jks \
  --out ArxCensus-1.0.apk \
  app/build/outputs/apk/release/app-release-unsigned.apk
```

> The Gradle wrapper JAR (`gradle/wrapper/gradle-wrapper.jar`) is not checked
> in — run `gradle wrapper` once in this directory to generate it, or open the
> project in Android Studio which will do it for you.

## Deploying via Workspace ONE (Zebra)

1. **Upload the signed APK** to Workspace ONE UEM as an *Internal Application*
   and assign it to your Zebra device smart group.
2. **Pre-grant the Usage Access appop** so users don't have to flip the switch
   themselves. Workspace ONE exposes this under the app's *Deployment →
   Application Configuration* / *App permissions* settings — or you can push a
   custom XML profile that issues the `appops` command. On Zebra devices this
   is commonly done with the MX (Mobility Extensions) AppManager profile, or
   with a run-once command:

   ```
   appops set com.kroger.mobeng.arx.census GET_USAGE_STATS allow
   ```

   Workspace ONE's "Run Intent" / "Custom Settings" profile or a StageNow
   barcode both work. Without this, the app will still run, but the user will
   see a banner prompting them to open *Usage Access settings* and enable it
   manually.
3. (Optional) If you want the app locked down as the only thing users can
   launch, add it to your Workspace ONE **Launcher** profile as a whitelisted
   app.

## Project layout

```
ArxCensus/
├── build.gradle.kts              Root Gradle script (AGP + Kotlin plugins)
├── settings.gradle.kts           Single-module project settings
├── gradle.properties
├── gradle/wrapper/…              Wrapper properties (JAR generated on first build)
└── app/
    ├── build.gradle.kts          App module config (compileSdk 34, minSdk 26)
    ├── proguard-rules.pro
    └── src/main/
        ├── AndroidManifest.xml
        ├── java/com/kroger/mobeng/arx/census/
        │   ├── AppStorageInfo.kt     Data class for one row
        │   ├── ByteFormat.kt         Bytes → human-readable string
        │   ├── MainActivity.kt       Screen + permission handling
        │   ├── StorageAdapter.kt     RecyclerView adapter
        │   ├── StorageRepository.kt  Queries PackageManager + StorageStatsManager
        │   └── UsageAccess.kt        Appop permission check + settings intent
        └── res/                  Layouts, strings, adaptive icon, theme
```

## Notes / limitations

- `StorageStatsManager` reports zero `appBytes` for a handful of heavily
  compressed system packages; these are still listed but sink to the bottom
  of the sort.
- The list does **not** include external/OBB storage. If you need that, add
  a `statsManager.queryExternalStatsForUser(...)` call in
  `StorageRepository` and add its fields to `AppStorageInfo`.
- No background collection / upload — this is a read-on-demand on-device
  report only. Extend `StorageRepository` if you need to POST the report to
  a backend.
