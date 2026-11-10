package com.jarvis.android

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.media.MediaActionSound
import android.media.MediaScannerConnection
import android.os.Bundle
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * CameraActivity provides Jarvis's native CameraX preview and photo capture directly,
 * saving photos to Gallery (DCIM/Camera) with shutter sound, visual indicator, and MediaStore indexing.
 */
class CameraActivity : ComponentActivity() {

    companion object {
        private const val TAG = "JarvisCamera"
    }

    private var imageCapture: ImageCapture? = null
    private lateinit var previewView: PreviewView
    private lateinit var flashOverlay: View
    private lateinit var statusText: TextView
    private var isCapturing = false
    private var lensFacing: Int = CameraSelector.LENS_FACING_BACK

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // 1. Check Camera Permission
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            Log.w(TAG, "Camera permission not granted in CameraActivity")
            finish()
            return
        }

        // Determine requested camera lens (back or front)
        val camExtra = intent.getStringExtra("camera") ?: intent.getStringExtra("lens") ?: "back"
        val isFront = camExtra.lowercase().contains("front") ||
                      camExtra.lowercase().contains("selfie") ||
                      camExtra.contains("ရှေ့")
        lensFacing = if (isFront) CameraSelector.LENS_FACING_FRONT else CameraSelector.LENS_FACING_BACK
        Log.d(TAG, "CameraActivity created with requested camera: '$camExtra' -> lensFacing: ${if (lensFacing == CameraSelector.LENS_FACING_FRONT) "FRONT" else "BACK"}")

        // 2. Build Programmatic Camera Preview UI
        val rootLayout = FrameLayout(this).apply {
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
            setBackgroundColor(Color.BLACK)
        }

        // CameraX PreviewView
        previewView = PreviewView(this).apply {
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
        }
        rootLayout.addView(previewView)

        // White Flash overlay for shutter animation
        flashOverlay = View(this).apply {
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
            setBackgroundColor(Color.WHITE)
            alpha = 0f
        }
        rootLayout.addView(flashOverlay)

        // Top Header Overlay
        val headerLayout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.WRAP_CONTENT
            ).apply {
                topMargin = (resources.displayMetrics.density * 48).toInt()
            }
        }

        val titleText = TextView(this).apply {
            text = "JARVIS CAMERA"
            setTextColor(Color.parseColor("#00E5FF"))
            textSize = 20f
            typeface = Typeface.DEFAULT_BOLD
            gravity = Gravity.CENTER
        }
        headerLayout.addView(titleText)

        val lensNameBurmese = if (lensFacing == CameraSelector.LENS_FACING_FRONT) "ရှေ့ကင်မရာ (Front)" else "နောက်ကင်မရာ (Back)"
        statusText = TextView(this).apply {
            text = "$lensNameBurmese ဖြင့် ဓာတ်ပုံရိုက်ကူးရန် အဆင်သင့်ဖြစ်ပါသည်..."
            setTextColor(Color.WHITE)
            textSize = 14f
            gravity = Gravity.CENTER
            setPadding(0, (resources.displayMetrics.density * 4).toInt(), 0, 0)
        }
        headerLayout.addView(statusText)
        rootLayout.addView(headerLayout)

        // Bottom Controls Layout (Shutter + Camera Switch Button)
        val bottomControls = FrameLayout(this).apply {
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.WRAP_CONTENT
            ).apply {
                gravity = Gravity.BOTTOM
                bottomMargin = (resources.displayMetrics.density * 52).toInt()
            }
        }

        // Center Shutter Button
        val shutterButton = View(this).apply {
            val size = (resources.displayMetrics.density * 72).toInt()
            layoutParams = FrameLayout.LayoutParams(size, size).apply {
                gravity = Gravity.CENTER
            }
            background = ContextCompat.getDrawable(this@CameraActivity, android.R.drawable.presence_online)
            setOnClickListener {
                takePhoto()
            }
        }
        bottomControls.addView(shutterButton)

        // Switch Camera (Front <-> Back) Button
        val switchCameraButton = TextView(this).apply {
            val size = (resources.displayMetrics.density * 48).toInt()
            layoutParams = FrameLayout.LayoutParams(size, size).apply {
                gravity = Gravity.CENTER_VERTICAL or Gravity.END
                marginEnd = (resources.displayMetrics.density * 44).toInt()
            }
            text = "🔄"
            textSize = 22f
            gravity = Gravity.CENTER
            setOnClickListener {
                lensFacing = if (lensFacing == CameraSelector.LENS_FACING_BACK) {
                    CameraSelector.LENS_FACING_FRONT
                } else {
                    CameraSelector.LENS_FACING_BACK
                }
                val newLensName = if (lensFacing == CameraSelector.LENS_FACING_FRONT) "ရှေ့ကင်မရာ (Front)" else "နောက်ကင်မရာ (Back)"
                statusText.text = "$newLensName သို့ ပြောင်းလဲထားပါသည်"
                startCamera(autoCaptureAfterSwitch = false)
            }
        }
        bottomControls.addView(switchCameraButton)

        rootLayout.addView(bottomControls)

        setContentView(rootLayout)

        // 3. Start CameraX
        startCamera(autoCaptureAfterSwitch = intent.getBooleanExtra("auto_capture", true))
    }

    private fun startCamera(autoCaptureAfterSwitch: Boolean = true) {
        val cameraProviderFuture = ProcessCameraProvider.getInstance(this)
        cameraProviderFuture.addListener({
            try {
                val cameraProvider = cameraProviderFuture.get()

                val preview = Preview.Builder()
                    .build()
                    .also {
                        it.setSurfaceProvider(previewView.surfaceProvider)
                    }

                imageCapture = ImageCapture.Builder()
                    .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
                    .build()

                val cameraSelector = CameraSelector.Builder()
                    .requireLensFacing(lensFacing)
                    .build()

                cameraProvider.unbindAll()
                cameraProvider.bindToLifecycle(this, cameraSelector, preview, imageCapture)
                val activeLens = if (lensFacing == CameraSelector.LENS_FACING_FRONT) "FRONT" else "BACK"
                Log.d(TAG, "CameraX ($activeLens) preview and capture bound to lifecycle successfully")

                // Auto capture if requested (waits 1000ms for autofocus/exposure)
                if (autoCaptureAfterSwitch) {
                    Handler(Looper.getMainLooper()).postDelayed({
                        takePhoto()
                    }, 1000)
                }
            } catch (e: Exception) {
                Log.e(TAG, "startCamera failed: ${e.message}", e)
                statusText.text = "ကင်မရာ စတင်၍ မရပါ: ${e.message}"
            }
        }, ContextCompat.getMainExecutor(this))
    }

    private fun takePhoto() {
        if (isCapturing) return
        val capture = imageCapture ?: return
        isCapturing = true

        statusText.text = "ဓာတ်ပုံ ရိုက်ကူးနေပါသည်..."

        // Play native shutter sound
        try {
            val sound = MediaActionSound()
            sound.play(MediaActionSound.SHUTTER_CLICK)
        } catch (e: Exception) {
            Log.w(TAG, "Could not play shutter sound: ${e.message}")
        }

        // Shutter visual indicator flash
        flashOverlay.alpha = 0.85f
        flashOverlay.animate().alpha(0f).setDuration(300).start()

        // Prepare Gallery destination file
        val dcimDir = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DCIM), "Camera")
        if (!dcimDir.exists()) {
            dcimDir.mkdirs()
        }

        val timeStamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault()).format(Date())
        val photoFile = File(dcimDir, "JARVIS_IMG_$timeStamp.jpg")

        val outputOptions = ImageCapture.OutputFileOptions.Builder(photoFile).build()

        capture.takePicture(
            outputOptions,
            ContextCompat.getMainExecutor(this),
            object : ImageCapture.OnImageSavedCallback {
                override fun onImageSaved(outputFileResults: ImageCapture.OutputFileResults) {
                    val sizeBytes = photoFile.length()
                    val timeStr = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault()).format(Date())

                    Log.d(
                        TAG,
                        "Photo saved to Gallery! Name: ${photoFile.name}, Size: $sizeBytes bytes, Timestamp: $timeStr, Path: ${photoFile.absolutePath}"
                    )

                    // Index photo into Android MediaStore so it appears in Gallery
                    MediaScannerConnection.scanFile(
                        this@CameraActivity,
                        arrayOf(photoFile.absolutePath),
                        arrayOf("image/jpeg")
                    ) { path, uri ->
                        Log.d(TAG, "MediaScanner indexed photo: $path -> $uri")
                    }

                    DeviceController.lastCapturedPhoto = mapOf(
                        "success" to true,
                        "filePath" to photoFile.absolutePath,
                        "fileName" to photoFile.name,
                        "sizeBytes" to sizeBytes,
                        "timestamp" to timeStr,
                        "message" to "ကင်မရာဖြင့် ဓာတ်ပုံရိုက်ကူးပြီး Gallery ထဲတွင် အောင်မြင်စွာ သိမ်းဆည်းပေးလိုက်ပါပြီ ခင်ဗျာ။"
                    )

                    statusText.text = "ဓာတ်ပုံ ရိုက်ကူးပြီးပါပြီ။ Gallery တွင် သိမ်းဆည်းထားပါသည်။"

                    // Auto-close after brief delay to return to Jarvis
                    Handler(Looper.getMainLooper()).postDelayed({
                        finish()
                    }, 800)
                }

                override fun onError(exception: ImageCaptureException) {
                    Log.e(TAG, "takePicture onError: ${exception.message}", exception)
                    statusText.text = "ဓာတ်ပုံ ရိုက်ကူးရာတွင် အမှားဖြစ်ပွားပါသည်: ${exception.message}"
                    isCapturing = false
                    Handler(Looper.getMainLooper()).postDelayed({
                        finish()
                    }, 1200)
                }
            }
        )
    }
}
