package io.github.ccch1mneyyy.dsh_app.pet

import io.github.ccch1mneyyy.dsh_app.phone.Json
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.nio.file.Files
import kotlin.math.roundToInt

/** One frame: which cell of the sheet, and for how long. */
data class PetFrame(val cell: Int, val ms: Int)

/** The three sizes in 宠物设置, by body height (dp) — the app's PetSize (`pet_state.dart` §2.10). */
enum class PetSize(val dp: Float) {
    SMALL(22f),
    MEDIUM(30f),
    LARGE(40f);

    companion object {
        /** The channel's name (`small` / `medium` / `large`); anything else reads as medium. */
        fun fromName(name: String?): PetSize = when (name) {
            "small" -> SMALL
            "large" -> LARGE
            else -> MEDIUM
        }
    }
}

/** A rectangle in logical pixels (the pack's canvas). */
data class PetBox(val x: Float, val y: Float, val w: Float, val h: Float) {
    val right: Float get() = x + w
    val bottom: Float get() = y + h

    fun union(o: PetBox): PetBox {
        val l = minOf(x, o.x)
        val t = minOf(y, o.y)
        return PetBox(l, t, maxOf(right, o.right) - l, maxOf(bottom, o.bottom) - t)
    }
}

/**
 * One animation: a grid of equal cells (`cols` per row, row-major), each cell
 * the animation's [box] on the canvas at `scale` sheet pixels per logical pixel.
 */
data class PetAnimation(
    val name: String,
    val sheet: String,
    /** Cell size in sheet pixels (= box × scale). */
    val frameW: Int,
    val frameH: Int,
    val cols: Int,
    val box: PetBox,
    val frames: List<PetFrame>,
    val loop: Boolean,
) {
    val totalMs: Long = frames.sumOf { it.ms.toLong() }
    val cells: Int get() = (frames.maxOfOrNull { it.cell } ?: 0) + 1
    val rows: Int get() = (cells + cols - 1) / cols
}

data class PetTier(val min: Int, val anim: String)

/** One idle action and how often it comes up (`idlePool`). */
data class PetIdleItem(val anim: PetAnimation, val ms: Long, val weight: Int)

/** A state's occasional replacement animation (`bonus`, e.g. whale-girl's attention extras). */
data class PetBonus(val anims: List<PetAnimation>, val chance: Float)

/**
 * A runtime pet pack (`assets/pets/<id>/pack.json`, or an installed `<root>/<id>/pack`,
 * [PetPackFiles]):
 * Clawd on Desk state names mapped to animations, busy tiers, reactions, timings. Parsing only;
 * no Android types, so the JVM tests cover it. A pack that fails the format's checks is rejected.
 */
