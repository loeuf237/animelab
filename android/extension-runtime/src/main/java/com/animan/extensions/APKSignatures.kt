package com.animan.extensions

import android.content.pm.PackageInfo
import java.security.MessageDigest

object APKSignatures {
    private fun digest(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    /** Bind trust to the entire set of current signers, not one arbitrary member. */
    fun current(info: PackageInfo): String {
        val values=requireNotNull(info.signingInfo).apkContentsSigners.map { digest(it.toByteArray()) }.sorted()
        require(values.isNotEmpty())
        return if(values.size==1) values[0] else digest(values.joinToString(":").toByteArray(Charsets.UTF_8))
    }
    fun history(info: PackageInfo): List<String> {
        val signing=requireNotNull(info.signingInfo)
        val values=if(signing.hasMultipleSigners()) signing.apkContentsSigners else signing.signingCertificateHistory
        return values.map { digest(it.toByteArray()) }
    }
}
