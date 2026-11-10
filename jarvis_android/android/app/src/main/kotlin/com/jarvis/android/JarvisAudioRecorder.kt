package com.jarvis.android

import android.content.Context
import android.media.MediaRecorder
import android.os.Build
import android.os.Environment
import android.util.Log
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * JarvisAudioRecorder handles voice recording on-demand ("recoder ဖွင့်ပြီးအသံဖမ်းပေးပါ", "ပိတ်မယ်").
 */
class JarvisAudioRecorder(private val context: Context) {

    companion object {
        private const val TAG = "JarvisAudioRecorder"
        @Volatile
        private var mediaRecorder: MediaRecorder? = null
        @Volatile
        private var currentFilePath: String? = null
        @Volatile
        private var recordStartTime: Long = 0

        val isRecording: Boolean
            get() = mediaRecorder != null
    }

    /**
     * Start native voice recording.
     * Order of operations:
     * 1. Prepare directory and output file (create parent folder if missing).
     * 2. Initialize MediaRecorder: audio source, output format, encoder, sampling rate, bit rate, output file.
     * 3. prepare() -> start(). If anything fails, log exact exception and return failure.
     * 4. Verify start succeeded and isRecording == true before returning "စဖမ်းနေပါပြီ".
     * 5. If failed, return failure with exact error details (never swallow exceptions).
     */
    fun startRecording(): Map<String, Any> {
        if (isRecording) {
            Log.w(TAG, "startRecording called while already recording: $currentFilePath")
            return mapOf(
                "success" to true,
                "isRecording" to true,
                "message" to "စဖမ်းနေပါပြီ",
                "filePath" to (currentFilePath ?: "")
            )
        }

        var mr: MediaRecorder? = null
        try {
            // 1. Ensure target directory exists
            val publicDir = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MUSIC), "JarvisRecordings")
            if (!publicDir.exists()) {
                val created = publicDir.mkdirs()
                Log.d(TAG, "Created public recordings folder: $created, path: ${publicDir.absolutePath}")
            }

            val targetDir = if (publicDir.exists() && publicDir.canWrite()) {
                publicDir
            } else {
                val fallback = File(context.getExternalFilesDir(Environment.DIRECTORY_MUSIC), "JarvisRecordings")
                if (!fallback.exists()) {
                    val fbCreated = fallback.mkdirs()
                    Log.d(TAG, "Created fallback app recordings folder: $fbCreated, path: ${fallback.absolutePath}")
                }
                fallback
            }