class PetPack(
    val id: String,
    val name: String,
    val pixelArt: Boolean,
    /** Sheet pixels per logical pixel: 1 for whale-girl, 5 for Deepy. */
    val scale: Int,
    val canvasW: Int,
    val canvasH: Int,
    val anchorX: Float,
    val baseline: Float,
    /** The idle body: where the bubble points and what the dock lines up with the edge. */
    val contentBox: PetBox,
    val animations: Map<String, PetAnimation>,
    val states: Map<String, List<String>>,
    val tiers: Map<String, List<PetTier>>,
    val reactions: Map<String, String>,
    /** One-off play time of a variant or reaction (`timings.playMs`). */
    val playMs: Map<String, Long>,
    /** `hitBoxes.wide`: the out-of-app window's size. Null when the pack has none. */
    val wideBox: PetBox?,
    /** Idle actions played now and then over `states.idle[0]` (`idlePool.anims`). */
    val idlePool: List<PetIdleItem>,
    /** `bonus`; null when the pack has no such key (format v1: a state's extra animations). */
    val bonus: Map<String, PetBonus>?,
    /** `hitBoxes.default`. */
    private val defaultHitBox: PetBox? = null,
    /** `sizeScale`: its body against the size's target height (2 for 奶蛙), as `pet_pack.dart`. */
    val sizeScale: Float = 1f,
    /** By animation: `hitBoxes.byAnim`, else `sleeping` for `sleepingAnims`, `wide` for `wideAnims`. */
    private val hitBoxByAnim: Map<String, PetBox> = emptyMap(),
) {
    /**
     * Where [anim]'s body is (logical px), the touch target: as the chat page's hitBoxFor
     * (`pet_pack.dart`), measured on the body, so a thought cloud, Zzz or notes are not in it.
     */
    fun hitBoxFor(anim: PetAnimation): PetBox = hitBoxByAnim[anim.name] ?: defaultHitBox ?: contentBox

    /** The animation [state] plays: the first tier reached, else the state's primary. Unknown → idle's. */
    fun primary(state: String, tier: Int): PetAnimation {
        tiers[state]?.let { list ->
            list.firstOrNull { tier >= it.min }?.let { t -> animations[t.anim]?.let { return it } }
        }
        states[state]?.firstOrNull()?.let { animations[it] }?.let { return it }
        if (state != IDLE) return primary(IDLE, 0)
        return idlePool.firstOrNull()?.anim ?: animations.values.first()
    }

    /**
     * The state's occasional replacement: `bonus[state]`, else (format v1) the state's own list
     * past its primary at up to a third of the time. Idle's list is the idle pool, not a bonus.
     */
    fun bonusOf(state: String, tier: Int): PetBonus? {
        bonus?.let { return it[state] }
        if (state == IDLE || tiers[state]?.any { tier >= it.min } == true) return null
        val p = primary(state, tier)
        val rest = states[state].orEmpty().mapNotNull { animations[it] }.filter { it !== p }
        return if (rest.isEmpty()) null else PetBonus(rest, 1f / 3)
    }

    fun reaction(kind: String): PetAnimation? = reactions[kind]?.let { animations[it] }

    /** How long a one-off of [anim] plays: `timings.playMs`, else two cycles (one for a one-shot). */
    fun playMsOf(anim: PetAnimation): Long = playMs[anim.name] ?: (if (anim.loop) 2 * anim.totalMs else anim.totalMs)

    /** Union of the boxes of [names] (logical px): the room the pet may need. */
    fun unionBox(names: Collection<String>): PetBox =
        names.mapNotNull { animations[it]?.box }.reduceOrNull(PetBox::union) ?: contentBox

    /** Every animation a state, tier or reaction can play, except [skipStates]' own. */
    fun usedAnimations(skipStates: Set<String> = emptySet()): Set<String> {
        val names = LinkedHashSet<String>()
        states.filterKeys { it !in skipStates }.values.forEach(names::addAll)
        tiers.filterKeys { it !in skipStates }.values.forEach { list -> list.forEach { names += it.anim } }
        names += reactions.values
        if (IDLE !in skipStates) idlePool.forEach { names += it.anim.name }
        bonus.orEmpty().filterKeys { it !in skipStates }.values.forEach { b -> b.anims.forEach { names += it.name } }
        return names
    }

    /**
     * The out-of-app window at rest, on the canvas: `hitBoxes.wide` with the idle picture's cell (the
     * hit box, measured on the body, leaves out the idle art's bottom row: 鲸娘's outline, Deepy's
     * shadow), else every state animation's box (roam aside). Held, the window adds the drag pose;
     * showing an animation that reaches past it, that animation's cell ([PetFrames]).
     */
    fun windowBox(): PetBox = wideBox?.union(primary(IDLE, 0).box) ?: unionBox(usedAnimations(skipStates = setOf("roam")))

    /** Pixel art kept at 1×: drawn at a whole number of physical pixels per art pixel, unfiltered. */
    val crisp: Boolean get() = pixelArt && scale == 1

    /**
     * Physical pixels per logical (art) pixel for [size] at [density] — the app's rule
     * (`pet_sprite.dart`'s petScale / petDevicePixels), so the out-of-app pet is as big as the one
     * on the chat page (docs/design/pets.md §2.10). Pixel art snaps [k] to a whole number of
     * physical pixels and keeps the three sizes apart ([devicePixels]); hi-res art draws at the
     * target body height.
     */
    fun screenScale(size: PetSize, density: Float): Float =
        if (pixelArt) devicePixels(size, density).toFloat() else size.dp * sizeScale * density / contentBox.h

    /**
     * Whole physical pixels per art pixel for [size]: `round(dp × density ÷ body)`, then small /
     * medium / large at least one apart — on a 2.75× phone 22/30/40 dp over a 49 px body round to
     * 1/2/2, and two of the three sizes would otherwise draw alike.
     */
    fun devicePixels(size: PetSize, density: Float): Int {
        fun at(s: PetSize): Int = (s.dp.toDouble() * sizeScale * density / contentBox.h).roundToInt().coerceAtLeast(1)
        val small = at(PetSize.SMALL)
        val medium = maxOf(small + 1, at(PetSize.MEDIUM))
        val large = maxOf(medium + 1, at(PetSize.LARGE))
        return when (size) {
            PetSize.SMALL -> small
            PetSize.MEDIUM -> medium
            PetSize.LARGE -> large
        }
    }

    companion object {
        const val IDLE = "idle"

        /** Clawd on Desk state names the overlay understands (anything else plays as idle). */
        val STATES = setOf(
            "idle", "thinking", "working", "juggling", "sweeping", "notification",
            "attention", "error", "carrying", "sleeping", "waking", "roam",
        )

        fun parse(text: String): PetPack {
            val root = Json.parse(text) as? Map<*, *> ?: bad("not an object")
            if (num(root["schema"])?.toInt() != 1) bad("schema must be 1")
            val id = (root["id"] as? String)?.takeIf { it.isNotBlank() } ?: bad("missing id")
            val scale = num(root["scale"])?.toInt()?.takeIf { it >= 1 } ?: bad("missing scale")
            val canvas = root["canvas"] as? Map<*, *> ?: bad("missing canvas")
            val canvasW = num(canvas["w"])?.toInt()?.takeIf { it > 0 } ?: bad("bad canvas")
            val canvasH = num(canvas["h"])?.toInt()?.takeIf { it > 0 } ?: bad("bad canvas")
            val animsRaw = root["animations"] as? Map<*, *> ?: bad("missing animations")
            val animations = LinkedHashMap<String, PetAnimation>()
            for ((k, v) in animsRaw) {
                val name = k as? String ?: bad("bad animation name")
                val a = v as? Map<*, *> ?: bad("bad animation $name")
                val sheet = a["sheet"] as? String ?: bad("$name: no sheet")
                if (sheet.contains('/') || sheet.contains('\\') || sheet.startsWith('.')) bad("$name: bad sheet")
                val box = box(a["box"]) ?: bad("$name: no box")
                val fw = num(a["frameW"])?.toInt() ?: bad("$name: no frameW")
                val fh = num(a["frameH"])?.toInt() ?: bad("$name: no frameH")
                if (fw != (box.w * scale).toInt() || fh != (box.h * scale).toInt()) bad("$name: cell ≠ box × scale")
                val cols = num(a["cols"])?.toInt()?.takeIf { it >= 1 } ?: bad("$name: no cols")
                val frames = (a["frames"] as? List<*>).orEmpty().map { f ->
                    val m = f as? Map<*, *> ?: bad("$name: bad frame")
                    val cell = num(m["i"])?.toInt()?.takeIf { it >= 0 } ?: bad("$name: bad frame index")
                    val ms = num(m["ms"])?.toInt()?.takeIf { it > 0 } ?: bad("$name: bad frame time")
                    PetFrame(cell, ms)
                }
                if (frames.isEmpty()) bad("$name: no frames")
                animations[name] = PetAnimation(name, sheet, fw, fh, cols, box, frames, a["loop"] != false)
            }
            if (animations.isEmpty()) bad("no animations")
            fun ref(name: Any?, where: String): String =
                (name as? String)?.takeIf { it in animations } ?: bad("$where names a missing animation")
            val states = LinkedHashMap<String, List<String>>()
            (root["states"] as? Map<*, *>)?.forEach { (k, v) ->
                val list = (v as? List<*>).orEmpty().map { ref(it, "states.$k") }
                if (k is String && list.isNotEmpty()) states[k] = list
            }
            val tiers = LinkedHashMap<String, List<PetTier>>()
            (root["tiers"] as? Map<*, *>)?.forEach { (k, v) ->
                val list = (v as? List<*>).orEmpty().map { t ->
                    val m = t as? Map<*, *> ?: bad("tiers.$k")
                    PetTier(num(m["min"])?.toInt() ?: 1, ref(m["anim"], "tiers.$k"))
                }.sortedByDescending { it.min }
                if (k is String && list.isNotEmpty()) tiers[k] = list
            }
            val reactions = LinkedHashMap<String, String>()
            (root["reactions"] as? Map<*, *>)?.forEach { (k, v) -> if (k is String) reactions[k] = ref(v, "reactions.$k") }
            (root["roam"] as? Map<*, *>)?.get("anim")?.let { ref(it, "roam") }
            val playMs = LinkedHashMap<String, Long>()
            ((root["timings"] as? Map<*, *>)?.get("playMs") as? Map<*, *>)?.forEach { (k, v) ->
                val ms = num(v)?.toLong()
                if (k is String && ms != null && ms > 0) playMs[k] = ms
            }
            val hits = root["hitBoxes"] as? Map<*, *>
            val wideBox = box(hits?.get("wide"))
            val sleepingBox = box(hits?.get("sleeping"))
            // As pet_pack.dart: wideAnims, then sleepingAnims, then byAnim, each over the one before.
            val hitBoxByAnim = LinkedHashMap<String, PetBox>()
            if (wideBox != null) (hits?.get("wideAnims") as? List<*>).orEmpty().filterIsInstance<String>().forEach { hitBoxByAnim[it] = wideBox }
            if (sleepingBox != null) (hits?.get("sleepingAnims") as? List<*>).orEmpty().filterIsInstance<String>().forEach { hitBoxByAnim[it] = sleepingBox }
            (hits?.get("byAnim") as? Map<*, *>)?.forEach { (k, v) -> box(v)?.let { b -> if (k is String) hitBoxByAnim[k] = b } }
            // `idlePool: {everyMs, anims: [...]}`; a bare list is read too.
            val poolRaw = root["idlePool"].let { (it as? Map<*, *>)?.get("anims") ?: it } as? List<*>
            val idlePool = poolRaw?.map { item ->
                val m = item as? Map<*, *> ?: bad("idlePool")
                val anim = animations.getValue(ref(m["anim"], "idlePool"))
                PetIdleItem(anim, num(m["ms"])?.toLong()?.takeIf { it > 0 } ?: (2 * anim.totalMs), (num(m["weight"])?.toInt() ?: 1).coerceAtLeast(1))
            } ?: states[IDLE].orEmpty().drop(1).map { name ->
                val anim = animations.getValue(name)
                PetIdleItem(anim, playMs[name] ?: (2 * anim.totalMs), 1)
            }
            val bonus = if ("bonus" in root.keys) LinkedHashMap<String, PetBonus>() else null
            (root["bonus"] as? Map<*, *>)?.forEach { (k, v) ->
                val m = v as? Map<*, *> ?: return@forEach
                val anims = (m["anims"] as? List<*>).orEmpty().map { animations.getValue(ref(it, "bonus.$k")) }
                val chance = (num(m["chance"])?.toFloat() ?: 0f).coerceIn(0f, 1f)
                if (k is String) bonus?.put(k, PetBonus(anims, chance))
            }
            val anchor = root["anchor"] as? Map<*, *>
            val firstBox = animations.values.first().box
            return PetPack(
                id = id,
                name = (root["name"] as? String) ?: id,
                pixelArt = root["pixelArt"] == true,
                scale = scale,
                canvasW = canvasW,
                canvasH = canvasH,
                anchorX = num(anchor?.get("x"))?.toFloat() ?: (canvasW / 2f),
                baseline = num(anchor?.get("baseline"))?.toFloat() ?: canvasH.toFloat(),
                contentBox = box(root["contentBox"]) ?: firstBox,
                animations = animations,
                states = states,
                tiers = tiers,
                reactions = reactions,
                playMs = playMs,
                wideBox = wideBox,
                idlePool = idlePool,
                bonus = bonus,
                defaultHitBox = box(hits?.get("default")),
                hitBoxByAnim = hitBoxByAnim,
                sizeScale = num(root["sizeScale"])?.toFloat()?.coerceIn(0.5f, 4f) ?: 1f,
            )
        }

        private fun bad(why: String): Nothing = throw PetPackException(why)

        private fun num(v: Any?): Number? = v as? Number

        private fun box(v: Any?): PetBox? {
            val m = v as? Map<*, *> ?: return null
            val x = num(m["x"])?.toFloat() ?: return null
            val y = num(m["y"])?.toFloat() ?: return null
            val w = num(m["w"])?.toFloat()?.takeIf { it > 0 } ?: return null
            val h = num(m["h"])?.toFloat()?.takeIf { it > 0 } ?: return null
            return PetBox(x, y, w, h)
        }
    }
}

