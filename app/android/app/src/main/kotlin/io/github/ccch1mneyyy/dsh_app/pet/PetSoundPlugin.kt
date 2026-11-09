package io.github.ccch1mneyyy.dsh_app.pet

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.SoundPool
import android.os.Handler
import android.os.Looper
import android.util.Log
import io.flutter.embedding.engine.plugins.FlutterPlugin
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.io.IOException
import kotlin.concurrent.thread

/**
 * The chat page pet's sounds (`PetSoundPlayer`, `lib/pets/pet_sounds.dart`; docs/design/naiwa-pet.md
 * §6.4): MethodChannel `dsh/pet_sound`, a [SoundPool] with one voice at a time.
 * The out-of-app pet makes none.
 *
 * - `load {assets: [String]}` → null at once: each Flutter asset into the pool unless it is loaded
 *   or loading; the decoding goes on behind.
 * - `play {asset, volume, rate}` → bool, whether a stream started: false until the asset is
 *   decoded, during a call or voice call, and at volume 0. The ringer mode is not asked: like a
 *   game's, the sounds go by the media volume (most phones sit on vibrate all day).
 *   Volume is clamped to 0…1 and rate to 0.5…2; either one absent is 1.
 * - `release` → null: the pool goes, with every asset in it.
 *
 * Errors: `bad_asset` for a path outside the sound sets ([PetSoundRules.assetOk]), `bad_args` for
 * an argument missing or of the wrong type.
 */
class PetSoundPlugin : FlutterPlugin, MethodChannel.MethodCallHandler {
    private lateinit var context: Context
    private lateinit var channel: MethodChannel
    private lateinit var flutterAssets: FlutterPlugin.FlutterAssets
    private var audio: AudioManager? = null
    private val main = Handler(Looper.getMainLooper())

    // Main thread only: the channel's calls, the pool's callbacks and the copies posted back come there.
    private var pool: SoundPool? = null
    private var stream = 0
    /** Asset → sample, loading or loaded. */
    private val ids = HashMap<String, Int>()
    /** Samples decoded: playable. */
    private val ready = HashSet<Int>()
    /** Assets being copied out of the APK before they load. */
    private val copying = HashSet<String>()
    /** Bumped by [release]: a copy finishing after it loads nothing. */
    private var generation = 0

