package com.animan.app

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import com.arthenica.ffmpegkit.FFmpegKitConfig

/** A package name or a listed filter is insufficient: encode, decode and inspect pixels. */
object HardsubProbe {
    private var cached: String? = null
    private fun run(tool: String, vararg args: String): String {
        val result = JSONObject(MediaBridge.execute(tool, JSONArray(args.toList()).toString(), 30000))
        check(!result.optBoolean("timedOut") && result.getInt("returncode") == 0) { "Native hardsub command failed" }
        return result.getString("stdout")
    }
    @Synchronized fun probe(directory: String): String {
        cached?.let { return it }
        val root = File(directory)
        val result = JSONObject().put("available", false).put("renderVerified", false)
        var stage = "directory"
        try {
            check(root.isDirectory)
            stage = "filters"
            val filters = run("ffmpeg", "-hide_banner", "-filters")
            val encoders = run("ffmpeg", "-hide_banner", "-encoders")
            check(Regex("(?m)^\\s*[A-Z.]+\\s+subtitles\\s").containsMatchIn(filters))
            check(Regex("(?m)^\\s*[A-Z.]+\\s+libx264\\s").containsMatchIn(encoders))
            check(Regex("(?m)^\\s*[A-Z.]+\\s+aac\\s").containsMatchIn(encoders))
            stage = "font_registration"
            val font = listOf("Roboto-Regular.ttf", "NotoSans-Regular.ttf")
                .map { File("/system/fonts", it) }.firstOrNull { it.isFile }
                ?: requireNotNull(File("/system/fonts").listFiles()?.firstOrNull {
                    it.isFile && it.name.endsWith(".ttf") && (it.name.startsWith("Roboto") || it.name.startsWith("NotoSans-"))
                })
            // Android has no default fontconfig configuration. Merely passing
            // fontsdir can silently produce a valid video with no subtitle pixels.
            // Keep the registered directory alive after the temporary probe ends.
            FFmpegKitConfig.setFontDirectory(EngineHost.context, "/system/fonts", null)
            val fonts = File(root, "fonts").apply { mkdirs() }
            font.copyTo(File(fonts, "probe.ttf"), overwrite = true)
            val sub = File(root, "probe.srt").apply {
                writeText("1\n00:00:01,000 --> 00:00:02,000\nANIMELAB P14\n")
            }
            val video = File(root, "probe.mp4")
            fun escaped(path: File): String {
                val first = path.canonicalPath.flatMap { if (it in "\\': \t\n") listOf('\\', it) else listOf(it) }.joinToString("")
                return first.flatMap { if (it in "\\'[],; \t\n") listOf('\\', it) else listOf(it) }.joinToString("")
            }
            stage = "encoding"
            run("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:r=10",
                "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", "-vf",
                "subtitles=filename=${escaped(sub)}:fontsdir=${escaped(fonts)}",
                "-c:v", "libx264", "-threads", "1", "-filter_threads", "1", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-sn", video.path)
            stage = "stream_metadata"
            val streams = JSONObject(run("ffprobe", "-v", "error", "-show_streams", "-of", "json", video.path)).getJSONArray("streams")
            val codecs = (0 until streams.length()).map { streams.getJSONObject(it).getString("codec_name") }
            check(codecs.toSet() == setOf("h264", "aac") && streams.length() == 2)
            fun frame(time: String, name: String): ByteArray {
                val file = File(root, name)
                run("ffmpeg", "-v", "error", "-y", "-ss", time, "-i", video.path, "-frames:v", "1",
                    "-threads", "1", "-pix_fmt", "gray", "-f", "rawvideo", file.path)
                return file.readBytes().also { check(it.size == 320 * 180) }
            }
            stage = "frame_decoding"
            val before = frame("0.2", "before.gray")
            val during = frame("1.2", "during.gray")
            val difference = before.indices.sumOf { kotlin.math.abs((during[it].toInt() and 255) - (before[it].toInt() and 255)).toLong() }
            stage = "rendered_pixels"
            check(difference > 10000) { "Subtitle pixels were not rendered" }
            result.put("available", true).put("renderVerified", true).put("fontPath", font.path)
                .put("pixelDifference", difference).put("reason", "")
        } catch (_: Exception) {
            result.put("reason", "JNI libass/libx264/AAC/font or rendered-pixel validation failed")
                .put("reasonCode", "hardsub_" + stage + "_failed")
        } finally {
            listOf("probe.srt", "probe.mp4", "before.gray", "during.gray", "fonts").forEach { File(root, it).deleteRecursively() }
        }
        return result.toString().also { cached = it }
    }
}