class PetPackException(message: String) : Exception(message)

/**
 * Where installed packs live: `<root>/<id>/pack`, `<root>` being the support directory's `pets/`
 * as Dart pushes it (docs/design/pet-packs.md §4). Set once at startup, idempotently; read from
 * the overlay's worker too.
 *
 * Nothing here throws. `null` clears the root; a path that is unusable — relative, blank, too
 * long — is ignored, so a bad message never loses a good root. With no root the overlay reads the
 * `files/pets/<id>` directory and the bundled assets exactly as before.
 */
internal object PetPackRoot {
    @Volatile
    private var dir: File? = null

    fun current(): File? = dir

    /** [path] as the root; null clears it, anything unusable is ignored. Whether the root changed. */
    fun set(path: String?): Boolean {
        if (path == null) {
            if (dir == null) return false
            dir = null
            return true
        }
        val next = usable(path) ?: return false
        if (next == dir) return false
        dir = next
        return true
    }

    /** [path] as a directory, or null when it cannot be one: relative, blank, too long. */
    fun usable(path: String): File? = try {
        path.takeIf { it.isNotBlank() && it.length <= MAX_PATH }?.let { File(it) }?.takeIf { it.isAbsolute }?.canonicalFile
    } catch (_: Exception) {
        null
    }