    override fun onAttachedToEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        context = binding.applicationContext
        audio = context.getSystemService(AudioManager::class.java)
        flutterAssets = binding.flutterAssets
        channel = MethodChannel(binding.binaryMessenger, CHANNEL).also { it.setMethodCallHandler(this) }
    }

    override fun onDetachedFromEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        channel.setMethodCallHandler(null)
        release()
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        val args = call.arguments as? Map<*, *> ?: emptyMap<String, Any?>()
        when (call.method) {
            "load" -> {
                val list = args["assets"] as? List<*>
                if (list == null || list.any { it !is String }) return result.error("bad_args", "assets: a list of strings", null)
                val assets = list.filterIsInstance<String>()
                assets.firstOrNull { !PetSoundRules.assetOk(it) }?.let { return result.error("bad_asset", "not a pet sound: $it", null) }
                load(assets)
                result.success(null)
            }
            "play" -> {
                val asset = args["asset"] as? String ?: return result.error("bad_args", "asset: a string", null)
                if (!PetSoundRules.assetOk(asset)) return result.error("bad_asset", "not a pet sound: $asset", null)
                val volume = PetSoundRules.volume(args["volume"]) ?: return result.error("bad_args", "volume: a number", null)
                val rate = PetSoundRules.rate(args["rate"]) ?: return result.error("bad_args", "rate: a number", null)
                result.success(play(asset, volume, rate))
            }
            "stop" -> {
                stop()
                result.success(null)
            }
            "release" -> {
                release()
                result.success(null)
            }
            else -> result.notImplemented()
        }
    }

    private fun load(assets: List<String>) {
        val sounds = pool()
        val compressed = ArrayList<Pair<String, String>>()
        for (asset in assets) {
            if (asset in ids || asset in copying) continue
            val key = flutterAssets.getAssetFilePathByName(asset)
            // Stored compressed, an asset has no file descriptor of its own: copied out first.
            val fd = try { context.assets.openFd(key) } catch (_: IOException) { null }
            if (fd == null) {
                copying += asset
                compressed += asset to key
                continue
            }
            fd.use { track(asset, sounds.load(it, 1)) }
        }
        if (compressed.isNotEmpty()) copyOut(compressed)
    }

    /** Off the main thread: [compressed] (asset to APK path) copied into the cache, then loaded from there. */
    private fun copyOut(compressed: List<Pair<String, String>>) {
        val gen = generation
        thread(name = "dsh-pet-sound", isDaemon = true) {
            val dir = File(context.cacheDir, CACHE_DIR)
            val files = compressed.map { (asset, key) ->
                asset to try {
                    copy(key, File(dir, asset.removePrefix(PetSoundRules.PREFIX)))
                } catch (e: IOException) {
                    Log.w(TAG, "sound $asset unreadable", e)
                    null
                }
            }
            main.post {
                if (gen != generation) return@post
                for ((asset, file) in files) {
                    copying -= asset
                    if (file != null) track(asset, pool().load(file.path, 1))
                }
            }
        }
    }

    /** [key]'s bytes into [file] in one step: a load never reads it half written. */
    private fun copy(key: String, file: File): File {
        val part = File.createTempFile(file.name, ".part", file.parentFile!!.apply { mkdirs() })
        try {
            context.assets.open(key).use { input -> part.outputStream().use { input.copyTo(it) } }
            if (!part.renameTo(file)) throw IOException("could not write $file")
        } finally {
            part.delete()
        }
        return file
    }

    /** [id] from SoundPool.load: 0 when it could not even open the file. */
    private fun track(asset: String, id: Int) {
        if (id != 0) ids[asset] = id else Log.w(TAG, "sound $asset not loaded")
    }

    private fun play(asset: String, volume: Float, rate: Float): Boolean {
        val sounds = pool ?: return false
        val id = ids[asset]?.takeIf { it in ready } ?: return false
        val am = audio ?: return false
        if (volume <= 0f || !PetSoundRules.audible(am.mode)) return false
        stop()
        stream = sounds.play(id, volume, volume, 1, 0, rate)
        return stream != 0
    }

    private fun stop() {
        if (stream != 0) pool?.stop(stream)
        stream = 0
    }

    private fun release() {
        generation++
        stop()
        pool?.release()
        pool = null
        ids.clear()
        ready.clear()
        copying.clear()
    }

    /** Made on the main thread, where its load callbacks then come. */
    private fun pool(): SoundPool = pool ?: SoundPool.Builder()
        .setMaxStreams(MAX_STREAMS)
        .setAudioAttributes(
            AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_GAME)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                .build(),
        )
        .build()
        .also { made ->
            made.setOnLoadCompleteListener { from, id, status ->
                if (from !== pool) return@setOnLoadCompleteListener
                if (status == 0) {
                    ready += id
                    return@setOnLoadCompleteListener
                }
                // Forgotten, so a later load tries again.
                val asset = ids.entries.find { it.value == id }?.key ?: return@setOnLoadCompleteListener
                ids.remove(asset)
                Log.w(TAG, "sound $asset: decoding failed ($status)")
            }
            pool = made
        }

    private companion object {
        const val CHANNEL = "dsh/pet_sound"
        const val TAG = "DshPet"
        const val MAX_STREAMS = 1
        /** Under cacheDir: assets stored compressed, copied out to load from a file. */
        const val CACHE_DIR = "pet_sounds"
    }
}

/** Pure parts of [PetSoundPlugin], unit-tested on the JVM. */
internal object PetSoundRules {
    /** The sound sets' folder (`app/assets/pet_sounds/<id>/`). */
    const val PREFIX = "assets/pet_sounds/"

    /** AudioManager.MODE_IN_CALL */
    private const val MODE_IN_CALL = 2

    /** AudioManager.MODE_IN_COMMUNICATION */
    private const val MODE_IN_COMMUNICATION = 3

    /** A clip of a sound set: under [PREFIX] (so never absolute), a `.wav`, without `..` or a backslash. */
    fun assetOk(asset: String): Boolean =
        asset.startsWith(PREFIX) && asset.endsWith(".wav") && ".." !in asset && '\\' !in asset

    /** 0…1; 1 when absent, null when not a number. */
    fun volume(value: Any?): Float? = number(value)?.coerceIn(0f, 1f)

    /** SoundPool's 0.5…2; 1 when absent, null when not a number. */
    fun rate(value: Any?): Float? = number(value)?.coerceIn(0.5f, 2f)

    /** AudioManager's audio mode: no call or voice call is on. */
    fun audible(audioMode: Int): Boolean = audioMode != MODE_IN_CALL && audioMode != MODE_IN_COMMUNICATION

    private fun number(value: Any?): Float? = when (value) {
        null -> 1f
        is Number -> value.toFloat().takeUnless { it.isNaN() }
        else -> null
    }
}
