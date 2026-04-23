package com.arx.census

import java.util.Locale

object ByteFormat {
    private val units = arrayOf("B", "KB", "MB", "GB", "TB")

    fun human(bytes: Long): String {
        if (bytes <= 0L) return "0 B"
        var value = bytes.toDouble()
        var unit = 0
        while (value >= 1024.0 && unit < units.lastIndex) {
            value /= 1024.0
            unit++
        }
        val pattern = if (unit >= 2) "%.2f %s" else "%.0f %s"
        return String.format(Locale.US, pattern, value, units[unit])
    }
}