    private const val MAX_PATH = 4096
}

/**
 * An installed pack on disk: its directory and parsed manifest. Only data files are read
 * (`pack.json`, `sounds.json`, `*.png`, `*.wav`); the pack is never executed, and a file outside
 * the directory — `..`, an absolute path, a symbolic link — is refused.
 */
internal object PetPackFiles {
    /** A pack id, as `pack.json` and its directory name: lowercase letters, digits and `-`. */
    private val ID = Regex("^[a-z0-9-]+$")

    /** One path segment: no separators, no control characters, no leading `.`. */
    private val SEGMENT = Regex("^[A-Za-z0-9_-][A-Za-z0-9._-]*$")

    /** The directories a pack may keep files in, besides its root. */
    private val SUBDIRS = setOf("sheets", "sounds")

    /** The manifest, capped: a broken pack never gets to hold the worker up on a huge file. */
    private const val MANIFEST_BYTES = 512 * 1024L

    class Installed(val dir: File, val pack: PetPack)

    fun idOk(id: String): Boolean = id.length in 1..64 && ID.matches(id)

    /** Whether [name] is one of a pack's data files, at its root or under `sheets`/`sounds`. */
    fun nameOk(name: String): Boolean {
        if (name.isEmpty() || name.length > 255 || name.contains('\\') || name.contains('\u0000')) return false
        val parts = name.split('/')
        if (parts.size > 2) return false
        if (parts.size == 2 && parts[0] !in SUBDIRS) return false
        if (parts.any { !SEGMENT.matches(it) }) return false
        val file = parts.last()
        if (file == "pack.json" || file == "sounds.json") return parts.size == 1
        return file.endsWith(".png") || file.endsWith(".wav")
    }

