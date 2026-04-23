package com.arx.census

import android.app.usage.StorageStatsManager
import android.content.Context
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.os.Process
import android.os.UserHandle
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class StorageRepository(private val context: Context) {

    private val pm: PackageManager = context.packageManager
    private val statsManager: StorageStatsManager =
        context.getSystemService(Context.STORAGE_STATS_SERVICE) as StorageStatsManager
    private val userHandle: UserHandle = Process.myUserHandle()

    suspend fun loadAll(): List<AppStorageInfo> = withContext(Dispatchers.IO) {
        val apps = pm.getInstalledApplications(PackageManager.GET_META_DATA)
        apps.mapNotNull { info -> query(info) }
            .sortedByDescending { it.totalBytes }
    }

    private fun query(info: ApplicationInfo): AppStorageInfo? {
        return try {
            val uuid = info.storageUuid
            val stats = statsManager.queryStatsForPackage(uuid, info.packageName, userHandle)
            AppStorageInfo(
                packageName = info.packageName,
                label = pm.getApplicationLabel(info).toString(),
                icon = runCatching { pm.getApplicationIcon(info) }.getOrNull(),
                isSystem = (info.flags and ApplicationInfo.FLAG_SYSTEM) != 0,
                appBytes = stats.appBytes,
                dataBytes = stats.dataBytes,
                cacheBytes = stats.cacheBytes
            )
        } catch (t: Throwable) {
            // Some system packages can throw; skip them rather than fail the whole scan.
            Log.w(TAG, "Failed to query ${info.packageName}: ${t.message}")
            null
        }
    }

    companion object {
        private const val TAG = "StorageRepository"
    }
}