            val timestamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault()).format(Date())
            val file = File(targetDir, "JARVIS_REC_$timestamp.m4a")
            currentFilePath = file.absolutePath
            Log.d(TAG, "Configuring MediaRecorder for output file: ${file.absolutePath}")

            // 2. Instantiate and configure MediaRecorder in exact required order
            mr = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                MediaRecorder(context)
            } else {
                @Suppress("DEPRECATION")
                MediaRecorder()
            }

            mr.setAudioSource(MediaRecorder.AudioSource.MIC)
            mr.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            mr.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
            mr.setAudioSamplingRate(44100)
            mr.setAudioEncodingBitRate(128000)
            mr.setOutputFile(file.absolutePath)

            // 3. prepare() -> start()
            Log.d(TAG, "Calling MediaRecorder.prepare()...")
            mr.prepare()
            Log.d(TAG, "prepare() succeeded. Calling MediaRecorder.start()...")
            mr.start()
            Log.d(TAG, "start() succeeded.")

            mediaRecorder = mr
            recordStartTime = System.currentTimeMillis()

            // 4. Verify start succeeded and isRecording is true
            val active = isRecording
            if (active) {
                Log.d(TAG, "MediaRecorder start verified successfully: isRecording=true, file=${file.absolutePath}")
                return mapOf(
                    "success" to true,
                    "isRecording" to true,
                    "message" to "စဖမ်းနေပါပြီ",
                    "filePath" to file.absolutePath
                )
            } else {
                Log.e(TAG, "MediaRecorder start called but isRecording returned false")
                mediaRecorder = null
                currentFilePath = null
                return mapOf(
                    "success" to false,
                    "isRecording" to false,
                    "message" to "အသံဖမ်းမရပါ: Recorder မစတင်နိုင်ပါ",
                    "filePath" to ""
                )
            }
        } catch (e: Exception) {
            val exDetails = "${e.javaClass.simpleName}: ${e.message}"
            Log.e(TAG, "MediaRecorder start failed with exception: $exDetails", e)
            try {
                mr?.reset()
                mr?.release()
            } catch (_: Exception) {}
            mediaRecorder = null
            currentFilePath = null
            return mapOf(
                "success" to false,
                "isRecording" to false,
                "exception" to exDetails,
                "message" to "အသံဖမ်းမရပါ: $exDetails"
            )
        }
    }

    /**
     * Stop native voice recording.
     * Order of operations:
     * 1. Check if recording is active.
     * 2. Call stop() and release().
     * 3. Verify file exists, size > 0, and duration.
     * 4. If file exists and size > 0, return "ရပ်ပါပြီ၊ X စက္ကန့်စာ သိမ်းပြီးပါပြီ".
     * 5. If file missing or size <= 0, return "ဖိုင်မသိမ်းမိပါ".
     */
    fun stopRecording(): Map<String, Any> {
        if (!isRecording) {
            Log.w(TAG, "stopRecording called but isRecording=false")
            return mapOf(
                "success" to false,
                "message" to "လက်ရှိတွင် အသံဖမ်းယူနေခြင်း မရှိပါ ခင်ဗျာ။"
            )
        }

        return try {
            val mr = mediaRecorder
            mediaRecorder = null
            Log.d(TAG, "Calling MediaRecorder.stop()...")
            mr?.stop()
            mr?.release()
            Log.d(TAG, "MediaRecorder stopped and released successfully.")

            val durationSec = ((System.currentTimeMillis() - recordStartTime) / 1000).coerceAtLeast(1)
            val path = currentFilePath ?: ""
            currentFilePath = null

            val file = File(path)
            val fileExists = file.exists()
            val fileSize = if (fileExists) file.length() else 0L

            Log.d(TAG, "stopRecording inspection: fileExists=$fileExists, fileSize=$fileSize bytes, duration=${durationSec}s, path=$path")

            if (fileExists && fileSize > 0L) {
                try {
                    android.media.MediaScannerConnection.scanFile(
                        context,
                        arrayOf(path),
                        arrayOf("audio/m4a", "audio/mp4", "audio/*"),
                        null
                    )
                } catch (se: Exception) {
                    Log.w(TAG, "MediaScanner indexing exception: ${se.message}")
                }

                mapOf(
                    "success" to true,
                    "durationSeconds" to durationSec,
                    "filePath" to path,
                    "fileExists" to true,
                    "fileSizeBytes" to fileSize,
                    "message" to "ရပ်ပါပြီ၊ $durationSec စက္ကန့်စာ သိမ်းပြီးပါပြီ"
                )
            } else {
                Log.e(TAG, "Recording file missing or empty: exists=$fileExists, size=$fileSize bytes, path=$path")
                mapOf(
                    "success" to false,
                    "fileExists" to false,
                    "fileSizeBytes" to fileSize,
                    "message" to "ဖိုင်မသိမ်းမိပါ"
                )
            }
        } catch (e: Exception) {
            val exDetails = "${e.javaClass.simpleName}: ${e.message}"
            Log.e(TAG, "MediaRecorder stop failed with exception: $exDetails", e)
            mediaRecorder = null
            currentFilePath = null
            mapOf(
                "success" to false,
                "exception" to exDetails,
                "message" to "အသံဖမ်းမရပါ: $exDetails"
            )
        }
    }
}