    /**
     * [name] inside [dir]: null when the name is not a data file, when any component is a symbolic
     * link, or when the resolved file would leave [dir] or is not a regular file.
     */
    fun file(dir: File, name: String): File? {
        if (!nameOk(name)) return null
        return try {
            val base = dir.canonicalFile
            var at = base
            for (part in name.split('/')) {
                at = File(at, part)
                if (Files.isSymbolicLink(at.toPath())) return null
            }
            val canon = at.canonicalFile
            if (!canon.path.startsWith(base.path + File.separator)) return null
            if (!canon.isFile) return null
            canon
        } catch (_: IOException) {
            null
        } catch (_: SecurityException) {
            null
        }
    }

    /**
     * The installed copy of [id] under [root], or null for the bundled pack: when the root or the
     * directory is missing, the manifest is unreadable or invalid, its `id` disagrees with the
     * directory, or a sheet it names is missing (a half-written pack).
     */
    fun installed(root: File?, id: String): Installed? {
        if (root == null || !idOk(id)) return null
        val packDir = try {
            val base = root.canonicalFile
            if (!base.isDirectory) return null
            val idDir = File(base, id)
            if (Files.isSymbolicLink(idDir.toPath())) return null
            val dir = File(idDir, "pack")
            if (Files.isSymbolicLink(dir.toPath())) return null
            val canon = dir.canonicalFile
            if (!canon.path.startsWith(base.path + File.separator)) return null
            canon
        } catch (_: IOException) {
            return null
        } catch (_: SecurityException) {
            return null
        }
        if (!packDir.isDirectory) return null
        val manifest = file(packDir, "pack.json") ?: return null
        if (manifest.length() > MANIFEST_BYTES) return null
        // Any failure — bad JSON, a broken manifest, an unreadable file — is a pack to skip.
        val pack = try {
            PetPack.parse(manifest.readText(Charsets.UTF_8))
        } catch (_: Exception) {
            return null
        }
        if (pack.id != id) return null
        if (!complete(packDir, pack)) return null
        return Installed(packDir, pack)
    }

