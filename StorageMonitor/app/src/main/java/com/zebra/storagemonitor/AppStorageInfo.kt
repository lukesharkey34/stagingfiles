package com.zebra.storagemonitor

import android.graphics.drawable.Drawable

data class AppStorageInfo(
    val packageName: String,
    val label: String,
    val icon: Drawable?,
    val isSystem: Boolean,
    val appBytes: Long,
    val dataBytes: Long,
    val cacheBytes: Long
) {
    val totalBytes: Long get() = appBytes + dataBytes + cacheBytes
}