    /** Every sheet [pack] names is there: a pack whose manifest arrived without its art is half a pack. */
    fun complete(dir: File, pack: PetPack): Boolean = pack.animations.values.all { sheet(dir, it.sheet) != null }

    /**
     * A sheet of an installed pack: the design's `sheets/<name>` (docs/design/pet-packs.md §1), else
     * `<name>` at the root as the bundled packs keep it.
     */
    fun sheet(dir: File, name: String): File? = file(dir, name) ?: file(dir, "sheets/$name")

    /** Any data file of an installed pack, by the same rule as [sheet]. */
    fun data(dir: File, name: String): File? =
        if (name == "pack.json" || name == "sounds.json") file(dir, name) else sheet(dir, name)

    /**
     * Where [id]'s files come from (docs/design/pet-packs.md §4), in order:
     * 1. `<root>/<id>/pack`, when it holds a complete, valid pack;
     * 2. [bundled], the APK's assets;
     * 3. the legacy flat `files/pets/<id>` — today's behaviour, unchanged.
     *
     * A rooted but empty, missing, half-written or broken installed pack falls through to the
     * bundled one. Null when nothing has the pack.
     */
    fun source(
        root: File?,
        id: String,
        bundled: ((String) -> InputStream?)?,
        legacy: File?,
    ): ((String) -> InputStream?)? {
        // An id is a folder name and nothing else: `..` or a separator never reaches assets either.
        if (!idOk(id)) return null
        installed(root, id)?.let { found ->
            return { name -> data(found.dir, name)?.inputStream() }
        }
        if (bundled != null && bundled("pack.json")?.also { it.close() } != null) return bundled
        if (legacy != null && file(legacy, "pack.json") != null) {
            return { name -> data(legacy, name)?.inputStream() }
        }
        return null
    }
}
